# TeamFlow 产品记忆与待办（dev-skill-coach）

> 本文件是**产品约定层**：只记录跨需求长期有效的信息（技术栈、团队规矩、已知待办）。
> 每个需求的迭代细节在各自任务夹 docs/teamflow/<日期-rN-slug>/ 内，不写进本文件。
> 权威架构文档：`docs/teamflow/architecture/ARCHITECTURE.md`（本文件只做索引与约定摘要）。

## 团队约定与技术栈

- 技术栈基线：Web 应用 = React + Vite（TypeScript）前端 / Python FastAPI 后端；AI 能力统一由服务端调用模型 API，Key 只经服务端 `.env` 注入，前端源码与构建产物中不得出现 Key。
- 数据落盘基线：首版用本地 SQLite 单库（`backend/app.db`），不引入外部数据库与云存储；用户可编辑的静态清单（课程/种子题）以服务端 JSON 文件维护。
- 文档基线：每个需求一个不可变任务夹 `docs/teamflow/<yyyyMMdd-rN-slug>/`，跨需求约定与待办只写 `docs/teamflow/memory.md`。
- 模块边界（2026-10-31 脚手架落定）：`frontend/` 只经 `src/api/client.ts` 出网（页面不直接 fetch）；`backend/` 路由层只做参数与错误映射，业务在 `app/services/`；画像 / 试卷 / 报告等结构化产物以 JSON 文本列入库，校验交给 pydantic（`app/schemas.py`）。
- 契约规则：JSON 字段名一律 snake_case；改字段必须同时改 `backend/app/schemas.py` 与 `frontend/src/api/types.ts`；错误统一为 `{ "error": { "code", "message", "retryable" } }`，message 中文且不含路径/堆栈/端点/Key。
- 视觉真源：`docs/teamflow/20261031-r1-dev-skill-coach/DESIGN.md` §0 的 token 与几何（40 按钮 / 24 徽章 / 96 磁贴 / 132 课程卡 / 128 textarea / 64 与 56 环）；实现只许引用 `frontend/src/styles/tokens.css`，改尺寸必须重算并回写设计文档。
- 验证命令：前端 `npm run typecheck` / `npm run lint` / `npm test` / `npm run build`；后端 `python -m pytest -q` / `python -m ruff check app tests`；探活 `GET /health`。

## 已知待办（下一批）

- [x] M2–M5 全部落地（2026-10-31 · 0.1.0 · 验收见 `docs/teamflow/20261031-r1-dev-skill-coach/ACCEPTANCE.md`）：画像五维 + `source_quote` 溯源与编辑、面试 ≥8 题逐题评分（`SCORING_TIMEOUT_S=14`）、笔试 ≥10 题客观 ≥8 本地判分、报告 3–5 条短板带证据 + 课程兜底 + Markdown 同源导出、历史趋势与刷新持久化。种子题库 12 题/方向（`backend/app/seed/questions.json`），课程 25 门（入门 14）。
- [ ] **R-1（P0 子项，验收返工项）**：AC-5「一键复制为 Markdown 文本」未实现——`ReportPage` 只有「导出 .md」，需补「复制 Markdown」按钮（`navigator.clipboard.writeText` + `api.reportMarkdown`）+ 成功 Toast + 失败提示（DESIGN §2.5 已定义，`components/ui/` 当前无 `Toast`）。
- [ ] 架构文档同步：`docs/teamflow/architecture/ARCHITECTURE.md` §3.2 / §7.2 仍把 profile/interview/exam/report/history 路由与四个 service 标为「⛔ 501 待 M2–M4」，需更新为已实现。
- [ ] 真实环境人工补测：浏览器视觉/动效走查、`vitest`+`vite build`、`ruff`、真实 PDF/DOCX 解析、配真实 Key 的端到端计时（AC-1 ≤30s / AC-3 单题 ≤15s / AC-4 10s / AC-7 ≤5 分钟）。
- [ ] QA round-2 三条 P3：上传上限校验收敛到 `services/parser.py` 单源、框架级 405 文案中文化、`.gitignore` 补 `backend/tests/.tmp/`。
- [ ] 25 门种子课程外链需人工点检一次（当前只校验数量与方向覆盖）。

## 说明

- 任务产物：docs/teamflow/<日期-rN-slug>/（一需求一夹，建后不可变）
- backlog（需求/任务/缺陷）事实源：$DSH_HOME/teamflow/<workspace>/（按工作区/项目隔离）
- 运行日志：logs/teamflow/<runId>/（run 期间的项目内暂存；run 结束由 host 归档到 $DSH_HOME/teamflow/<workspace>/logs/<runId>/，项目内不留存）
