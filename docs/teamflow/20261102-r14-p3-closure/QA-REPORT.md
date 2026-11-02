# r14 QA 报告：关闭 r13 验收 4 条 P3 遗留

- 任务夹：`docs/teamflow/20261102-r14-p3-closure/`（基线依赖 `docs/teamflow/20261102-r13-answer-bias-shuffle`）
- 性质：tech-driven closure，纯数据处理 + 启动接线；**不新增/不改功能性 AC**，只关闭 r13 `ACCEPTANCE.md` §4 的 4 条 P3。
- 被测工作区改动：`repository.py` / `question_bank.py` / `question_shuffle.py` / `question_merge.py` / `seed/questions.json` / 三个测试文件 / 本夹两份工具报表。

## 1 结论

**通过。** 4 条 P3 全部关闭，全局与按语言分布均落区间，>3× 长答案清零，双 `--check` 0 差异，全量 `pytest` **532 collected / exit 0**（r13 基线 527，新增 5 条）。`ruff` 本机不可用，按环境缺失记录（非本轮缺陷）。

## 2 逐条 P3 验证

| 编号 | 关闭方式 | 证据 | 结论 |
|---|---|---|---|
| P3-1 存量库不刷新 | `repository.refresh_questions()`（1 次 SELECT 建 id 映射、逐字段比对、仅差异行全字段 UPDATE）+ `question_bank.ensure_seeded()` 每次启动 `import_seed → refresh_from_seed → count` | `test_ensure_seeded_refreshes_stale_rows_on_startup`（旧种子导入 → 旧题干/旧答案被刷回 → 历史 attempts 逐条不变）；`test_refresh_questions_ignores_unknown_and_empty_rows`（空列表 0、未知 id 不新增）；`refresh` 库内一致时第二次返回 0 | 关闭 |
| P3-2 长答案只出清单 | `LENGTH_REWRITES` 40 条绝对映射 + `_apply_length_rewrites()` 三态记账；`MAX_LONG_ANSWER_COUNT = 0` | 报表 §5：样本 611、中位 1.46、2–3× 抽检 129 道、**>3× 0 道**；§5.1：表内 40 条，改写 17 / 已是改写态 23 / **stale 0**；`test_length_rewrites_are_current`（stale 空、覆盖全表）、`test_long_answer_ratio_within_budget`（0 上限） | 关闭 |
| P3-3 判断题单向 | `JUDGE_FLIPS` 支持 `answer` 双向（缺省 `B`），38 条（原 29 A→B + 新增 10 − 删 1）；门禁断言 `directions == {"A","B"}` | 全局 **A85/B71 = 54.5/45.5%**；按语言全部落 40%–60%（通用 58.6 / go 58.8 / python 55.0 / java 52.6 / css·js 42.9 / html·react·ts·vue3 50.0）；`test_judge_polarity_half_half`、`test_judge_polarity_half_half_per_language`、`test_judge_flip_table_is_self_consistent` | 关闭 |
| P3-4 按语言子集仍偏 | 轮转计数按 `language` 独立累加（`_language_of`）+ `metrics.single/judge.by_language` + 按语言门禁 | 各语言单选 A 25.0%–29.5%、D 21.4%–25.0%（（通用）26.5→25.0、python 29.5、go 28.3、css 28.6、react 29.0）；全局 A146/B139/C135/D131 = 26.5/25.2/24.5/23.8%；`test_single_positions_balanced_per_language` 逐桶比对 | 关闭 |

## 3 数据与幂等

| 检查 | 实测 |
|---|---|
| seed 重生成 | `--write` → **779 条 / 726558 字节**（存量 260 + 新增 519；越界丢 0、字面重复 0、近重复 0） |
| `question_merge --check` | 0 差异（exit 0） |
| `question_shuffle --check` | 0 差异（exit 0） |
| 报表 | 两份均在 `docs/teamflow/20261102-r14-p3-closure/`；合并报表标题已刷为 r14；打乱报表 §2/§3 含按语言表、§5.1 含 40 条压缩对照 |
| 冻结基线 | `R13_SEED_BYTES = 191135`、`R13_SEED_SHA256 = 017e6777…4c7`（只覆盖前 260 行；P3-2 压缩 23 道存量题后重算，`test_r12_question_merge.py` 绿） |
| 解析一致性 | 406 校验对、反向题面 6 道、**违规 0** |

## 4 测试与环境

| 命令 | 结果 |
|---|---|
| `cd backend && python -X utf8 -m pytest -q -p no:cacheprovider` | **532 collected，exit 0**（r13 527 + r14 新增 5：`test_question_bank` 2、按语言 2、`test_length_rewrites_are_current` 1） |
| `pytest tests/test_r13_question_shuffle.py tests/test_r12_question_merge.py tests/test_question_bank.py -q` | **69 passed**（重生成后再跑一次仍全绿） |
| 门禁变红（`R13_SEED_PATH` 指向「全部单选答案 = A」的变异 seed） | 见 §5 |
| `cd frontend && npm run typecheck` | 0 error（本轮前端零改动，采信本会话实跑） |
| `npm run lint` | 0 error / 28 warning（等于 `--max-warnings 28` 上限） |
| `npx vitest run` | 10 files / **133 tests passed** |
| `npm run build` | 通过（`dist/index-*.js 285.84 kB`） |
| `python -m ruff check app tests` | **本机无 `ruff` 模块**（`No module named ruff`，`backend/.venv` 也不存在）→ 环境缺失，非本轮缺陷（同 r12/r13 口径） |

## 5 门禁变红证据

将 `R13_SEED_PATH` 指向 `backend/tests/.tmp/r14_mutant_seed.json`（把全部 `single` 的 `answer` 强改为 `["A"]`，其余行不动），`tests/test_r13_question_shuffle.py` 必须变红：

- 实测 **6 条红**（exit 1）：
  1. `test_committed_seed_is_already_balanced` —— 落盘单选 `{'A': 1.0, 'B': 0.0, 'C': 0.0, 'D': 0.0}`，越界 `0.2-0.32`；
  2. `test_single_positions_balanced_per_language` —— css 0.321 / go 0.34 / js 0.323 / python 0.328 逐桶越界；
  3. `test_long_answer_ratio_within_budget` —— 答案被强改为 A 后 `java-q3` 正确项 >3×（1 > 0）；
  4. `test_length_rewrites_are_current` —— 33 条改写表基线失配（正确答案位置被强改后 before 不再命中）；
  5. `test_explanation_refs_stay_consistent_with_answers` —— `l100-006`/`l100-014`/`l100-024` 解析引用错位；
  6. `test_seed_bytes_are_reproducible` —— 磁盘 seed 与重算不一致。
- 说明：变异文件只用于证明门禁有效，验证后已删除；仓库 seed 未受影响（随后双 `--check` 仍 0 差异）。

> 变异文件只落在 `backend/tests/.tmp/`（gitignored 的临时目录），不进入仓库。

## 6 已知限制与说明

1. **启动覆写会改线上库行**：每次启动会把库内同 id 行刷成当前 seed（不新增/不删除）；这是 P3-1 的设计目的，第二次启动恒 0 改写。回滚见 `TECH-CHANGE.md` §7。
2. **`ruff` 不可用**：本机环境缺失，后端 lint 无法实跑；不影响 pytest 与前端门禁结论。
3. **全量 pytest 耗时较长**（约 20 分钟，含题库重算类用例），本轮单进程串行跑完，未再并发（并发会共用 `tests/.tmp` 与临时库）。
4. **门禁文件仍名 `test_r13_question_shuffle.py`**：属有意取舍（见 `TECH-CHANGE.md` §8.1），内容已按 r14 扩展。
