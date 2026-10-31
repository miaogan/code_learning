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
- 反馈约定（2026-10-31 · r2 落定）：**成功用 Toast（唯一出口 `frontend/src/components/ui/Toast.tsx`，右下 24、`--elev-2`、2s）**，**失败一律页内 `InlineError`（中文原因 + 重试），禁止只用 Toast 承载失败**；报告类文本（复制/导出）只能取自 `api.reportMarkdown`（后端 `services/markdown.py` 单一渲染源），前端禁止二次拼串或裁剪。
- 记忆约定（2026-10-31 · r3 落定）：画像恒为**单一当前画像 + 增量合并**（同一能力项（归一后）证据累积、旧证据不删、消失项标 `status=historical` 且不参与出题/诊断）；成长记忆唯一来源是成长时间线表与 `GET /api/timeline`，事件指标必须复用既有 service（`history` / `diagnosis`）计算，前端不得自行做减法或二次拼装。
- 简历润色约定（2026-10-31 · r3 落定）：润色只在 `backend/app/services/resume_polish.py` 单一入口（路由与页面零提示词），为其被诊断报告复用留出入口；建议文本必须逐字带原句溯源，数字/专名的幻觉由后置校验降级为「仅措辞建议」、缺数值写 `〈待补充〉` 不编造。
- 一次性升级说明（2026-10-31 · r3 上线须知）：`timeline_events` 由 `backend/app/db.py` 的 `CREATE TABLE IF NOT EXISTS` 随 `init_db()` 自建，**没有迁移脚本、不删旧库、无需手工建表**；`ProfileSkill` / `ProfileProject` 新增 `source_quotes` / `status`，旧画像里只有单条 `source_quote` 的记录由 pydantic validator 自动回填（读旧数据不报错、首次写入后转多证据）；历史 runs / documents **不回填**为时间线事件（时间线只记本版本起的新事件，空态文案「历史数据从本版本起记录」）；润色建议缓存是**进程内**的（重启即失效，`/full` 会重跑并如实标 `regenerated: true`），采纳/临时岗位/成稿一律不入库。
- 验证命令：前端 `npm run typecheck` / `npm run lint` / `npm test` / `npm run build`；后端 `python -m pytest -q` / `python -m ruff check app tests`；探活 `GET /health`。

## 已知待办（下一批）

- [x] M2–M5 全部落地（2026-10-31 · 0.1.0 · 验收见 `docs/teamflow/20261031-r1-dev-skill-coach/ACCEPTANCE.md`）：画像五维 + `source_quote` 溯源与编辑、面试 ≥8 题逐题评分（`SCORING_TIMEOUT_S=14`）、笔试 ≥10 题客观 ≥8 本地判分、报告 3–5 条短板带证据 + 课程兜底 + Markdown 同源导出、历史趋势与刷新持久化。种子题库 12 题/方向（`backend/app/seed/questions.json`），课程 25 门（入门 14）。
- [x] **R-1（P0 子项，验收返工项）已关闭**（2026-10-31 · r2 验收通过，见 `docs/teamflow/20261031-r2-ac5-copy-markdown/ACCEPTANCE.md`）：AC-5「一键复制为 Markdown 文本」已补齐——`复制 Markdown` 按钮（导出 .md 左侧、secondary/40 高、忙态防重复）+ `navigator.clipboard.writeText(await api.reportMarkdown(id))` 零变换（字节相等 103B）+ 成功 Toast（2s / 右下 24 / `--elev-2`）+ 失败页内 `InlineError`（三条失败路径实测）+ `check_copy_markdown.mjs` 7 条断言全 PASS（HEAD 负向自检 5 FAIL 有效）；门禁 typecheck/lint 0 error、pytest 73 全绿。检查器按约定落 `logs/teamflow/<runId>/scripts/`（gitignored，host 归档，不常驻仓库）。
- [ ] 架构文档同步：`docs/teamflow/architecture/ARCHITECTURE.md` §3.2 / §7.2 仍把 profile/interview/exam/report/history 路由与四个 service 标为「⛔ 501 待 M2–M4」，需更新为已实现。
- [ ] 真实环境人工补测：浏览器视觉/动效走查（含 Toast 位置与复制后真机粘贴）、`vitest`+`vite build`、`ruff`、真实 PDF/DOCX 解析、配真实 Key 的端到端计时（AC-1 ≤30s / AC-3 单题 ≤15s / AC-4 10s / AC-7 ≤5 分钟）。
- [ ] QA round-2 三条 P3：上传上限校验收敛到 `services/parser.py` 单源、框架级 405 文案中文化、`.gitignore` 补 `backend/tests/.tmp/`（本轮已随 r2 工程约束补齐）。
- [ ] 25 门种子课程外链需人工点检一次（当前只校验数量与方向覆盖）。
- [x] **r3 长期记忆 + 简历润色已交付并验收**（2026-10-31 · 任务夹 `docs/teamflow/20261031-r3-memory-resume-polish/` · 判定「⚠️ 有条件通过」）：15 条 AC 全部由验收人亲自复跑的执行证据支撑（pytest 113 全绿、typecheck/lint 0 error、functional 18/18、parity 14/14、copy 6/6、memory_polish 28/28、T7 25/25）。**必须闭合**：R-1 润色页「原版」Tab 要显示整篇简历正文（现为被改写句原文拼接，与 DESIGN §240 不符，二选一：补只读正文接口并双侧同步契约，或降级设计并改 meta 文案）；R-2 删除仓库根误产物 `nul`（0 字节，`git add -A` 会带进提交）。**可随下轮清理**：导出文件名取原文件名（DESIGN §284，需 `file_name` 来源）、删除 `profile_merge.py` 的 `CONTRACT_READY` 死分支（双模型定义双源风险）、补合并摘要条「查看历史能力项」入口。
- [x] r3 的两处取舍已由验收定稿（2026-10-31）：①AC-7「能力项不足」只落 payload `tech_fallback`、暂不加 InterviewPage/ExamPage 页面提示（接受，页面提示留后续需求）；②润色建议缓存保持**进程内**（接受，`/full` 如实标 `regenerated: true`，满足 AC-10「采纳/临时岗位不入库」边界；跨重启复用需另立需求并先评估该边界）。

## 说明

- 任务产物：docs/teamflow/<日期-rN-slug>/（一需求一夹，建后不可变）
- backlog（需求/任务/缺陷）事实源：$DSH_HOME/teamflow/<workspace>/（按工作区/项目隔离）
- 运行日志：logs/teamflow/<runId>/（run 期间的项目内暂存；run 结束由 host 归档到 $DSH_HOME/teamflow/<workspace>/logs/<runId>/，项目内不留存）
