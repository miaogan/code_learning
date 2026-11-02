# r14 技术变更单：关闭 r13 验收 4 条 P3 遗留（存量刷新 / 长答案压缩 / 判断双向 / 语言分桶）

**基线依赖**：`docs/teamflow/20261102-r13-answer-bias-shuffle`（ACCEPTANCE §4 列出的 4 条 P3）
**性质**：tech-driven closure（纯数据处理 + 启动接线）。**不新增/不改任何功能性 AC**；本轮只关闭 r13 验收的 P3 已知限制，历史任务夹文档一律不改写。

## 1 背景与目标（一句话）

r13 验收判「✅ 通过」但留 4 条 P3（均不阻断）；本轮逐条关闭：存量库启动覆写（P3-1）、40 道长答案自动压缩（P3-2）、判断题双向翻转（P3-3）、单选/判断按 `language` 分桶均衡（P3-4）。

## 2 影响面

| 类型 | 文件 | 说明 |
|---|---|---|
| 改动 | `backend/app/repository.py` | 新增 `_QUESTION_REFRESH` / `_normalized_question()` / `refresh_questions()` / `refresh_question()`（P3-1） |
| 改动 | `backend/app/services/question_bank.py` | 新增 `refresh_from_seed()`；`ensure_seeded()` 改为 `import_seed()` + `refresh_from_seed()` + `count_questions()`（P3-1） |
| 改动 | `backend/app/services/question_shuffle.py` | `LENGTH_REWRITES` 40 条 + `_apply_length_rewrites()`（P3-2）；`JUDGE_FLIPS` 38 条双向（P3-3）；`_language_of()` / `_answer_counts_by_language()` 分桶与按语言报表（P3-4）；`REPORT_PATH` 指本夹 |
| 改动 | `backend/app/services/question_merge.py` | 报表标题 r12 → r14；`write()` 写盘后双次 build 并逐字节守幂等 |
| 重算 | `backend/app/seed/questions.json` | 779 道重新序列化（726558 字节，行序/行数不变） |
| 改动 | `backend/tests/test_question_bank.py` | 新增 `test_ensure_seeded_refreshes_stale_rows_on_startup`、`test_refresh_questions_ignores_unknown_and_empty_rows` |
| 改动 | `backend/tests/test_r13_question_shuffle.py` | `MAX_LONG_ANSWER_COUNT` 3 → 0；新增 `test_length_rewrites_are_current`；新增两条按语言门禁；`JUDGE_FLIP_COUNT` 29 → 38、断言 `directions == {"A","B"}` |
| 改动 | `backend/tests/test_r12_question_merge.py` | 冻结基线 `R13_SEED_BYTES=191135` / `R13_SEED_SHA256=017e6777…`（P3-2 压缩 23 道存量题所致） |
| 新增 | `docs/teamflow/20261102-r14-p3-closure/SHUFFLE-REPORT.md` | 工具生成：前后分布 + 按语言表 + 38 条对照 + 40 条压缩表 |
| 新增 | `docs/teamflow/20261102-r14-p3-closure/QUESTION-BANK-MERGE-REPORT.md` | 工具生成（标题已刷 r14） |
| 同步 | `docs/teamflow/memory.md` | r13 收口待办 4 条关闭 + r14 约定补记 |

**零改动（硬边界）**：`exam.py`（`grade_objective` 单一判分）、`exam_selector.py`、`practice.py`、`proficiency.py`、`db.py`、`schemas.py`、`frontend/**`、`docs/question-bank-staging/**`；HTTP 契约零改动。

## 3 技术方案（关键点）

### 3.1 P3-1：启动覆写既有行（存量库不再保留旧偏置）

`insert_question()` 的 `ON CONFLICT DO NOTHING` 只增不覆盖（r6 AC-1），已部署 `app.db` 永远刷不到 r13 的选项顺序与判断题极性。新增分工：
- `repository.refresh_questions(rows)`：一次 `SELECT` 建 `id → 行` 映射，逐行用 `_normalized_question()` 规范化比对（JSON 列按序列化文本比，避 list/dict 顺序噪声）；**只 UPDATE 差异行、绝不新增**（seed 有而库里没有的 id 直接跳过，交给 `import_seed()`）。
- 幂等真值：库内已与种子逐字段一致时返回 `0`，且不写 `updated_at`。
- `ensure_seeded()` = 导入新增 → 覆写差异 → 计数；每次启动执行。
- 历史 `question_attempts` 只存 `correct`（0/1），不存作答 key → 覆写题目行不会让历史判分错位。

### 3.2 P3-2：40 道长答案自动压缩（只动正确项文本）

- `LENGTH_REWRITES`：40 条 `{"<id>": {"before", "after"}}` **绝对映射**（按 id 排序），只替换 `answer` 指向选项的 `text`；**不动选项顺序、key 与解析**（语义与判分集合不变）。
- `_apply_length_rewrites()` 三态记账：`applied`（命中 before）/ `already`（已是 after，含从 seed 读回的存量改写态）/ `stale`（两者都不是，必须为 0，非 0 即门禁红）。
- 门禁 `MAX_LONG_ANSWER_COUNT = 0`：>3× 清单必须为空；实测 611 道样本中位 1.46，2–3× 抽检 129 道，>3× 0 道。
- 本次台账：表内 40 条，改写 17 条、已是改写态 23 条、stale 0 条。

### 3.3 P3-3：判断题双向翻转（29 → 38 条）

- `JUDGE_FLIPS` 每条新增可选 `answer`（缺省 `"B"`＝改写成错误陈述；`"A"`＝把伪命题改写成真命题）。
- 38 条 = 原 29 条 A→B + 新增 10 条 − 删除 1 条（`iq380-036`）：新增中 `iq380-215`/`iq380-230` 为 A→B，`ts-q17`、`react-q17`、`js-q18`、`js-q20`、`html-q17`、`html-q20`、`vue3-q17`、`vue3-q20` 为 B→A。
- 仍是**绝对映射**（不是相对取反）→ 重复运行不会二次翻转。
- 全局落点 A85/B71 = 54.5/45.5%；按语言全部落 40%–60%（通用 58.6、go 58.8、python 55.0、java 52.6、css/js 42.9、html/react/ts/vue3 50.0）。

### 3.4 P3-4：单选轮转按 `language` 分桶

- `_language_of(row)` 取闭集 `language`（空串＝通用桶）；轮转的「当前位置计数」按桶独立累加，而不是全局一份计数。
- 效果：每种语言的子集各自均衡（实测各桶 A 25.0–29.5%，D 21.4–25.0%）；全局 A146/B139/C135/D131 = 26.5/25.2/24.5/23.8%。
- `metrics` 增加 `single.by_language` / `judge.by_language`（各含 `before` / `after`），报表 §2/§3 追加按语言表；门禁按语言分组复算并逐桶比对。
- 小样本保护：`MIN_SINGLE_SAMPLE_PER_LANGUAGE = 20`、`MIN_JUDGE_SAMPLE_PER_LANGUAGE = 6`，低于样本量的桶只记录不判定（避免 4 道题的桶抖动误红）。

### 3.5 不变量（沿用 r13，未被破坏）

- 写盘唯一者仍是 `question_merge`（`question_shuffle --write` 委托它）；`dumps()` 仍是唯一序列化出口。
- `question_merge --check` 逐字节 0 差异是唯一幂等判据。
- 离线工具运行时不得 import（`test_engineering_gates.py` 白名单 + 反向断言）。

## 4 行为兼容性（用户可见变化，明确声明）

- **可见**：存量 `app.db` 首次启动会把库内同 id 行的选项顺序 / 判断题极性 / 正确项措辞刷成当前 seed（`updated_at` 变化；不新增、不删除）；第二次启动恒 0 改写。
- **可见**：23 道存量题正确项措辞被压缩（语义与判分 key 不变）；38 道判断题题面为改写后陈述。
- **不可见**：判分函数、组卷阶梯、熟练度公式与阈值、HTTP 契约、错误码、UI 组件零改动；历史 `question_attempts` 判分不受影响。

## 5 回归与验证计划（地板只增不减）

| 命令 | 期望 |
|---|---|
| `cd backend && python -X utf8 -m pytest -q -p no:cacheprovider` | ≥527 collected 全绿（r14 新增用例只增不减） |
| `cd backend && python -X utf8 -m pytest tests/test_r13_question_shuffle.py tests/test_r12_question_merge.py tests/test_question_bank.py -q -p no:cacheprovider` | 定向三文件 **69 passed** |
| `cd backend && python -X utf8 -m app.services.question_merge --check` | 0 差异 |
| `cd backend && python -X utf8 -m app.services.question_shuffle --check` | 0 差异 |
| `cd backend && python -X utf8 -m app.services.question_merge --write` 后重跑双 `--check` | 逐字节不变（726558 B） |
| `cd frontend && npm run typecheck && npm run lint && npx vitest run && npm run build` | typecheck 0 / lint 0 error 28 warn（上限）/ vitest 133 全绿 / build OK（本轮前端零改动） |
| `cd backend && python -X utf8 -m ruff check app tests` | 本机无 `ruff` 模块（`No module named ruff`）→ 按环境缺失记录，非本轮缺陷（同 r12/r13 口径） |

功能回归：练习单题判分（单选/多选/判断）、笔试出卷结构闸门、熟练度账本、`filtered_count` 均零改动，只做定向用例与 seed 幂等回归。

## 6 门禁常量与依据（`test_r13_question_shuffle.py`）

| 常量 | 值 | 依据 |
|---|---|---|
| `SINGLE_POSITION_RATIO` | `(0.20, 0.32)` | 需求口径 20%–30%，上界 32% 容纳小桶抽样波动 |
| `JUDGE_TRUE_RATIO` | `(0.40, 0.60)` | 判断题极性区间，全局与按语言同口径 |
| `MAX_LONG_ANSWER_COUNT` | `0` | r14 · P3-2 起由 `LENGTH_REWRITES` 改写，>3× 必须清零 |
| `LENGTH_RATIO_SPOTCHECK` | `2.0` | 2–3× 抽检面（实测 129 道） |
| `JUDGE_FLIP_COUNT` | `38` | 表内条数须与之相等，且 `directions == {"A","B"}` |
| `MIN_SINGLE_SAMPLE_PER_LANGUAGE` | `20` | 低于该样本量的语言桶只记录不判定 |
| `MIN_JUDGE_SAMPLE_PER_LANGUAGE` | `6` | 同上（判断题桶样本更小） |

冻结基线（`test_r12_question_merge.py`，只覆盖前 260 行序列化块）：`R13_SEED_BYTES = 191135`、`R13_SEED_SHA256 = 017e67770f2586b5e7e7d189de255d8a9c5a2208d4ab2df9987ffcee12aad4c7`（r14 压缩 23 道存量题后重算）。

## 7 风险与回滚

| 风险 | 处置 |
|---|---|
| 启动覆写改动线上库 | 只覆盖 seed 内同 id 行（不新增/不删除）；逐字段比对后仅写差异；库内一致时 0 改写；`reflect` 后 `updated_at` 会变，属预期 |
| 长答案改写语义漂移 | `before` 不精确匹配即记 `stale` 且测试红，**绝不静默改写**；只动正确项文本，key/解析不动 |
| 判断题新增 8 条 B→A 的事实正确性 | 表内逐条人工核对（r13 的 29 条已核对过），报表给「原句 → 新句」对照表 |
| 分桶小样本抖动 | `MIN_*_SAMPLE_PER_LANGUAGE` 跳过小桶判定 |
| 字节契约破坏 | `dumps()` 单一出口 + 双 `--check` 0 差异 + 冻结基线 |

**回滚**：撤掉 `ensure_seeded()` 的 `refresh_from_seed()` 调用（`import_seed` 保持，存量库回到只增不覆盖）＋ `git checkout backend/app/seed/questions.json` ＋ 还原 `question_shuffle.py` 的 `LENGTH_REWRITES` / `JUDGE_FLIPS` 与本轮门禁常量，随后按「先撤代码再 `question_merge --write`」重生成 seed。已部署库如需回到旧顺序须人工重导，撤代码本身不会自动回退已覆写的行。

## 8 假设与取舍（用户可推翻）

1. **门禁文件沿用 `test_r13_question_shuffle.py` 名**（内容 r14 扩展）：避免历史夹引用断链与常量第三处来源；若团队要求按需求新建测试文件，需同步迁两条按语言用例。
2. **`JUDGE_FLIP_COUNT` 直接等于表条数 38**：不按「最小必要翻转数」动态推导，表变则门禁变，避免两处口径。
3. **存量 23 道改写态从 seed 读回后落 `already`**：重复运行不二次压缩，`stale` 仅表示基线漂移。
4. **启动覆写不做「删多余行」**：库内存在但 seed 没有的行保持不动（r6 AC-1 边界），本轮不扩权限。
5. **`ruff` 缺失按环境缺失记录**：本机 `backend/.venv` 亦不存在，lint 以 frontend 侧为准（同 r12/r13）。

## 9 交付物与验收要点

- 代码：`repository.refresh_questions/1`、`question_bank.refresh_from_seed/ensure_seeded`、`question_shuffle` 的 40 条压缩表与 38 条双向表及分桶、重算后的 `questions.json`、三个测试文件。
- 文档：本夹 `SHUFFLE-REPORT.md` / `QUESTION-BANK-MERGE-REPORT.md`（工具生成）、本变更单、`QA-REPORT.md`、`ACCEPTANCE.md`。
- 验收看点：4 条 P3 逐条关闭有测试或实测证据；全局与按语言分布落区间；>3× 为 0；`stale` 为 0；双 `--check` 0 差异；冻结基线逐位相等；启动覆写「第二次 0 改写」；地板 ≥527。
