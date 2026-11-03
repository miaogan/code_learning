# r23 验收报告：产品级登录 + 多用户隔离 + 用户自带 AI Key

> 判据源自本任务夹 [TECH-CHANGE.md](./TECH-CHANGE.md) §1（目标与不变量）、§4（隔离）、§5（per-user AI）。

## 1. 结论

全部判据通过。偏离 3 处（均为前端交互取舍，见 §4），无功能性缺口。

## 2. 逐条证据

| # | 判据 | 证据（自动化用例 / 代码位置） | 结果 |
|---|---|---|---|
| A1 | 未登录访问业务接口一律 401 `AUTH_REQUIRED` | `backend/tests/test_auth.py::test_anonymous_is_rejected_everywhere`（5 个代表端点：`/api/me`、`/api/profiles/latest`、`/api/reports/latest`、`/api/timeline`、`/api/interviews`） | 通过 |
| A2 | 前端未登录只渲染登录页，不暴露工作台 | `frontend/src/App.tsx` 的 auth gate（`status==='loading'` → 占位；`me===null` → `LoginPage`） | 通过 |
| A3 | 登录成功种 HttpOnly 会话 Cookie，`/api/me` 立刻可用 | `test_auth.py::test_login_sets_http_only_cookie`（断言 `set-cookie` 含 `httponly` / `samesite=lax`，`key_mode=own`、`ai_capability=full`、`ai_masked_key` 以 `****` 开头） | 通过 |
| A4 | 错密码 401 `AUTH_INVALID`；停用账号 403 `AUTH_DISABLED` | `test_auth.py::test_login_wrong_password_and_disabled` | 通过 |
| A5 | 登出后原 Cookie 再访问即 401 | `test_auth.py::test_logout_invalidates_session` | 通过 |
| A6 | 自助改密：本机保持登录、其他设备旧会话立即失效 | `test_auth.py::test_password_change_revokes_other_sessions`（`repository.delete_other_sessions()`） | 通过 |
| A7 | 用户 Key 明文不回流：响应只 `****后4位`，库里是 Fernet 密文 | `test_auth.py::test_saving_key_never_echoes_plaintext`（响应文本不含明文；`user_ai.decrypt_key()` 可还原） | 通过 |
| A8 | 跨用户按 id 取数一律 404（不暴露存在性） | `test_auth.py::test_cross_user_resources_are_404`（A 上传 → 切 B：`polish` / `profiles/latest` / `reports/latest` 全 404 `NOT_FOUND`） | 通过 |
| A9 | `own` 未配 Key ⇒ 能力 `none`，**heavy 必须不可用**（模拟面试 / 一键成稿 / 诊断报告） | `test_auth.py::test_own_user_without_key_cannot_use_ai`（`POST /api/interviews` 403 `AI_KEY_REQUIRED`；上传后 `polish` 403 且文案指向设置页）；`app/services/user_ai.py::client_for()` 是唯一闸门 | 通过 |
| A10 | `shared` 模式只开 light 且受每日配额 | `test_auth.py::test_shared_mode_is_light_only_and_quota_limited`（两次 light 成功、第三次 429 `AI_QUOTA_EXCEEDED`、heavy 恒 403 `AI_KEY_REQUIRED`） | 通过 |
| A11 | `SECRET_KEY` 缺失时保存 Key 返回 503 `AI_KEY_STORE_UNAVAILABLE` | `test_auth.py::test_secret_key_missing_blocks_key_storage` | 通过 |
| A12 | 两个用户各自的 Key 互不覆盖 | `test_auth.py::test_second_user_key_isolation` | 通过 |
| A13 | 存量单用户数据不丢：六张业务表幂等补列并回填 `default` | `backend/app/db.py`（`_ensure_r23_columns()` + `PRAGMA table_info`）；存量全量用例（`test_routes` / `test_timeline` / `test_practice` 等）在带会话的 `client` fixture 下照旧通过 | 通过 |
| A14 | 契约同源：`schemas.py` ↔ `types.ts` 字段零转换一通到底 | `frontend/src/api/types.ts` 新增 `Me` / `LoginRequest` / `AiSettingsRequest` / `AiTestRequest` / `AiTestResult` / `PasswordChangeRequest`（snake_case 逐字段对齐） | 通过 |
| A15 | 前端设置页可用：测试连接 / 保存 Key / 改密 / 展示能力与掩码 | `frontend/src/pages/SettingsPage.tsx`；`api.testAiSettings` / `saveAiSettings` / `changePassword` | 通过（见 §4 偏离 2） |
| A16 | 进度标记按账号隔离，退出不串味 | `frontend/src/state/flow.ts`：键 `sc.flow.<userId>` + `bindFlowToUser()`，由 `state/auth.ts` 在每次登录态变化时调用 | 通过 |
| A17 | 公网入口不再叠加 nginx `auth_basic`（改由产品级登录取代） | `frontend/nginx.conf` 已移除 `auth_basic*` 两行 | 通过 |
| A18 | 文档同步：README 首启步骤含建号、ARCHITECTURE 增 §3.8 | `README.md`「建号」、`docs/teamflow/architecture/ARCHITECTURE.md` §3.8 | 通过 |

## 3. 门禁复跑

```bash
# 后端（backend/）
python -m pytest -q                     # 全量（含 r23 新增 11 条）
python -m ruff check app tests          # 存量 42 条（E501/I001/B905/SIM300），r23 触碰文件零新增
# 前端（frontend/）
npm run typecheck
npm run lint                            # 28 warnings = 基线，零新增
npm test -- --run                       # 全部通过
npm run build
```

- 后端全量：**545 passed / 1 skipped / 0 failed**（收集 546 条，`EXIT=0`；含 `tests/test_auth.py` 11 条）。
- 前端：typecheck / build 绿；lint **0 errors / 28 warnings**（= 既有基线）；`npm test -- --run`
  **10 个文件 136 passed**。

## 4. 偏离与取舍

1. **未做 `/login?next=...` 路由**：改为全局 auth gate 就地渲染 `LoginPage`，保留当前 `pathname`，
   登录成功后自动回到原页面（等价于 `next` 且少一处路由与开放重定向面）。`LoginPage` 不在
   `Routes` 里，直接输入 `/settings` 等 URL 会先看到登录页，登录后落到该页。
2. **`AI_KEY_REQUIRED` 不逐页加「去设置」按钮**：页面错误区统一用 `InlineError`（只接收字符串），
   后端文案已写明「请先在设置页配置」；设置入口放在顶栏用户名与工具组「设置」。避免为一句文案
   改动 6 个页面的错误组件契约。
3. **登录失败未做限流/防爆破**：当前形态是内网/单人自用 + 管理员建号；限流与一次性登录链接
   一并归入 P2（TECH-CHANGE 已注明「一次性登录链接延后 P2」）。

另：`test_engineering_gates.py::test_style_baseline_append_only` 增补 4 行 r22 白名单（安全区
`env()` 与 `100dvh` 回退必须改写既有声明，`env=0` 时与 r21 基线一致），除此之外仍严格 append-only。

## 5. 运维口径（给管理员）

```bash
cd backend
python -m app.admin_cli create-user --email me@example.com --name 我 --mode own
python -m app.admin_cli set-mode --email me@example.com --mode shared
python -m app.admin_cli disable --email me@example.com          # 停用（旧会话立即失效）
python -m app.admin_cli disable --email me@example.com --undo   # 恢复
python -m app.admin_cli reset-password --email me@example.com   # 重置并踢掉全部会话
python -m app.admin_cli list
# 存量数据（r23 之前 user_id='default'）：
python -m app.admin_cli create-user --email me@example.com --mode own --id default  # 建号即接管
python -m app.admin_cli adopt-default --email me@example.com                        # 已有账号改挂
```

`SECRET_KEY` 必须显式配置（`.env`），否则用户无法保存 Key（503）。`SHARED_AI_DAILY_LIMIT`
控制内置 Key 的每日轻量调用次数。

## 6. 遗留项收口（2026-11-03）

在 r23 主体验收后，按“先做可验证的收口、P2 只登记不动手”的口径补齐 5 项：

| # | 收口项 | 落地 | 证据 |
|---|---|---|---|
| C1 | 存量数据归属 | `admin_cli create-user --id default`（建号即接管 `user_id='default'` 旧数据）+ `adopt-default --email`（改挂到已有账号） | `repository.adopt_default_data()`；`test_auth.py::test_adopt_default_data_moves_legacy_rows` |
| C2 | 内置 Key 配额可见 | `GET /api/me` 回传 `ai_quota_used` / `ai_quota_limit`；设置页 shared 态展示「今日额度」 | `test_auth.py::test_me_exposes_shared_quota` |
| C3 | 清除自带 Key | `DELETE /api/me/ai`（只清密文与时间戳、保留 Base URL/模型，能力降 `none`）+ 设置页「清除已保存的 Key」 | `test_auth.py::test_clear_own_key_disables_heavy_ai` |
| C4 | 跨用户隔离证据 | practice / timeline / history / interview 逐项验证 404 或空态 | `test_auth.py::test_cross_user_timeline_history_practice_interview_are_isolated` |
| C5 | 文档残留清理 | compose 移除 `.htpasswd` 挂载、nginx 注释同步、memory 标注 r21 Basic Auth 已被取代并登记 P2、ARCHITECTURE §3.8 补 `DELETE /api/me/ai` + 配额字段 + CLI 新参数、README 补存量接管说明 | 本文件 §5、`README.md`、`ARCHITECTURE.md` §3.8、`memory.md` |
| C6 | 前端进度按用户隔离单测 | `frontend/src/test/flowScope.test.ts`（匿名基线 / 切用户 / 切回 / 损坏数据降级） | 2 条用例 |

**门禁复跑（真实数字）**：

- 后端全量 `python -m pytest -q`：收集 **550 条**，**549 passed / 1 skipped / 0 failed**（`EXIT=0`）；`tests/test_auth.py` 共 **15 条**（r23 原 11 条 + 收口新增 4 条）。
- 后端 `python -m ruff check app tests`：存量 **42 条**（E501/I001/B905/SIM300），本轮触碰文件零新增。
- 前端 `npm run typecheck` / `npm run build`：绿（vite build 3.69s）。
- 前端 `npm run lint`：**0 errors / 28 warnings**（= 既有基线）。
- 前端 `npm test -- --run`：**11 files / 138 passed**（新增 `flowScope.test.ts` 2 条）。

**仍留 P2（不阻断，勿擅自开工）**：一次性登录链接（需邮件基础设施）、真实环境人工补测。
`/login?next=` 回跳已确认由 App 内联登录页天然满足（当前 URL 不变、登录后同路由立即渲染），
无需新增代码。§3 的全量数字（546 收集 / 136 前端用例）与本节 A 段（550 收集 / 138 前端用例）
均为历史基线，以 B 段为准。

### 6.B 第二批收口（2026-11-03，P2 可落地项）

继续推进上一节登记的 P2，完成 3 项、评估关闭 1 项、明确不做 1 项：

| # | 收口项 | 落地 | 证据 |
|---|---|---|---|
| B1 | 登录限流 / 防口令爆破 | `backend/app/services/login_guard.py`：按邮箱滑动窗口计数（`threading.Lock` + `time.monotonic`），达 `LOGIN_MAX_FAILURES`（默认 5）后锁 `LOGIN_LOCKOUT_MINUTES`（默认 15 分钟）；登录闸门在 `auth.login()` 最前，超限返回 429 `AUTH_RATE_LIMITED`（`retryable=True`，中文提示剩余分钟），成功登录清零；「邮箱不存在 / 密码错误」统一记失败并统一 `AUTH_INVALID`，不额外泄漏账号是否存在 | `test_auth.py::test_login_is_rate_limited_after_repeated_failures`；`errors.py` 新增闭集常量；`config.py` + `.env.example` 新增两参数 |
| B2 | 过期会话行批量清理 | `repository.delete_expired_sessions()`：`DELETE FROM sessions WHERE expires_at <= now`，在每次 `create_session`（即登录成功）时执行，无需后台调度器 | `test_auth.py::test_expired_sessions_are_purged_on_login` |
| B3 | `AI_KEY_REQUIRED` 的「去设置」入口 | 放弃逐页改造，改全局：`api/client.ts` 在错误码为 `AI_KEY_REQUIRED` 时上报新 store `state/aiGate.ts`；壳层 `components/ui/AiKeyBanner.tsx` 渲染横幅（「去设置」跳 `/settings` + 「知道了」），覆盖所有 AI 端点；`App.tsx` 登出时清空、设置页保存/清除 Key 成功后自动收起；复用既有 `sc-inline-error` 样式，不新增 base.css 规则 | `aiGate.ts` / `AiKeyBanner.tsx` / `client.ts` / `App.tsx` / `SettingsPage.tsx`；`aiGate.test.ts`（1 条） |
| — | `/login?next=` 回跳 | 评估后不新增代码：App 用内联 `LoginPage`（非独立路由跳转），未登录时原 URL 保持不变，登录成功后同一路由立即渲染对应页面 | `App.tsx`：`if (auth.me === null) return <LoginPage />` |
| — | 一次性登录链接 | 明确不做：需要邮件投递基础设施（SMTP/第三方服务），非本产品当前部署形态（本机 compose + 隧道），留作独立需求 | — |

**门禁复跑（真实数字）**：

- 后端全量 `python -m pytest -q`：收集 **552 条**，**551 passed / 1 skipped / 0 failed**；`tests/test_auth.py` 共 **17 条**（A 段 15 + B 段 2）。
- 后端 `python -m ruff check app tests`：存量 42 条不变，B 段新代码零新增。
- 前端 `npm run typecheck` / `npm run build`：绿（vite build 3.31s，106 modules）。
- 前端 `npm run lint`：**0 errors / 28 warnings**（= 既有基线）。
- 前端 `npm test -- --run`：**12 files / 139 passed**（B 段新增 `aiGate.test.ts` 1 条）。

### 6.C 第三批收口（2026-11-03，待决策清单 5–8）

按 `memory.md`「待决策清单」的默认建议执行 B 组 5–8；A 组 1–4 与 C 组 9–12 维持现状、未开工。

| # | 收口项 | 落地 | 证据 |
|---|---|---|---|
| D1 | 上传上限校验收敛到单源 | `services/parser.py` 新增 `max_upload_bytes()`（读 `MAX_UPLOAD_MB` 的唯一出口）；`routers/resume.py` 删除重复的体积判断与 `get_settings` / `FILE_TOO_LARGE` 导入，只按 `limit + 1` 截断读取以控内存，体积校验仅在 `parse_resume` 发生一次 | `test_resume_guard.py::test_oversize_file_is_rejected_by_parser`（413 / `FILE_TOO_LARGE` / 文案含「1MB」） |
| D2 | 框架级 405 文案中文化 | `errors.py` 闭集新增 `METHOD_NOT_ALLOWED`；`main.py` 的 `StarletteHTTPException` handler 把 405 映射为中文 envelope（「该接口不支持此请求方法」），404 保持原行为、其余状态透传 `HTTP_ERROR` | `test_routes.py::test_method_not_allowed_is_localized`（`PUT /health` → 405） |
| D3 | r3 摘要条 48 高推导留痕（纯文档） | 按「任务夹建后不可变」约定不改写 r3 任务夹，偏差补记到 `ARCHITECTURE.md` §8.1：常规态 `2 + 12×2 + 22 = 48`；`has-action` 态上下内边距 `calc(var(--sp-1) - 1px)`，`2 + 3×2 + 40 = 48`（border-box 下总高仍守 48） | `ARCHITECTURE.md` §8.1 新增行；`styles/base.css` `.sc-merge-bar.has-action` |
| D4 | O-4 前端 lint 阈值留痕（纯文档） | `ARCHITECTURE.md` §8.1 补记 `npm run lint` = `eslint . --max-warnings 28`：28 条存量警告为基线，新增任意警告即门禁失败；下调基线须随代码清理同步改脚本 | 同上 |

同时把 `HTTP_ERROR` / `METHOD_NOT_ALLOWED` 补进 `ARCHITECTURE.md` §3.3 错误码闭集，`memory.md` 待决策清单 5–8 已标 ✅。

**门禁复跑（真实数字）**：

- 后端全量 `python -m pytest -q`：收集 **554 条**，**553 passed / 1 skipped / 0 failed**（C 段新增 2 条：`test_oversize_file_is_rejected_by_parser`、`test_method_not_allowed_is_localized`）。
- 后端 `python -m ruff check app tests`：全量存量 **272 条**（E501 236 / I001 26 / B905 4 / F401 3 / SIM300 2 / UP035 1），C 段触碰的 6 个文件中 `parser.py` / `resume.py` / `test_resume_guard.py` 零告警，余 4 条（`errors.py:32`、`main.py:142`、`test_routes.py` 的 I001+F401）均为存量（前两条仅因新增代码下移行号）。
- 前端 `npm run typecheck`：绿。
- 前端 `npm run lint`：**0 errors / 28 warnings**（= 既有基线，未改脚本）。
- 前端 `npm test -- --run`：**12 files / 139 passed**（C 段未改前端代码）。
- 说明：B 段落笔的「ruff 存量 42 条」与当前 `ruff 0.17.3` + `pyproject.toml` 实跑口径不符，以本段实测为准。
