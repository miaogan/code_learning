# ARCHITECTURE · 开发者能力提升教练（dev-skill-coach）工程方案与脚手架

> 基线依赖：`docs/teamflow/20261031-r1-dev-skill-coach/DESIGN.md`（视觉 / 信息架构唯一真源，本文件不重复其数值）。
> 定位：产品级长期文档。任务级契约（PRD / 技术方案 / QA）在任务夹内，不在本文件。
> 本文只描述**已经落盘**的骨架与下游要填的坑；标「待」的条目一律列在 §7，不算已完成。

---

## 1. 选型结论与权衡

| 层 | 选型 | 版本基线 | 一句话理由 |
| --- | --- | --- | --- |
| 前端 | React 18 + Vite 5 + TypeScript 5 | `react ^18.3`、`vite ^5.4`、`typescript ^5.5` | 6 页线性向导、无 SSR 需求，Vite 冷启动最快、心智负担最低 |
| 路由 | react-router-dom v6 | `^6.26` | 6 条静态路由 + NavLink 步骤态，无需文件路由 |
| 样式 | 手写 CSS + CSS 变量 token | `src/styles/tokens.css` | DESIGN §0 是写死规格（token / 几何 / 逐组件状态色），CSS 变量最贴近、产物零运行时 |
| 后端 | Python 3.11+ + FastAPI + uvicorn | `fastapi>=0.110` | 与简历解析（pypdf / python-docx）与 AI 结构化校验（pydantic）天然同栈 |
| 模型调用 | httpx 异步调用 OpenAI 兼容 `/chat/completions` | `httpx>=0.27` | 单一入口、超时/重试/JSON 兜底集中在一个模块 |
| 持久化 | SQLite（标准库 `sqlite3`，`backend/app.db`） | 3.x | 4 张表、单用户、零外部服务；手写 SQL 比引 ORM 更轻 |
| 测试 | pytest + ruff（后端）/ vitest + tsc + eslint（前端） | — | 只需在两处夹具中防回归，不引 E2E 框架（首版无浏览器自动化要求） |
| CI | GitHub Actions 双 job | — | 与本地命令等价，便于「网关失败即定位」 |

### 1.1 四个关键取舍（放弃的方案 + 代价）

1. **不做 SSR / Next.js**：产品是本地单用户工具，无 SEO、无分享页、无服务端渲染诉求。放弃：SSR、文件路由、RSC 全套。代价：路由表手写 6 条、首屏无 HTML 直出 —— 可接受，因为首屏只等本地 `/health`。
2. **后端选 Python 而非 Node**：AI 与文档解析两件事都在 Python 生态里更成熟，`pypdf` / `python-docx` 直接解决 AC-1，`pydantic` 直接承担 AC-2 / AC-5 的 schema 校验与「非法 JSON → 一次重试」。放弃：单运行时（全 TS）的部署便利。代价：需要 Node + Python 两套工具链；用根 README 三步（前端 `npm i`、后端 `venv`、`.env`）与 CI 双 job 兜住。
3. **SQLite 直连、不用 ORM / 迁移框架**：首版仅 `documents / profiles / runs / reports` 4 表，单进程本地库。放弃：SQLModel、alembic。代价：手写 SQL、改字段要自己写升级语句 —— 应对方式是把**结构化产物（画像 / 报告 / 试卷）以 JSON 文本列存**，表结构只保留 id、外键、时间戳与状态，schema 演进上移到应用层 pydantic 校验（见 §3.4）。
4. **样式手写 CSS、不用 Tailwind / CSS-in-JS**：DESIGN §0.7 的 6 处几何（40 按钮 / 24 徽章 / 96 磁贴 / 132 课程卡 / 128 textarea / 64-56 环）是**恰好闭合**的推导，任何 utility 类拼装都会让尺寸漂移。放弃：原子类书写效率。代价：类名集中维护，约定「组件类以 `.sc-` 前缀 + BEM-lite 命名」，新增组件必须复用 token、禁止写裸色值。

---

## 2. 目录树（本仓库实际结构，`*` 为已落盘）

```
code_learning/                        # 产品根 = 工作区根（本产品线独占该仓库）
├─ AGENTS.md                          # 团队守则 + 文档索引 + TeamFlow 托管区 *
├─ README.md                          # 三步运行 / 验收速览 *
├─ .editorconfig                      # 跨编辑器基础统一 *
├─ .gitignore                         # 构建产物 / 缓存 / 密钥 / 本地库 *
├─ .github/workflows/ci.yml           # 双 job（前端 build+test、后端 lint+test）*
├─ docs/teamflow/
│  ├─ architecture/ARCHITECTURE.md    # 本文件（产品级长期文档）*
│  ├─ memory.md                       # 跨需求约定 / 待办（低频更新）*
│  └─ 20261031-r1-dev-skill-coach/    # 任务夹（PRD / DESIGN / 技术方案 / QA / 验收）
├─ frontend/                          # Vite + React + TS 单页应用
│  ├─ index.html                      # 挂载点 + 中文 lang *
│  ├─ package.json / package-lock.json
│  ├─ tsconfig.json                   # 应用侧（DOM / bundler / strict）
│  ├─ tsconfig.node.json              # 构建脚本侧（vite.config.ts）
│  ├─ vite.config.ts                  # 插件 + /api、/health 代理 + vitest 配置 *
│  ├─ eslint.config.js                # ESLint 9 flat config *
│  ├─ .env.example                    # 仅 VITE_API_BASE（不含任何密钥）*
│  └─ src/
│     ├─ main.tsx                     # 入口：BrowserRouter 挂载 *
│     ├─ App.tsx                      # 全局壳：顶栏 56 + 侧栏 240 / <1024 顶部步骤条 *
│     ├─ vite-env.d.ts                # import.meta.env 类型 *
│     ├─ api/client.ts                # fetch 封装 + 错误 envelope 解析 *
│     ├─ api/types.ts                 # 与后端 schema 同构的 TS 类型（snake_case）*
│     ├─ lib/format.ts               # 分数 / 用时 / 字数格式化（mono 数值统一入口）*
│     ├─ state/flow.ts               # 步骤进度标记（localStorage，useSyncExternalStore）*
│     ├─ styles/tokens.css           # DESIGN §0.2–0.4 全量 token *
│     ├─ styles/base.css             # reset + 壳布局 + 组件类（`.sc-*`）*
│     ├─ components/ui/              # 通用件：Button / Card / Chip / RingProgress /
│     │                                Stepper / PhaseLoader / InlineError / EmptyState *
│     ├─ pages/                      # 6 页：Upload / Profile / Interview / Exam / Report / History *
│     └─ test/format.test.ts         # vitest 单测（格式化函数）*
└─ backend/                           # FastAPI 服务
   ├─ requirements.txt                # 运行时 + 测试依赖 *
   ├─ pyproject.toml                  # ruff / pytest 配置（不打包发布）*
   ├─ .env.example                    # AI_* / DB_PATH / CORS 示例（无真实 key）*
   ├─ app/
   │  ├─ __init__.py
   │  ├─ main.py                      # app 工厂、lifespan 建库、CORS、异常处理器、GET /health *
   │  ├─ config.py                    # pydantic-settings：AI_* / DB_PATH / 上传上限 *
   │  ├─ db.py                        # sqlite3 连接 + 4 表 create-if-not-exists *
   │  ├─ errors.py                    # AppError → 统一错误 envelope（中文 message）*
   │  ├─ schemas.py                   # Profile / Question / Report / Course / ErrorBody *
   │  ├─ routers/                     # resume / profile / interview / exam / report / courses / history *
   │  ├─ services/                    # parser / ai / profile / interview / exam / diagnosis / courses *
   │  └─ seed/{courses.json, questions.json}   # 精选清单（人工维护，便于集中换链）*
   ├─ tests/{test_health.py, test_courses.py, test_resume_guard.py}   # pytest *
   └─ app.db                          # 运行时生成（gitignore）
```

运行日志：`logs/teamflow/<runId>/` 仅 run 期间暂存，run 结束由 host 归档并从项目删除（已 gitignore）。

---

## 3. 模块切分与契约

### 3.1 前端模块

| 路径 | 职责 | 约束 |
| --- | --- | --- |
| `src/App.tsx` | 全局壳、6 路由、步骤导航状态 | 不发起业务请求 |
| `src/api/client.ts` | 唯一 HTTP 出口：base 解析、JSON、错误 envelope → `ApiError` | 页面与组件**禁止**直接 `fetch` |
| `src/api/types.ts` | 契约类型（字段名与后端一致，snake_case） | 改字段必须同步 `backend/app/schemas.py` |
| `src/state/flow.ts` | `hasResume / hasProfile / hasReport` 三标记 + 订阅 | 仅作步骤门禁提示；**后端为权威** |
| `src/styles/tokens.css` | DESIGN §0.2–0.4 全部变量 | 禁止组件内写裸色值 / 裸 px 尺寸 |
| `src/components/ui/*` | 通用件（无业务语义） | 只接 props，不 import `api` |
| `src/pages/*` | 页面装配、状态机（idle/loading/error/empty/success） | 只经 `api/client.ts` 取数 |
| `src/lib/format.ts` | 数值/时长/字数格式化，保证 mono + tabular | 分数永远 ≤3 字符（DESIGN §0.7 第 2 条） |

### 3.2 后端模块

| 路径 | 职责 | 已实现 / 待填 |
| --- | --- | --- |
| `app/main.py` | app 工厂、CORS（5173/127.0.0.1）、`AppError` → envelope、`GET /health` | ✅ 已实现 |
| `app/config.py` | `Settings`（AI_BASE_URL / AI_API_KEY / AI_MODEL / AI_TIMEOUT_S / DB_PATH / 上传上限） | ✅ |
| `app/db.py` | 连接、`init_db()` 建 4 表、`get_connection()` 依赖 | ✅（表结构见 §3.4） |
| `app/errors.py` | 错误码常量 + `AppError` | ✅ |
| `app/schemas.py` | pydantic v2 模型（Profile 5 维度 / 题目 / 报告 / 课程） | ✅ 模型齐备，AI 侧未接 |
| `app/routers/resume.py` | `POST /api/resumes` 上传 → 校验 → 抽取 → 入库 → 元信息 | ✅ 文本/ PDF / DOCX 抽取（依赖装好后生效） |
| `app/routers/profile.py` | `POST /api/resumes/{id}/profile`、`GET|PATCH /api/profiles/{id}` | ⛔ 501 待 M2 |
| `app/routers/interview.py` | 出题 / 逐题作答评分 | ⛔ 501 待 M3 |
| `app/routers/exam.py` | 出卷 / 提交判分 | ⛔ 501 待 M3 |
| `app/routers/report.py` | 生成诊断报告 / `GET /markdown` | ⛔ 501 待 M4 |
| `app/routers/history.py` | 历史记录列表 | ⛔ 501 待 M5 |
| `app/routers/courses.py` | `GET /api/courses`（读 seed，校验 ≥20 门且 ≥3 门入门） | ✅ |
| `app/services/parser.py` | 类型白名单、10MB、空文件/加密 PDF 中文错误、`chars/sections` 统计 | ✅ |
| `app/services/ai.py` | OpenAI 兼容客户端：`complete_model(system, user, Model)`，超时、1 次重试、非法 JSON → `AI_SCHEMA_INVALID` | ✅（无 key 时抛 `AI_UNAVAILABLE`，页面得中文提示而非 500） |
| `app/services/{profile,interview,exam,diagnosis}.py` | 提示词 + 校验 + 落库 | ⛔ 待 M2–M4（仅签名与契约注释） |
| `app/services/courses.py` | 加载 seed、按方向/短板匹配（含「无匹配兜底」） | ✅ 加载与匹配骨架 |

### 3.3 HTTP 契约（单一前缀 `/api`）

| 方法 | 路径 | 请求 | 成功响应 | 备注 |
| --- | --- | --- | --- | --- |
| GET | `/health` | — | `{status, version, ai_configured, db}` | AC-8 即时探活 |
| POST | `/api/resumes` | multipart `file` | `{resume_id, file_name, chars, sections}` | AC-1；错误码见 §3.5 |
| POST | `/api/resumes/{resume_id}/profile` | — | `Profile` | 501 待 M2（AC-2） |
| GET | `/api/profiles/latest` | — | `Profile` | 404 = 尚无画像（前端引导态） |
| PATCH | `/api/profiles/{id}` | `ProfilePatch` | `Profile` | 逐条编辑（AC-2） |
| POST | `/api/interviews` | `{profile_id}` | `{run_id, questions[]}` | 501 待 M3（AC-3） |
| POST | `/api/interviews/{run_id}/answers` | `{question_id, answer}` | `{score, comment}` | 失败不丢答案由前端保证 |
| POST | `/api/exams` | `{profile_id}` | `{run_id, questions[]}` | 501 待 M3（AC-4） |
| POST | `/api/exams/{run_id}/submit` | `{answers[]}` | `{total, correct_count, elapsed_s, per_question[]}` | 501 待 M3 |
| POST | `/api/reports/generate` | `{run_ids[]}` | `Report` | 501 待 M4（AC-5/6） |
| GET | `/api/reports/latest` | — | `Report` | 404 = 未生成 |
| GET | `/api/reports/{id}/markdown` | — | `text/markdown` | AC-9（P1） |
| GET | `/api/history` | — | `RunSummary[]` | AC-10（P1） |
| GET | `/api/courses` | — | `Course[]` | ✅ AC-6 数据面 |

**错误 envelope**（全站唯一形态，HTTP 状态码取 4xx/5xx）：

```json
{ "error": { "code": "FILE_TOO_LARGE", "message": "文件超过 10MB，请压缩或分卷", "retryable": false } }
```

`code` 闭集（`app/errors.py` 常量）：`EMPTY_FILE` `ENCRYPTED_PDF` `FILE_TOO_LARGE` `UNSUPPORTED_TYPE` `PARSE_FAILED` `AI_UNAVAILABLE` `AI_SCHEMA_INVALID` `NOT_IMPLEMENTED` `NOT_FOUND` `VALIDATION_ERROR`。**message 一律中文**，且不含文件绝对路径、堆栈、模型端点或 key。

### 3.4 数据模型（SQLite，`backend/app.db`）

| 表 | 关键列 | 用途 |
| --- | --- | --- |
| `documents` | `id TEXT PK, file_name, mime, chars INT, sections INT, text TEXT, created_at TEXT` | 简历正文（原文件**不落盘**，仅在内存解析后入库正文，缩小敏感数据面） |
| `profiles` | `id TEXT PK, document_id TEXT, payload TEXT(JSON), created_at, updated_at` | AC-2 画像；5 维度整体 JSON，靠 pydantic 校验而非列约束 |
| `runs` | `id TEXT PK, kind TEXT('interview'|'exam'), profile_id, payload TEXT(JSON), status TEXT, created_at` | AC-3/4 测评；逐题得分与答案都在 payload |
| `reports` | `id TEXT PK, payload TEXT(JSON), created_at` | AC-5/6 诊断报告（短板 + 课程映射） |

约定：时间为 ISO-8601 UTC 字符串；payload 存 JSON 文本，读写两侧过 pydantic 模型；`init_db()` 只用 `CREATE TABLE IF NOT EXISTS`，字段变更需在 `memory.md` 记录一次性升级说明（不做迁移框架）。

### 3.5 上传解析契约（AC-1）

- 白名单：`.pdf` `.docx` `.txt`（按扩展名 + 声明 MIME 双校验）；上限 `MAX_UPLOAD_MB=10`，超限先于解析拒绝（不读全文件到内存的边界由 Starlette 表单大小检查兜住）。
- 失败映射：空内容 / 0 字节 → `EMPTY_FILE`；PDF 加密 → `ENCRYPTED_PDF`；超限 → `FILE_TOO_LARGE`；类型不在白名单 → `UNSUPPORTED_TYPE`；抽取异常 → `PARSE_FAILED`。**任何失败都不写库**，因此不会生成画像数据（AC-1 末句）。
- 统计规则：`chars` = 正文去空白后字符数；`sections` = 命中「教育 / 工作经历 / 项目 / 技能」等标题行的数量，上限 99。

### 3.6 AI 调用契约（`app/services/ai.py`）

`async def complete_model(system, user, model_cls, *, retries=1) -> BaseModel`：单次 HTTP 超时 `AI_TIMEOUT_S=20`；把模型输出剥 ``` 围栏后 `json.loads`，再 `model_cls.model_validate`；**校验失败重试 1 次**（第二次在 user 后追加「只输出 JSON」）；仍失败 → `AI_SCHEMA_INVALID`；网络 / 401 / 429 / 超时 → `AI_UNAVAILABLE`（`retryable` 视 4xx 除外为 true）。无 `AI_API_KEY` 时**不发请求**，直接 `AI_UNAVAILABLE` 中文提示。调用方（M2–M4）必须传 pydantic 模型，禁止返回裸 dict。

### 3.7 流程状态与门禁

- 步骤门禁：`state/flow.ts` 的 localStorage 标记只用于「侧栏对勾 + 提示先完成上一步」；**刷新后的真实数据以 `GET /api/profiles/latest`、`GET /api/reports/latest` 为准**（避免标记与库不一致）。
- 未上传简历时直达 `/profile` `/interview` `/exam` `/report`：目标页渲染 `EmptyState`（原因句 + 主按钮「上传简历」），**不重定向、不白屏**（DESIGN §4.3）。
- 前端不出现任何 Key / 端点 / 模型名（AC-8）；`.env.example` 只给 `VITE_API_BASE`。

---

## 4. 依赖清单

### 4.1 前端（`frontend/package.json`）

运行时：`react ^18.3`、`react-dom ^18.3`、`react-router-dom ^6.26`（3 个，刻意保持极薄）。
开发：`vite ^5.4`、`@vitejs/plugin-react ^4.3`、`typescript ^5.5`、`@types/react`、`@types/react-dom`、`@types/node`、`vitest ^2.0`、`eslint ^9`、`@eslint/js`、`typescript-eslint ^8`、`eslint-plugin-react-hooks`、`eslint-plugin-react-refresh`、`globals`。
策略：semver 区间 + **`package-lock.json` 需在首次可联网安装后提交**（`npm ci` 依赖它；本机环境未能生成，见 §7.2）；CI 用 `npm ci`。不引 UI 组件库（规格已定死）、不引状态库、不引 Tailwind。

### 4.2 后端（`backend/requirements.txt`）

`fastapi>=0.110`、`uvicorn[standard]>=0.29`、`pydantic-settings>=2.2`、`python-multipart>=0.0.9`（上传表单）、`httpx>=0.27`（模型调用 + TestClient）、`pypdf>=4.0`（PDF 文本层）、`python-docx>=1.1`（DOCX）、`pytest>=8.0`、`ruff>=0.4`。
线程模型：FastAPI 同步路由跑在 threadpool（解析类阻塞调用安全）；`ai.py` 用 `httpx.AsyncClient`，异步路由不阻塞事件循环。

---

## 5. 构建 / 运行 / 测试 / CI

| 目的 | 命令（在 `frontend/`） |
| --- | --- |
| 开发 | `npm run dev`（:5173，`/api` `/health` 代理到 :8000） |
| 类型检查 | `npm run typecheck`（`tsc -p tsconfig.json --noEmit` + node 侧项目） |
| 构建 | `npm run build`（typecheck 后 `vite build`） |
| 单测 | `npm test`（vitest run，当前覆盖 `lib/format.ts`） |
| Lint | `npm run lint`（ESLint 9 flat config，含 react-hooks / react-refresh） |

| 目的 | 命令（在 `backend/`，激活 venv 后） |
| --- | --- |
| 安装 | `python -m venv .venv && .venv/Scripts/pip install -r requirements.txt`（macOS/Linux 用 `bin/pip`） |
| 启动 | `.venv/Scripts/python -m uvicorn app.main:app --reload --port 8000` |
| 测试 | `.venv/Scripts/python -m pytest -q` |
| Lint | `.venv/Scripts/python -m ruff check app tests` |
| 探活 | `curl http://127.0.0.1:8000/health` → `{"status":"ok",...}` |

**CI（`.github/workflows/ci.yml`）**：`frontend` job（node 22，`npm ci` → typecheck → lint → test → build）；`backend` job（python 3.11，pip 缓存，`ruff check` → `pytest -q`）。两个 job 独立，任一失败即红；无部署步骤（首版本地运行）。密钥只经 `.env`，CI 中不注入真实 key，测试用 `AI_API_KEY` 缺失路径验证「中文提示而非 500」。

---

## 6. 安全与密钥（AC-8 落点）

1. 前端不读、不写、不显示任何模型密钥；唯一可配项是 `VITE_API_BASE`（默认空 = 走 Vite 代理），构建产物中检索不到 key（CI 后端 job 的测试不含 key，前端无相关代码）。
2. `backend/.env` 与 `.env.*` 全部 gitignore（仅保留 `*.example`）；`.gitignore` 已补齐 node_modules / dist / `__pycache__` / `.venv` / `*.db` / `*.log` 等。
3. 上传统一「不落原文件、只存正文」；错误响应不回传路径、堆栈、内部端点；uvicorn 访问日志不含请求体。
4. 首版为本地单用户、无鉴权（PRD §3 非目标），README 明确仅本地/内网运行，不暴露公网。

---

## 7. 落地清单（已落盘 / 未落盘，逐条可核对）

### 7.1 已落盘（有文件、有命令可验证）

| 项 | 证据 |
| --- | --- |
| 目录骨架（frontend / backend / docs / logs / .github） | 实际目录树，见 §2 |
| 前端工程配置 | `package.json`、`tsconfig*.json`、`vite.config.ts`、`eslint.config.js`、`index.html`、`.env.example` |
| 前端壳与 6 路由 | `src/main.tsx`、`src/App.tsx`、`src/pages/*.tsx` |
| 设计 token 与组件类 | `src/styles/tokens.css`、`src/styles/base.css`（含 40 按钮 / 24 徽章 / 96 磁贴 / 132 课程卡 / 128 textarea / 环 64-56 的 CSS 尺寸） |
| 通用件 8 个 | `src/components/ui/*.tsx` |
| API 契约类型 + fetch 封装 | `src/api/{types,client}.ts` |
| 后端 app 工厂 / 配置 / 建库 / 错误 envelope / `/health` | `backend/app/{main,config,db,errors}.py` |
| 上传解析链路（文本 / PDF / DOCX + 四类中文错误） | `backend/app/services/parser.py`、`routers/resume.py` |
| AI 客户端骨架（超时 / 重试 / schema 校验 / 无 key 提示） | `backend/app/services/ai.py` |
| 课程清单 25 门 + `/api/courses` | `backend/app/seed/courses.json`、`services/courses.py` |
| pydantic 契约模型（画像 5 维度 / 题目 / 报告 / 课程） | `backend/app/schemas.py` |
| 后端测试 3 文件 | `backend/tests/*.py` |
| CI 双 job | `.github/workflows/ci.yml` |
| AGENTS.md + memory.md + README | 仓库根与 `docs/teamflow/` |

### 7.2 未落盘（明确未完成，不计入「已完成」）

| 项 | 现状 | 归属 |
| --- | --- | --- |
| 画像生成（AC-2 端到端） | 路由返回 501 `NOT_IMPLEMENTED`，prompt / 校验 / 编辑保存未写 | M2 |
| 面试出题与逐题评分（AC-3） | 501，含「失败不丢答案」的前端状态机未接 | M3 |
| 笔试卷生成与判分（AC-4） | 501，计时与未答确认未接 | M3 |
| 诊断报告与课程匹配（AC-5/6 端到端） | 501，严重度算法 + Markdown 导出未写 | M4 |
| 历史与趋势（AC-9/AC-10） | 501，页面仅空态 | M5 |
| 题库种子量 | 仅 12 道（frontend/backend/algorithm/basics 各 3），目标 ~80 | M2/M3 |
| 前端页面业务态 | 6 页均只有「引导空态 + 壳」，卡片/答题/报告 UI 未接 | M2–M5 |
| 真实 PDF / DOCX 解析实测 | 代码已写，但本机缺 `pypdf` / `python-docx` 且 pip 安装被 sandbox 拒绝，**未用真实文件验证** | M2 |
| 前端依赖与构建（typecheck / lint / vitest / build） | **未执行**：本机 sandbox 拒绝 npm 生命周期脚本 spawn（`EPERM`），`node_modules` 装不起来；只做了 import 图静态校验（30 条相对引用全部可解析、22 个模块） | 依赖装好后第一件事 |
| `frontend/package-lock.json` | **未生成**（同上；`npm ci` 尚不可用，CI 前端 job 会因缺 lockfile 失败） | 首次联网安装 |
| 后端 ruff lint 实跑 | **未执行**：全局 Python 无 `ruff`，`venv` 创建被 sandbox 拒绝（`WinError 5`）；`pytest` 10 项已实跑通过 | 验收前补跑 |
| E2E / 浏览器自动化 | 未建（首版无该要求） | — |
| CI 实跑 | workflow 已写，**未在 GitHub 上真跑过**；后端等价命令（pytest）本地已通过，前端等价命令受上述环境限制未跑 | 验收前 |
| Docker 打包 / 一键启动脚本 | 未做（README 为三步手动流程） | 后续 |

---

## 8. 下游交接（谁在哪填哪）

- **M2 画像**：`services/profile.py`（prompt + `Profile` 校验）、`routers/profile.py` 四个端点、`pages/ProfilePage.tsx` 五维卡 + `SourceQuote` + 原地编辑 + 「缺失来源」徽章、`seed/questions.json` 扩到 ~80。
- **M3 双测评**：`services/{interview,exam}.py`（出题 / 评分 / 判分）、`routers/{interview,exam}.py`、`pages/{InterviewPage,ExamPage}.tsx`（逐题单屏、得分环 56、计时环 64、粘性提交条）。
- **M4 报告**：`services/diagnosis.py`（严重度 + 优先级 + 课程映射兜底）、`routers/report.py`、`pages/ReportPage.tsx`（短板卡 / 证据 chip / 课程卡 132）。
- **M5 闭环**：`pages/HistoryPage.tsx` + `routers/history.py`、`GET /api/reports/{id}/markdown`、刷新持久化与 5 分钟演练、AC-8 产物级密钥核查。
- **统一约束（不许破）**：所有新组件复用 `tokens.css`；所有新端点返回 `AppError` envelope 与中文 message；所有改字段同步 `frontend/src/api/types.ts` ↔ `backend/app/schemas.py`；新增尺寸必须回写 DESIGN §0.7 的推导。
