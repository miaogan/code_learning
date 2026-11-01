# TeamFlow 产品记忆与待办（dev-skill-coach）

> 本文件是**产品约定层**：只记录跨需求长期有效的信息（技术栈、团队规矩、已知待办）。
> 每个需求的迭代细节在各自任务夹 docs/teamflow/<日期-rN-slug>/ 内，不写进本文件。
> 权威架构文档：`docs/teamflow/architecture/ARCHITECTURE.md`（本文件只做索引与约定摘要）。

## 团队约定与技术栈

- 技术栈基线：Web 应用 = React + Vite（TypeScript）前端 / Python FastAPI 后端；AI 能力统一由服务端调用模型 API，Key 只经服务端 `.env` 注入，前端源码与构建产物中不得出现 Key。
- 数据落盘基线：首版用本地 SQLite 单库（`backend/app.db`），不引入外部数据库与云存储；**题库自 r6 起由 SQLite 的 `questions` 表承载（`backend/app/seed/questions.json` 退为唯一导入源，幂等导入不覆盖已有行）**，课程清单仍以服务端 JSON 文件维护。
- 文档基线：每个需求一个不可变任务夹 `docs/teamflow/<yyyyMMdd-rN-slug>/`，跨需求约定与待办只写 `docs/teamflow/memory.md`。
- 模块边界（2026-10-31 脚手架落定）：`frontend/` 只经 `src/api/client.ts` 出网（页面不直接 fetch）；`backend/` 路由层只做参数与错误映射，业务在 `app/services/`；画像 / 试卷 / 报告等结构化产物以 JSON 文本列入库，校验交给 pydantic（`app/schemas.py`）。
- 契约规则：JSON 字段名一律 snake_case；改字段必须同时改 `backend/app/schemas.py` 与 `frontend/src/api/types.ts`；错误统一为 `{ "error": { "code", "message", "retryable" } }`，message 中文且不含路径/堆栈/端点/Key。
- 视觉真源：`docs/teamflow/20261031-r1-dev-skill-coach/DESIGN.md` §0 的 token 与几何（40 按钮 / 24 徽章 / 96 磁贴 / 132 课程卡 / 128 textarea / 64 与 56 环）；实现只许引用 `frontend/src/styles/tokens.css`，改尺寸必须重算并回写设计文档。
- 反馈约定（2026-10-31 · r2 落定）：**成功用 Toast（唯一出口 `frontend/src/components/ui/Toast.tsx`，右下 24、`--elev-2`、2s）**，**失败一律页内 `InlineError`（中文原因 + 重试），禁止只用 Toast 承载失败**；报告类文本（复制/导出）只能取自 `api.reportMarkdown`（后端 `services/markdown.py` 单一渲染源），前端禁止二次拼串或裁剪。
- 记忆约定（2026-10-31 · r3 落定）：画像恒为**单一当前画像 + 增量合并**（同一能力项（归一后）证据累积、旧证据不删、消失项标 `status=historical` 且不参与出题/诊断）；成长记忆唯一来源是成长时间线表与 `GET /api/timeline`，事件指标必须复用既有 service（`history` / `diagnosis`）计算，前端不得自行做减法或二次拼装。
- 简历润色约定（2026-10-31 · r3 落定）：润色只在 `backend/app/services/resume_polish.py` 单一入口（路由与页面零提示词），为其被诊断报告复用留出入口；建议文本必须逐字带原句溯源，数字/专名的幻觉由后置校验降级为「仅措辞建议」、缺数值写 `〈待补充〉` 不编造；**「原文」类视图与导出文件名一律取服务端字段**（`PolishResponse.resume_text` / `file_name`，源自 `documents.text` / `documents.file_name`），禁止用建议句拼接重建正文、禁止前端自造或按日期臆造文件名（r4 定稿，2026-11-01）。
- 模拟面试约定（2026-11-01 · r5 落定）：面试是**多轮对话流**（面试官逐条发言、基于上一答追问/澄清/施压），不再一次性返回题目列表；每题（含追问）独立 0–10 评分 + ≤120 字点评，写入 `runs.payload.questions[]`——**该数组是会话唯一真相**，不另存 messages 副本；题号 `iq-N` 递增且刷新不变，追问额外带 `parent_id`；开局计划必须过 `rules.py` 配额闸门（≥8 题 / 技术≥5 / 项目≥3 / 挑战≤20%），不合格 502 且不静默补题。每场面试四项设定（目标岗位自由文本 / 工作经验：应届、1-3年、3-5年、5-10年、10年以上 / 面试市场：国内、北美、欧洲、其他 / 公司规模：大厂、中型、初创）随 `payload.settings` 落库（**不建表**）、必须进入每一轮提示词并真实改变出题口径，**临时设定永不写回画像**；单轮「提交→出分」沿用 15s 预算（`SCORING_TIMEOUT_S=14`），超时整轮 503 且零副作用。
- 笔试组卷与熟练度约定（2026-11-01 · r6 落定）：题库四维（`direction` / `kind` / `difficulty`(basic·intermediate·challenge) / `essentiality`(must_know·advanced·nice_to_know)）闭集集中在 `rules.py`，`schemas.py` 与 `types.ts` 逐字对齐；每题单用户熟练度记录（作答事件支撑**真实滑动窗口**：默认 30 天内答对 ≥2 次且最近一次正确＝熟练，超窗或最近答错即回流；简答题不计分故永不参与熟练判定），阈值只在 `config.py` 单一出处。组卷＝「可考池 − 熟练题 − 最近 3 卷已出题」内同相关度同难度档**随机抽题**，结构闸门（10–12 题 / 客观 ≥8 / 挑战 ≤20% / ≥2 个方向）必须恒定；不足时按唯一阶梯逐级放宽：L1 基线 → L2 回流已熟练 `must_know` → L3 回流其他熟练题 → L4 放松近 3 卷排除 → L5 跨方向补 → L6 全库，**任何一层都不得因过滤返回 400**；每次出卷把 `stage`/`filtered_count` 记进 `runs.payload`，旧 payload 读侧给默认值。判分仍纯本地零 AI、10s 内出分。
- 契约可空口径（2026-11-01 · r8 落定）：提示词允许的 `null` 必须被契约接受——`ProfileProject.role/period` 为 `str | None = None` 且 `frontend/src/api/types.ts` 逐字镜像 `string | null`，两侧靠 `test_r8_profile_nullable_mirror` 静态门禁牵制，任一侧回退即红；同口径的 `skills`/`tech_stack`/`projects`/`bullets` 的 `null`/缺键只在 `ProfileDraft` 的 before-validator 归一为 `[]`（`Profile` 继承即覆盖草稿/响应/存量三条路），**不得**用空串伪装「未知」、不得 `extra="allow"`、不得放宽 `name`/`source_quote` 必填；下游一律显式承载 `null`（数字采集 `period or ""`、面试输入省略 `None` 键、合并用 `_prefer_text` 空值不覆盖已知值），前端空值归一单点收敛在 `src/lib/profileText.ts` 的 `textOrEmpty`/`joinMeta`。
- 模型供应商切换约定（2026-11-01 · r9 落定）：AI 供应商走「配置档 + `AI_PROVIDER` 选择」——空值＝legacy（直读 `AI_BASE_URL`/`AI_MODEL`/`AI_API_KEY`/`AI_TIMEOUT_S`，行为零变化），否则按 `AI_<DEEPSEEK|LMSTUDIO>_{BASE_URL,MODEL,API_KEY,JSON_MODE,TIMEOUT_S}` 取用；**具名档的 base_url/model/key 一律不回落全局**（防把云端 Key 发给本地端点），`AI_JSON_MODE` 闭集只收 `json_object`(缺省)/`none`（`none`＝整键不发 `response_format`，供 LM Studio），空 key 省略 `Authorization`；`/health` 只暴露 `ai_provider`/`ai_model`/`ai_json_mode`（永不暴露 key），`health()` 必须 live `get_settings()`；`tests/conftest.py::tmp_db` 必须置空 `AI_PROVIDER` 与各档变量（否则宿主 `.env` 会让既有用例集体变红），门禁不得依赖本机 LM Studio（真实链路用 `AI_LIVE` 开关 + QA 脚本）；**数值型档位**（`AI_TIMEOUT_S`/`AI_MAX_RETRIES`/`AI_DEEPSEEK_TIMEOUT_S`/`AI_LMSTUDIO_TIMEOUT_S`）在 `.env` 里写成空值时按「未设置」回落字段默认值（`Settings` 的 before 校验器兜住），否则空串进 `float`/`int` 会在构造期抛错、整个后端起不来——字符串字段不适用该规则，它们的「空＝继承全局」是 r9 的真语义。
- 本地档实测标定（2026-11-01 · r9 QA 复测 D-1/D-2）：`AI_LMSTUDIO_TIMEOUT_S` 交付默认 **600s**（旧 180s 实测会把本地画像掐成 503；本机 qwen3.5-9b 单次画像实测 201–224s，×3 余量，只是单请求上限），示例值与字段默认值由门禁 52 互锁且不得低于实测下限 300s；本地小模型画像的 `target_role` 允许为 `null`（模型**原始 JSON** 就是 null，非解析/落库丢值），下游出口固定为「面试提示词回落 `rules.DEFAULT_TARGET_ROLE`、诊断走 `TargetRole(None)` 的 AC-10 降级文案」，口径钉在 `tests/test_profile_null_contract.py::test_target_role_null_is_accepted_and_downstream_defaults_hold`；**不要靠改提示词去抬本地小模型的产出**（TECH-CHANGE §2 明确不改业务提示词，属产品决策另开需求）。
- 一次性升级说明（2026-10-31 · r3 上线须知）：`timeline_events` 由 `backend/app/db.py` 的 `CREATE TABLE IF NOT EXISTS` 随 `init_db()` 自建，**没有迁移脚本、不删旧库、无需手工建表**；`ProfileSkill` / `ProfileProject` 新增 `source_quotes` / `status`，旧画像里只有单条 `source_quote` 的记录由 pydantic validator 自动回填（读旧数据不报错、首次写入后转多证据）；历史 runs / documents **不回填**为时间线事件（时间线只记本版本起的新事件，空态文案「历史数据从本版本起记录」）；润色建议缓存是**进程内**的（重启即失效，`/full` 会重跑并如实标 `regenerated: true`），采纳/临时岗位/成稿一律不入库。
- 验证命令：前端 `npm run typecheck` / `npm run lint` / `npm test` / `npm run build`；后端 `python -m pytest -q` / `python -m ruff check app tests`；探活 `GET /health`。

## 已知待办（下一批）

- [x] M2–M5 全部落地（2026-10-31 · 0.1.0 · 验收见 `docs/teamflow/20261031-r1-dev-skill-coach/ACCEPTANCE.md`）：画像五维 + `source_quote` 溯源与编辑、面试 ≥8 题逐题评分（`SCORING_TIMEOUT_S=14`）、笔试 ≥10 题客观 ≥8 本地判分、报告 3–5 条短板带证据 + 课程兜底 + Markdown 同源导出、历史趋势与刷新持久化。种子题库 12 题/方向（`backend/app/seed/questions.json`），课程 25 门（入门 14）。
- [x] **R-1（P0 子项，验收返工项）已关闭**（2026-10-31 · r2 验收通过，见 `docs/teamflow/20261031-r2-ac5-copy-markdown/ACCEPTANCE.md`）：AC-5「一键复制为 Markdown 文本」已补齐——`复制 Markdown` 按钮（导出 .md 左侧、secondary/40 高、忙态防重复）+ `navigator.clipboard.writeText(await api.reportMarkdown(id))` 零变换（字节相等 103B）+ 成功 Toast（2s / 右下 24 / `--elev-2`）+ 失败页内 `InlineError`（三条失败路径实测）+ `check_copy_markdown.mjs` 7 条断言全 PASS（HEAD 负向自检 5 FAIL 有效）；门禁 typecheck/lint 0 error、pytest 73 全绿。检查器按约定落 `logs/teamflow/<runId>/scripts/`（gitignored，host 归档，不常驻仓库）。
- [ ] 架构文档尾巴：`ARCHITECTURE.md` §3.3 路由表（含 `GET /api/interviews/{run_id}`）、§3.4.1 payload v2、§7.1/§7.2 状态列已随 r5 同步；仍待整理的是 §7.2 表格里的 r5 行与 §8 交接段（仍写「待落地 / 进行中」），以及 §8 末尾重复的一条「统一约束」。
- [ ] 真实环境人工补测：浏览器视觉/动效走查（含 Toast 位置与复制后真机粘贴）、`vitest`+`vite build`、`ruff`、真实 PDF/DOCX 解析、配真实 Key 的端到端计时（AC-1 ≤30s / 面试单题 ≤15s / AC-4 10s / AC-7 ≤5 分钟）；r5 追加：配置真实影响出题的端到端冒烟（≥2 组配置题面对比）、多轮追问措辞抽查、无 Key 开局 InlineError 冒烟、390px 真机与软键盘遮挡。
- [ ] r5 三条 P3 观察（验收已记录、不阻断，见 r5 `ACCEPTANCE.md` §5）：配置态缺会话状态行（`InterviewPage.tsx:288` 仅 chat/ended 渲染）、`Composer.tsx:73` 仅 `maxLength` 无字数计数与超限提示、`frontend/package.json` 的 lint 脚本加 `--max-warnings 28` 未在技术方案改动面声明。
- [ ] r6 三条 P3 工艺观察（验收已记录、不阻断，见 r6 `ACCEPTANCE.md` §6）：过滤信息行无 tooltip 说明「怎样才能让题回流」、结果面板不复显本卷过滤事实、L2 兜底回流时文案不提示「另有 N 道因保持卷面结构被重新纳入」——建议合并为一个「熟练度说明」小需求，优先级 D-9 > D-7 > D-8；另 r6 的 390px 真实视口/键盘走查仍需真机确认一次。
- [ ] r8 两条 P3 观察（验收已记录、不阻断，见 r8 `ACCEPTANCE.md` §5）：①9 题卷追问上限被压到 3 次（12 轮预算里 9 道正题占位），若产品要求用满 4 次需另立需求改预算并同步额度断言；②r5 `TECHNICAL.md:186,302` 仍记 `is_follow_up_allowed` 3 参旧签名（代码已 4 参，历史夹不可改）——由后续需求在架构文档补记。
- [ ] QA round-2 三条 P3：上传上限校验收敛到 `services/parser.py` 单源、框架级 405 文案中文化、`.gitignore` 补 `backend/tests/.tmp/`（本轮已随 r2 工程约束补齐）。
- [ ] 25 门种子课程外链需人工点检一次（当前只校验数量与方向覆盖）。
- [x] **r3 遗留 4 条已立项闭合**（2026-11-01 · 任务夹 `docs/teamflow/20261101-r4-r3-acceptance-closure/`）：r3 判定「⚠️ 有条件通过」，本需求把 R-1（润色页「原版」Tab 改为渲染 `documents.text` 整篇正文，按 DESIGN §240，走补契约 `resume_text` 而非降级设计）、D-2（导出文件名取简历原名，契约补 `file_name`，无文件名回退日期格式）、D-3（删 `profile_merge.py` 的 `CONTRACT_READY` 死分支与四个双份模型）、D-4（合并摘要条补「查看历史能力项」入口）四条已于 2026-11-01 全部闭合并**通过验收**（判定「✅ 通过」，见该任务夹 `ACCEPTANCE.md`），不做任何新功能。R-2（仓库根 `nul`）已由 host 手动删除并确认目录干净，不再处理。**本轮新发现 2 条 P3（不阻断，留后续清理）**：①`backend/app/services/profile.py:150` 的 `if "merge_summary" in getattr(ProfileWithMerge, "model_fields", {})` 为恒真历史防御分支，可删或补注释；②DESIGN（r3）§0.5-4 摘要条 48 高推导需按 border-box 的 1px 边框补偿回写（实现取 `calc(var(--sp-1) - 1px)`）。
- [x] r3 的两处取舍已由验收定稿（2026-10-31）：①AC-7「能力项不足」只落 payload `tech_fallback`、暂不加 InterviewPage/ExamPage 页面提示（接受，页面提示留后续需求）；②润色建议缓存保持**进程内**（接受，`/full` 如实标 `regenerated: true`，满足 AC-10「采纳/临时岗位不入库」边界；跨重启复用需另立需求并先评估该边界）。

## 说明

- 任务产物：docs/teamflow/<日期-rN-slug>/（一需求一夹，建后不可变）
- backlog（需求/任务/缺陷）事实源：$DSH_HOME/teamflow/<workspace>/（按工作区/项目隔离）
- 运行日志：logs/teamflow/<runId>/（run 期间的项目内暂存；run 结束由 host 归档到 $DSH_HOME/teamflow/<workspace>/logs/<runId>/，项目内不留存）
