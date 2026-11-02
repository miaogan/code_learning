# r14 验收报告：关闭 r13 验收 4 条 P3 遗留

- 任务夹：`docs/teamflow/20261102-r14-p3-closure/`（基线依赖 `docs/teamflow/20261102-r13-answer-bias-shuffle`）
- 验收对象：分支 `feat/dev-skill-coach` 工作区未提交改动 —— `backend/app/repository.py`、`backend/app/services/question_bank.py`、`backend/app/services/question_shuffle.py`、`backend/app/services/question_merge.py`、`backend/app/seed/questions.json`（重算）、三个测试文件；本夹 `SHUFFLE-REPORT.md` / `QUESTION-BANK-MERGE-REPORT.md`（工具生成）、`TECH-CHANGE.md` / `QA-REPORT.md`。按团队约定 Agent 不提交。
- 验收口径来源：`TECH-CHANGE.md` 明确「不新增/不改功能性 AC」，只关闭 r13 `ACCEPTANCE.md` §4 的 4 条 P3；故判据 = 4 条 P3 的关闭证据 + 不回归 r12/r13 既有约束（单写入者、`dumps` 单一序列化、启动幂等、契约零改动）。

## 1 判据逐条核对

| # | 判据 | 实测结果 | 结论 |
|---|---|---|---|
| 1 | P3-1 存量库能被刷成当前种子 | `ensure_seeded()` = `import_seed → refresh_from_seed → count`；测试把旧题干/旧答案导入后启动即刷回真实种子；库内已一致时第二次 `refresh_questions()` 返回 0 | 通过 |
| 2 | P3-1 覆写不越界 | 空列表返回 0；未知 id 不新增（`test_refresh_questions_ignores_unknown_and_empty_rows`）；只覆盖 seed 内同 id 行，不删行 | 通过 |
| 3 | P3-1 历史判分不受影响 | `question_attempts` 只存 `correct`；测试插一条历史作答后覆写题目行，attempts 逐条不变 | 通过 |
| 4 | P3-2 >3× 长答案清零 | 报表 §5：样本 611、中位 1.46、2–3× 129 道、**>3× 0 道**；门禁 `MAX_LONG_ANSWER_COUNT = 0` | 通过 |
| 5 | P3-2 改写表干净 | 40 条绝对映射；本次 applied 17 / already 23 / **stale 0**；`test_length_rewrites_are_current` 断言 stale 空且覆盖全表 | 通过 |
| 6 | P3-2 只动正确项文本 | 改写只替换 `answer` 指向选项的 `text`，选项顺序 / key / 解析不动（实现与报表对照表可逐条核对） | 通过 |
| 7 | P3-3 判断双向可用 | `JUDGE_FLIPS` 38 条且 `directions == {"A","B"}`；新增 8 条 B→A（ts/react/js/html/vue3 的 q17·q18·q20 组）、2 条 A→B（`iq380-215`/`iq380-230`）；绝对映射仍幂等 | 通过 |
| 8 | P3-3 全局与按语言极性 | 全局 A85/B71 = **54.5/45.5%**；按语言 42.9%–58.8% 全落 40%–60% | 通过 |
| 9 | P3-4 按语言单选均衡 | 轮转计数按 `language` 独立累加；各语言 A 25.0%–29.5%、D 21.4%–25.0%；全局 A146/B139/C135/D131 = 26.5/25.2/24.5/23.8% | 通过 |
| 10 | P3-4 门禁按语言复算 | `test_single_positions_balanced_per_language` / `test_judge_polarity_half_half_per_language` 逐桶比对 metrics 与实时分布；小桶由 `MIN_*_SAMPLE_PER_LANGUAGE` 跳过判定 | 通过 |
| 11 | 数据一致性与幂等 | `--write` → 779 条 / **726558 字节**；`question_merge --check` 0 差异、`question_shuffle --check` 0 差异（重生成后复跑仍 0） | 通过 |
| 12 | 冻结基线迁移正确 | `R13_SEED_BYTES = 191135`、`R13_SEED_SHA256 = 017e6777…4c7`；`test_r12_question_merge.py` 绿（只覆盖前 260 行，P3-2 压缩 23 道存量题后重算） | 通过 |
| 13 | 地板只增不减 | 全量 `pytest` **532 collected / exit 0**（r13 527 + 新增 5）；定向三文件 **69 passed** | 通过 |
| 14 | 门禁可变红 | `R13_SEED_PATH` 指向「单选答案全 A」变异 seed → **6 条红**（分布 / 按语言 / 长答案 / 改写表 / 解析一致性 / 字节复现） | 通过 |
| 15 | 运行时与契约零改动 | `git status`：仅上列后端文件 + 本夹文档；`exam.py`/`exam_selector.py`/`practice.py`/`proficiency.py`/`db.py`/`schemas.py`/`frontend/**` 零改动 | 通过 |
| 16 | 前端门禁 | 本轮前端零改动；本会话实跑 typecheck 0 / lint 0 error 28 warn / vitest 133 / build OK | 通过（采信） |
| 17 | 报表同源 | 两份报表均由工具生成且落在本夹；合并报表标题已刷 r14；数字与 seed 同源（`--check` 0 差异） | 通过 |

## 2 架构一致性

| 蓝图要求 | 实测 | 结论 |
|---|---|---|
| SQL 只在 `repository.py` / `db.py` | 新增 `_QUESTION_REFRESH` 在 `repository.py`；`question_bank` 只调用 repository 函数 | 符合 |
| 单写入者 + 单一序列化出口 | seed 仍只由 `question_merge.write()` 写；`dumps()` 仍是唯一序列化出口；`shuffle --write` 仍委托 | 符合 |
| 启动路径幂等 | `import_seed` 只增（`DO NOTHING`）+ `refresh_from_seed` 只覆写差异行；两次启动新增 0、改写 0 | 符合 |
| 运行时不得 import 离线工具 | 启动链路只 import `question_bank`/`repository`；`question_shuffle` 仍仅被 `question_merge` 引用 | 符合 |
| 契约零改动 | `schemas.py` / `types.ts` 零改动，`language`/`source` 仍不进 HTTP 契约 | 符合 |
| 无重复实现 | 分布统计/解析判角/冻结基线常量仍单一出处；新测试从工具派生而非复制正则 | 符合 |

## 3 复跑命令

```bash
cd backend && python -X utf8 -m app.services.question_merge --write      # 779 条 / 726558 字节
cd backend && python -X utf8 -m app.services.question_merge --check      # exit 0
cd backend && python -X utf8 -m app.services.question_shuffle --check    # exit 0
cd backend && python -X utf8 -m pytest -q -p no:cacheprovider            # 532 collected, exit 0
cd backend && python -X utf8 -m pytest tests/test_r13_question_shuffle.py \
    tests/test_r12_question_merge.py tests/test_question_bank.py -q     # 69 passed
cd backend && $env:R13_SEED_PATH="<变异 seed>"; python -X utf8 -m pytest tests/test_r13_question_shuffle.py -q  # 必须红（实测 6 failed）
```

前端本轮零改动，四门禁结果见 `QA-REPORT.md` §4。

## 4 遗留（全为 P3，均不阻断）

| 编号 | 内容 | 处置建议 |
|---|---|---|
| P3-a | `ruff` 本机不可用（`No module named ruff`，`backend/.venv` 不存在），后端 lint 未实跑 | 与 r9/r12/r13 同口径记录；CI 或含 ruff 的环境补跑一次 |
| P3-b | 门禁文件沿用 `test_r13_question_shuffle.py` 名（内容已 r14 扩展） | 有意取舍（防历史夹引用断链）；若团队要求按需求拆分再迁 |
| P3-c | 全量 `pytest` 约 20 分钟（题库重算类用例 CPU 密集），并发跑会共用 `tests/.tmp`/临时库 | 工艺观察：CI 串行或按目录分片，不并发 |
| P3-d | 启动覆写首次会改动存量库行（`updated_at` 变化） | 设计目的（P3-1）；如需审计留痕可加启动日志，另立需求 |

## 5 验收判定说明

- 功能性：4 条 P3 全部关闭 —— 存量库启动覆写（含不新增/attempts 不变）、>3× 清零（40 条表、stale 0）、判断题 38 条双向（全局 54.5/45.5、按语言 42.9–58.8）、按语言分桶单选均衡（25.0–29.5）。
- 结构性：SQL 边界、单写入者、`dumps` 单一出口、启动幂等、契约零改动全部保持；新增门禁从工具派生、无第二份实现。
- 验证：532 collected exit 0、定向 69 passed、双 `--check` 0 差异、变异 seed 6 条红。
- 因此判 **通过**；4 条 P3 为环境/工艺留痕，不构成返工条件。

验收结论：✅ 通过
