# r15 验收报告：清除题干/解析中的「参考答案要点」并补门禁

- 任务夹：`docs/teamflow/20261102-r15-question-text-cleanup/`（基线依赖 `docs/teamflow/20261102-r12-question-bank-merge`、`20261102-r13-answer-bias-shuffle`、`20261102-r14-p3-closure`）
- 验收对象：分支 `feat/dev-skill-coach` 工作区未提交改动 —— `backend/app/services/question_merge.py`、`backend/app/services/question_shuffle.py`（仅报表路径）、`backend/app/seed/questions.json`（重算）、`backend/tests/test_r12_question_merge.py`、`docs/teamflow/memory.md`；本夹 `TECH-CHANGE.md` / `QA-REPORT.md` 与两份工具报表。按团队约定 Agent 不提交。
- 验收口径来源：`TECH-CHANGE.md` 明确「不新增/不改功能性 AC」，只关闭 r12 `ACCEPTANCE.md` §4 的 P3-D-2 文本残留项；故判据 = 清理彻底 + 只动该串 + 幂等 + 不回归 r12/r13/r14 既有约束（单写入者、`dumps` 单一序列化、启动幂等、契约零改动）。

## 1 判据逐条核对

| # | 判据 | 实测结果 | 结论 |
|---|---|---|---|
| 1 | 题干/解析不再含素材编辑用语 | 落盘 seed `prompt`/`explanation` 含「参考答案要点」= **0**（HEAD 版 = 60） | 通过 |
| 2 | 清理面与预期一致 | 49 道题：`prompt` 45 行 / `explanation` 15 行（11 道两字段同时命中）；`git diff --numstat` seed 60/60 行 | 通过 |
| 3 | 只替换固定串、不顺手改题 | 真实数据对拍（恒等函数版 `build_seed()` vs 落盘 seed）：新值恒等于「旧值只做该串替换」，命中数恒 60；`kind`/`direction`/`difficulty`/`essentiality`/`language` 零变化 | 通过 |
| 4 | 判分与选项不受影响 | `answer` / `options` 逐行零改动；`grade_objective()` 输入不变 | 通过 |
| 5 | 幂等（单写入者） | `question_merge --check` exit 0、`question_shuffle --check` exit 0（重生成报表后复跑仍 0 差异） | 通过 |
| 6 | 冻结基线不破 | `R13_SEED_BYTES = 191135`、`R13_SEED_SHA256 = 017e6777…4c7` 未变；`test_r12_question_merge.py` 绿 | 通过 |
| 7 | 题量与分布不漂移 | 779 道；`single` 551 / `multiple` 60 / `judge` 156 / `text` 12；单选 A146/B139/C135/D131 = 26.5/25.2/24.5/23.8%，判断 A85/B71 = 54.5/45.5%，按语言各桶落区间 | 通过 |
| 8 | r13/r14 其它门禁不回退 | >3× 长答案 0 道（2–3× 129、中位 1.46）、`LENGTH_REWRITES` stale 0、解析一致性违规 0、保持原序 106 道 | 通过 |
| 9 | 门禁可变红 | 落盘前 `-k "meta_phrase"` → **2 条红**（offenders 点名 + 对拍不符）；`--write` 后 3 条全绿 | 通过 |
| 10 | 地板只增不减 | 全量 `pytest` **535 collected / exit 0**（1 skip；r14 532 + 本轮 3）；定向三文件 **72 passed** | 通过 |
| 11 | 运行时与契约零改动 | `git status`：仅上列 5 个文件 + 本夹；`question_bank.py`/`repository.py`/`db.py`/`schemas.py`/`types.ts`/`exam*.py`/`practice.py`/`proficiency.py`/`frontend/**` 零改动 | 通过 |
| 12 | 前端门禁 | 本轮前端零改动；采信 r14 实跑结论（typecheck 0 / lint 0 error 28 warn / vitest 133 / build 通过），未复跑 | 通过（采信） |
| 13 | 报表同源 | 两份报表均由工具生成、落本夹、标题为 r15；数字与 seed 同源（`--check` 0 差异） | 通过 |
| 14 | 存量库可落地 | 依赖 r14 `ensure_seeded()` 的启动覆写：这 49 行文本在下次启动刷成当前 seed，不新增行、历史 `question_attempts` 不变 | 通过（复用 r14） |
| 15 | 记忆已收口 | `memory.md` 记录 r15 约定（`sanitize_text()` 位置、`_TEXT_REWRITES` 口径、返回新字典、3 条门禁、命中数 60 的复核要求），r12 §4 的 D-2 标为已关闭并指向本夹 | 通过 |

## 2 架构一致性

| 蓝图要求 | 实测 | 结论 |
|---|---|---|
| SQL 只在 `repository.py` / `db.py` | 本轮零 SQL 改动 | 符合 |
| 单写入者 + 单一序列化出口 | seed 仍只由 `question_merge.write()` 写，`dumps()` 仍是唯一格式知识；`shuffle --write` 仍委托 | 符合 |
| 正文清理位置 | `build_seed()` 内 `merge_rows()` 之后、`question_shuffle.apply()` 之前：去重口径不受影响，写盘仍单一路径 | 符合 |
| 运行时不得 import 离线工具 | 启动链路仍只 import `question_bank`/`repository`；`sanitize_text()` 只在离线流水线内被调用 | 符合 |
| 契约零改动 | `schemas.py` / `types.ts` 无 diff；题干只是文本值变化 | 符合 |
| 无重复实现 | 替换表 `_TEXT_REWRITES` 单一出处；门禁从工具派生（`qm._TEXT_REWRITES` / `qm.sanitize_text()`），不复制正则或文本 | 符合 |
| 确定性 | 无随机、无正则上下文推断、无 AI 改写：整串替换 + `--check` 逐字节 0 差异 | 符合 |

## 3 复跑命令

```bash
cd backend && python -X utf8 -m app.services.question_merge --write      # 779 条 / 725928 字节
cd backend && python -X utf8 -m app.services.question_merge --check      # exit 0
cd backend && python -X utf8 -m app.services.question_shuffle --check    # exit 0
cd backend && python -X utf8 -m pytest -q -p no:cacheprovider            # 535 collected, exit 0
cd backend && python -X utf8 -m pytest tests/test_r12_question_merge.py \
    tests/test_r13_question_shuffle.py tests/test_question_bank.py -q    # 72 passed
```

前端本轮零改动，四门禁结果见 `QA-REPORT.md` §4（采信 r14 实跑）。

## 4 遗留（全为 P3，均不阻断）

| 编号 | 内容 | 处置建议 |
|---|---|---|
| P3-e | 替换后个别解析仍以「参考要点」作指代（如 `l100-064`「不符合参考要点。」），措辞偏内部 | 属文案润色范畴；若要做，另立需求按题审校，勿混入数据清理 |
| P3-f | `ruff` 本机不可用（`No module named ruff`），后端 lint 未实跑 | 与 r9/r12/r13/r14 同口径记录；CI 或含 ruff 的环境补跑一次 |
| P3-g | 存量库需一次服务启动才刷新这 49 行文本 | 依赖 r14 启动覆写；部署后首启即生效，无需手工 SQL |
| P3-h | 全量 `pytest` 约 24 分钟（题库重算类 CPU 密集），并发会共用 `tests/.tmp` | 工艺观察：CI 串行或按目录分片 |
| P3-i | r12 收口仍有 D-4 / D-6 未关闭 | 不在本轮范围；按 r12 `ACCEPTANCE.md` §4 逐项另立需求 |

## 5 验收判定说明

- 功能性：r12 P3-D-2 的文本残留项关闭 —— 60 处（49 道题）清理完毕、落盘 0 命中、替换幅度受控（`answer`/`options` 零改动）、真实数据对拍证明「只做该串替换」。
- 结构性：SQL 边界、单写入者、`dumps` 单一出口、启动幂等、契约零改动全部保持；替换表单一出处、门禁从工具派生，无第二份实现。
- 验证：535 collected exit 0（1 skip）、定向 72 passed、双 `--check` 0 差异、门禁先红（2 条）后绿（3 条）。
- 存量库通过 r14 启动覆写落地；前端零改动，采信 r14 实跑。
- 因此判 **通过**；§4 的 5 条 P3 为环境/文案/工艺留痕，不构成返工条件。

验收结论：✅ 通过
