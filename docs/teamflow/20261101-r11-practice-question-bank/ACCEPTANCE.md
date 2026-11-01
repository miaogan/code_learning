# r11 在线练习题库与练习页 · 产品验收报告

> 任务夹：`docs/teamflow/20261101-r11-practice-question-bank/` · 分支 `feat/dev-skill-coach`（未提交）
> 验收日期：2026-11-02 · 运行 `tf-mvxtymng-j6eln4` · 环境：Windows 10 / Python 3.13 / Node 20 / SQLite
> 依据：本任务夹 `PRD.md` §7（18 条 AC，P0 16 / P1 2）、QA-REPORT（修复后第 2 轮）+ 验收阶段**独立复算与实跑**

## 1. 判定摘要

- **功能面：18 条 AC 全部满足**，无 P0/P1/P2 开放功能缺陷；门禁全部达标（pytest 466 passed+1 skipped、vitest 133、typecheck 0、lint 0 error/28 warning、build OK、`/health` 200）。
- 验收阶段在 QA 之外**另做了一套独立取数**（`logs/teamflow/tf-mvxtymng-j6eln4/scripts/check_accept_r11_prd.py`，37/37 绿）：直接从 `seed/questions.json` 重算题量与分布、从 `schemas.py`/`types.ts` 重解闭集与镜像、从运行时对象量测时延，**不复用 QA 断言**。
- 同时补上了 QA 环境做不到的**真实浏览器实跑**：`/practice` 全链路点击（筛选→作答→反馈→解析折叠→完成态→错题本）与 **390px 视口实测**（QA 记录的「沙箱禁 Chromium」在本验收环境可由宿主浏览器服务绕开）。
- **架构面存在 3 处需要收口的口径问题**（1 处 P0-AC 文档缺项 + 2 处实现与文档/蓝图的偏离），均为文档与契约层、**无功能影响**，据此判**有条件通过**（§4/§5）。

## 2. 验收方式与实测证据（本阶段亲自执行）

| # | 命令 / 操作 | 结果 |
|---|---|---|
| 1 | `cd backend && python -m pytest -p no:cacheprovider -o addopts="" -q` | exit 0，**466 passed, 1 skipped**（门禁 ≥368 ✅；注：`pyproject` 的 `addopts=-q` 会吞掉汇总行，须清空才看得到计数） |
| 2 | `cd frontend && npx vitest run` | exit 0，**133 passed / 10 files**（门禁 ≥124 ✅） |
| 3 | `npm run typecheck` / `npm run lint` / `npm run build` | exit 0 / 0 error·28 warning / exit 0（dist 产出） |
| 4 | 起 uvicorn（`AI_API_KEY=` 置空）+ `curl /health` | 200，`ai_configured:false`、`db:sqlite`（AC-15 零 Key 可跑） |
| 5 | `check_accept_r11_prd.py`（**本阶段新增，独立复算**） | **37/37 通过**：闭集/镜像/新增 180 题/每语言 20 道全部分布闸门/answer⊆options/解析≥10 字/同语言去重 0/可用==库存 260/八模型双侧/无 Key 200/时延 |
| 6 | QA 检查器全量复跑 | functional **73/73**、static **33/33**、data **13/13**、interface **242/242**、exam_kind_cov **8/8**、delivery PASS、question_bank 全 PASS |
| 7 | `check_t1_upgrade_e2e.py`（真 r6 DDL 建库→启动升级） | OK：`filled_first_run=260`、二次 0 变更、`schema_version` 二次不变、`reimport_added=0` |
| 8 | `check_t4_practice_e2e.py` | PASS：20 题全答、错题本 3、`stats.hit=248` |
| 9 | 浏览器实跑 `/practice`（localhost:5173 → 后端 :8000 代理，真实 SQLite） | 侧栏「工具」组首位＝练习；5 组筛选 chip；命中 248→Python 22；「全库已练 0 / 248」；提交前 DOM 无 `answer`/`explanation`（`hasAnswerWord:false`）；未选提交→中文「先选一个答案，再提交」；作答后 ✓/✗+正确答案+解析默认展开+`aria-valuetext="已完成 1 / 10 题（10%）"`；末题「查看本轮结果」→ 完成态 30% + 去错题本/再来一轮/回到筛选；错题本 7 条含语言·方向·难度·最近答错时间·次数、按时间倒序、语言过滤 chips、「错题重练 · 7 题」 |
| 10 | 同一轮实跑中的题卡形态 | 单选=4 radio、多选=4 checkbox、**判断=2 radio（复用单选分支）**；10 题内含判断 2 道（判断题在练习池真实可达） |
| 11 | 390px 视口实测（同源 iframe 宽 390，`matchMedia('(max-width: 640px)')`＝true） | `scrollWidth 375 == clientWidth 375`（**横向溢出 0**）、开始按钮高 **40px**、筛选纵向堆叠、30 个 chip 正常换行；截图复核无遮挡/无裁切 |
| 12 | `git diff --stat -- frontend/src/pages/ExamPage.tsx` | **空**（PRD「笔试页零改动」成立） |
| 13 | `git status --porcelain=v1 -uall` + 越界扫描 | 48 项＝产品代码 + 本任务夹 + `.dsh/memory`；无 `node_modules/dist/__pycache__/*.db/.env` 噪声 |

## 3. 逐条 AC 核对

| AC | 结论 | 验收证据（本阶段复核点） |
|---|---|---|
| AC-1 语言第五维闭集 + 方向归属单一出处 | ✅ | 独立重解 `rules.LANGUAGES`＝`("",python,java,go,html,css,js,ts,vue3,react)`；`schemas.QuestionLanguage` 与 `types.ts` 联合类型**逐字同序 10 项**（我自己写的解析器，非 QA 断言）；库内语言-方向越界 0、闭集外取值 0；`""`≠`"all"` 由契约门禁钉住 |
| AC-2 存量 80 题确定性回填 | ✅ | 表驱动用例 `BACKFILL_CASES`（>8 条）+ 方向约束反例（前端方向命中 python 必须留空）+ 两次 `dumps()` 字节相等；升级链实跑 `filled_first_run=260 / second=0`；回填结果表（css 3 / js 7 / python 2 / react 5 / ts 2，留空 61 为算法与基础题，如实上报） |
| AC-3 180 新增 + 分布闸门 | ✅ | **独立重算**：新增 180 道（py/java/go/html/css/js/ts/vue3/react 各 20），每语言 basic 10–13 / intermediate 5–8 / challenge 2–4、single≥12、multiple≥3、judge≥3、must_know≥6、advanced≥4、含代码块≥2、text=0；算法 61 / 基础 61 且 `language=""`；全库 260≥260；0 例 `blank` |
| AC-4 题面质量硬校验 | ✅ | 单选恰 1 / 多选≥2 / **judge 选项恰 2 且答案恰 1 指向其一**；answer⊆options、选项 2–6、key A–F 唯一；全库解析≥10 字；同语言归一化题干重复 **0**；可用题数 260==库存 260 |
| AC-5 DDL + repository，存量库自动升级 | ✅ | `grep` 确认 **DDL 只在 `db.py`、SQL 只在 `repository.py`**（`CREATE TABLE/ALTER/INDEX` 与 `SELECT/INSERT/UPDATE` 在别处均 0 处）；真 r6 老库（11 列）启动→补列→260 行、老行不被覆盖、二次 0 变更；练习与笔试均 200 |
| AC-6 判断题口径 + 单一判分 | ✅ | `judge` 在 `rules.OBJECTIVE_KINDS` 单一出处；`grade_objective` 全库唯一判分 def（practice 只调不判）；实跑 判断题＝2 radio 走单选分支、`ExamPage.tsx` diff 为空；降级开关 `EXAM_EXCLUDED_KINDS=()`，QA 40 卷覆盖恒含 judge、置 `("judge",)` 时 10 卷 0 judge 且结构仍达标；0 处填空/blank 残留（命中项均为无关词如 `.sc-compose-blank`） |
| AC-7 练习页筛选生效 | ✅ | 真实浏览器：5 组 chip 全在、切换 Python 后命中 248→22；服务层「返回题 100% 命中筛选」17 条断言绿；`limit` 10/20/0 生效；0 命中给中文放宽建议；练习题池 248（12 道 text 不进） |
| AC-8 逐题作答与即时反馈 | ✅ | 实跑：未作答→「先选一个答案，再提交」且不出解析；作答后同屏 ✓/✗ + 正确答案 + 解析默认展开可折叠 + 「第 i / 10 题 · 正确 n · 正确率」；题单 10 题 id 无重复；末题「查看本轮结果」→ 完成态（30% + 三出口） |
| AC-9 unseen / wrong 口径 | ✅ | 服务层构造数据断言：unseen＝无任何 attempt 事件（含笔试事件）、wrong＝最近一次错误、两者互斥可叠加；`check_t4_practice_e2e` 实跑 `hit` 随作答单调变化 |
| AC-10 错题本与重练 | ✅ | 实跑 7 条：题面截断+可展开、语言/方向/难度、最近答错时间、答错次数、按时间倒序（00:13→00:12）、语言过滤 chips、「错题重练 · 7 题」；答对即移出由服务层断言覆盖 |
| AC-11 落库与熟练度零改动 | ✅ | `run_id=practice:<session>`、`source='practice'` 列、同会话同题一条；`proficiency.evaluate()`/`config.py` 阈值未改；组卷**六级阶梯代码零改动**（`git diff` 抽查无阶梯改动）；练熟后候选池过滤、全库熟练仍 200 结构达标（测试 + 40 卷探针）；text 不参与熟练判定 |
| AC-12 契约双侧同步与错误形态 | ✅ | 八模型在 `schemas.py`/`types.ts` 双侧存在（我独立解析）；`PracticeScope` 闭集==`rules.PRACTICE_SCOPES`；非法语言/方向/limit → 422 `VALIDATION_ERROR` 中文、`retryable:false`，零新增错误码；空结果 200+空列表；题单响应无 `answer`/`explanation` |
| AC-13 五种空/错态中文 | ✅ | 实跑覆盖「未选提交」「完成态」「错题本数据态」；QA 断言覆盖题库空态/筛选无结果中文建议/`InlineError`+重试/判分失败保留已选；无白屏无英文 |
| AC-14 零回归门禁 | ✅ | pytest 466/1、vitest 133、typecheck 0、lint 0·28、build OK、`/health` 200；笔试出卷+提交、报告、面试、时间线、润色、复制 Markdown 抽样回归绿；`ruff` 本机未安装（环境限制，历史既有，非交付缺陷） |
| AC-15 离线零 AI + 时延 | ✅ | practice 服务无 AI 依赖（严格正则）；无 Key 四端点全 200；**本阶段独立时延**：题单 4.0–5.3ms（≤300ms）、单题判分 max 13.9ms（P95≤50ms）；题库 seed 固化、运行时零生成 |
| AC-16 交付文档 | ⚠️ 部分满足 | `DESIGN.md`（布局/筛选/解析/390 堆叠/空态文案/无障碍焦点）、`TECHNICAL.md`（回填关键词表+正反例、判断题口径、四端点、DDL 升级路径、attempts 取舍、闭集单一出处清单）齐备；QA-REPORT 有语言题量·难度·题型·必备度分布表与回填结果表、判断题抽检；**但缺 PRD 明确要求的「练习 vs 笔试共用同一题库」说明段**（QA 矩阵标注「见 §6·§7」，而 §6 是分布表、§7 是回填表，实无该说明）→ 见条件 C-1 |
| AC-17（P1）390px 可用 | ✅ | 390px 视口实测：`scrollWidth<=clientWidth`（375==375，溢出 0）、按钮 40 高、筛选纵向堆叠、chip 正常换行、截图无文字裁切与遮挡；代码块内滚由静态 CSS 覆盖（真机软键盘仍建议抽测一次） |
| AC-18（P1）进度可见 | ✅ | 实跑显示「第 1 / 10 题 · 正确 0」→「第 10 / 10 题 · 正确 3 · 正确率 30%」，`role=progressbar` 且 `aria-valuetext="已完成 1 / 10 题（10%）"`；「全库已练 0 / 248」取自服务端 `stats.practiced`；刷新本次统计重置（无新表） |

## 4. 架构一致性核查（M3 质量门 · 必查）

**做对的（我独立核实，不只看测试绿）**
1. 闭集单一出处成立：语言闭集/前后端归属/方向映射/scope/limit/客观题/降级开关全部只在 `rules.py`；`schemas.py` 与 `types.ts` 只是镜像，且镜像由静态门禁牵制。
2. 分层未被打破：**DDL 只在 `db.py`、SQL 只在 `repository.py`**（越界 grep 均 0 处）；路由只做参数/错误映射，业务在 `services/practice.py`。
3. 无重复实现：全库仅一个客观题判分函数 `exam.grade_objective`（practice 只调用）；题面围栏解析只有 `lib/promptCode.ts`、渲染只有 `PromptBody`（题卡与错题本共用）；无第二套闭集字面量、无第二套错误码。
4. 既有主流程未被破坏：`ExamPage.tsx` diff 为空、组卷六级阶梯零改动、`test_engineering_gates` 等既有门禁全绿。

**偏离/待收口（判 ⚠️ 的依据）**

| 编号 | 问题 | 性质 | 影响 |
|---|---|---|---|
| **C-1** | AC-16 要求的「练习 vs 笔试共用同一题库」说明在 QA-REPORT 中缺失（哪一层共享、哪一层刻意不同、为什么），QA 却自评 PASS | P0-AC 文档缺项 | 后续读者无法从任务夹判断「练习与笔试共享到哪一层」，属可验收性的缺口 |
| **C-2** | `exam_selector.py:11` 的 docstring 把「**每种可用客观题型各 ≥1**」列为 `_fit_structure()` 的结构闸门（不满足返回 `None`），但 `_fit_structure()` 实际只校验原四条约束；题型覆盖只是取题排序策略（`_prefer_kind_diversity`）。同时该新增步骤（r11 为让判断题在卷面可达而引入，`+45/-4`）**未记录进 `TECHNICAL.md`**（grep 0 处），而 PRD §3.1/AC-11 的口径是「r6 组卷口径保留」 | 实现超出蓝图 + 文档契约不一致 | 行为上 40/40 卷均含三种题型（策略有效），但「文档承诺的结构闸门」不存在，下一个开发者按 docstring 依赖会踩空；组卷行为变更无技术文档背书 |
| **C-3** | `frontend/src/lib/practice.ts` 的 `directionChips()` 内硬编码 4 个方向字面量（`全部/前端/后端/算法与数据结构/计算机基础`）；`types.ts` 有镜像门禁，但该函数本身无门禁——`rules.DIRECTIONS` 增补时新方向 chip 会静默缺失（与蓝图「方向闭集单一出处、前端只消费服务端 direction」的意图相反） | 闭集潜在第二来源 | 当前四方向下无功能影响；属下一轮加方向时的漂移风险 |

> 说明：`PromptBody.tsx` 比蓝图多抽 1 个模块属**正向收敛**（消除题卡/错题本两处渲染），不算返工项，只需在技术文档文件清单里补记（并入 C-2 的文档动作）。

## 5. 结论与条件

**功能验收通过**（18 条 AC 中 17 条全满足、AC-16 部分满足；0 条 P0/P1/P2 功能缺陷），但按验收规则，**「功能全绿 + 偏离蓝图/文档契约不一致」不得判无条件通过**，故：

**判定：有条件通过** —— 以下 3 项收口后即可终结（预计 ≤1 小时，均不涉及功能改造与整轮复测）：

1. **C-1**：在 QA-REPORT 补「练习 vs 笔试共用同一题库」说明段——共享层：同一份 `seed/questions.json`、同一张 `questions` 表、同一个 `exam.grade_objective()`、同一张 `question_attempts`（`source` 区分）、同一套 `proficiency.evaluate()` 阈值；刻意不同层：练习池只收 `single/multiple/judge`（12 道 `text` 不进）且不设卷面结构闸门，笔试收含 `text` 的可用题且受 10–12 题/客观≥8/挑战≤20%/方向覆盖约束；原因：练习要「即时判分 + 秒开 + 任选范围」，笔试卷要「结构稳定 + 可对比 + 防泄题」。
2. **C-2**：`exam_selector.py` docstring 与实现对齐（二选一：把「每种可用客观题型≥1」降级表述为**取题策略**，或真正在 `_fit_structure()` 里校验），并把 `_prefer_kind_diversity`（含引入原因：r11 判断题在旧取题顺序下结构不可达）+ `PromptBody.tsx` 补记进 `TECHNICAL.md`。
3. **C-3**：`directionChips()` 改由单一常量/类型派生（或补静态门禁），消除方向闭集的第二份字面量。

**遗留与说明**
- QA 的 3 条 P3 观察（OBS-1/2/3）与本阶段 C-1/C-2/C-3 对应，其中 OBS-1↔C-3、OBS-2↔提示词文档补记、OBS-3↔C-2；均已纳入上表，不另计。
- 环境限制（如实记录）：`ruff` 本机未安装（历史既有）；QA 记录的「沙箱禁 Chromium」在本验收环境不成立——已用宿主浏览器完成 `/practice` 全链路点击与 390px 视口实测，AC-17 由「静态断言 + 待人工补测」升级为**实测通过**。仍建议真机（手机软键盘）抽测一次代码块横向滚动。
- 分支 `feat/dev-skill-coach` 原地继续、未提交；验收阶段未修改任何产品代码，只新增本报告、一个独立复核脚本与状态文件。

验收结论：⚠️ 有条件通过
