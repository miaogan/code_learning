# r12 题库素材合并 · 验收报告

**交付面**：分支 `feat/dev-skill-coach`（未提交）。5 处修改（`repository.py` / `seed/questions.json` / 2 个测试文件 / `memory.md`）+ 6 处新增（离线工具 `question_merge.py`、`test_r12_question_merge.py`、staging 4 份素材、`NOTICE-fe-interview.md`）+ 本任务夹文档。**基线**：`docs/teamflow/20261101-r11-practice-question-bank`；**契约**：本夹 `TECH-CHANGE.md`（技术驱动返工，明确不改写 r11 任何 AC）。需求目标：把 `docs/question-bank-staging/` 519 道素材去重、归一化、标来源后并入题库，且练习/笔试/熟练度零回归。

## 1 验收方法（不复述 QA 结论，只认复跑与复算）

1. 逐项复跑 r12 契约项与门禁：`question_merge --check`、数据 28 项检查、练习四端点与笔试卷真实 HTTP、后端全量 pytest、前端 typecheck/lint。
2. 独立探针补 QA 盲区：`logs/teamflow/tf-mvy1bqfh-vtjllw/scripts/check_accept_r12_wrongbook.py`（错题本「答错入册→字段齐全→答对移出」确定性顺序，两次连跑全绿）。
3. 反证核查：D-1 的存量冻结门禁是否真能变红（读断言 + QA 探针实测）、QA 报告的「17/17」是否可复现（发现 1 条用例本身红绿不定，见 §4-A1）、内容抽检 4 道逐题人工判正确性。

## 2 验收项核对

### 2.1 r12 契约项（TECH-CHANGE §1–§5，全部实测）

| 验收项 | 判定 | 证据（本轮复跑） |
|---|---|---|
| 519 道全量并入、总量 779 | ✅ | 实测 779 条；kind `single 551 / judge 156 / multiple 60 / text 12`；source `seed 260 / tiji 20 / local100 100 / iq380 379 / fe-interview 20` |
| 五维分布与蓝图一致 | ✅ | language `''294/python 86/java 84/go 74/js 46/react 45/vue3 42/css 40/html 36/ts 32`；direction `后端 423/前端 267/算法 56/计基 33`；difficulty `283/359/137`（challenge 17.587% ≤20%） |
| 归一化正确（judge 重建 / 方向推断 / 9 条冲突纠正） | ✅ | 数据 28 项检查：结构合规（answer⊆options、选项 2–6、key 唯一、解析≥10 字、无 blank）0 异常；方向↔语言零冲突；通用方向 language 恒空；9 条纠正清单在合并报表 §5 |
| 去重（字面 0 / 近重复 0） | ✅ | 报表 §1「读入 519 → 越界 0 / 字面重复 0 / 近重复 0」；`--check` 重算与已提交 seed 逐字节一致（说明取舍规则可复现，不是手改数据） |
| 幂等（重新生成 0 差异） | ✅ | `python -X utf8 -m app.services.question_merge --check` → exit 0「题库 seed 与素材重算逐字节一致：可用 779 道」 |
| 存量 260 行不可变（含可失败门禁） | ✅ | `check_qa_r12_data.py`：存量 260 行 `dumps()` 复现 192393 字节、与 `git show HEAD` 逐行相等；`test_r12_question_merge.py:38,43` 钉死 `R11_SEED_BYTES/R11_SEED_SHA256`，:381–384 断言失败即红（QA 探针实测等长篡改后变红） |
| 种子导入幂等（存量库 +519、再启 0 新增） | ✅ | pytest 全量绿（含 r11 `ensure_seeded` 用例）；`source` 列 schema 未改（`git diff` 无 `db.py`/`schemas.py`） |
| 回滚（只删本批、幂等、未初始化库中文提示） | ✅ | QA 实跑 779→260→0；`RollbackUnavailable` 单测在 `test_r12_question_merge.py:527`；`repository.delete_questions_by_source` 按 `source` 删，存量 `'seed'` 不受伤 |
| 许可合规（MIT 留痕） | ✅ | `NOTICE-fe-interview.md`：MIT 全文（`Permission is hereby granted…`）+ 上游 `https://github.com/haizlin/fe-interview` + 改写说明；01/02/03 为自建/本地生成，无外部许可义务 |
| `source` 不进 HTTP 契约 | ✅ | `schemas.py`/`types.ts`/`exam.py`/前端零改动；纸面响应无 `answer`/`source` 泄漏（运行时实测）；静态门禁在 `test_engineering_gates.py` |
| 零业务代码改动（只改数据 + 离线工具） | ✅ | `git diff --stat`：5 文件 9301 insertions / 0 deletions；运行时链路唯一改动是 `repository.py` 新增 `delete_questions_by_source`（仅离线工具调用，0 删除既有行） |
| 练习可用（779 池） | ✅ | `/health` 200（`ai_configured=false`）；9 语言纸 200 且 100% 命中筛选；`limit=0` 767 道（779−12 text）无重复；python 纸含 judge；judge 同题 A/B 判分互斥并回显正确答案+解析；非法 `language` 仍 422 |
| 笔试可用（779 池） | ✅ | 笔试卷 E2E 4/4：779 库、10 卷均 ≥10 题、无答案泄漏、含 judge 12 道、提交判分 `correct 5/8`（62.5） |
| 性能/零 AI | ✅ | 无 Key 下全链路 200；全量纸 29ms / 388KB，单题判分 19–25ms（AC-15 P95≤50ms 达标） |
| 回归门禁地板 | ✅ | 后端 `pytest` 全量 **512 collected / exit 0**（1 skip = `AI_LIVE` 手动冒烟）；前端 `typecheck` exit 0、`lint` 0 error / 28 warning（≤28）；`vitest 133`、`build` 由 QA 实测（前端零 diff，沿用） |

### 2.2 r11 基线 AC 回归（r12 只应「题库变大」，不应改行为）

| AC | r12 影响与判定 | 证据 |
|---|---|---|
| AC-1 语言闭集/方向单一出处 | ✅ 未改 | `rules.py` 零 diff；数据检查 language 全在闭集、方向↔语言零冲突 |
| AC-2 存量 80 题回填 | ✅ 未改 | 存量 260 行冻结；`question_backfill --check` dev 实跑 exit 0 |
| AC-3「每语言恰好 20 道 / 全库 260」 | ⚠️ **被 r12 用户决策取代** | TECH-CHANGE §7-5：519 全量并入与「每语言 20」二选一，用户选并入；不视为回归（题库总量 779） |
| AC-4 全库结构校验 | ✅ 更严 | 28 项数据检查全 PASS（含同语言题干去重 0、id 唯一、前缀不撞 legacy/r11/面试域） |
| AC-5 DDL 补列 + 重复导入 0 新增 | ✅ 未改 | `db.py` 零 diff；`source` 列早已存在；二次导入 0 新增（pytest） |
| AC-6 judge 入客观闭集 / 单一判分函数 | ✅ 未改 | `exam.py` 零 diff；156 道 judge 可达、A/B 互斥判分；无填空残留 |
| AC-7 筛选 + scope + limit（10/20/全部） | ✅ 未改 | 四端点实测；全量 767；0 命中给中文建议（r11 用例绿） |
| AC-8 作答交互 / 进度 / 末题态 | ✅ 未改 | 前端零 diff；vitest 133（QA） |
| AC-9 unseen / wrong 口径 | ✅ 未改 | 练习写同一 `question_attempts`；pytest 口径用例全绿 |
| AC-10 错题本（字段/倒序/语言过滤/答对移出） | ✅ 未改 | 独立探针两次全绿：入册、`prompt/language/direction/difficulty/last_wrong_at/wrong_count` 齐全、答对后移出 |
| AC-11 熟练度/笔试卷过滤/全熟练仍 200 | ✅ 未改 | 笔试卷 E2E 4/4；`test_exam_filter` 779 下 `per_paper` 推导用例绿 |
| AC-12 契约逐字对齐 / 错误码闭集 | ✅ 未改 | `schemas.py`↔`types.ts` 零 diff；错误矩阵沿用 |
| AC-13 五种中文态 | ✅ 未改 | 前端零 diff；vitest（QA） |
| AC-14 门禁地板 | ✅ | pytest 512 ≥368；vitest 133 ≥124；typecheck 0；lint 0err/28warn；build OK；`/health` 200 |
| AC-15 练习零 AI + 延迟预算 | ✅ | 见 §2.1 性能行 |
| AC-16 文档（设计/技术/QA 报告） | ✅ 适配 | 本轮无 UI 改动 → 无需 DESIGN；契约 `TECH-CHANGE.md` + 工具产出 `QUESTION-BANK-MERGE-REPORT.md` + `QA-REPORT.md` 齐备 |
| AC-17 390px / AC-18 进度 / AC-19 薄弱地图 / AC-20 竞争力 | ✅ 未触碰 | 前端零 diff（`git status` 无 `frontend/`），属 r11 已验收基线；390px 真实视口仍列人工补测（§5） |

## 3 架构一致性核查（M3 门禁）

- **按蓝图落地**：离线工具 `question_merge.py`（check/write/rollback）独立成模块；数据只走 seed JSON + 既有 `ensure_seeded()` 导入；库层唯一新增 `delete_questions_by_source`（唯一 SQL 出口，占位符拼装、SQL 骨架为常量）。QA 的接口/蓝图静态检查 52/52（本轮复跑一致）。
- **单一出处（无重复实现）**：方向知识只由 `rules.direction_of_language()` 派生，工具内零方向表；序列化只有 `dumps()` 一处（未退化为 `json.dump(indent=2)`）；判分只有 `exam.grade_objective()`；`source` 只在种子与库列、不进契约。
- **未破坏既有结构**：运行时零业务代码改动；`question_attempts` 表、熟练度公式与阈值、练习池过滤（排除 text）全部沿用 r11。
- **蓝图 vs 实现唯一偏差**：`TECH-CHANGE.md:36` 仍写 id 前缀 `iq-NNN`，实现取 `iq380-NNN`（避开面试 `iq-` 命名空间，代码更安全）。属**文档未回写**（P3），不影响契约与运行。

## 4 缺陷与观察（本轮无 P0/P1/P2）

| 编号 | 级别 | 说明 | 处置 |
|---|---|---|---|
| D-2 | P3 | 新增题答案分布偏 A（judge A 87/120=72.5%；single A 204/B 137/C 49/D 5），且 45 道题干含「参考答案要点」而学员看不到该参考 | 内容质量，结构门禁不覆盖；建议另立「题库内容质量」需求（重排正确项 + 改自洽题干），不阻断本次合并 |
| D-4 | P3 | `TECH-CHANGE.md:36` 写 `iq-NNN`，实现 `iq380-` | 文档回写（1 行），不阻断 |
| D-6 | P3 | `docs/question-bank-staging/` 仅 fe-interview 有 NOTICE，01/02/03 三来源无 PROVENANCE 留痕 | 建议补 `PROVENANCE.md`（自建/AI 生成 + 方式 + 日期），写入在验收写边界外，留后续 |
| A1 | P3（QA 脚本） | `check_qa_r12_runtime.py:89-93`「答错进错题本」用同一题 A 答错、B 答对两个 session，若抽到的 judge 正确答案是 B 则最后一条是「对」→ 错题本为空，用例红绿随机（本轮复跑即红） | 非产品缺陷；验收已用独立探针复验同口径通过，建议 QA 脚本改为「先错后对两条路径显式构造」 |
| D-5 | P3 已关闭 | `memory.md` r12 收口①仍写「待确认 LICENSE」 | **验收本轮已改为「已完成（MIT 已核实、NOTICE 已回填）」** |

## 5 环境限制与人工补测

- 沙箱不能起 Chromium：`/practice` 390px 真实视口/键盘走查未做（前端零 diff），仍需真机确认一次（沿用 r11 清单）。
- 本机 `ruff` 未安装（`No module named ruff`），非代码失败；由开发机补跑。
- 45 道「参考答案要点」题干的可读性定稿与答案分布均衡决策，属产品内容评审（§4 D-2）。

## 6 验收结论

需求目标全部达成：519 道素材全量并入（779 道）、分布与蓝图逐项一致、去重/归一化可复现（`--check` 逐字节幂等）、存量 260 行有真会红的 sha256 冻结门禁、许可留痕合规、练习与笔试在 779 池上实跑全通、后端 512 用例与前端门禁全绿。架构按蓝图落地、无重复实现、无结构性改动。遗留 3 条 P3 与 1 条 QA 脚本问题均为文档/内容质量类，不阻断交付；`memory.md` 的 D-5 已当场关闭。上轮唯一阻断项（D-1 存量不可变无门禁）已验证关闭。

验收结论：✅ 通过
