# r23 技术方案：产品级登录 + 多用户数据隔离 + 用户自带 AI Key

## 1. 目标与不变量

- 登录后才能使用产品；6 张业务表按 `user_id` 隔离，跨用户读取/写入一律 404。
- 不开放注册：管理员用 CLI 建号、改 Key 模式、停用、重置密码。
- 每位用户可在设置页填写自己的 AI Key（自己承担额度）；未填写时只能用管理员同意的内置 Key，
  且内置 Key 只能跑「轻量」AI 场景，并受每日配额限制。
- 用户自己的 Key 只以密文落库，任何响应**绝不**回显明文（只回显后 4 位）。

## 2. 认证

- 服务端 `sessions` 表 + HttpOnly Cookie（`sc_session`，`SameSite=Lax`、`Path=/`、`Max-Age`）。
- 密码哈希：标准库 `hashlib.scrypt`（n=2^14, r=8, p=1, dklen=32），格式 `scrypt$<salt>$<hash>`，零新依赖。
- 会话 token：`secrets.token_urlsafe(32)`，库里只存 SHA-256 摘要；`SESSION_DAYS=30` 过期。
- `COOKIE_SECURE` 开关：开发默认 false（http），生产 https 时置 true。
- 非安全方法的 `Origin` 校验：有 Origin 且与请求 Host 不同源、又不在 `CORS_ORIGINS` 内 → 403。

## 3. 表结构变更

新增：

- `users(id, email UNIQUE, password_hash, display_name, role, key_mode, ai_base_url, ai_model,
  ai_api_key_enc, ai_json_mode, ai_updated_at, disabled, created_at)`；`key_mode ∈ own|shared`。
- `sessions(token_hash PK, user_id, created_at, expires_at)`。
- `ai_usage(id PK, user_id, day, created_at)`：内置 Key 每日调用计数。

存量 6 表各加 `user_id TEXT NOT NULL DEFAULT 'default'`：
`documents / profiles / runs / reports / timeline_events / question_attempts`。
`questions` 是共享题库，不加。

存量数据回填：`ALTER TABLE ... ADD COLUMN ... DEFAULT 'default'` 本身即回填，旧数据归 `default`；
管理员可用 CLI 建号后再用 SQL 手工迁移（本版不做归属迁移工具）。

索引：`(user_id, created_at/updated_at/occurred_at/answered_at)` + `runs(user_id, kind, created_at)`。

`init_db()` 顺序：`SCHEMA`（新库含新列）→ `_ensure_r11_columns()` → `R23_SCHEMA` →
`_ensure_r23_columns()` → `SCHEMA_INDEXES`（含 r23 索引，必须在补列后）。

## 4. 隔离实现

- `app/context.py`：`ContextVar` 保存当前 `user_id`（默认 `'default'`）。
- `deps.current_user` 为 **async** 依赖：读 Cookie → 查会话 → 校验过期/停用 → `set_current_user_id`。
  async 而非 sync 是刻意的：sync 依赖跑在线程池，ContextVar 的写入不会回传到端点上下文。
- `repository.py` 是唯一 SQL 出口：所有读写 SQL 追加 `AND user_id = ?` / 写入带 `user_id`。
  服务层签名零改，靠 ContextVar 取当前用户。
- 所有按 id 取数的接口天然满足 `WHERE id = ? AND user_id = ?`（防 IDOR）。

## 5. per-user AI

- `AIClient.__init__(settings=None, runtime=None)`：显式 runtime 优先，否则 `settings.resolve_ai()`。
- `services/user_ai.py` 是用户 AI 口径的单一出口：
  - `own` 且三件套齐全 → 用户 runtime（provider=`user`），能力 `full`；
  - `shared` → 服务端 `resolve_ai()`，能力 `light`；
  - `own` 未配 / `shared` 但服务端未就绪 → `none`。
- 能力分级：
  - light：画像生成 `POST /api/resumes/{id}/profile`、润色建议 `POST /api/resumes/{id}/polish`；
  - heavy：一键成稿 `polish/full`、模拟面试（开局 + 每题）、诊断报告 `POST /api/reports/generate`；
  - 零 AI 不受限：笔试 / 练习 / 题库 / 时间线 / 历史 / 课程。
- 闸门：`full` 全开；`light` 只开 light；`none` 全禁。
  heavy 被 `own` 未配置拦截 → `AI_KEY_REQUIRED` 403（`retryable=false`）。
- 内置 Key 配额：`key_mode='shared'` 用户每日 `SHARED_AI_DAILY_LIMIT`（默认 20）次；
  超限 `AI_QUOTA_EXCEEDED` 429。
- Key 加密：`cryptography.Fernet`，密钥由 `SECRET_KEY` 经 SHA-256 派生；
  `SECRET_KEY` 为空时保存 Key 返回 `AI_KEY_STORE_UNAVAILABLE` 503。
- 用户 Key 失效文案改为「请检查你在设置页填写的 API Key 与额度」。

## 6. 接口契约

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/auth/login` | `{email,password}` → 设 Cookie，返回 `MeResponse` |
| POST | `/api/auth/logout` | 清 Cookie |
| GET | `/api/me` | 当前用户 + `ai_capability` + `ai_masked_key` |
| PUT | `/api/me/ai` | 保存 Key 三件套（`api_key` 缺省=不改） |
| POST | `/api/me/ai/test` | 用当前/临时 Key 做一次最小调用，返回 `{ok,message}` |
| PATCH | `/api/me/password` | `{old_password,new_password}` |

`MeResponse.ai_capability ∈ full|light|none`。前端 `types.ts` 同步。

## 7. 前端

- `state/auth.ts`（`useSyncExternalStore`）：登录态、`me`、`ai_capability`，`refresh()`。
- `/login`、`/settings`；其余路由未登录统一跳 `/login?next=...`。
- `client.ts` 遇 401 → 清理登录态并跳登录；`AI_KEY_REQUIRED` 由页面渲染「去设置」。
- `flow.ts` 存储键改为 `sc.flow.<userId>`，登录/登出时切换命名空间。
- 顶栏显示用户名 + 「设置 / 退出」。

## 8. 回滚

- 代码回滚：恢复 r22 tag 即可；新增表与列可留在库里（旧代码忽略未知列/表）。
- 若必须清理：`DROP TABLE users, sessions, ai_usage`；6 表的 `user_id` 列在 SQLite 需重建表或保留不用。
- 回滚后需同时恢复 nginx `auth_basic` 两行与 compose 的 `.htpasswd` 只读挂载（r23 收口已移除挂载）。
