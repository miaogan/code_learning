# r15 · 题干/解析元信息清理（技术变更单）

> 关闭 r12 验收 P3-D-2 的剩余项：45 道题的题干、15 条解析里残留「参考答案要点」这一素材整理用语。
> 不改 HTTP 契约、不改判分/组卷/熟练度、不改前端。

## 1. 背景与目标

- r12 合并外部素材时，`iq380` / `local100` 两批题目的 `stem` 与解析里带有「参考答案要点」这一**素材编辑用语**：
  - 45 道题的 `prompt` 以「以下哪种做法最符合参考答案要点？」这类句式结尾；
  - 15 条 `explanation` 以「参考答案要点：/包括/明确/指出/提到」开头或引用该串；
  - 二者重叠 11 道，去重后 **49 道题、60 处**（`iq380` 44 处 + `local100` 16 处）。
- 题干里出现「参考答案要点」会让考生看到**出题过程的元信息**（提示该题由参考答案反向加工而来），
  解析里出现则让讲解读起来像内部备注；r13/r14 只处理答案位置与长度，未覆盖这一项。
- 目标：在唯一重算流水线上做**确定性替换**，让落盘 seed 的题干/解析不再含该串，并补一条常驻门禁防止回潮。

## 2. 影响面

| 文件 | 改动 | 说明 |
| --- | --- | --- |
| `backend/app/services/question_merge.py` | 修改 | 新增 `_TEXT_REWRITES` 与 `sanitize_text()`；`build_seed()` 在 `merge_rows()` 之后、`question_shuffle.apply()` 之前逐行清理；`REPORT_PATH` 指向 r15 任务夹 |
| `backend/app/services/question_shuffle.py` | 修改 | `REPORT_PATH` 指向 r15 任务夹（工具报表随需求落盘） |
| `backend/app/seed/questions.json` | 重写 | 49 道题文本变更（题干 45 / 解析 15，含 11 道重叠）；题量、顺序、答案 key、选项顺序全部不变 |
| `backend/tests/test_r12_question_merge.py` | 修改 | 新增门禁：seed 的 `prompt`/`explanation` 不得含「参考答案要点」；并断言清理只动该串 |
| `docs/teamflow/20261102-r15-question-text-cleanup/**` | 新增 | 本任务夹四份文档 + 工具报表 |
| `question_bank.py` / `repository.py` / `db.py` / `schemas.py` / `types.ts` / 前端 / `exam*.py` / `practice.py` / `proficiency.py` | **零改动** | 文本清理只发生在离线 seed 流水线，运行时读库口径不变 |

## 3. 技术方案

### 3.1 确定性替换表（唯一出处）

```python
#: 素材整理用语 → 面向考生的表述（r12 D-2 收口）。
#: 只做整串替换，不做正则/上下文推断：替换后不含原串即幂等（二次重算 0 差异）。
_TEXT_REWRITES = (
    ("prompt", "参考答案要点", "要求"),
    ("explanation", "参考答案要点", "参考要点"),
)
```

- **题干**换成「要求」：`以下哪种做法最符合要求？`、`以下哪项描述与要求一致？`，句法自然且不泄露来源。
- **解析**换成「参考要点」：保留原讲解的指代关系（`参考要点包括…` / `参考要点明确…` / `不符合参考要点。`）。
- 只处理这两个字段：`options` 实测 0 处，题干/解析之外的字段不碰。

### 3.2 接线位置

`question_merge.build_seed()` 的现有顺序不变，只在合并结果上插入一步：

```text
素材读取 → normalize_record → merge_rows(existing, candidates) → sanitize_text() → question_shuffle.apply() → dumps()
```

- 放在 `merge_rows()` **之后**：存量 260 行（不带 `source`、原样读回）也会过一遍，命中即清理、不命中零改动；
  经实测存量行不含该串，r13 冻结基线（前 260 行 `191135` 字节 / `017e6777…`）不受影响。
- 放在 `question_shuffle.apply()` **之前**：选项重排/判断题翻转不依赖该串；调换顺序不影响结果，
  保持「先清正文、再动选项」的可读顺序。
- 写盘仍只有 `question_merge.dumps()` 一处；`--check` 与 `--write` 共用 `build_seed()`，幂等判据不变。

### 3.3 为什么不用正则/大模型改写

- 60 处上下文各不相同（「最符合 / 符合 / 与…一致 / 最不符合」），但**共同点只是这一个名词短语**；
  整串替换语义无损，且能逐字节复现。正则或 AI 改写会引入不可复现的措辞漂移，破坏 `--check` 的 0 差异判据。
- 替换后若某题读起来仍别扭，属文案润色范畴，不在本轮做（避免把数据清理变成 779 道题的重写）。

## 4. 行为兼容

| 面 | 结论 |
| --- | --- |
| HTTP 契约 | 零改动（`schemas.py` / `types.ts` 无 diff）；题干只是文本值变化 |
| 判分 | 零改动：`answer` / `options` / `kind` 不变，`grade_objective()` 输入不变 |
| 组卷与熟练度 | 零改动：`direction` / `difficulty` / `essentiality` / `language` 不变 |
| 存量库 | 启动 `import_seed()` 不新增；`refresh_from_seed()` 只覆写这 49 行的 `prompt`/`explanation`（r14 已具备的能力），历史 `question_attempts` 只存 `correct`，判分不受影响 |
| 幂等 | `question_merge --check` / `question_shuffle --check` 双 0 差异 |
| 题干去重 | 替换只缩短/替换固定串，不改变题干归一化去重结果（实测题量仍 779、去重 0） |

## 5. 验证计划

1. `cd backend && python -X utf8 -m app.services.question_merge --write`：重生成 seed + 两份报表。
2. `python -X utf8 -m app.services.question_merge --check`：逐字节 0 差异（exit 0）。
3. `python -X utf8 -m app.services.question_shuffle --check`：0 差异（exit 0）。
4. 定向测试：`python -m pytest -q tests/test_r12_question_merge.py tests/test_r13_question_shuffle.py tests/test_question_bank.py` —— 全绿。
5. 数据自查：`prompt`/`explanation` 含「参考答案要点」= 0；题量 779；答案位置/判断极性/按语言分布与 r14 一致。
6. 前端零改动，typecheck/lint/vitest/build 沿用 r14 实跑结论（本轮复跑可不阻塞）。
7. `ruff` 仍为环境缺失（与 r12/r13/r14 同口径），非本轮缺陷。

## 6. 门禁与冻结基线

| 门禁 | 位置 | 口径 |
| --- | --- | --- |
| 题干/解析不得含素材元信息串 | `test_r12_question_merge.py::test_seed_text_has_no_staging_meta_phrase` | 读**落盘** seed，`prompt`/`explanation` 任一命中即红 |
| 清理只动该串 | 同上 | 对命中行断言替换后其余文本逐字相同（防止顺手改题） |
| 种子字节幂等 | `question_merge --check` | 重算与已提交 seed 逐字节 0 差异 |
| 位置/极性/长度/按语言 | `test_r13_question_shuffle.py`（r14 口径） | 不变，继续值守 |
| 冻结基线 | `test_r12_question_merge.py` | `R13_SEED_BYTES=191135` / `R13_SEED_SHA256=017e6777…` 只锚前 260 行存量块，不受本轮影响 |

## 7. 风险与回滚

| 风险 | 处置 |
| --- | --- |
| 替换误伤题干语义 | 只替换固定 6 字串，且门禁断言「除该串外逐字相同」；人工抽检 10 条（含 2 道判断题） |
| 报表路径改到 r15 后旧报表失效 | r13/r14 报表留在各自任务夹，属历史产物；r15 生成新报表 |
| 已部署库题干未刷新 | r14 的 `refresh_from_seed()` 启动覆写已覆盖；无需手工 SQL |
| 回滚 | `git revert` 本轮提交 + 重跑 `question_merge --write` 即恢复原文本（工具确定性） |

## 8. 取舍

1. **整串替换而非逐题重写**：可审计、可幂等、改动面 49 行数据；不做文案润色的连带修改。
2. **题干用「要求」、解析用「参考要点」**：同一原串按字段给不同目标词，避免题干出现「参考」字样干扰作答。
3. **门禁放在 r12 测试文件**：该文件已负责合并流水线与 seed 契约，不新建第 4 个题库测试文件。
4. **报表路径迁到 r15**：沿用「工具报表随当前需求落盘」的惯例（r13/r14 同做法）。

## 9. 交付物

- 代码：`question_merge.py` / `question_shuffle.py`（仅路径）/ 门禁测试。
- 数据：`backend/app/seed/questions.json`（49 行文本变更）。
- 文档：本任务夹 `TECH-CHANGE.md`、`QA-REPORT.md`、`ACCEPTANCE.md`、`QUESTION-BANK-MERGE-REPORT.md`、`SHUFFLE-REPORT.md`、`meta.json`。
- 记忆：`docs/teamflow/memory.md` 关闭 r12 D-2 并补 r15 约定。
