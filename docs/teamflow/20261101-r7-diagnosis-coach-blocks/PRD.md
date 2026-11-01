<!-- meta: summary="在既有 3–5 条带证据短板的诊断报告上旁挂三块可复算区块：知识薄弱地图（方向×难度×必备级别聚合）、简历改进要点（复用润色引擎 + 跳转定位）、市场竞争力对标（内置岗位能力模型 + 可复算差距），并保证 .md 导出/复制 Markdown 单源一致、契约双侧同步、旧报告不报错。" -->

基线依赖：20261101-r6-exam-proficiency-filter、20261031-r3-memory-resume-polish、20261101-r5-interview-chat-config、20261031-r2-ac5-copy-markdown（各既有行为不得回归）

# r7 · 诊断报告补强：简历怎么改 / 哪些知识薄弱 / 如何提升市场竞争力

## 1. 背景与目标

四步闭环、多轮对话面试（r5）、成长时间线（r3）、简历润色（r3/r4）、题库熟练度过滤（r6）都已交付。诊断报告目前只有一件事做得好：**给出 3–5 条带真题证据的短板 + 课程**。用户拿到报告后仍然要自己回答三个问题——「我哪些知识薄弱？」「简历该怎么改？」「离目标岗位还差什么？」——目前只能靠人肉对照历史页、润色页和自己脑补。

本轮是这个系列的收尾轮，只补强报告**读完之后能立刻动手**的三块内容，主轴（短板）不动：

1. **知识薄弱地图**：把已经算过的错题/低分题按「方向 × 难度 × 必备级别」摊开，给出可复算排序的薄弱清单。
2. **简历改进要点**：只给 3–5 条「改什么 + 具体位置 + 一句话问题」，并一键跳到润色页对应条目（润色能力**复用**，不重写）。
3. **市场竞争力对标**：内置岗位能力模型，输出「用户画像 vs 目标岗位」的可复算差距与「先后补什么」。

目标（可验收）：报告页在既有短板主轴之下多出三块可用区块；.md 导出与「复制 Markdown」拿到同一份文本；旧报告打开不报错；全量门禁只增不减。

## 2. 现状核对（以下为代码事实，不是从 PRD 推的）

| 事实 | 位置 | 对本轮的约束 |
|---|---|---|
| 短板聚类/排序/证据在 `build_shortfalls`，严重度阈值只在 `rules.py`（`SEVERITY_HIGH_BELOW=4.0`、`SEVERITY_MEDIUM_BELOW=7.0`、`MIN/MAX_SHORTFALLS=3/5`） | `backend/app/services/diagnosis.py` | 薄弱地图必须复用这里的 `_scored` / `_cluster` / `question_ref` 口径，不得另写算分 |
| 面试按 `kind`、笔试按 `direction` 聚类；简答题（kind=text）不判分不写熟练度 | `diagnosis._cluster` / `rules.OBJECTIVE_KINDS` | 薄弱地图的分母只含**已计分**题；简答题不进分母 |
| 分数口径唯一实现 `history.score_of(kind, payload)`；时间线也用它 | `backend/app/services/history.py` | 报告侧如需分数，一律走它 |
| 题库已带四维标签 `direction / kind / difficulty(basic\|intermediate\|challenge) / essentiality(must_know\|advanced\|nice_to_know)`，闭集在 `rules.DIRECTIONS / DIFFICULTIES / ESSENTIALITIES` | `backend/app/services/question_bank.py`、`rules.py` | 薄弱地图的三键取值只能来自闭集，标签从 `load_questions()` 反查题目 id 得到 |
| 润色引擎 `build_suggestions(resume_text, profile, target_role, *, client)` 走 `POLISH_SYSTEM` 单提示词，返回含 `section/original_text/suggested_text/reason/start/end`，另有 `validate_suggestions` 反幻觉校验 | `backend/app/services/resume_polish.py`、`schemas.PolishSuggestion` | 简历要点**只能**复用它；diagnosis 内不得再写润色提示词 |
| 报告 `.md` 由 `to_markdown(report)` 单源渲染；页面「复制 Markdown」/导出都取 `GET /api/reports/{id}/markdown` 文本，前端不二次拼串 | `backend/app/services/markdown.py`、`routers/report.py`、`frontend/src/pages/ReportPage.tsx` | 新区块必须进 `to_markdown`；前端只渲染后端文本 |
| `Report` 契约字段：`id/run_ids/interview_avg/exam_total/shortfalls/generated_at/interview_settings`；`Shortfall` 含 `question_ref` | `schemas.py`、`frontend/src/api/types.ts` | 新增字段必须双侧同步、snake_case、有默认值 |
| 面试设定四项落 `runs.payload.settings`，读取投影唯一实现 `history._interviews_settings_of`（→ `rules.settings_or_none`），缺失返回 `None` 不补默认 | `r5` 交付 | 竞争力对标的岗位来源要沿用它，不得新写解析 |
| 路由为 `react-router` 固定 7 条 path，`/polish` 目前**不读** query 参数 | `frontend/src/App.tsx`、`PolishPage.tsx` | 跳转定位需要给润色页加一个只读定位入参 |
| `courses.json` 是 seed 目录唯一业务数据文件（`courses.py` 用 `lru_cache` 加载 + 校验） | `backend/app/seed/` | 岗位能力模型放同目录，加载器同风格 |

## 3. 用户故事与验收标准

### 区块 A · 知识薄弱地图（哪些知识比较薄弱）

**US-A**：作为刚做完笔试+面试的候选人，我想看到「我在哪些方向上、哪种难度、是否必备题上失分最多」，以便把有限的复习时间投到必须补的地方。

- 每条薄弱项字段：`point`（薄弱知识点名称，方向级）、`direction`、`wrong`（错题/低分题数）、`total`（参与统计的总题数）、`difficulty`（涉及难度集合）、`essentiality`（涉及必备级别集合）、`samples`（1–3 条 `{question_id, score, evidence}`，`evidence` 沿用 `Q{index} · {score}/10` 口径）、`summary`（一句话薄弱点描述）、`rate`（错误率，服务端算好，前端不重算）。
- 排序：**必备级别优先**（must_know → advanced → nice_to_know）→ 组内错误率降 → 均分升 → 题量降 → `question_id` 字典序稳定收尾。全部在纯函数里，AI 不参与。

**AC-1（口径复用，简答题不计分）**：薄弱地图的题目集合必须由 `diagnosis` 既有 `_scored(run)`（面试取 payload 回写的 `score`，笔试取逐题结果/本地比对）与 `history.score_of` 口径产生；构造一场含 2 道简答题（kind=text）的笔试 fixture，断言这 2 题既不进 `wrong` 也不进 `total`，且 `total` 等于 `_scored` 返回条数。静态断言：`services/` 内不出现第二份均分/判分实现（新增模块只允许 import 既有函数）。

**AC-2（三键聚合与字段完整）**：以「方向 × 难度 × 必备级别」三键聚合，构造覆盖 2 方向 × 3 难度 × 3 必备级别的 fixture，断言输出分组条数等于预期分组数、每条 `difficulty`/`essentiality` 集合非空且取值属于 `rules.DIFFICULTIES` / `rules.ESSENTIALITIES`、`samples` 长度 1–3 且每个 `question_id` 都能在 `question_bank.load_questions()` 里反查到、`wrong ≤ total`、`rate = wrong/total` 与 `round` 口径一致。

**AC-3（排序可复算、无 AI 参与）**：对 AC-2 的 fixture 断言输出顺序严格满足「必备级别优先 → 错误率降 → 均分升 → 题量降 → id」，并断言同一输入连续两次调用结果逐字相同；用 `monkeypatch` 让 `AIClient.complete_model` 抛异常，顺序与 `summary` 字段（模板文案）均不变化。

### 区块 B · 简历改进要点（简历怎么改）

**US-B**：作为准备投递的候选人，我想知道简历里**哪一条**写得不行、问题是什么，并能一键跳到润色页那一条，而不是重读整页建议。

- 报告给 3–5 条要点，每条：`section`（`project|experience|education|summary` 闭集）、`location`（人可读位置，如「项目二 · 第 2 条」）、`anchor_text`（**逐字来自简历正文**的短句，用于定位）、`issue`（一句话问题，如「只写了『参与开发』，没有问题、没有量化结果」）、`focus_key`（跳转定位键）。
- 每条带一个跳转动作：`/polish?focus=<focus_key>`，润色页据此聚焦到同一 `section` + `anchor_text` 的建议条目。

**AC-4（复用润色引擎，无第二份提示词）**：简历要点必须通过 `resume_polish.build_suggestions(...)`（同一 `POLISH_SYSTEM`、同一 `client` 注入点）产出后取前 3–5 条；断言：①`monkeypatch` 记录调用次数 ≥1 且传入的 `resume_text` 与简历正文逐字相等；②`diagnosis`/新增服务模块内不存在新的系统提示词字面量（静态：除 `resume_polish.POLISH_SYSTEM` 外无第二份含「润色」的系统提示词定义）；③`anchor_text` 在正文中 `find` 命中且与建议 `original_text` 一致（逐字），命中不到的建议整条丢弃而不是猜。

**AC-5（跳转定位到润色页）**：点击要点跳转后，润色页读取 `focus` 入参，在建议列表中找到 `anchor_text` 逐字相等的条目 → 滚动到该卡片并加焦点高亮（可见焦点环，键盘可达）；找不到时按该 `section` 预筛并在列表顶部显示中文提示「未找到对应条目，已按「项目」筛选」。页面 DOM 与文案中不出现任何提示词文本（静态：前端源码不引用 `POLISH_SYSTEM` 或提示词片段）。

**AC-6（简历缺失降级）**：无简历 / 正文为空 / 无画像时：`resume_pointers` 为空数组，报告页该区块显示中文占位「还没有可定位的简历正文，先上传简历再回来看改进要点」，跳转按钮不渲染，其余区块正常，`POST /api/reports/generate` 仍 200。

### 区块 C · 市场竞争力对标（如何提升市场竞争力）

**US-C**：作为有目标岗位的候选人，我想看到「我 vs 这个岗位的能力模型」差在哪几项、差多少、先补什么。

- 内置岗位能力模型数据 `backend/app/seed/role_models.json`（与 `courses.json` 同级、人工维护）：每个方向（与 `rules.DIRECTIONS` 一致）3–4 个岗位级别，每级 6–8 项能力项（含 `name` / `required` 档位）+ 必备技能清单（≥3 项）。
- 报告输出：目标岗位、来源、逐项差距（`required` / `user_level` / `gap`）、缺失的必备技能、以及「先后补什么」有序前 3 项。
- 排序：**必备项优先 → 差距最大优先 → 能力项名稳定**，全纯函数。

**AC-7（模型数据与加载器）**：`role_models.json` 存在且结构与数量满足：方向覆盖 `rules.DIRECTIONS` 四项、每方向级别 3–4、每级能力项 6–8、必备技能 ≥3；加载器（`lru_cache` + pydantic 校验，风格同 `courses.py`）在文件缺失 / JSON 损坏 / 缺字段时抛中文 `VALIDATION_ERROR`（`{error:{code,message,retryable}}`，无路径堆栈），不 500；测试断言上述数量、闭集一致性与两条异常路径。

**AC-8（差距可复算）**：`build_role_fit(profile, target_role)` 纯函数，输入画像技能/技术栈与模型级别，输出 `items[]`（`name/required/user_level/gap`）与 `missing_must[]`；断言：①`gap` 计算与排序严格为「必备优先 → gap 降 → name」；②同一输入两次结果相同；③`missing_must` 恰等于模型中 `must_have` 里画像未命中的技能集合（不靠 AI）；④不合格输入（画像为空）返回全缺失，不抛异常。

**AC-9（目标岗位来源优先并注明）**：岗位来源优先级 = 最近一次面试的 `runs.payload.settings.target_role`（经 `history._interviews_settings_of` 读取，缺失为 `None`）> 画像 `profile.target_role`；两者都存在且不同时，响应带 `role_source`（`"interview"` / `"profile"`）与 `role_source_label`（「本次面试设定」/「简历画像」），报告页与 `.md` 均显示来源；不得静默取其一或取默认值。

**AC-10（无匹配岗位模型降级）**：`target_role` 未命中任何模型（含空值）时：`role_fit.model` 为 `null`、`items[]` 为空、`notice`＝「暂无该岗位的能力模型」；报告 HTTP 200，其余区块完整，`.md` 也包含该提示。

### 横向契约与工程质量

**AC-11（AI 只补文案，失败降级）**：三块区块的**条目、顺序、数值**全部由纯函数产出；AI 仅可为区块补 1 句自然语言（薄弱项 `summary`、竞争力 `conclusion`）。断言：①`AIClient.complete_model` 抛异常 / 返回坏 JSON / 未配置 Key 三种情况下报告均 200 且三块结构完整（模板文案可读、非占位符）；②AI 返回的 `name` 与原条目不逐字相等时整条丢弃，绝不新增或删除条目；③构造 AI 返回条目数 ≠ 输入条目数的响应，输出条数不变。

**AC-12（markdown 单源一致）**：`to_markdown` 增加三块（薄弱地图表、简历要点列表、「用户画像 vs 目标岗位」差距表 + 来源 + 降级提示），顺序与 `Report` 字段一致；断言 `GET /api/reports/{id}/markdown` 文本里三块的条目数、名称顺序与 `report.weakness_map/resume_pointers/role_fit` 逐条一致；断言前端 ReportPage 不含拼装 `.md` 的逻辑（静态：无模板拼串导出路径，导出仍取 markdown 端点文本）。

**AC-13（契约双侧同步 + 旧报告兼容）**：`backend/app/schemas.py` ↔ `frontend/src/api/types.ts` 逐字镜像新增字段（`weakness_map` / `resume_pointers` / `role_fit` 及其内层、全部 snake_case、`Optional` 且默认 `None`/`[]`）；把 r1–r6 形态的旧 report payload（无三字段）喂给 `repository.latest_report()` → 反序列化成功、接口 200、页面三块显示「旧报告不含该区块，重新生成可补全」而不是空白卡片或白屏；历史页 `GET /api/runs` 与旧报告打开均回归通过。

**AC-14（主轴不破）**：同一 fixture 在本轮改造前后 `build_shortfalls` 输出的 `name/severity/evidence/question_ref` 序列**完全一致**，`3 ≤ len(shortfalls) ≤ 5`；报告页 DOM 顺序仍是「短板总览 → 短板卡片」，三块在其后；`Shortfall` 字段无删改。

**AC-15（门禁只增不减）**：`pytest ≥ 204 passed + 本轮新增`、`vitest ≥ 72 passed + 本轮新增（≥8 条前端断言，覆盖渲染/降级/跳转定位纯函数）`、`typecheck` 0 error、`lint` 0 error / ≤28 warning、`npm run build` 通过、`GET /health` 200；新增后端用例覆盖：聚合/排序/简答题排除/模型数据校验/差距排序/来源优先/无模型降级/AI 降级/旧报告反序列化/markdown 三块。

**AC-16（样式与错误形态）**：只用 `frontend/src/styles/tokens.css` 变量，无裸色值（含 CSS 注释里的色值字面量，`test_engineering_gates.py` 同口径）；三块 390px 无横向滚动、窄屏堆叠顺序为「薄弱地图 → 简历要点 → 竞争力对标」；错误一律 `{error:{code,message,retryable}}`，`message` 中文、不含路径/堆栈/Key。

**AC-17（DESIGN.md 交付）**：任务夹内 DESIGN.md 说明三块在报告页的信息层级、与「3–5 条短板主轴」的视觉关系、窄屏堆叠顺序、无数据/降级形态与文案、跳转高亮的焦点态；尺寸改动须重算推导并回写（DESIGN §0.7 约定）。

**AC-18（改动面白名单 + 无新依赖）**：仅允许改动 `backend/app/seed/role_models.json`（新增）、`backend/app/services/diagnosis.py` 或新增 `services/{weakness,role_fit,resume_hints}.py`、`services/markdown.py`、`schemas.py`、`frontend/src/api/types.ts`、`components/report/*`、新增报告区块组件、`pages/ReportPage.tsx`、`pages/PolishPage.tsx`（仅定位入参/高亮）、对应 tests；`repository.py` 若需读取一律在其内、DDL 只在 `db.py`、routers 只做参数校验与错误映射；不新增 pip/npm 依赖。

**AC-19（P1 · 薄弱地图上限）**：薄弱地图最多展示 8 条，超出时显示「其余 N 条已折叠」并可展开；列表为空（无已计分题）时显示「本次测评还没有可统计的计分题」。

**AC-20（P1 · 先补项标记）**：竞争力对标的「先后补什么」按排序取前 3 项并带 1/2/3 序号与视觉标记，序号与 `items[]` 顺序一致（前端不重排）。

**优先级**：P0 = AC-1、2、3、4、5、6、7、8、9、10、11、12、13、14、15、16、17、18；P1 = AC-19、20。

## 4. 范围与非目标

**范围**：报告 payload 三块新数据 + 报告页三块 UI + `.md` 三块渲染 + 润色页定位入参 + 岗位能力模型 seed 与加载器 + 后端/前端测试。

**非目标（本轮不做）**：
- 不做岗位能力模型管理 UI、不做简历编辑器、不改润色提示词与反幻觉逻辑。
- 不做跨用户/多人对比、不做行业薪资或市场行情数据、不接外部招聘 API。
- 不改短板主轴算法、课程匹配、时间线、题库过滤、面试对话流程。
- 不做报告版本化/分享链接；不改 `Report.id` 生成方式。
- 不更新 `memory.md`（本轮无新的跨需求团队约定；seed 目录与单源导出约定已存在）。

## 5. 反面目标 / anti-goals

以下都是「测试全绿但用户会当场拒绝」的失败形态，每条都可被使用者直接观察到：

1. **报告首屏被三块新内容顶走**：打开报告页第一屏看不到带证据的短板，用户会认为原来的诊断被稀释了——验收人只需看首屏截图/DOM 顺序即可判定。
2. **薄弱地图的错题数与历史页对不上**：同一场笔试在历史页显示 12 题错 8，报告地图写「8/10」，用户一对照就整份报告不可信。
3. **简历要点指向不存在的句子**：点「改这一条」跳到润色页，高亮不到任何条目或高亮到另一句，用户点一次就不再信任这条链路。
4. **竞争力差距像 AI 编的**：差距项无法从岗位模型复算，或必备技能明明缺却说已满足，用户拿一张 JD 一比就发现不符。
5. **报告变慢或 AI 一挂就空白**：多一次模型调用后生成时间从 <10s 涨到 30s+，或未配置 Key 时报告页转圈/白屏而不是降级文案——用户看不到任何「可读的降级结果」。

## 6. 交互流程摘要

1. 用户在报告页点「生成报告」→ 后端合并最近面试+笔试 → 算短板（不变）→ 算薄弱地图（纯函数）→ 取画像/简历 → 复用润色引擎取 3–5 条要点 → 读岗位模型算差距 → AI 可选补 1 句文案（失败降级）→ 存库并返回。
2. 报告页自上而下：概览（分数/关联测评）→ **短板总览 + 3–5 条短板卡片（主轴，位置不变）** → 「提升路线」分区：①薄弱地图（表格）②简历改进要点（3–5 条 + 跳转）③市场竞争力对标（来源徽标 + 差距表 + 先补 3 项）。
3. 点简历要点 → `/polish?focus=<key>` → 润色页滚动并高亮对应建议；未命中按 `section` 预筛 + 顶部提示。
4. 「复制 Markdown」/「导出 .md」仍取后端文本，三块内容天然同源。
5. 无简历：要点区块出中文占位、无跳转；无匹配岗位模型：竞争力区块出「暂无该岗位的能力模型」并保留其余区块；旧报告：三块位置显示「旧报告不含该区块，重新生成可补全」。

## 7. 依赖与风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| 岗位能力模型是人工数据，覆盖不到自由文本 `target_role` | 竞争力区块高频降级 | 内置别名表做包含匹配；降级文案明确；模型先覆盖 `rules.DIRECTIONS` 四方向，别铺量 |
| 报告生成多一次润色模型调用，时延上升 | 用户等不动 | 设上限（≤8s）超时即降级为模板要点；AI 与润色调用并行/串行均失败可报告；报告绝不因 AI 失败失败 |
| 简历要点定位依赖 `original_text` 逐字命中 | 跳转后高亮不到 | 服务端只在命中时产出该条；前端未命中回退 `section` 预筛 + 中文提示 |
| 新增字段破坏旧报告反序列化 | 历史页白屏 | 三字段全部可选带默认；旧报告 fixture 常驻用例 |
| 样式新增区块易出现裸色值/窄屏横滚 | 门禁失败 | 只用 tokens；390px 用例；`test_engineering_gates.py` 口径先行 |
| `to_markdown` 与页面双源漂移 | 复制/导出不一致（r2 AC-5 回归） | 页面只展示后端 markdown 文本，前端不拼串；断言条目数/顺序一致 |

## 8. 里程碑建议

- **波次 1（后端纯函数）**：薄弱地图聚合与排序（复用 `_scored`/`_cluster`）、岗位模型 seed + 加载器、`build_role_fit` 差距排序、来源优先级；全部纯函数先测。
- **波次 2（编排与契约）**：`build_report` 接线三块（AI 只补文案 + 降级）、`schemas.py` ↔ `types.ts`、旧报告兼容。
- **波次 3（单源渲染与前端）**：`markdown.py` 三块、报告页三块组件与窄屏堆叠、润色页 `focus` 入参与高亮、降级形态与文案。
- **波次 4（设计与门禁）**：DESIGN.md、全量门禁（pytest/vitest/typecheck/lint/build/health）与新增用例补齐。

## 9. 工程约束（原文保留）

1. 分支 `feat/dev-skill-coach` **原地继续，不新开分支**；Agent **不提交**，由流水线验收后统一提交。
2. 工作区当前未提交改动只有 1 处：`?? docs/teamflow/20261101-r7-diagnosis-coach-blocks/`（本任务夹）。**保持原样**：不 stash、不清理、不 amend、不新建分支；开发只在其上加代码改动。
3. 先读 `AGENTS.md`、`docs/teamflow/architecture/ARCHITECTURE.md` 与 r3/r4/r5/r6 任务夹；`repository.py` 是唯一 SQL 出口（DDL 只在 `db.py`），routers 只做参数校验与错误映射，services 承载业务。
4. 本轮 UI 新增区块较多，需要设计说明（三块在报告页的信息层级、与既有 3–5 条短板主轴的视觉关系、窄屏堆叠顺序、无数据时的降级形态）—— DESIGN.md 随任务夹交付。
5. **.gitignore 审计（本栈，dev 阶段动作）**：确认/补齐后端 `__pycache__/`、`*.py[cod]`、`backend/.venv/`、`venv/`、`.venv/`、`.pytest_cache/`、`.ruff_cache/`、`backend/tests/.tmp/`、`backend/.test-scaffold.db`、`*.db`、`*.db-wal`、`*.db-shm`、`*.db-journal`、`*.sqlite3*`；前端 `node_modules/`、`node_modules-*/`、`.pnpm-store/`、`dist/`、`frontend/.vite/`、`frontend/.npm-cache/`、`*.tsbuildinfo`、`coverage/`；密钥 `.env`/`.env.*`（保留 `.env.example`）；编辑器 `.vscode/`、`.idea/`、`*.log`、`.DS_Store`。本轮若新增产物（如角色模型缓存、报告测试临时库）未被覆盖，**补 .gitignore，不提交产物**。
6. 文档只在 `docs/teamflow/` 写（本任务夹 + 必要的 `architecture/ARCHITECTURE.md` 题库/报告表述同步）；不写宿主 `docs/<职责>/`，不在项目根散落日志。
7. 契约硬约束：`backend/app/schemas.py` ↔ `frontend/src/api/types.ts` 必须同时改、snake_case、可选项带默认；错误统一 `{error:{code,message,retryable}}`；样式只用 `tokens.css` 变量。

## 10. 假设与待澄清

**（a）未定事实（kind=fact）**
- 岗位能力模型如何与自由文本 `target_role` 对齐（关键词包含 vs 别名词典 vs 人工映射表）：决定命中率与降级频率；若选定别名词典，模型文件需增加 `aliases` 字段。
- 简历要点复用的那次润色模型调用是否计入报告生成关键路径与超时预算：决定「报告慢但更准」还是「报告快但要点走模板」。
- 岗位模型的级别如何与 `r5` 的 `years_experience` 五档对应（1:1 映射还是合并档位）：决定默认展示哪个级别。
- 旧报告的三块要不要在打开时惰性重算：默认不重算（保持「旧报告不含该区块，重新生成可补全」），若要求重算则需引入报告补算任务与幂等写库。

**（b）用户口味（kind=taste）**
- 三块与短板主轴的排布顺序与视觉层级：强烈建议短板在上、三块作为「提升路线」分区按 薄弱地图 → 简历要点 → 竞争力纵向排列；若用户想「先看竞争力再看短板」，信息层级会整体反转。
- 简历要点跳转形态：滚动+高亮（当前推荐，保留润色页上下文）vs 打开即预筛该 section（更快但丢失上下文）。
- 竞争力对标的目标级别由谁定：按年限自动匹配（推荐）vs 固定中位级 vs 页面允许手动切换（不写回画像）。
- 薄弱地图列表上限：8 条 + 折叠（推荐）vs 全量展开 vs 只给 Top 5。

（本节所有条目均已进入状态文件 `openQuestions`，并附推荐默认值。）
