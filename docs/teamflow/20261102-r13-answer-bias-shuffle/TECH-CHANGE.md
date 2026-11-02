# r13 技术变更单：题库答案位置偏置修复（选项打乱 + 判断题极性改写）

**基线依赖**：`docs/teamflow/20261102-r12-question-bank-merge`（779 道 seed 的现状与 D-2 观察）
**性质**：tech-driven rework（纯数据处理）。**不新增/不改任何功能性 AC**；本轮只关闭 r12 QA-REPORT D-2 的数据质量观察项，历史任务夹 PRD 一律不改写。

## 1. 背景与目标（一句话）

`backend/app/seed/questions.json` 的选项排列存在可利用的位置偏置（单选 A 58.6%、判断「正确」68.6%），本轮用**确定性离线变换**把答案位置分布拉平，同时不改业务代码、UI 与判分口径。

## 2. 影响面

| 类型 | 文件 | 说明 |
|---|---|---|
| 新增 | `backend/app/services/question_shuffle.py` | 变换库（`apply(rows)->rows`）+ 校验 + 报表 + CLI `--check/--write` |
| 改动 | `backend/app/services/question_merge.py` | `build_seed()` 末尾接 `question_shuffle.apply()`；`REPORT_PATH` 改指 r13 夹 |
| 重算 | `backend/app/seed/questions.json` | 779 道重新序列化（行序/行数不变） |
| 新增 | `backend/tests/test_r13_question_shuffle.py` | 常驻门禁（分布/极性/长度比/key 闭集/幂等/解析引用一致性） |
| 改动 | `backend/tests/test_r12_question_merge.py` | `R11_SEED_SHA256` / `R11_SEED_BYTES` 迁移为 r13 基线 |
| 新增 | `docs/teamflow/20261102-r13-answer-bias-shuffle/SHUFFLE-REPORT.md` | 工具生成的报表（本夹内） |
| 同步 | `docs/teamflow/memory.md` | 一条约定 + 一条待办（同主题行替换） |

**零改动（硬边界）**：`question_bank.py` / `question_merge` 之外的 runtime、`exam.py`（`grade_objective` 单一判分）、`exam_selector.py`、`practice.py`、`proficiency.py`、`repository.py`、`db.py`、`schemas.py`、`frontend/**`、`docs/question-bank-staging/**`。

## 3. 技术方案（关键点）

### 3.1 位置均衡：确定性轮转分配（不是纯哈希碰运气）

对每道 `single`：按 `sha256(id|option_text)` 得选项的内容序 → 计算「答案应落的位置」＝**按 id 哈希定序后轮转，把答案填到当前累计计数最低的位置** → 按位置重编 key `A..D`，干扰项按内容序占其余槽位，`answer` 随之重映射。
- 纯哈希实测：A 22.7 / B 24.9 / C 25.8 / D 26.7 → 尚可；但叠加 3.2 的跳过后 D 掉到 19.6%（擦线）。
- 轮转分配实测：**A 138 / B 138 / C 138 / D 137（25.0 / 25.0 / 25.0 / 24.9）**，跳过题的不均衡被其余题补偿。
- 幂等：分配只依赖「内容身份 + 固定 id 序」，重复运行得到同一排列；`multiple` 同样重排并重映射整组答案。

### 3.2 解析里的字母引用必须同步（本轮最大技术风险）

解析按 key 引用选项（实测 461 处，覆盖 155 题，形式：`A 项` / `选项 A` / `选项A` / `A项`，另有 `A 正确` / `B、C` / `正确项为 A、B、D` 等）。key 重编后**必须同映射重写**，否则解析指向错项。
- 自动重映射集：显式四类形式 + 「字母 + 判定词（正确/错误/误/是/为/不是/干扰项）」+ 「由 、和与或 连接的纯字母序列」。
- 护栏：字母被字母数字/`++`/`#`/`/`包裹或后跟「语言/编译器/标准」→ 判为**非引用**（实测存在 `C 的构建流程`、`Java/C++`、`ACID`、`MAC`、`DAG` 等真误伤样本）。
- 校验：变换后断言「`X 项错误` ⇔ X ∉ answer」「`正确项为 …` 集合 == answer」；`X∈options` 恒成立。基线实测 449/450 通过，唯一例外 `iq380-164` 入白名单并注明。
- **兜底**：仍无法可靠判角的题（实测 **106 道**）**不打乱**（原文与 key 保持自洽），计入报表 `skipped_no_ref_parse`，不猜。

### 3.3 判断题：不改选项，改陈述极性

选项恒为 `A. 正确 / B. 错误`（156 道实测均为该形态），打乱会破坏语义 → **不打乱**，改为把部分陈述改写成「错误陈述」。
- 现存量 A 107 / B 49，**只需翻转 29 条**即达 A 78 / B 78（50 / 50）。
- 实现：`_JUDGE_FLIPS` 显式表（29 条，字段 `id` / `statement` / `explanation`），**绝对映射**（不是相对取反）→ 天然幂等，重复运行不会二次取反。
- 新陈述只取反命题、不改事实；解析同步改写为该否定陈述的说明。无法安全取反者保留原样并计入 `judge_kept_as_is`。

### 3.4 答案长度偏长：只出清单，不自动改写

统计「正确项平均长度 / 干扰项平均长度」比值：实测 **>3× 40 条**（最长 7.61× = `iq380-047`）、2–3× 106 条、全量中位 1.46（n=611）。产出按比值倒序的清单（>3× 给裁剪建议、2–3× 入抽检清单），**一律不改写语义**——改写风险高于收益，交人工评审。

### 3.5 工具化与单写入者

`question_shuffle.py`：`--check`（重算到字节比对，只读）/ `--write`（**委托** `question_merge.write()`，不自己写盘）/ `--report`（打印清单）。
`seed` 的唯一写入者仍是 `question_merge`，`dumps()` 仍是唯一格式知识；因此 `question_merge --check` 在打乱后仍须 0 差异（当前基线实测 779 道 / 0 差异）。

### 3.6 冻结基线迁移（明确动作）

`test_r12_question_merge.py` 的 `R11_SEED_SHA256`/`R11_SEED_BYTES` 断言「前 260 行与 r11 逐字节一致」——本轮打乱必然改变存量 260 行 → 常量**迁移到 r13 基线**（`R13_SEED_SHA256`/`R13_SEED_BYTES`），保留「等长改写也变红」的语义，并在报表写明「冻结基线已迁移到 r13」。

## 4. 行为兼容性（用户可见变化，明确声明）

- **可见**：练习/笔试里同一题的选项顺序与字母标签会变（内容不变）；**29 道判断题题面改为否定式陈述**，解析随之改写；解析内字母引用随新 key 同步。
- **不可见**：判分（`grade_objective` 集合相等）、组卷阶梯、熟练度公式与阈值、HTTP 契约、错误码、UI 组件零改动。
- **存量库**：`import_seed` 是 `ON CONFLICT DO NOTHING`（只增不覆盖）→ 已部署 `app.db` 的选项顺序**不会被刷新**，其库内行仍自洽（判分与历史 `question_attempts` 的 key 语义均无错位）。**因此本轮修复对「新建库/重导库」生效；存量库偏置保留**，见 §7 待办。

## 5. 回归与验证计划（地板只增不减）

| 命令 | 期望 |
|---|---|
| `cd backend && AI_API_KEY= python -X utf8 -m pytest -q -p no:cacheprovider` | 基线实测 **512 collected 全绿**；新增门禁后 ≥522 |
| `cd backend && python -X utf8 -m app.services.question_merge --check` | 0 差异（当前基线 779 道成立） |
| `cd backend && python -X utf8 -m app.services.question_shuffle --check` | 0 差异（打乱已落盘） |
| `cd backend && python -X utf8 -m app.services.question_shuffle --write` 后重跑 `--check` 与 `merge --check` | 两次运行**逐字节相同**（确定性证据） |
| `cd frontend && npm run typecheck && npm run lint && npx vitest run && npm run build` | typecheck 0 / lint 0 error ≤28 warn / vitest **133** 实测全绿 / build 通过 |
| `cd backend && python -X utf8 -m app.services.question_bank`（或 TestClient 冒烟）| `/health` 200；练习与笔试判分抽样不回归 |

功能回归：练习单题判分（单选/多选/判断）抽样、笔试出卷结构闸门、熟练度账本、`filtered_count` 不变；四类 UI 态无语义变化故只做冒烟。

## 6. 门禁常量与依据（写进 `test_r13_question_shuffle.py`）

| 常量 | 值 | 依据 |
|---|---|---|
| `SINGLE_POSITION_RATIO` | `(0.20, 0.32)` | 需求口径「20%–30%、任一位置 ≤35%」；上界抬到 32% 容纳 551 样本抽样波动（p=0.25 时 σ≈1.85%，约 3σ） |
| `JUDGE_TRUE_RATIO` | `(0.40, 0.60)` | 需求 A-4；156 样本 p=0.5 时 σ≈4%，取 ±10%≈2.5σ |
| `MAX_LONG_ANSWER_COUNT` | `45` | r13 基线 40 条（>3×）+ 5 条缓冲；只防「新增题把长正确项推高」，不要求自动改写 |
| `LENGTH_RATIO_SPOTCHECK` | `2.0` | 2–3× 实测 106 条为抽检面 |
| `JUDGE_FLIP_COUNT` | `29` | 由 107/49 → 78/78 的最小翻转数，表内条数须与之相等 |

另需断言：key 恒为 `A..D` 且顺序即位置、判断题选项恒 `("正确","错误")` 两项、`answer ⊆ options` 且非空、解析非空 ≥10 字、表内每条 flip 后 `answer == ["B"]`。**变红证据**：临时把全部单选答案改成 A、把 flip 表清空 → 三个门禁必须各红一条，纳入 QA 报告。

## 7. 风险与回滚

| 风险 | 处置 |
|---|---|
| 解析字母误映射（`C 语言`、`C++`、`ACID`…） | 语言名护栏 + 106 题不打乱 + §3.2 双校验；失败即红 |
| 29 条判断题事实被改写 | 表内逐条人工核对；报表给「原句→新句」对照表供 QA/验收逐条过 |
| 分布漂移（后续新增题） | 每次 `--write` 重算 + 常驻门禁兜底 |
| 存量库偏置仍在 | 记为待办（需 `repository` 覆写函数 + 历史 attempts 评估，超出「不动业务代码」，另立需求） |
| 字节契约被破坏 | `dumps()` 单一序列化出口；`merge --check` 0 差异是唯一幂等判据 |

**回滚**：`git checkout backend/app/seed/questions.json` + 删除 `question_shuffle.py` + 还原 `question_merge`（3 行）与 r12 常量即可；无需重建数据库（库从不被覆写）。顺序须**先撤代码再 `merge --write`**，否则会用打乱后的流水线重新生成。

## 8. 假设与待澄清（用户可推翻的取舍）

1. **key 随位置重编**（而非「key 与内容绑定、只换数组顺序」）：后者下「全选 A」仍可拿 58.6%，等于没修——若产品坚持字母与内容绑定，本需求目标不可达。
2. **工具归属**：`question_shuffle` 做变换库、写盘委托 `question_merge`（保「单写入者 + 单一序列化」）；若要求它自己写盘，则 `question_merge --check` 需前置调用它，序列化出口变两处。
3. **判断题只翻 29 条**（最小必要量，达成 50/50）：若产品要「独立均衡、全部可翻」，扩到 78 条，人工成本约 2.7×。
4. **106 道解析无法判角的题保持原序**：若产品要求「一道不落全部打乱」，需逐题人工改写解析，成本另计（本轮选安全优先）。
5. **答案长度只出建议清单、不自动改写**：需求 B 已明确；若要求自动裁剪，属另开需求（语义风险高）。
6. **存量 `app.db` 不重导**：见 §4/§7；如需线上生效必须改 `repository.py`。
7. **报表路径**：`REPORT_PATH` 改指 r13 夹，r12 夹只读，不在历史夹内产生新内容。

## 9. 交付物与验收要点

- 代码：`question_shuffle.py`（+ 内置 `_JUDGE_FLIPS` 29 条）、`question_merge.py` 接线、重算后的 `questions.json`、`test_r13_question_shuffle.py`。
- 文档：本夹 `SHUFFLE-REPORT.md`（**打乱前后位置分布对比表 / 判断题极性改写条数与对照表 / 长度比分布与剩余 >3× 清单（40 条 id）/ 跳过题清单 106 条 / 幂等与变红证据**）。
- 验收看点：分布落区间、解析引用无错位（抽检显式形式题）、29 条极性对照表事实未变、`merge --check` 0 差异、门禁可变红、地板未降。
