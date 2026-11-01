# r11 练习题库与练习页 · QA 复测报告（缺陷修复后第 2 轮）

> 任务夹：`docs/teamflow/20261101-r11-practice-question-bank/` · 分支 `feat/dev-skill-coach`（未提交）· 复测日期 2026-11-01
> 运行 ID：`tf-mvxtymng-j6eln4` · 环境：Windows 10 · Python 3.13 · Node 20 · SQLite（本地）
> 本轮性质：**修复后复测**（上轮报 P1×1 + P2×2 + P3×1，dev 修复轮已改代码），按 QA 规则先复跑上轮全部检查器，再补上轮未覆盖的表面。

## 1. 结论

**通过，可验收（0 条 P0/P1/P2 开放缺陷）**。上轮 4 条缺陷全部关闭并按当轮的 Check command 逐条复跑验证：
判断题现在**真的进得了笔试卷**（40 个种子 × 卷面题型覆盖恒含 judge，降级开关也能一键摘掉），组卷侧客观题闭集接线已生效，提交面卫生干净，进度轨无障碍语义补齐。
练习域四端点、题库 260 题数据面、存量库升级、前端四件套门禁全部绿；新增 2 个探针（接口一致性 242 项、笔试题型覆盖 40 卷）证明「文件存在 ≠ 能跑」这一类风险已排除。
仅剩 3 条 P3 观察项（架构/文档口径），不阻塞验收。

## 2. 范围与环境

| 项 | 说明 |
|---|---|
| 变更面 | 后端 `db.py`/`repository.py`/`rules.py`/`schemas.py`/`question_bank.py`/`question_backfill.py`/`practice.py`/`routers/practice.py`/`main.py`/`seed/questions.json`/`exam_selector.py`；前端 `PracticePage` + 6 个 practice 组件 + `lib/practice.ts` + `lib/promptCode.ts` + `PromptBody` + `ExamQuestionCard` + `SegTabs` + `App.tsx` + `client.ts` + `types.ts` + 样式（append-only） |
| 环境限制 | 沙箱禁止启动 Chromium（crashpad 需 PROCESS_ALL_ACCESS，已记录在案，**非交付缺陷**）→ UI 用 React 真渲染（SSR）+ 纯函数断言；`ruff` 本机未安装（历史既有，非本轮引入）。真实点击级交互与 390 真机列入 §8 人工补测 |
| 数据面 | 题库 260 题（客观 248 / 简答 12，练习题池 248）；存量库升级用真 r6 DDL 建库后启动验证 |

## 3. 实跑证据（命令 / 退出码 / 结果）

| # | 命令 | 退出码 | 结果 |
|---|---|---|---|
| 1 | `cd backend && AI_API_KEY= python -X utf8 -m pytest -p no:cacheprovider -q` | 0 | **467 收集 / 0 失败**（1 skipped；门禁 ≥368 ✅，含上轮红过的 `test_r11_touched_paths_resolve`） |
| 2 | `cd backend && AI_API_KEY= python -X utf8 -m pytest -p no:cacheprovider -q tests/test_engineering_gates.py -k r11` | 0 | 6/6（含 dev 新增 `test_r11_judge_reachable_in_exam_paper`） |
| 3 | `cd frontend && npm run typecheck` | 0 | 0 error |
| 4 | `cd frontend && npm run lint` | 0 | 0 error / 28 warning（= 基线 28） |
| 5 | `cd frontend && npx vitest run` | 0 | **133 passed / 10 files**（基线 109 + 24） |
| 6 | `cd frontend && npm run build` | 0 | dist 产出（101 modules，JS 285.84 kB / CSS 63.15 kB） |
| 7 | `cd backend && AI_API_KEY= python -X utf8 ../logs/teamflow/tf-mvxtymng-j6eln4/scripts/check_qa_r11_functional.py` | **0** | **73/73**（上轮 69/72；D1 的 3 条 AC-6 断言全绿） |
| 8 | `cd backend && AI_API_KEY= python -X utf8 ../logs/teamflow/tf-mvxtymng-j6eln4/scripts/check_qa_r11_static.py` | **0** | **33/33**（上轮 31/33；D2/D3 断言全绿） |
| 9 | `cd backend && AI_API_KEY= python -X utf8 ../logs/teamflow/tf-mvxtymng-j6eln4/scripts/check_qa_r11_data.py` | 0 | 13/13（回填确定性、两道分布闸门、AC-4 八条结构校验） |
| 10 | `cd backend && AI_API_KEY= python -X utf8 ../logs/teamflow/tf-mvxtymng-j6eln4/scripts/check_r11_delivery.py` | 0 | `RESULT: PASS（0 失败）`（契约镜像 / 路由 / 样式 append-only） |
| 11 | `cd backend && AI_API_KEY= python -X utf8 ../logs/teamflow/tf-mvxtymng-j6eln4/scripts/check_r11_question_bank.py` | 0 | 全部通过（含存量库 80→260 端到端、二次导入 0 新增、11 语言组卷） |
| 12 | `cd backend && AI_API_KEY= python -X utf8 ../logs/teamflow/tf-mvxtymng-j6eln4/scripts/check_t1_upgrade_e2e.py` | 0 | `filled_first_run=260 / 二次 0 变更 / schema_version 第二次不变 / reimport_added=0` |
| 13 | `cd backend && AI_API_KEY= python -X utf8 ../logs/teamflow/tf-mvxtymng-j6eln4/scripts/check_t4_practice_e2e.py` | 0 | PASS（20 题全答、错题本 3、stats.hit 248） |
| 14 | `cd frontend && npx esbuild ../logs/teamflow/tf-mvxtymng-j6eln4/scripts/check_qa_r11_ui.tsx --bundle --platform=node --format=cjs --jsx=automatic --define:import.meta.env='{"VITE_API_BASE":""}' --external:react --external:react-dom --external:react/jsx-runtime --external:react/jsx-dev-runtime --external:react-dom/server --external:react-router-dom --outfile=../logs/teamflow/tf-mvxtymng-j6eln4/probe/qa_ui.cjs && NODE_PATH=$PWD/node_modules node ../logs/teamflow/tf-mvxtymng-j6eln4/probe/qa_ui.cjs` | 0 | **32/32**（上轮 31；本轮**新增 1 条 D4 断言**：`aria-valuetext` 含「已完成 4 / 10 题（40%）」） |
| 15 | `cd frontend && npx esbuild ../logs/teamflow/tf-mvxtymng-j6eln4/scripts/check_exam_card_render.tsx --bundle --platform=node --format=cjs --jsx=automatic --external:react --external:react-dom --external:react/jsx-runtime --external:react/jsx-dev-runtime --external:react-dom/server --outfile=../logs/teamflow/tf-mvxtymng-j6eln4/probe/exam_card.cjs && NODE_PATH=$PWD/node_modules node ../logs/teamflow/tf-mvxtymng-j6eln4/probe/exam_card.cjs` | 0 | 11/11（无围栏题面逐字不变、judge 走 radio、footer 位置） |
| 16 | `cd backend && AI_API_KEY= python -X utf8 ../logs/teamflow/tf-mvxtymng-j6eln4/scripts/check_qa_r11_interface.py`（**本轮新增**） | 0 | **242/242**：跨模块成员存在性 + 调用实参形状 + 蓝图 api 45 个符号 + 前端整包具名 import 解析 |
| 17 | `cd backend && AI_API_KEY= python -X utf8 ../logs/teamflow/tf-mvxtymng-j6eln4/scripts/check_qa_r11_exam_kind_cov.py`（**本轮新增**） | 0 | 8/8：40 卷题型覆盖恒 == `['judge','multiple','single']`；`EXAM_EXCLUDED_KINDS=('judge',)` 下 10 卷 0 judge 且结构仍达标 |
| 18 | `cd backend && DB_PATH=tests/.tmp/qa-r11-live2.db AI_API_KEY= python -m uvicorn app.main:app --port 8139` + `curl -sS http://127.0.0.1:8139/health` | 0 | `{"status":"ok",…,"ai_configured":false}`（端口 8137 被上一轮遗留进程占用，本轮改用 8139 避免测到旧代码） |
| 19 | 同上服务 + `curl -X POST /api/practice/paper`（python/10） | 0 | 200，`n=10`、`kinds=['single','judge']`、**无 answer/explanation 泄漏**、`hit=22` |
| 20 | 同上服务 + `curl /api/practice/stats?language=python` / `/api/practice/wrong-book?language=all` | 0 | 200：`{"total":248,"practiced":0,"wrong_total":0,"hit":22}` / `{"items":[],"total":0}` |
| 21 | 同上服务 + `curl -d '{"language":"cobol"}'` / `'{"direction":"backend"}'` / `'{"limit":7}'` | 422 | 三例均 `VALIDATION_ERROR`「请求参数不合法，请检查后重试」、`retryable:false`（错误码闭集零新增） |
| 22 | `git status --porcelain=v1 -uall` | 0 | 48 项，全部为产品代码 + 任务夹 + `.dsh/memory`；`grep -E "node_modules\|dist/\|__pycache__\|\.db$\|\.env$\|\.idea"` → **NO_NOISE** |
| 23 | `git diff --stat -- frontend/src/pages/ExamPage.tsx` | 0 | 空（PRD「笔试页零改动」成立） |

## 4. 上轮缺陷逐条复测（对比表，非开放缺陷）

| 编号 | round-1 级 | 模块 | 上轮问题 | 本轮复测结论 | 复测证据 |
|---|---|---|---|---|---|
| D1 | P1 | 笔试组卷（判断题入卷） | 30 卷 300 题 0 道 judge，判断题结构不可达 | **已关闭** | #7 的 3 条 AC-6 断言 PASS；#17 四十卷覆盖恒含 judge（`{'judge+multiple+single': 40}`） |
| D2 | P2 | 架构（组卷侧闭集接线） | `is_exam_objective_kind`/`EXAM_EXCLUDED_KINDS` 是死开关 | **已关闭** | #8 断言 PASS；#17 降级档 10 卷 0 judge、结构仍达标、覆盖 == `['multiple','single']` |
| D3 | P2 | 版本控制 / 文档边界 | 任务夹外 6 个游离文档会被收官提交带入 | **已关闭** | #8 断言 PASS；#22 `NO_NOISE`，游离素材已迁入 `logs/teamflow/tf-mvxtymng-j6eln4/source-material/` |
| D4 | P3（观察） | 无障碍（进度轨） | 只有 `aria-valuenow`，读屏读成「4」 | **已关闭** | `PracticeProgress.tsx:43` 补 `aria-valuetext="已完成 {done} / {total} 题（{pct}%）"`；#14 新增断言 PASS |

## 5. 用例矩阵（按 AC，通过/失败/阻塞）

| AC | 覆盖方式 | 断言数 | 结果 |
|---|---|---|---|
| AC-1 语言第五维闭集与方向归属 | rules↔schemas↔types.ts 三方逐字、`""`≠`"all"`、方向闭集单一出处 | 6 | PASS |
| AC-2 存量 80 题确定性回填 | 摘 language 跑两遍逐字节相等、第二遍 0 变更、方向约束反例 | 7 | PASS |
| AC-3 扩容与分布闸门 | 每语言新增 20 道 + single≥12/multiple≥3/judge≥3 + 难度/必备度/代码块 | 3 | PASS |
| AC-4 题面质量硬校验 | 答案形状/⊆options/选项 2–6/解析≥10 字/同语言去重/可用==库存/无 blank | 6 | PASS |
| AC-5 DDL 补列与幂等导入 | 真 r6 老库（11 列）→ 补列 → 260 行、老行不覆盖、二次 0 变更、练习与笔试 200 | 5 | PASS |
| AC-6 判断题口径与单一判分 | 选项两态/解析非空/单一 `grade_objective`/**进制可达**/**可降级** | 6 | PASS（上轮 3 FAIL） |
| AC-7 筛选生效 | 语言 100% 命中、多维筛选、0 命中中文建议、limit 10/20/0、越界 422 | 17 | PASS |
| AC-8 逐题作答与即时反馈 | 答对/答错回显、未作答 400 中文、题单 id 唯一、页面层早返回 | 7 | PASS |
| AC-9 unseen/wrong 口径 | unseen 精确排除已作答、wrong=最近一次错误、互斥 | 4 | PASS |
| AC-10 错题本与重练 | 答错即入/跨会话答对即出、字段齐全、倒序、语言过滤、重练新会话 | 7 | PASS |
| AC-11 落库与熟练度 | `run_id=practice:<session>`、`source=practice`、同题一条事件、练熟后 `filtered_count` 上升 | 6 | PASS |
| AC-12 契约与错误形态 | 四端点字段镜像、422/400/404 中文逐字、空结果 200、无 answer 泄漏 | 12 | PASS |
| AC-14 门禁与抽样回归 | pytest/vitest/typecheck/lint/build//health + 笔试/报告/面试/时间线抽样 | 6 | PASS |
| AC-15 零 AI 与时延 | 无 Key 四端点 200、practice 不 import AI、题单首屏与判分 P95 达标 | 4 | PASS |
| AC-16 交付文档 | 分布表/回填表/共用说明/判断题抽检见 §6·§7 与本轮证据 | - | PASS |
| AC-17 390px | 640px 媒体查询覆盖（列宽/筛选行/题卡/代码块内滚）+ 真机人工补测 | 2 | PASS（静态）+ 人工补测 |
| AC-18 进度可见 | 进度行「第 3 / 10 · 正确 2 · 正确率 50%」、`role=progressbar`+`aria-valuetext`、`stats.practiced` 去重、`hit == hit_count` | 5 | PASS |

阻塞项：**0**（`ruff` 未安装属环境限制，非交付缺陷；浏览器不可用属环境限制）。

## 6. 题库分布（全库 260 题，本轮独立复算 `check_qa_r11_data.py`）

| 语言 | 题量 | basic | intermediate | challenge | single | multiple | judge | text | must_know | 含代码块 |
|---|---|---|---|---|---|---|---|---|---|---|
| python | 22 | 13 | 7 | 2 | 14 | 4 | 4 | 0 | 7 | 2 |
| java | 20 | 12 | 6 | 2 | 12 | 4 | 4 | 0 | 7 | 2 |
| go | 20 | 12 | 6 | 2 | 12 | 4 | 4 | 0 | 7 | 2 |
| html | 20 | 12 | 6 | 2 | 12 | 4 | 4 | 0 | 7 | 2 |
| css | 23 | 15 | 6 | 2 | 14 | 5 | 4 | 0 | 7 | 2 |
| js | 27 | 18 | 6 | 3 | 16 | 6 | 4 | 1 | 10 | 2 |
| ts | 22 | 13 | 7 | 2 | 14 | 4 | 4 | 0 | 6 | 2 |
| vue3 | 20 | 12 | 6 | 2 | 12 | 4 | 4 | 0 | 7 | 2 |
| react | 25 | 15 | 7 | 3 | 15 | 5 | 4 | 1 | 8 | 2 |
| 通用/算法 | 61 | 46 | 9 | 6 | 35 | 16 | 0 | 10 | 15 | 0 |

新增 9 语言 × 20 道闸门：每语言 `single 12 / multiple 4 / judge 4`、`basic 12 / intermediate 6 / challenge 2`、`must_know 6–7`、含代码块 2 —— 全绿；练习题池 248（= 260 − 12 道 text）。

## 7. 存量回填结果表（AC-2）

| 命中语言 | 条数 | 留空 | 说明 |
|---|---|---|---|
| css | 3 | 61 | 算法/计算机基础题恒空（方向约束）；后端 HTTP/SQL/Docker 类题不含语言词，属**预期留空** |
| js | 7 | | |
| python | 2 | | |
| react | 5 | | |
| ts | 2 | | |

确定性：同一份「无 language 键」的 80 题连跑两遍 `question_backfill.dumps()` 逐字节相等，第二遍 `hits={}`；反例「前端方向 + Python 关键词」按方向约束留空。本轮 `check_t1_upgrade_e2e.py` 复跑确认存量 80 题库升级后 `filled_first_run=260 / second=0`。

## 8. 架构与接口一致性核查（本轮新增要求）

- **蓝图符合度**：闭集单一出处 `rules.py`（语言/方向/scope+limit/客观题/降级开关）、契约只由 `schemas.py`↔`types.ts` 承载、SQL 只在 `repository.py`、判分只有 `exam.grade_objective`、题面围栏解析只有 `lib/promptCode.ts`（渲染只有 `PromptBody`）、方向归属只在前端**消费**服务端 `direction` 字段（grep 确认前端无语言→方向推导）。`check_qa_r11_interface.py` 逐条核对蓝图 api 的 45 个符号全部存在，且 242 项跨模块调用（成员存在性 + 实参形状）全绿 —— 这条覆盖「文件存在但调用点拼错/签名不匹配 = 到手即死」的风险类。
- **重复实现扫描**：全库 `is_objective_kind` 调用点 6 处（exam/question_bank/practice 各按职责使用，无第三份闭集字面量）；`grep OBJECTIVE_KINDS = {…}` 在测试目录已 0 处；前端无第二个围栏解析器（`NO_SECOND_FENCE_PARSER`）。
- **偏差记录（P3）**：见 §9 的 OBS-1 / OBS-2 / OBS-3。

## 9. 缺陷表（本轮开放项）

**P0/P1/P2 开放缺陷：0 条 —— 未发现缺陷。** 以下 3 条为 P3 观察项（不阻塞验收）：

| 编号 | 严重级(P0/P1/P2/P3) | 功能模块 | 复现步骤 | 期望行为 | 实际行为 | 关联验收项 | 检测命令 | 通过判据 |
|---|---|---|---|---|---|---|---|---|
| OBS-1 | P3（观察） | 架构/前端方向闭集 | `grep -n "label: '前端'" frontend/src/lib/practice.ts` | 方向 chip 从单一常量/类型派生，与 `rules.DIRECTIONS` 增补自动同步 | `directionChips()` 内硬编码四个方向字面量；`types.ts` 有镜像门禁（`test_r11_contract.py:215`）但**该函数**无门禁 → `rules.DIRECTIONS` 增补时新方向 chip 会静默缺项（typecheck 不红） | AC-7 | `cd frontend && grep -n "label: '\(前端\|后端\)'" src/lib/practice.ts` | 修复后该 grep 0 命中（chip 由导出的方向常量派生）；现状恒定 2 命中 |
| OBS-2 | P3（观察） | 架构（蓝图文件集） | `ls frontend/src/components/exam/PromptBody.tsx` | 蓝图把围栏渲染写在 `ExamQuestionCard` 内 | 实际抽出 `PromptBody.tsx`（+`splitInlineCode`），比蓝图多 1 个模块 —— 换来「题卡与错题本共用唯一渲染点」，方向正确但蓝图与实现不一致 | AC-16 | `cd backend && AI_API_KEY= python -X utf8 ../logs/teamflow/tf-mvxtymng-j6eln4/scripts/check_qa_r11_interface.py` | 该命令 exit 0（模块解析与导出完好）；建议把 `PromptBody` 回写进 TECHNICAL 蓝图文件清单 |
| OBS-3 | P3（观察） | 架构/文档口径 | `grep -n "每种可用客观题型各 ≥1" backend/app/services/exam_selector.py` | 模块 docstring 把「每种可用客观题型各 ≥1」列为 `build_paper()` 的结构闸门条件（不满足返回 `None`） | 代码只做取题排序（`_prefer_kind_diversity`），`_fit_structure()` 未校验 kind 覆盖 → 语义是**策略**而非**约束**；实数据下 40 卷恒成立，无用户影响 | AC-6 | `cd backend && AI_API_KEY= python -X utf8 ../logs/teamflow/tf-mvxtymng-j6eln4/scripts/check_qa_r11_exam_kind_cov.py` | 该命令 exit 0（8/8，40 卷覆盖恒等）；建议 docstring 把该条措辞改为「取题顺序保证（best effort）」或补一条真实校验 |

## 10. 人工补测清单（环境限制，非交付缺陷）

| # | 项 | 方法 | 工具 |
|---|---|---|---|
| 1 | 390×844 真机：`scrollWidth<=clientWidth`、筛选 3 行堆叠、按钮 40 高可点 | 打开 `/practice` → 切 device 390 → DevTools Console 量 `document.documentElement.scrollWidth` | Chrome DevTools / Playwright |
| 2 | 点击级交互：解析折叠焦点、错题本行展开、提交失败保留已选 | 手点 3 条主路径 | Chrome |
| 3 | 读屏与键盘：radio/checkbox 切换、进度轨朗读（`aria-valuetext`）、SegTabs | NVDA / VoiceOver | 读屏工具 |
| 4 | 判断题真机呈现：出笔试卷 → 找 judge 题 → 两个 radio + 提交后判分非空 | 出卷 → 作答 → 看结果页 | Chrome |
| 5 | 动画/过渡观感与 `prefers-reduced-motion` 生效 | DevTools 开启 reduce motion 看进度轨与卡片 | Chrome |

## 11. 结论与建议

- **可验收**：练习域主路径（按语言筛选 → 逐题作答 → 即时反馈+默认展开解析 → 错题本重练 → 完成态）在真实 HTTP 与真实渲染两侧均有实跑证据；题库 260 题、存量库自动升级、四端点契约与错误矩阵、零 AI 依赖、时延指标全部达标；上轮 4 条缺陷逐条关闭。
- 回归契约（下轮复跑即可）：§3 的 #1–#17 全部 exit 0；尤其 #7/#8 是上轮缺陷的 Check command，#16/#17 是本轮新增的接口与笔试覆盖探针。
- 建议（非阻塞）：① 把 `directionChips()` 改成从单一常量派生并加门禁（OBS-1）；② 蓝图文件清单补 `PromptBody.tsx`（OBS-2）；③ `exam_selector` 的 docstring 把「题型覆盖」措辞从「结构闸门」改成「取题顺序保证」（OBS-3）。
- 环境限制：浏览器不可用、`ruff` 未安装 → 对应项已列 §10 与 §3 说明，**不作为交付缺陷**。
