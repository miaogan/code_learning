# TECHNICAL · 首版四步闭环技术方案（dev-skill-coach）

> 基线依赖：`docs/teamflow/20261031-r1-dev-skill-coach/PRD.md` + 同夹 `DESIGN.md`（视觉/几何唯一真源）。
> 架构总览与既有脚手架：`docs/teamflow/architecture/ARCHITECTURE.md`。
> 定性：本需求为**首个技术方案**，全部为新增能力，无沿用/修订项，**无「取代」声明**。
> 增量原则：ARCHITECTURE 定下的目录、命名、错误 envelope、`/api` 前缀、SQLite 4 表**不推翻**；本文件只补「怎么填坑 + 任务边界 + 契约逐字签名」。

---

## 0. 一页结论

| 结论 | 内容 |
|---|---|
| 代码不动骨架 | 6 页 + 7 路由文件 + 4 表全部保留；**新增 4 个模块、修改 12 个模块、扩充 1 份种子数据、新增 5 份测试** |
| AI 用在哪 | 只用 3 处：画像生成（M2）、面试出题+逐题评分（M3）、报告文案（M4，**失败即降级**）。笔试**全程不调 AI** |
| 为什么笔试题智隔离 | 客观题判分必须确定且 `提交后 10s 内` 出分（AC-4）；答案只活在服务端 `runs.payload`，`ExamQuestion` 响应模型**天然无 answer 字段** |
| 时序保底 | 单题评分请求设 `timeout_s=14`（< AC-3 的 15s）；画像/报告用默认 20s，超时→中文 `AI_UNAVAILABLE` |
| 数据权威 | 服务端为唯一权威；前端刷新只靠 `GET /api/profiles/latest`、`GET /api/reports/latest`、`GET /api/history`，localStorage 只做导航对勾 |
| 可测性 | 所有 AI 服务签名带 `*, client: AIClient \| None = None`，测试注入 `FakeAI`，**测试零网络** |

---

## 1. 数据模型与存储

### 1.1 表结构（沿用 `backend/app/db.py`，不动列，只加索引）

| 表 | 列 | 本次写入内容 |
|---|---|---|
| `documents` | id, file_name, mime, chars, sections, text, created_at | 已实现（AC-1）；本次不改 |
| `profiles` | id, document_id, payload(JSON), created_at, updated_at | payload = `Profile` 全字段；**每次生成插新行**（不覆盖旧行，为 AC-10 留痕）；PATCH 只改该行 |
| `runs` | id, kind, profile_id, payload(JSON), status, created_at | status = `created`/`in_progress`/`completed`；逐题答案与分数回写 payload |
| `reports` | id, payload(JSON), created_at | payload = `Report` 全字段（含 `run_ids`） |

`backend/app/db.py` 只新增两条幂等索引（建表语句末尾）：

```sql
CREATE INDEX IF NOT EXISTS idx_runs_kind_created ON runs (kind, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_reports_created ON reports (created_at DESC);
```

> 无列变更 ⇒ 无需在 `memory.md` 写升级语句；索引 `IF NOT EXISTS` 对既有 `app.db` 幂等。

### 1.2 payload 形状（写入/读取唯一格式，两侧都过 pydantic）

`runs.payload` · 面试：
```json
{"questions":[{"id":"iq-1","kind":"technical","prompt":"...","hint":"...",
  "answer":null,"score":null,"comment":null,"answered_at":null,"elapsed_s":null}],
 "answered_count":0,"total":8}
```
`runs.payload` · 笔试（**answer 仅存服务端**，永不进响应）：
```json
{"questions":[{"id":"fe-q1","kind":"single","direction":"前端","prompt":"...",
  "options":[{"key":"A","text":"..."}],"answer":["B"],"difficulty":"basic"}],
 "started_at":"2026-10-31T05:00:00+00:00","submitted_at":null}
```
`reports.payload`：`Report` 直存；`profiles.payload`：`Profile` 直存。

### 1.3 契约变更清单（必须两侧同步：`schemas.py` ↔ `api/types.ts`）

| 变更 | 后端 | 前端 |
|---|---|---|
| 新增请求模型 3 个 | `InterviewCreateRequest{profile_id}`、`ExamCreateRequest{profile_id}`、`ReportGenerateRequest{run_ids: list[str] \| None = None}` | 同名 interface |
| `Shortfall` 新增可溯字段 | `question_ref: str \| None = None`（题目原始 id，如 `fe-q1`；`evidence` 保留展示形「Q3 · 4/10」） | `question_ref: string \| null` |
| `Report` 新增溯源 | `run_ids: list[str]`（此报告引用的 run） | `run_ids: string[]` |
| 既有未用模型落位 | `ProfilePatch`/`ScoreResult`/`ExamResult`/`RunSummary` 已齐备，直接返回 | 补齐同名 interface（`ScoreResult`/`ExamResult`/`RunSummary`/`InterviewRun`/`ExamRun`/`AnswerRequest`/`ExamAnswers`/`ProfilePatch`） |
| 错误码 | **不新增**。画像缺 `source_quote` 由 `ProfileDraft` 的 `Field(min_length=1)` 拦下 → `ai.py` 重试 1 次 → `AI_SCHEMA_INVALID`（闭环已够） | 无需改 |

### 1.4 新增存储封装 `backend/app/repository.py`（唯一 SQL 出口）

理由：本次 5 个路由器都要读写同一批表，SQL 散落在路由层必然漂移（字段名/排序/JSON 反序列化各写一遍）。统一到这一层后，路由层只做参数校验与错误映射（符合 ARCHITECTURE §3.1「路由只做参数与错误映射」）。

签名（下游逐字调用）：`insert_document(meta: ResumeMeta, text: str) -> None`、`get_document_text(document_id: str) -> str | None`、`insert_profile(profile: Profile) -> None`、`latest_profile() -> Profile | None`、`get_profile(profile_id: str) -> Profile | None`、`save_profile(profile: Profile) -> None`、`insert_run(run_id: str, kind: str, profile_id: str, payload: dict[str, Any]) -> None`、`get_run(run_id: str) -> dict[str, Any] | None`、`save_run(run_id: str, payload: dict[str, Any], status: str) -> None`、`list_runs(kind: str | None = None, limit: int = 20) -> list[dict[str, Any]]`、`insert_report(report: Report) -> None`、`latest_report() -> Report | None`、`get_report(report_id: str) -> Report | None`。

返回 `None` 表示不存在（**不抛异常**，由路由层翻成 `NOT_FOUND` 中文提示），这是错误映射的唯一分工点。

---

## 2. API 设计（前缀 `/api`，全站无鉴权）

| 方法 | 路径 | 请求 | 200 响应 | 失败 |
|---|---|---|---|---|
| GET | `/health` | — | `{status,version,ai_configured,db}` | — |
| POST | `/api/resumes` | multipart `file` | `ResumeMeta` | 413/415/400（已实现） |
| POST | `/api/resumes/{resume_id}/profile` | 空 body | `Profile` | 404 `NOT_FOUND`「找不到这份简历，请重新上传」；503 `AI_UNAVAILABLE`；502 `AI_SCHEMA_INVALID` |
| GET | `/api/profiles/latest` | — | `Profile` | 404（前端引导态，非报错） |
| PATCH | `/api/profiles/{profile_id}` | `ProfilePatch` | `Profile`（更新的 `updated_at`） | 404；`skills[].source_quote` 空 → 400 `VALIDATION_ERROR` |
| POST | `/api/interviews` | `{profile_id}` | `InterviewRun{run_id, questions[]}`（**不含答案/分数**） | 404 画像不存在；502 出题不合格（数量/配比/重复） |
| POST | `/api/interviews/{run_id}/answers` | `{question_id, answer}` | `ScoreResult{score, comment}` | 404 run 或题目不存在；503 超时（`retryable=true`，**前端不清空作答**） |
| POST | `/api/exams` | `{profile_id}` | `ExamRun{run_id, questions[]}`（**不含答案**） | 404；400 题库不足（补齐后仍 <10 道） |
| POST | `/api/exams/{run_id}/submit` | `{answers:{qid: ["A"] \| "文本"}}` | `ExamResult{total,correct_count,objective_total,elapsed_s,per_question[]}` | 404；400「这份笔试卷已提交」（status 已 completed） |
| POST | `/api/reports/generate` | `{run_ids?}`（缺省取最近面试+笔试各一） | `Report` | 404 无可用测评；400「至少需要一次测评」 |
| GET | `/api/reports/latest` | — | `Report` | 404 |
| GET | `/api/reports/{report_id}/markdown` | — | `text/markdown; charset=utf-8` | 404 |
| GET | `/api/history` | `?limit=10` | `RunSummary[]`（`created_at DESC`） | 400 limit 越界 → 走 `Query(ge=1, le=50)` 自动 422→envelope |
| GET | `/api/courses` | — | `Course[]` | —（已实现） |

约定：**全部改回具体 `response_model`**（现在 5 个路由是 `status_code=501` + `-> None`，必须删掉 501 与占位体）；`POST` 使用 pydantic body 模型，**禁止**像现在这样把 `profile_id: str` 裸写在函数签名里（会被 FastAPI 当 query 参数，前端必然对不上）。

### 2.1 各端点内部逻辑（判定规则写死，避免实现自由发挥）

- **画像**：`documents.text` → 截断 12k 字（超出追加「（已截取前 12000 字）」）→ `complete_model(PROFILE_SYSTEM, 正文, ProfileDraft)` → `verify_quotes(draft, text)`：每条 `source_quote` 去空白后须能在正文里定位（同文包含匹配，允许跨行合并空白）；命中失败 → 抛 `AI_SCHEMA_INVALID`（`ai.py` 已重试 1 次）⇒ anti-goal 1「无源之词」在入库前被拦。
- **面试出题**：`InterviewDraft{questions: list[InterviewQuestion]}` → 校验 `len>=8`、`technical>=5`、`project>=3`、`challenge<=2`（≤20% 向上取整）、`prompt` 去重 → 不满足即 502 中文「本次出题不合格，请重试」（**不做静默补题**：补题=题目与简历脱节，anti-goal 2）。
- **面试评分**：`timeout_s=14` 调 `ScoreDraft{score: 0–10, comment<=120字}` → 回写 payload（`answer/score/comment/answered_at/elapsed_s`）→ `answered_count==total` 时 `status=completed`。重复提交同一题=重答，覆盖旧分（幂等）。
- **笔试组卷**：读 `seed/questions.json`，按 `profile.tech_stack + target_role` 命中的 `direction` 排序取题；客观题（`single`/`multiple`）先取满 ≥8，再补 `text` 至 ≥10、≤12；`challenge` 占比 ≤20%；方向题不足则跨方向补齐（**题量优先于方向纯度**，且这不是 AI 出题所以不会与简历脱节）。`started_at=now(UTC)` 入 payload。
- **笔试判分**：`single` = 选项集合相等；`multiple` = 完全集合相等（**不给部分分**，口径写在报告里）；`text` → `correct=null` 不计分。`total = round(correct_count / objective_total * 100, 1)`（`objective_total>=8` 保证分母）。`elapsed_s = round((submitted_at - started_at).total_seconds(), 1)`，缺 `started_at` 记 0，上限 99:59 只在展示层截断。
- **报告**：先本地统计（每题得分→按 `direction` 聚类算均分）→ 严重度 `avg<4 → high`、`<7 → medium`、否则 `low` → 候选排序 `(severity, avg)` → 取 3..5 条 → 每条 `evidence="Q{n} · {score}/10"`、`question_ref=该题原始 id`，并**用 run payload 校验证据题号真实存在**，不存在的候选直接丢弃 → `match_for_shortfall(name)` 取课程（兜底入门课）→ AI 只补 `diagnosis`/`actions` 文案，**AI 失败则用模板文案**（报告仍成功，不返回 501/503）。
- **Markdown 导出**：`services/markdown.py` 由 `Report` 纯函数生成；页面预览区与导出**同源**（前端不自己拼字符串），保证 AC-9「与页面一致」。

---

## 3. 前端组件与页面切分

### 3.1 页面（`frontend/src/pages/`，6 页全部从「引导空态」升级为真实页面）

| 页面 | 内部状态机 | 组件拆分（新增） |
|---|---|---|
| `UploadPage.tsx` | 已实现，本次仅接「解析完成→生成画像」按钮 | 复用现有 |
| `ProfilePage.tsx` | `idle/loading(三段阶段文案)/empty(404)/ready/editing` | `components/profile/ProfileDimension.tsx`（单维度卡：标题+条目+溯源引用）、`components/profile/ProfileEditor.tsx`（行内编辑：textarea + 保存/取消） |
| `InterviewPage.tsx` | `idle(EmptyState)/intro(开始)/running(逐题单屏)/scoring/answered(同卡出分)/done(汇总)` | `components/interview/QuestionCard.tsx`（题面+`textarea` 128+提交+环）、`components/interview/ScoreBadge.tsx`（`RingProgress` 56 + 分数 + 点评） |
| `ExamPage.tsx` | `idle/running(题卡+计时环 64)/submitting/submitted(结果面板)` | `components/exam/ExamQuestionCard.tsx`（题干+`.sc-opt` 选项组）、`components/exam/ExamResultPanel.tsx`（总分环 56/客观题数/用时/逐题对错） |
| `ReportPage.tsx` | `loading/empty(404)/ready/generating/exporting` | `components/report/ShortfallCard.tsx`（4px 严重度扇区+诊断+动作）、`components/report/EvidenceChip.tsx`（24 高 chip「Q3 · 4/10」）、`components/report/CourseCard.tsx`（132 高，`target="_blank" rel="noopener noreferrer"`；`url===null` → 置灰不可点） |
| `HistoryPage.tsx` | `loading/empty/ready` | `components/history/TrendTable.tsx`（分数 + 与上一次的 delta 列，颜色不单独承载信息，带 ↑/↓ 文案） |

### 3.2 组件与页面的硬规则

1. 页面是**唯一**发起请求的层；组件只收 props，不 import `api`（沿用 ARCHITECTURE §3.1）。
2. 通用件（`components/ui/*`）**一个都不改**：本次新增 UI 元素（选项组、严重度扇区、趋势表）都只是 CSS 类 + 现有 `Card/Chip/RingProgress/Button` 组合。
3. 面试「同卡出分」：`QuestionCard` 的 props 里带 `score/comment` 时为已答态，**不换页、不卸载 textarea 内容**（AC-3「失败永不清空作答」的实现位点）。
4. 报告缺来源 → 不做「缺失来源」徽章（后端已拦住脏数据）；若 `source_quote` 为空的历史脏数据出现，`ProfileDimension` 展示 `InlineError` 文案「缺失来源」。

### 3.3 样式类清单（`frontend/src/styles/base.css` 唯一新增处，页面只许用这些）

`.sc-grid-2`、`.sc-profile-dim`、`.sc-profile-dim-head`、`.sc-source-quote`、`.sc-edit-row`、`.sc-qcard`、`.sc-qcard-head`、`.sc-qcard-prompt`、`.sc-score-side`、`.sc-opt`、`.sc-opt.is-selected`、`.sc-opt.is-correct`、`.sc-opt.is-wrong`、`.sc-shortfall`、`.sc-sev-bar`、`.sc-evidence-chip`、`.sc-course-card`、`.sc-course-card.is-disabled`、`.sc-trend-table`、`.sc-delta-up`、`.sc-delta-down`、`.sc-btn-row`、`.sc-meta-line`。

约束：只用 `tokens.css` 变量，禁止裸色值/裸尺寸（AGENTS §4）。**改任何 DESIGN §0.7 尺寸必须重算并回写 DESIGN**——本次不新增尺寸，全部复用 40/24/56/64/96/128/132。

---

## 4. 状态管理

- **无状态库**（不引 redux/zustand/jotai）。三件套：`useAsync`（数据获取）+ 页面局部 `useState`（表单/阶段）+ `state/flow.ts`（localStorage 三标记，仅导航对勾与门禁提示）。
- 新增 `frontend/src/lib/useAsync.ts`：
  ```ts
  export interface AsyncState<T> { status: 'idle'|'loading'|'success'|'error'; data: T|null; error: ApiError|null }
  export function useAsync<T>(loader: (signal: AbortSignal) => Promise<T>, deps: readonly unknown[]): AsyncState<T> & { reload: () => void }
  ```
  实现要求：`useEffect` 内建 `AbortController`，deps 变化先 abort 上一次（防竞态）；`loader` 用 ref 保存最新引用，**不进 deps**；`reload()` 用自增 tick 触发；`AbortError` 不写 `error`（避免"已取消"变成红色错误条）。
- `frontend/src/api/client.ts` 扩展（唯一 HTTP 出口，全部方法名逐字）：
  ```ts
  generateProfile(resumeId: string, signal?: AbortSignal): Promise<Profile>
  patchProfile(profileId: string, patch: ProfilePatch): Promise<Profile>
  createInterview(payload: InterviewCreateRequest): Promise<InterviewRun>
  scoreAnswer(runId: string, payload: AnswerRequest): Promise<ScoreResult>
  createExam(payload: ExamCreateRequest): Promise<ExamRun>
  submitExam(runId: string, answers: ExamAnswers): Promise<ExamResult>
  generateReport(payload: ReportGenerateRequest): Promise<Report>
  latestReport(): Promise<Report>
  reportMarkdown(reportId: string): Promise<string>   // 内部新增 requestText()，非 JSON
  listCourses(): Promise<Course[]>                    // 已存在
  history(limit = 10): Promise<RunSummary[]>
  ```
- 提交类交互统一：`inFlight` 布尔 → 按钮 disabled；失败 → `InlineError`（`error.message` + `retryable` 时给「重试」）；成功 → 只替换受影响对象，**不做全局乐观更新**（PATCH 后以响应体为唯一真值）。

---

## 5. 关键实现点与边界

| # | 情形 | 期望行为 |
|---|---|---|
| 1 | 上传 0 字节 / 加密 PDF / >10MB / 非白名单 | 中文 `message`，**不写库**（已实现，本次回归测试固定住） |
| 2 | 画像 `source_quote` 为空或不在原文 | 入库前拦下 → 重试 1 次 → 502「AI 返回的结构不符合预期，请重试一次」 |
| 3 | 正文 >12k 字 | 截断后调用，并在 `ProfileDimension` 顶部提示「长简历已截取前 12000 字」 |
| 4 | 未配置 `AI_API_KEY` | `503` 中文「AI 服务尚未配置…」，前端 `InlineError` + 指向 README「配置 .env」 |
| 5 | 单题评分 14s 超时 / 429 | `AI_UNAVAILABLE retryable=true`；**textarea 内容保留**，点「重试」重发同一次作答 |
| 6 | 连点提交 | 前端 disabled + 后端幂等（重答覆盖同一题） |
| 7 | 面试中途刷新 | 明确不保留：回到 `idle`，提示「中途刷新需重新开始一次面试」（AC-7 只承诺画像/记录/最新报告持久化，不再加 run 详情端点以免过度设计） |
| 8 | 题库某方向不足 | 跨方向补齐；补齐后仍 <10 → 400「题库不足，暂无法出卷」，不出 9 题卷 |
| 9 | 试卷重复提交 | 400「这份笔试卷已提交」；重考请重新 `POST /api/exams` |
| 10 | 报告候选证据题号不存在 | 丢弃该候选；剩余 <3 条 → 用模板文案补齐到 3 条（不返回 501） |
| 11 | 课程 `url=null` | 卡置灰 + 文案「暂无外链」，**不 construct 链接、不 404** |
| 12 | 历史 <2 次测评 | 表格展示但 delta 列显示「暂无对比」 |
| 13 | 时间 | 全库 ISO-8601 UTC 存；展示层 `toLocaleString('zh-CN')`；用时统一 `formatElapsed`（上限 99:59） |
| 14 | 同页重复请求竞态 | `useAsync` 先 abort 上一次；`AbortError` 静默 |

---

## 6. 测试策略

### 6.1 后端（pytest，`backend/tests/`）

- `conftest.py`：`tmp_path` 级临时 SQLite（`monkeypatch.setenv("DB_PATH", ...)` + `get_settings.cache_clear()`），每个测试独立库；`FakeAI` 实现 `async complete_model(system, user, model_cls)` 返回预置 pydantic 模型，**全测试零网络**。
- `test_profile_service.py`：`verify_quotes` 三态（原文命中/仅空白差异命中/完全不命中）；`generate_profile` 在 `FakeAI` 下产出 5 维度且每条带 quote；缺 quote → `AI_SCHEMA_INVALID`。
- `test_interview_service.py`：出题配比校验（8 题但 technical=4 → 502；challenge=3 → 502；prompt 重复 → 502）；评分 0–10 越界被 schema 拒；逐题回写后 `answered_count` 与 `status` 正确。
- `test_exam_service.py`：组卷 ≥10 且客观 ≥8、challenge ≤20%；判分（单选对错、多选少选=错、text 不计分）；`total` 计算；`elapsed_s` 由服务端时间；重复提交 400。
- `test_report_service.py`：短板条数 3..5；排序严格按 `(severity, 均分)`；`evidence`/`question_ref` 指向真实题目；每条 ≥1 课程（含兜底分支）；AI 失败降级仍产出 `Report`。
- `test_routes.py`：删除 501 后逐端点 200/404/400；错误 envelope 形状；`/api/reports/{id}/markdown` 返回的文本含每条短板标题、证据、课程标题（AC-9 一致性的机器可验部分）；`/api/history` 排序与 limit。
- 保留既有 `test_health.py` / `test_courses.py` / `test_resume_guard.py` 全绿。

### 6.2 前端（vitest，`frontend/src/**/*.test.ts`）

- 已有 `test/format.test.ts` 继续；
- `lib/useAsync.test.ts`：用 `react-dom/server` 或最小 hook harness 验证 idle→success / error / reload 三态（不引 `@testing-library`，避免新依赖）；
- `lib/delta.test.ts`（若 delta 计算落在 `format.ts` 的 `formatDelta`，一并覆盖正负零）；
- 组件冒烟：`renderToStaticMarkup` 渲染 `EvidenceChip`/`CourseCard(url=null)`，断言置灰与无 `href`。

### 6.3 AC 覆盖映射

| AC | 机器验证 | 人工点检 |
|---|---|---|
| AC-1 | `test_routes` + `test_resume_guard` | 真 PDF/DOCX 抽一次 |
| AC-2 | `test_profile_service` | 页面逐条编辑并刷新 |
| AC-3 | `test_interview_service` | 8 题逐题出分、断网重试不清空 |
| AC-4 | `test_exam_service` | 提交到结果计时（计时器肉眼 <10s） |
| AC-5 | `test_report_service` | 短板能点回题号 |
| AC-6 | `test_courses` + `test_report_service` | 点 3 门外链 |
| AC-7 | `test_routes`（latest 读回） | 全流程 5 分钟演练 + 刷新 |
| AC-8 | `grep` 产物扫描（见 verifyScripts） | 前端无 Key 输入 |
| AC-9 | `test_routes` markdown 断言 | 页面与 .md 逐条对齐 |
| AC-10 | `test_routes` history | 连做两次看 delta |

---

## 7. 任务拆分（并行边界 = 文件所有权）

> 本阶段未收到下游预派任务，以下为并行化任务清单。**T0 是唯一前置**（契约与存储基座），其后后端 6 条链路 + 前端 6 个工作面彼此文件互斥，可并行。

| 任务 | 文件（拥有/修改） | 读取依赖 | 验收要点 |
|---|---|---|---|
| **T0 契约与存储基座** | `backend/app/schemas.py`、`backend/app/db.py`、`backend/app/repository.py`（新）、`backend/app/services/rules.py`（新）、`frontend/src/api/types.ts`、`frontend/src/api/client.ts` | ARCHITECTURE §3、DESIGN §0 | 3 个请求模型 + `Shortfall.question_ref` + `Report.run_ids` 两侧同步；索引幂等；`repository` 13 个函数齐备且不抛异常；`client.ts` 10 个方法齐备、`requestText()` 落地 |
| **T1 画像链** | `backend/app/services/profile.py`、`backend/app/routers/profile.py` | schemas/repository/ai/rules | 生成→校验→落库→PATCH；缺 quote 拦截；404 中文 |
| **T2 面试链** | `backend/app/services/interview.py`、`backend/app/routers/interview.py` | 同上 + seed | 8 题配比校验；`timeout_s=14`；逐题回写与 status |
| **T3 笔试链** | `backend/app/services/exam.py`、`backend/app/routers/exam.py` | 同上 + seed/questions.json | ≥10 题客观 ≥8；判分口径；`elapsed_s` 服务端算；重复提交 400 |
| **T4 报告链** | `backend/app/services/diagnosis.py`、`backend/app/services/markdown.py`（新）、`backend/app/routers/report.py` | 同上 + courses | 3..5 条、排序、证据校验、课程兜底、AI 降级、markdown 与页面一致 |
| **T5 历史链** | `backend/app/services/history.py`（新）、`backend/app/routers/history.py` | repository | `RunSummary[]` 倒序、limit 1..50 |
| **T6 题库扩充** | `backend/app/seed/questions.json` | courses.json 的 direction 取值 | 约 80 道；4 方向各 ≥12；`single`/`multiple`/`text` 齐备；`challenge` ≤20%；key 唯一 |
| **T7 前端基础设施** | `frontend/src/lib/useAsync.ts`（新）、`frontend/src/styles/base.css` | §3.3 类清单 | abort 竞态、AbortError 静默；§3.3 全部类落地且只用 token |
| **T8 画像页** | `frontend/src/pages/ProfilePage.tsx`、`frontend/src/components/profile/ProfileDimension.tsx`、`ProfileEditor.tsx` | types/client/useAsync/base.css | 五维卡 + 溯源 + 行内编辑；404 空态；截断提示 |
| **T9 面试页** | `frontend/src/pages/InterviewPage.tsx`、`frontend/src/components/interview/QuestionCard.tsx`、`ScoreBadge.tsx` | 同上 | 逐题单屏同卡出分；失败不清空；8 题完成汇总 |
| **T10 笔试页** | `frontend/src/pages/ExamPage.tsx`、`frontend/src/components/exam/ExamQuestionCard.tsx`、`ExamResultPanel.tsx` | 同上 | 计时环 64 + 选项组 + 结果面板（56 环/用时/逐题） |
| **T11 报告页** | `frontend/src/pages/ReportPage.tsx`、`frontend/src/components/report/ShortfallCard.tsx`、`CourseCard.tsx`、`EvidenceChip.tsx` | 同上 | 严重度扇区、证据 chip、外链新标签、置灰无 href、导出同源 |
| **T12 历史页** | `frontend/src/pages/HistoryPage.tsx`、`frontend/src/components/history/TrendTable.tsx` | 同上 | delta 文案 + 颜色双通道；<2 次显示「暂无对比」 |
| **T13 后端测试** | `backend/tests/conftest.py`（新）、`test_profile_service.py`、`test_interview_service.py`、`test_exam_service.py`、`test_report_service.py`、`test_routes.py` | T1–T5 全部模块 | 零网络 FakeAI；每端点错误码；markdown 断言 |
| **T14 交付自检** | 无源码改动（发现即就地修） | 全部 | 跑 verifyScripts；只记录结论，**不写 QA-REPORT/ACCEPTANCE** |
| **T15 git 收尾** | `.gitignore`、`README.md` | PRD §9 | 下述工程约束全部满足 |

**并行编排**：T0 →（T1,T2,T3,T4,T5,T6,T7 并行）→（T8–T12 并行，T13 待后端就绪）→ T14 → T15。
冲突规则：`base.css` 只归 T7；`seed/questions.json` 只归 T6；`schemas.py`/`types.ts`/`client.ts` 只归 T0（后续任务发现契约缺口**回到 T0 owner 改**，不得各自打补丁）。

### 7.1 工程约束（来自 PRD §9，逐条落到任务）

| 约束 | 落点 |
|---|---|
| 从基线提交 `32487b4` 起，在 `feat/dev-skill-coach` 分支开发 | **T15**（开工前核对分支，若偏离先切分支；不 rebase 历史） |
| `?? docs/` 未提交改动随本次一并收尾提交 | **T15**（`git add docs/` + 本次任务夹一起提交） |
| 本次改动单独存档、可撤销 | **T15**（提交前确认存档开启；改动不混入其他需求） |
| `.gitignore` 补齐 node_modules/dist/.env/`__pycache__`/.venv/*.db，**保留 `logs/teamflow/` 排除** | **T15** `frontend/`.`gitignore` + 根 `.gitignore` 双侧核对 |
| 密钥只在服务端 | **T0/T14**（`client.ts`/页面不出现 Key、端点、模型名；T14 产物扫描） |

---

## 8. 依赖、风险与未决

| 项 | 状态 | 处置 |
|---|---|---|
| `pypdf` / `python-docx` | 本机未装（venv 创建被 `WinError 5` 拒绝） | 契约与失败码已测（TXT + 413/415/400）；真 PDF/DOCX 由 T14/QA 在可安装环境点检 |
| `package-lock.json` | 缺（`npm install` 报 `EPERM spawn`） | T0–T12 仍按 TS 严格类型书写；T14 在可安装环境首跑 typecheck/lint/build |
| AI 真实 Key | 无 | 全部走 `FakeAI`；真实链路由 QA 用 key 抽测 1 次 |
| 单题 15s 上限 | 模型侧不可控 | `timeout_s=14` 硬兜底 + 中文可重试错误；不静默降级为 0 分 |
| Markdown 与页面一致性 | 双语言格式化天然易漂移 | 约定：markdown 分数/用时只调 `formatScore`/`formatElapsed` 的**同规则**（整数不带 `.0`、用时 mm:ss 上限 99:59）；前端**不二次拼串**，只用后端文本 |
| 题库 80 道人工撰写成本 | T6 单点 | 允许分批：先 4 方向各 12（48 道）即满足 ≥10 题组卷，余量在 T14 补齐 |

**未决（不影响开工，按默认落地）**：课程清单外链人工点检排期；报告导出文件名格式（默认 `诊断报告-{report_id}.md`）；历史页 delta 阈值（默认任意差值都显示，不设"显著变化"门限）。
