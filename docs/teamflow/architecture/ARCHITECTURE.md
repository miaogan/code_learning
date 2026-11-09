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
| 持久化 | SQLite（标准库 `sqlite3`，`backend/app.db`） | 3.x | 7 张表、单用户、零外部服务；手写 SQL 比引 ORM 更轻 |
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
│     ├─ state/aiGate.ts             # AI 能力不足（403 AI_KEY_REQUIRED）全局提示，壳层横幅消费 *
│     ├─ styles/tokens.css           # DESIGN §0.2–0.4 全量 token *
│     ├─ styles/base.css             # reset + 壳布局 + 组件类（`.sc-*`）*
│     ├─ components/ui/              # 通用件：Button / Card / Chip / RingProgress /
│     │                                Stepper / PhaseLoader / InlineError / EmptyState / AiKeyBanner *
│     ├─ pages/                      # 6 页：Upload / Profile / Interview / Exam / Report / History *
│     └─ test/format.test.ts         # vitest 单测（格式化函数）*
└─ backend/                           # FastAPI 服务
   ├─ requirements.txt                # 运行时 + 测试依赖 *
   ├─ pyproject.toml                  # ruff / pytest 配置（不打包发布）*
   ├─ .env.example                    # AI_* / DB_PATH / CORS 示例（无真实 key）*
   ├─ app/
   │  ├─ __init__.py
   │  ├─ main.py                      # app 工厂、lifespan 建库、CORS、异常处理器、GET /health *
   │  ├─ core/                        # 基础设施：config / db / errors / repository / auth / context / observability *
   │  ├─ schemas.py                   # Profile / Question / Report / Course / ErrorBody *（契约硬约束，留顶层）
   │  ├─ deps.py                      # FastAPI 依赖（current_user 等）*
   │  ├─ routers/                     # auth / resume / profile / interview / exam / practice / report / courses / history / timeline *
   │  ├─ services/                    # 业务域分包：ai/ resume/ profile/ interview/ assessment/ report/（+ login_guard.py）*
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
| `src/state/aiGate.ts` | `AI_KEY_REQUIRED` 提示状态（client 上报、`AiKeyBanner` 消费） | 仅存文案，不做跳转；跳转由横幅按钮负责 |
| `src/styles/tokens.css` | DESIGN §0.2–0.4 全部变量 | 禁止组件内写裸色值 / 裸 px 尺寸 |
| `src/components/ui/*` | 通用件（无业务语义） | 只接 props，不 import `api` |
| `src/pages/*` | 页面装配、状态机（idle/loading/error/empty/success） | 只经 `api/client.ts` 取数 |
| `src/lib/format.ts` | 数值/时长/字数格式化，保证 mono + tabular | 分数永远 ≤3 字符（DESIGN §0.7 第 2 条） |
| `src/lib/practice.ts` | 练习页业务文案与纯逻辑唯一出处；方向 chip 由 `DIRECTION_LABEL` 派生 | `satisfies Record<Exclude<PracticeDirectionFilter,'all'>, string>`，新增方向漏项即 typecheck 红 |
| `src/components/exam/PromptBody.tsx` | 题面围栏（代码块/表格）渲染唯一出口 | 题卡与错题本共用，禁止各自解析 |

### 3.2 后端模块

| 路径 | 职责 | 已实现 / 待填 |
| --- | --- | --- |
| `app/main.py` | app 工厂、CORS（5173/127.0.0.1）、`AppError` → envelope、`GET /health` | ✅ 已实现 |
| `app/core/config.py` | `Settings`（AI_BASE_URL / AI_API_KEY / AI_MODEL / AI_TIMEOUT_S / DB_PATH / 上传上限） | ✅ |
| `app/core/db.py` | 连接、`init_db()` 建 7 表、`get_connection()` 依赖 | ✅（表结构见 §3.4；r6 增 `questions` / `question_attempts`） |
| `app/core/errors.py` | 错误码常量 + `AppError` | ✅ |
| `app/schemas.py` | pydantic v2 模型（Profile 5 维度 / 题目 / 报告 / 课程）；**HTTP 契约唯一真源** | ✅ 齐备；r5 起含 4 项面试设定（`InterviewSettings` / `InterviewSettingsPatch`）、会话与回合（`InterviewRun` / `InterviewTurn` / `InterviewSession`），`RunSummary` / `Report` 增 `interview_settings`；r44 设定扩为 6 键（可选 `direction` / `sub_direction`，空串 = 不限，老 payload 缺键仍合法） |
| `app/routers/resume.py` | `POST /api/resumes` 上传 → 校验 → 抽取 → 入库 → 元信息 | ✅ 文本/ PDF / DOCX 抽取（依赖装好后生效） |
| `app/routers/profile.py` | `POST /api/resumes/{id}/profile`、`GET|PATCH /api/profiles/{id}` | ⛔ 501 待 M2 |
| `app/routers/interview.py` | 开局 / 每轮作答 / 会话恢复（r5 契约 v2：只转发与错误 envelope，业务在 `services/interview/interview.py`） | ✅ 三路由 |
| `app/routers/exam.py` | 出卷 / 提交判分 | ✅ 已交付 |
| `app/routers/report.py` | 生成诊断报告 / `GET /markdown` | ✅ 已交付 |
| `app/routers/history.py` | 历史记录列表（r3 起含长期记忆聚合） | ✅ 已交付 |
| `app/routers/courses.py` | `GET /api/courses`（读 seed，校验 ≥20 门且 ≥3 门入门） | ✅ |
| `app/services/resume/parser.py` | 类型白名单、10MB、空文件/加密 PDF 中文错误、`chars/sections` 统计 | ✅ |
| `app/services/ai/ai.py` | OpenAI 兼容客户端：`complete_model(system, user, Model)`，超时、1 次重试、非法 JSON → `AI_SCHEMA_INVALID` | ✅（无 key 时抛 `AI_UNAVAILABLE`，页面得中文提示而非 500） |
| `app/services/{profile/profile,interview/interview,assessment/exam,report/diagnosis}.py` | 提示词 + 校验 + 落库 | ✅ 已交付；`interview.py` 为 r5 会话引擎（比赛制/评分/追问/会话读取闭环） |
| `app/services/report/rules.py` | 阈值与口径唯一出处（r5 增 4 项面试配置闭集 + `experience_band_of` / `is_follow_up_allowed`） | ✅ |
| `app/services/report/courses.py` | 加载 seed、按方向/短板匹配（含「无匹配兜底」） | ✅ 加载与匹配骨架 |

### 3.3 HTTP 契约（单一前缀 `/api`）

| 方法 | 路径 | 请求 | 成功响应 | 备注 |
| --- | --- | --- | --- | --- |
| GET | `/health` | — | `{status, version, ai_configured, db}` | AC-8 即时探活 |
| POST | `/api/resumes` | multipart `file` | `{resume_id, file_name, chars, sections}` | AC-1；错误码见 §3.5 |
| POST | `/api/resumes/{resume_id}/profile` | — | `Profile` | AC-2 |
| GET | `/api/profiles/latest` | — | `Profile` | 404 = 尚无画像（前端引导态） |
| PATCH | `/api/profiles/{id}` | `ProfilePatch` | `Profile` | 逐条编辑（AC-2） |
| POST | `/api/interviews` | `InterviewCreateRequest`（`profile_id` + 可选 `settings` 4 项） | `InterviewRun`（`{run_id, settings, question, total}`，**只含第 1 条发言**） | 开局：补全 settings → 生成计划 → 闸门校验（≥8 题/技术 ≥5/项目 ≥3/挑战 ≤20%）→ 落库；不合规 502 且不落 run（AC-3） |
| POST | `/api/interviews/{run_id}/answers` | `{question_id, answer}` | `{score, comment, next_question, run_status, answered_count, total, interview_avg}` | 每轮一次 AI 调用同轮产出「评分 + 下一条发言」（可追问，带 `parent_id`）；先算后写，失败零副作用（AC-5/AC-9/AC-10） |
| GET | `/api/interviews/{run_id}` | — | `InterviewSession`（`{run_id, status, settings, questions[], answered_count, total, current_id, interview_avg}`） | **r5 新增**：刷新/重进恢复会话；`status=completed` ⇒ `current_id=null`（前端只读） |
| POST | `/api/exams` | `{profile_id}` | `{run_id, questions[]}` | AC-4 |
| POST | `/api/exams/{run_id}/submit` | `{answers[]}` | `{total, correct_count, elapsed_s, per_question[]}` | — |
| POST | `/api/reports/generate` | `{run_ids[]}` | `Report`（r5 起含 `interview_settings`） | AC-5/6 |
| GET | `/api/reports/latest` | — | `Report` | 404 = 未生成 |
| GET | `/api/reports/{id}/markdown` | — | `text/markdown` | AC-9（P1） |
| GET | `/api/history` | — | `RunSummary[]`（r5 起每行带 `interview_settings: InterviewSettings\|null`） | AC-10（P1）；`null` 前端渲染「未记录设定」，不出现 undefined |
| GET | `/api/courses` | — | `Course[]` | ✅ AC-6 数据面 |

**错误 envelope**（全站唯一形态，HTTP 状态码取 4xx/5xx）：

```json
{ "error": { "code": "FILE_TOO_LARGE", "message": "文件超过 10MB，请压缩或分卷", "retryable": false } }
```

`code` 闭集（`app/core/errors.py` 常量）：`EMPTY_FILE` `ENCRYPTED_PDF` `FILE_TOO_LARGE` `UNSUPPORTED_TYPE` `PARSE_FAILED` `AI_UNAVAILABLE` `AI_SCHEMA_INVALID` `NOT_IMPLEMENTED` `NOT_FOUND` `VALIDATION_ERROR` `HTTP_ERROR`（其它框架级状态透传）`METHOD_NOT_ALLOWED`（框架级 405 中文 envelope），r23 增 `AUTH_REQUIRED` `AUTH_INVALID` `AUTH_DISABLED` `AUTH_RATE_LIMITED`（HTTP 429，登录失败达阈值后锁定）`PASSWORD_INVALID` `FORBIDDEN` `AI_KEY_REQUIRED` `AI_QUOTA_EXCEEDED` `AI_KEY_STORE_UNAVAILABLE`。**message 一律中文**，且不含文件绝对路径、堆栈、模型端点或 key。

### 3.4 数据模型（SQLite，`backend/app.db`）

| 表 | 关键列 | 用途 |
| --- | --- | --- |
| `documents` | `id TEXT PK, file_name, mime, chars INT, sections INT, text TEXT, created_at TEXT` | 简历正文（原文件**不落盘**，仅在内存解析后入库正文，缩小敏感数据面） |
| `profiles` | `id TEXT PK, document_id TEXT, payload TEXT(JSON), created_at, updated_at` | AC-2 画像；5 维度整体 JSON，靠 pydantic 校验而非列约束 |
| `runs` | `id TEXT PK, kind TEXT('interview'|'exam'), profile_id, payload TEXT(JSON), status TEXT, created_at` | AC-3/4 测评；逐题得分与答案都在 payload |
| `reports` | `id TEXT PK, payload TEXT(JSON), created_at` | AC-5/6 诊断报告（短板 + 课程映射） |
| `timeline_events` | `id TEXT PK, type, ref_id, occurred_at, payload TEXT(JSON), created_at`，`UNIQUE(type, ref_id)` | r3 成长时间线：事件以 JSON 快照定格，重算报告不回写事件、分数不漂移 |
| `questions` | `id TEXT PK, direction, kind, difficulty, essentiality, prompt, options TEXT(JSON), answer TEXT(JSON), source, created_at, updated_at` | r6 **题库承载**（11 列）：`seed/questions.json` 退为唯一导入源；`answer` 只服务端可见，不入任何响应模型 |
| `question_attempts` | `id TEXT PK, question_id, run_id, correct INT(0/1), answered_at, created_at`，`UNIQUE(question_id, run_id)` | r6 客观题作答事件：熟练度判定的唯一事实源（简答不计分故永不写入） |

> 共 **7 张表**（r1 的 4 张 + r3 的 `timeline_events` + r6 的 `questions` / `question_attempts`）。DDL 只有 `app/core/db.py` 一处出处，SQL 只有 `app/core/repository.py` 一处出口。
>
> r23 追加 `users` / `sessions` / `ai_usage` 三张表，并给上表 6 张业务表（除共享题库 `questions`）各加
> `user_id TEXT NOT NULL DEFAULT 'default'`；存量行由 `ADD COLUMN ... DEFAULT` 直接回填为 `default`。见 §3.8。

约定：时间为 ISO-8601 UTC 字符串；payload 存 JSON 文本，读写两侧过 pydantic 模型；`init_db()` 只用 `CREATE TABLE IF NOT EXISTS`，字段变更需在 `memory.md` 记录一次性升级说明（不做迁移框架）。

#### 3.4.1 `runs.payload` v2（r5 起，面试会话的唯一真相）

面试不再"一次性下发 8 题"，payload 升级为**对话流会话**：`settings` / `calibration` / `plan` / `plan_index` / 递增 `questions[]` / `answered_count` / `total` / `follow_up_count` / `turn` / `current_id`。**零新表、零 SQL 迁移**（表结构不动，只加 JSON 字段），`version: 2` 仅用于读取分支。

- `questions[]` 只追加、永不变序，`id = iq-{len+1}` 单调；`len(questions) ≤ turn + 1`（running 时恰等于）⇒ **气泡条数 = 已提出题数**，不预先铺开未来题目。
- `parent_id ≠ null` 表示追问，且 `kind` 与父题逐字相同；追问配额 ≤ 4，`challenge` 类不生成追问（开局计划合格 ⇒ 结束仍合格）。
- `current_id` 指向唯一未答发言，结束置 `null`；它是**并发/重试的唯一推进依据**（重答旧题只覆盖分数，不追加发言、不推进 turn）。
- `settings`（4 项：`target_role` / `years_experience` / `market` / `company_size`）**只进 payload、绝不写回 `profiles`**（临时设定不污染长期资产）；每轮提示词由 `rules.py` 纯映射注入。
- `status` 不进 payload —— 权威在 `runs.status`（`running` / `completed`）。
- 向后兼容：旧 payload 缺 `settings`/`parent_id`/`plan`/`current_id` 逐字段降级（`null` / `null` / `[]` / 首个未答 id）；历史与报告投影读不到设定 → `interview_settings: null`，前端显示「未记录设定」。

#### 3.4.2 题库 id 前缀与 `source` 口径（r16 定稿）

外部素材（`docs/question-bank-staging/`）并入 seed 时，id 由 `question_merge.ID_PREFIX` 按「来源 + 源内原序（1 起，`%03d`）」生成；
**四前缀与来源一一对应、不得改名**（改名会让 `--rollback` 与已部署库的既有行分叉）：

| `source` | 种子 id 前缀 | 示例 | 素材 | 许可留痕 |
| --- | --- | --- | --- | --- |
| `tiji` | `tiji-` | `tiji-001` | `01-题集20.json`（20 道） | 自建，见 `PROVENANCE.md` |
| `local100` | `l100-` | `l100-001` | `02-本地100题.json`（100 道） | 自建，见 `PROVENANCE.md` |
| `iq380` | `iq380-` | `iq380-001` | `03-七方向379题.json`（379 道） | 自建，见 `PROVENANCE.md` |
| `fe-interview` | `fei-` | `fei-001` | `04-fe-interview20.json`（20 道，MIT） | `NOTICE-fe-interview.md` |

- `iq380-` **刻意不用 `iq-`**：面试发言 id 同为 `iq-{序号}`（`runs.payload.questions[].id`），同名不同域，
  数据不撞但 grep / 日志会混淆，故加宽前缀。
- 存量 260 道不写 `source`（读侧缺省 `seed`）；`source` 进种子与 `questions` 列，**不进 HTTP 契约**（`schemas.py` / `types.ts` 零改动）。
- 素材留痕统一在 `docs/question-bank-staging/`：自建三源看 `PROVENANCE.md`，MIT 源看 `NOTICE-fe-interview.md`。
- **历史笔误更正**：`docs/teamflow/20261102-r12-question-bank-merge/TECH-CHANGE.md` §3.2 写 `iq-NNN`，与实现（`iq380-`）不符；
  r12 任务夹为历史产物不可改，**以实现代码与本表为准**（r16 收口，见 `docs/teamflow/20261102-r16-d4-d6-closure/ACCEPTANCE.md`）。

#### 3.4.3 题库共享口径（练习 vs 笔试，r17 补记）

练习（`/practice`）与笔试（`/exam`）**共用同一个题库**：共享在「数据与判分」层，差异只在「取题与卷面约束」层。

| 层 | 共享 / 刻意不同 | 事实 |
| --- | --- | --- |
| 数据源 | 共享 | 两者都读 `questions` 表，唯一导入源是 `backend/app/seed/questions.json`（幂等导入） |
| 判分 | 共享 | 全库唯一客观题判分函数 `exam.grade_objective()`（集合相等），练习只调用不重写 |
| 作答记录 | 共享 | 都写 `question_attempts`，`source` 列区分 `exam` / `practice`（`run_id=practice:<session>` 命名空间） |
| 熟练度 | 共享 | 阈值只在 `config.py`；练习答对同样计入滑动窗口，练习与笔试**同一份**熟练题判定（默认跳过、超期或答错回流，r52） |
| 取题池 | 刻意不同 | 练习只收客观题 `kind ∈ {single, multiple, judge}`；笔试还收 `text` |
| 卷面结构 | 刻意不同 | 笔试受 10–12 题 / 客观 ≥8 / 挑战 ≤20% / 方向 ≥2 的结构闸门与 L1–L6 阶梯；练习无卷面闸门，只有筛选与题量 |
| 抽样 | 刻意不同 | 笔试从「可考池 − 熟练 − 近 3 卷」抽题；练习按用户筛选从池内取并默认排除熟练题，可重复练同一道未熟练的题（r52） |

理由：两者需要同一套「题面 / 答案 / 判分 / 熟练度」事实，但「卷面必须像一场考试」是笔试独有的产品约束；把结构闸门搬进练习会让「按语言筛 20 道」不可达。

### 3.5 上传解析契约（AC-1）

- 白名单：`.pdf` `.docx` `.txt`（按扩展名 + 声明 MIME 双校验）；上限 `MAX_UPLOAD_MB=10`，超限先于解析拒绝（不读全文件到内存的边界由 Starlette 表单大小检查兜住）。
- 失败映射：空内容 / 0 字节 → `EMPTY_FILE`；PDF 加密 → `ENCRYPTED_PDF`；超限 → `FILE_TOO_LARGE`；类型不在白名单 → `UNSUPPORTED_TYPE`；抽取异常 → `PARSE_FAILED`。**任何失败都不写库**，因此不会生成画像数据（AC-1 末句）。
- 统计规则：`chars` = 正文去空白后字符数；`sections` = 命中「教育 / 工作经历 / 项目 / 技能」等标题行的数量，上限 99。

### 3.6 AI 调用契约（`app/services/ai/ai.py`）

`async def complete_model(system, user, model_cls, *, retries=1) -> BaseModel`：单次 HTTP 超时 `AI_TIMEOUT_S=20`；把模型输出剥 ``` 围栏后 `json.loads`，再 `model_cls.model_validate`；**校验失败重试 1 次**（第二次在 user 后追加「只输出 JSON」）；仍失败 → `AI_SCHEMA_INVALID`；网络 / 401 / 429 / 超时 → `AI_UNAVAILABLE`（`retryable` 视 4xx 除外为 true）。无 `AI_API_KEY` 时**不发请求**，直接 `AI_UNAVAILABLE` 中文提示。调用方（M2–M4）必须传 pydantic 模型，禁止返回裸 dict。

### 3.7 流程状态与门禁

- 步骤门禁：`state/flow.ts` 的 localStorage 标记只用于「侧栏对勾 + 提示先完成上一步」；**刷新后的真实数据以 `GET /api/profiles/latest`、`GET /api/reports/latest` 为准**（避免标记与库不一致）。
- 未上传简历时直达 `/profile` `/interview` `/exam` `/report`：目标页渲染 `EmptyState`（原因句 + 主按钮「上传简历」），**不重定向、不白屏**（DESIGN §4.3）。
- 前端不出现任何 Key / 端点 / 模型名（AC-8）；`.env.example` 只给 `VITE_API_BASE`。
- r23 起 `flow.ts` 的键是 `sc.flow.<userId>`（`bindFlowToUser()` 随登录态切换命名空间），登出回匿名基线。

### 3.8 登录、会话与多用户隔离（r23）

| 路径 | 职责 |
| --- | --- |
| `app/core/auth.py` | `scrypt` 密码哈希 / 校验、会话 token（库里只存 SHA-256 摘要）、Cookie 读写（`sc_session`，HttpOnly + SameSite=Lax） |
| `app/core/context.py` | `ContextVar` 承载当前 `user_id`（缺省 `'default'`） |
| `app/deps.py` | **async** 依赖 `current_user`（sync 依赖跑线程池，ContextVar 写不回端点上下文）；类型别名 `CurrentUser = Annotated[...]` 规避 ruff B008 |
| `app/services/ai/user_ai.py` | per-user AI 单一出口：能力分级 `full \| light \| none`、内置 Key 每日配额、Fernet 加密存取 Key |
| `app/admin_cli.py` | 管理员建号（`--id` 可指定，如 `default` 接管存量）/ 切 Key 模式 / 停用 / 重置密码 / 列表 / `adopt-default` 存量改挂（不开放注册的唯一入口） |

- 隔离口径：`core/repository.py` 全部读写 SQL 带 `user_id` 条件；按 id 取数查不到即 404（不暴露跨用户存在性）。
- 能力分级：light = 画像生成 + 润色建议；heavy = 一键成稿 / 模拟面试（开局与每题）/ 诊断报告；笔试 / 练习 / 题库 / 时间线 / 历史 / 课程零 AI 不受限。
- `own` 未配 Key ⇒ `none`，heavy 直接 403 `AI_KEY_REQUIRED`（`retryable=false`）；`shared` 恒 `light` 且受 `SHARED_AI_DAILY_LIMIT` 约束（超限 429 `AI_QUOTA_EXCEEDED`）。
- Key 明文只进 `Fernet` 密文列，所有响应只回 `****后4位`；`SECRET_KEY` 为空时保存 Key 返回 503 `AI_KEY_STORE_UNAVAILABLE`。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/auth/login` | `{email,password}` → 设 Cookie + `MeResponse` |
| POST | `/api/auth/logout` | 204，清 Cookie |
| GET | `/api/me` | 当前用户 + `ai_capability` + `ai_masked_key` + 内置配额 `ai_quota_used` / `ai_quota_limit` |
| PUT | `/api/me/ai` | 保存/沿用 Key（`api_key` 缺省=不改） |
| DELETE | `/api/me/ai` | 清除自带 Key（保留 Base URL/模型），能力降 `none` |
| POST | `/api/me/ai/test` | 用表单/已存 Key 做一次最小调用 → `{ok,message}` |
| PATCH | `/api/me/password` | 204；旧会话全部失效 |


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
| 后端 app 工厂 / 配置 / 建库 / 错误 envelope / `/health` | `backend/app/main.py`、`backend/app/core/{config,db,errors}.py` |
| 上传解析链路（文本 / PDF / DOCX + 四类中文错误） | `backend/app/services/resume/parser.py`、`routers/resume.py` |
| AI 客户端骨架（超时 / 重试 / schema 校验 / 无 key 提示） | `backend/app/services/ai/ai.py` |
| 课程清单 25 门 + `/api/courses` | `backend/app/seed/courses.json`、`services/report/courses.py` |
| 画像生成（AC-2 端到端） | `services/profile/profile.py`、`routers/profile.py`（生成 / 读取 / 逐条编辑）、`pages/ProfilePage.tsx` 五维卡 + 溯源 |
| 双测评（AC-3/AC-4 端到端） | `services/interview/interview.py`、`services/assessment/exam.py`、`routers/{interview,exam}.py`、`pages/{InterviewPage,ExamPage}.tsx` |
| 面试对话流（r5 · 多轮追问 + 4 项设定） | `services/interview/interview.py`（会话引擎）+ `services/report/rules.py`（设定闭集 / `experience_band_of` / `is_follow_up_allowed`）+ `routers/interview.py`（3 路由）+ `pages/InterviewPage.tsx` 与 `components/interview/*`（7 态 + 气泡组件） |
| 题库组卷与选池 | `services/assessment/exam_selector.py`（`rank_pool` / `build_paper` / L1–L6 阶梯，结构闸门唯一实现） |
| 诊断报告 + 课程匹配（AC-5/AC-6） | `services/report/diagnosis.py`、`routers/report.py`（含 `GET /markdown`）、`pages/ReportPage.tsx` |
| 历史与趋势（AC-9/AC-10） | `services/interview/history.py`、`routers/history.py`、`pages/HistoryPage.tsx`；r3 起含长期记忆聚合 |
| 题库种子 779 道（r12 起） | `backend/app/seed/questions.json`（r6 起退为**唯一导入源**，运行时由 `questions` 表承载；r11 起每次启动幂等导入，r14 起启动同时覆写既有行差异）；素材输入与留痕在 `docs/question-bank-staging/`（`PROVENANCE.md` + `NOTICE-fe-interview.md`），id 前缀口径见 §3.4.2 |
| pydantic 契约模型（画像 5 维度 / 题目 / 报告 / 课程） | `backend/app/schemas.py` |
| 后端测试 38 文件（pytest 零网络） | `backend/tests/*.py` |
| 容器化交付（r10） | `docker-compose.yml`、`backend/Dockerfile`、`frontend/Dockerfile`、`frontend/nginx.conf`、`docker.env.example`、任务夹 `docs/teamflow/20261101-r10-docker-compose-deploy/DEPLOY.md`；`WEB_PORT=8080` 单端口对外、SQLite 落 `skillcoach-data` 卷 |
| 前端 `package-lock.json` + 已装依赖 | `frontend/package-lock.json`、`frontend/node_modules/` |
| CI 双 job | `.github/workflows/ci.yml` |
| 本地工程验证（r43 补记） | `pypdf` 6.21.4 / `python-docx` / `ruff` 均已装，真实 PDF / DOCX 解析与 `python -m ruff check app tests` 可在本机实跑（r42 起纳入每次交付门禁） |
| AGENTS.md + memory.md + README | 仓库根与 `docs/teamflow/` |
| CI 实跑（r51 核实、r53 复核） | GitHub Actions 共 32 次运行；最近 `CI #32`（commit `163ebb4`，`feat/dev-skill-coach`）成功、耗时 1m6s；#21–#26 曾红灯、后续修复，#27–#32 连续通过。`Question bank byte gate` 已随 #32 在远端跑绿。证据：[Actions](https://github.com/miaogan/code_learning/actions) |

### 7.2 未落盘（明确未完成，不计入「已完成」）

| 项 | 现状 | 归属 |
| --- | --- | --- |
| iOS 真机 HEIC 相册转码行为 | r42 已实测桌面 Chromium 与后端字节嗅探；iOS Safari 无真机，仅按公开行为推断（见 `docs/teamflow/20261108-r42-task-recovery-heic/QA-REPORT.md` §3.2） | 有真机时补测 |

---

## 8. 下游交接（谁在哪填哪）

- **M1–M5 已全部交付**（画像 / 双测评 / 报告 / 历史与趋势），各里程碑的模块与页面清单见 §7.1；本文件不再保留「待填」交接清单。
- **r5 面试对话流已交付（2026-11-01）**：`services/interview/interview.py`（`fill_settings` / `calibration_of` / `validate_questions` / `validate_session` / `create_run` / `score_answer` / `load_session`）、`services/report/rules.py`（4 项设定闭集 + `experience_band_of` + `is_follow_up_allowed`）、`routers/interview.py`（3 路由）、`pages/InterviewPage.tsx` + `components/interview/*`（7 态 + 气泡组件）、`RunSummary` / `Report` 投影字段；契约与 payload 不变量见 §3.3 / §3.4.1，技术方案见任务夹 `docs/teamflow/20261101-r5-interview-chat-config/TECHNICAL.md`。
- **统一约束（不许破）**：所有新组件复用 `tokens.css`；所有新端点返回 `AppError` envelope 与中文 message；所有改字段同步 `frontend/src/api/types.ts` ↔ `backend/app/schemas.py`；新增尺寸必须回写 DESIGN §0.7 的推导。

### 8.1 历史任务夹的偏差补记（产物不可改，以实现为准）

任务夹 `docs/teamflow/<yyyyMMdd-rN-slug>/` **建后不可变**；历史文档与实现不一致时，只在本节补记，不回改任务夹。

| 来源 | 历史文档写法 | 实现真相 |
| --- | --- | --- |
| r5 `TECHNICAL.md:186` | `is_follow_up_allowed(kind, follow_up_count, total_questions)`（3 参） | `is_follow_up_allowed(kind, follow_up_count, asked, planned_total)`（4 参，`services/report/rules.py`）：r8 起以「不挤占剩余正题轮次」替代「answered+1 ≤ 12」 |
| r5 `TECHNICAL.md:302` | 调用处同记 3 参 | 同上；调用方 `services/interview/interview.py` 已传 4 参 |
| r11 `TECHNICAL.md` | 未记 `exam_selector._prefer_kind_diversity()` 与 `PromptBody.tsx` | 二者已落盘：题型覆盖是取题策略（见 `services/assessment/exam_selector.py` 模块 docstring）；`components/exam/PromptBody.tsx` 是题面围栏渲染唯一出口（题卡与错题本共用）；练习与笔试的共享口径见 §3.4.3 |
| r11 `QA-REPORT.md` | 缺 AC-16 要求的「练习 vs 笔试共用同一题库」说明段 | 已按不可变约定补记在 §3.4.3（r17 收口） |
| r12 `TECH-CHANGE.md` §3.2 | id 前缀写 `iq-NNN` | 实现取 `iq380-`（避开面试发言 `iq-` 域），见 §3.4.2 |
| r3 `DESIGN.md` §0.5-4 | 摘要条 48 高按 `2px 边框 + 12px×2 内边距 + 22px 行高` 推导 | 常规态一致；`has-action` 态为容纳 40 高按钮，上下内边距取 `calc(var(--sp-1) - 1px)`（3px），即 `2 + 3×2 + 40 = 48`，在 border-box 下总高仍守 48（`styles/base.css` `.sc-merge-bar.has-action`） |
| r5 `TECHNICAL.md` | 未声明前端 lint 的「警告阈值」 | `frontend/package.json` 的 `npm run lint` 固定 `eslint . --max-warnings 28`：存量 28 条警告为基线，新增任何警告即门禁失败；下调基线须随代码清理同步改脚本，不写回历史任务夹 |
