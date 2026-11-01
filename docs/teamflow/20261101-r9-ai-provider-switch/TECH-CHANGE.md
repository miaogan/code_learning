# 技术变更单 · AI 供应商可切换（本地 LM Studio ⇄ 云端 DeepSeek）

> 任务夹 `docs/teamflow/20261101-r9-ai-provider-switch/` · 分支 `feat/dev-skill-coach`（原地继续，Agent 不提交）· 类型：tech-driven rework（无功能 PRD）· 基线依赖 `docs/teamflow/20261101-r8-profile-null-contract/`——其 AC 全部继续有效；本单**不新增、不修改任何功能 AC**。

## 1 背景与目标

一句话：把写死的单套模型配置升级为「配置档 + `AI_PROVIDER` 一键切换」，用真实本地 LM Studio 跑通同一画像链路，同时保证 DeepSeek 与既有门禁零回退。契约依据（已实测，勿重复试错）：

| # | 事实 | 影响 |
|---|---|---|
| F1 | LM Studio `POST /v1/chat/completions` 带 `response_format:{"type":"json_object"}` → **400** `'response_format.type' must be 'json_schema' or 'text'`；不带该字段 200（11.6s）；带 `{"type":"text"}` 也 200 | `response_format` 必须可配 |
| F2 | 本地端点无鉴权 | 空 key 时**省略** `Authorization` |
| F3 | 本地 9B 单次 11–13s，画像类长结构化输出 30–60s ≫ 现 `AI_TIMEOUT_S=20` | 超时须按档独立 |
| F4 | 输出常带 ```json 围栏；`_extract_json_object` 已有剥离逻辑 | 需回归钉住，不放宽校验 |

## 2 改动面

| 文件 | 动作 | 说明 |
|---|---|---|
| `backend/app/config.py` | 改 | 档位字段 + `resolve_ai()` 单一解析出口（阈值/开关仍只住本文件） |
| `backend/app/services/ai.py` | 改 | `response_format` 三档策略、空 key 省略 header、按档超时 |
| `backend/app/schemas.py` | 改 | `HealthResponse` 增 `ai_provider/ai_model/ai_json_mode` |
| `backend/app/main.py` | 改 | `health()` 改为 live `get_settings()`（去 import 期闭包缓存） |
| `backend/tests/conftest.py` | 改 | `tmp_db` 置空 `AI_PROVIDER` 与各档变量 → 与宿主 `.env` 解耦 |
| `backend/tests/test_health.py` | 改 | 修掉环境敏感断言（现裸断 `ai_configured is False`） |
| `backend/tests/test_ai_provider.py` | 新增 | 解析/请求体/重试/围栏/health/闭集互锁 ~12 例 |
| `backend/.env.example` | 改 | 档位示例（无任何真实密钥） |
| `frontend/src/api/types.ts` | 改 | `Health` 镜像 3 个**可选** `string`（前端不渲染） |
| `docs/teamflow/memory.md` | 改 | 追加 1 条 r9 供应商切换约定 |

明确不改：各业务 service 的**提示词与响应模型**（profile/diagnosis/interview/resume_polish）、`schemas.py` 业务模型（r8 的 `role/period` 可空逻辑保留）、`repository.py`/`db.py`（零 DDL 零迁移）、业务 routers、前端页面与样式、依赖清单（httpx 已有，零新增）。不提交 `backend/.env`、`*.db`、诊断脚本。

## 3 技术方案

### 3.1 配置档模型（`config.py` 仍是开关唯一出处）

- 全局：`ai_provider: str = ""`、`ai_json_mode: Literal["json_object","none"] = "json_object"`；既有 `ai_base_url/ai_api_key/ai_model/ai_timeout_s/ai_max_retries` 语义不变。
- 显式两档（N 套＝加 5 个字段）：`ai_deepseek_{base_url,model,api_key,json_mode,timeout_s}`、`ai_lmstudio_{...}`。默认值：deepseek 给公开 base_url/model；lmstudio 只给 `base_url=http://localhost:1234/v1`，**model 必须显式填**（本地模型 id 因机器而异）。
- `Settings.resolve_ai() -> AiRuntime(provider, base_url, model, api_key, json_mode, timeout_s, max_retries, ready)` 为唯一解析出口，`AIClient` 与 `/health` 共用，禁止各处读裸字段。

| 情形 | base_url / model / key | json_mode / timeout_s |
|---|---|---|
| `AI_PROVIDER` 空（legacy） | 直读全局三项，**零变化** | 全局 / 全局 |
| `AI_PROVIDER=deepseek`\|`lmstudio` | **只读该档，绝不回落全局**（防把云端 Key 发给本地端点） | 该档非空取该档，空则回落全局 |
| 未知 provider 名 | `ready=false` → 调用时 503 中文「AI_PROVIDER 未识别，可用 deepseek / lmstudio」 | — |
| 该档 base_url/model 缺失 | `ready=false` → 503 中文「未配置」 | — |

`ai_configured` = `ready`：legacy＝key 非空（**语义零变化**）；具名档＝base_url+model 齐备（key 可空，本地无鉴权）。`get_settings.cache_clear()` 后即时生效（测试与切换依赖此点）。

### 3.2 response_format 策略（`ai.py::_chat`）

| `AI_JSON_MODE` | 请求体 | 适配 |
|---|---|---|
| `json_object`（缺省） | `"response_format":{"type":"json_object"}` | DeepSeek / OpenAI，与现在逐字一致 |
| `none` | **整键不发**（也不发 `{"type":"text"}`） | LM Studio 等仅接受 text/json_schema 的端点 |
| `json_schema` | 本轮**不实现**（落在闭集外 → 503 中文提示） | 后续需与 pydantic `model_json_schema()` 联动 |

- `Authorization` 仅当 key 非空才发送；`Content-Type` 恒发。
- 超时优先级：调用点显式 `timeout_s`（面试单题 `SCORING_TIMEOUT_S=14` 保持不变）> 该档 `timeout_s` > 全局 `ai_timeout_s`。⚑ 本地档必须配 180，否则画像必 503。
- 重试不变：`ai_max_retries+1` 次，第二次提示追加 `JSON_RETRY_HINT`；与 json_mode 无关，`none` 下同样生效。
- 错误语义不变、永不 500：超时/连接/429/5xx → `AI_UNAVAILABLE` 503；其它 4xx → 502；非 JSON / 校验失败 → `AI_SCHEMA_INVALID` 502 `retryable=true`（小模型缺字段、类型漂移即走此路）。

### 3.3 可观测性与测试确定性

- `HealthResponse` 增 `ai_provider / ai_model / ai_json_mode`（**白名单，不含 key 的任何片段**）；`types.ts` 的 `Health` 镜像为可选 `string`。
- `health()` 改为处理内 `get_settings()`（live 读取），修掉「import 期闭包 + lru_cache 导致环境敏感」。
- `test_health_returns_ok`：改走 `client` fixture（其 `tmp_db` 置空 `AI_API_KEY`/`AI_PROVIDER` 并清缓存），断言 `ai_configured is False`、`ai_provider=="legacy"`、`ai_model` 为非空字符串、响应体不含 `key`/`sk-`——**任何开发者本机 `.env` 下都确定**。
- `conftest.tmp_db` 追加 `monkeypatch.setenv("AI_PROVIDER","")` 与各档关键变量置空：宿主把 `AI_PROVIDER` 设成 lmstudio 时既有 300+ 例也不会集体变红。

### 3.4 小模型鲁棒性（只改传输，不放松校验）

沿用既有三条机制：围栏/解释文字剥离、第二次追加 JSON 约束、`AI_SCHEMA_INVALID` 中文降级；单测钉住 ```json 围栏 / 前后解释文字 / 纯文本三形态。**不放宽**：不加 `extra="allow"`、不把缺字段补空串、不动 `source_quote` 反幻觉校验。

## 4 行为兼容影响

- **唯一的用户可见变化**：`/health` 多 3 个只读字段（前端不渲染）；切换供应商后「生成质量与耗时」随模型而变（本地 9B 更慢、可能更差，走既有中文降级），**不新增任何 UI 或交互**。
- **零变化保证**：不设 `AI_PROVIDER`/`AI_JSON_MODE` 时，DeepSeek/OpenAI 的请求体、错误码、超时、重试、提示词逐字一致；r8 的 null 口径与 20 条 AC 全部保持；`schemas.py` ↔ `types.ts` 同步新增（AGENTS 硬约束）。

## 5 回归与验证计划

门禁地板（只增不减）：pytest ≥ **305 + 新增 ≥12**（期望 ≥317 全绿）、vitest ≥109、typecheck 0 error、lint 0 error / ≤28 warning、build 通过、`/health` 200、**零新依赖**。

新增用例清单：legacy 解析零变化 / 具名档取值且 key 不回落 / 空 key 无 `Authorization` / 三档 `response_format` 请求体 / 未知 provider 503 / 缺 base_url 503 / 围栏三形态 / `json_mode=none` 下重试追加约束 / `/health` 三字段且响应体无 key / 闭集互锁门禁（`ai_json_mode` 闭集 + `ai.py` 内无第二处硬编码 `json_object`）。**门禁不得依赖本机 LM Studio**：真实链路用 `AI_LIVE=1` 跳过开关 + QA 脚本，pytest 恒离线。

```
cd backend && python -m pytest -q -p no:cacheprovider
cd backend && python -m pytest -q -p no:cacheprovider tests/test_ai_provider.py tests/test_health.py
cd backend && python -m ruff check app tests            # 本机可能缺 ruff，如实记录不绕过
cd frontend && npm run typecheck && npm run lint && npx vitest run && npm run build
curl -sS http://127.0.0.1:8000/health
cd frontend && grep -riE "sk-|api_key|AI_API_KEY" src/ dist/ || echo NO_KEY_LEAK
git status --porcelain=v1 -uall && git branch --show-current
```

真实切换验收（QA 必测，先本地后云端）：
1. `AI_PROVIDER=lmstudio`（`http://localhost:1234/v1` / `qwen3.5-9b` / `json_mode=none` / `timeout=180`）→ 上传 → `POST /api/resumes/{id}/profile` **200**，skills/projects/target_role 有值，`source_quote` 在正文逐字命中；若该小模型确实产不出合规结果，**如实记录降级表现，不得伪造通过**。
2. `AI_PROVIDER=deepseek` 同链路再跑 **200**，两次的 provider/model 均可从 `/health` 读到。
3. 报告附：切换前后 `/health` 输出、两次请求状态与耗时、`response_format` 三档对照表；**零 Key 泄露**。

## 6 风险与回滚

| 风险 | 处置 |
|---|---|
| 云端 Key 被发往本地端点 | 具名档 base_url/model/key 一律不回落全局（§3.1 硬规则） |
| `/health` 泄露密钥 | 字段白名单 + 用例断言响应体不含 `key`/`sk-` |
| 宿主 `.env` 的 `AI_PROVIDER` 让既有用例集体变红 | `conftest.tmp_db` 强制置空；三种环境（未设 / lmstudio / deepseek）各跑一次 |
| 本地 9B 长输出超时 / 不合 schema / 产出不达画像标准 | 档内 180s + 既有 `AI_SCHEMA_INVALID` 中文降级，结果如实报告；**不放宽校验**（属产品决策，只记录证据） |

回滚：**配置级**——删 `AI_PROVIDER`/`AI_JSON_MODE` 即完全回到当前行为（零代码回滚）；**代码级**——revert 本单 9 个改动文件（无 DDL、无数据迁移、无新依赖，回滚无副作用）。

## 7 假设与待澄清

1. 档位变量取「扁平前缀 `AI_DEEPSEEK_*` / `AI_LMSTUDIO_*`」，未取「`AI_PROVIDERS` JSON 字典或 `__` 嵌套」；若改字典，只需重写 `config.py` 解析器与 `.env.example`，其余方案不变。
2. 新增第三套供应商需在 `config.py` 加 5 个显式字段；若要求「零代码新增任意供应商」，须改成环境变量前缀扫描（与 pydantic-settings 单一配置源冲突）——待运维确认。
3. 具名档**不回落**全局 base_url/model/key 是安全取舍；若团队宁愿「只覆盖 model、其余复用全局」，等于放弃防泄漏规则（不推荐）。
4. `json_schema` 本轮不做（闭集只收 `json_object`/`none`）；若必须支持，改动面 +`ai.py`（注入 `model_json_schema()`）与一档回归用例。
5. LM Studio 的 model 名不设默认（须显式 `AI_LMSTUDIO_MODEL=qwen3.5-9b`）；若要求自动探测 `/v1/models`，需新增外网调用与缓存，会破坏「`/health` 不联网」原则。
6. `ai_configured` 语义按 provider 分化（legacy＝有 Key；具名＝base_url+model 齐备）；若要求该字段恒指「有 Key」，需另加 `ai_ready` 而不动旧字段。
7. `/health` 新增字段是否纳入前端契约镜像：本单按 AGENTS 规则镜像到 `types.ts`（仅可选类型、不渲染）；若判定 health 不属镜像范围，可撤这 1 处改动。
