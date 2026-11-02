# r15 QA 报告：清除题干/解析中的「参考答案要点」并补门禁

- 任务夹：`docs/teamflow/20261102-r15-question-text-cleanup/`（基线依赖 `docs/teamflow/20261102-r12-question-bank-merge` 的 P3-D-2）
- 性质：tech-driven closure，纯数据处理 + 常驻门禁；**不新增/不改功能性 AC**，只关闭 r12 `ACCEPTANCE.md` §4 的 P3-D-2 中的「文本残留」部分。
- 被测工作区改动：`backend/app/services/question_merge.py`、`backend/app/services/question_shuffle.py`（仅报表路径）、`backend/app/seed/questions.json`（重算）、`backend/tests/test_r12_question_merge.py`、`docs/teamflow/memory.md`、本夹四份文档 + 两份工具报表。

## 1 结论

**通过。** 60 处素材编辑用语（去重后 49 道题）全部清理，落盘 seed 的题干/解析 **0 命中**；新增 3 条门禁且经「先红后绿」实证有效（`--write` 前 2 条实测失败）；双 `--check` 0 差异；定向三文件 **72 passed**；全量 `pytest` **535 collected / exit 0**（含 1 skip；r14 基线 532，本轮新增 3）。`ruff` 本机不可用，按环境缺失记录（非本轮缺陷）。

## 2 D-2 收口逐项验证

| 项 | 处置 | 证据 | 结论 |
|---|---|---|---|
| 题干残留 45 道 | 整串替换 `参考答案要点` → `要求` | seed 侧 `prompt` 命中 0；抽检 `l100-018` / `l100-019` / `l100-044` / `l100-062` / `l100-066` / `l100-069` / `l100-070` 均已改为「…最符合要求？」 | 关闭 |
| 解析残留 15 条 | 整串替换 `参考答案要点` → `参考要点` | `explanation` 命中 0；抽检 `l100-064`「不符合参考要点。」、`l100-099`「参考要点明确：…」、`iq380-370`「参考要点指出，…」 | 关闭 |
| 替换幅度受控 | 只动 `_TEXT_REWRITES` 列出的字段与原串 | `git diff --numstat`：seed **60/60 行**，仅 `prompt` 45 行、`explanation` 15 行（11 道两字段同时命中 → 49 道题）；`answer` / `options` 逐行零改动 | 关闭 |
| 不顺手改题 | 真实数据对拍 | 用 `monkeypatch` 把 `sanitize_text()` 换成恒等函数跑一次 `build_seed()`，与落盘 seed 逐题比对：新值恒等于「旧值只做该串替换」；`id` / `direction` / `kind` / `difficulty` / `essentiality` / `language` 全部零变化；命中总数恒为 60 | 关闭 |
| 防回潮 | 3 条门禁（§5） | 纯函数口径（返回新字典、不改入参、二次调用无变化）、落盘 seed 0 命中、真实数据命中数 60 | 关闭 |
| 存量库落地 | 依赖 r14 的启动覆写 | `ensure_seeded()` = `import_seed → refresh_from_seed → count`；这 49 行的 `prompt`/`explanation` 在下次启动被刷成当前 seed，历史 `question_attempts` 只存 `correct`，不受影响 | 关闭（复用 r14 能力） |

## 3 数据与幂等

| 检查 | 实测 |
|---|---|
| seed 重生成 | `--write` → **779 条 / 725928 字节**（存量 260 + 新增 519；越界丢 0、字面重复 0、近重复 0、方向纠正 9、方向推断 20） |
| 字节账 | r14 基线 726558 → 725928 = **−630 字节**：题干 45 处各 −4 字符、解析 15 处各 −2 字符（`参考答案要点` 6 字 → `要求` 2 字 / `参考要点` 4 字），共 −210 字符 × 3 字节/字符，与实测一致 |
| 串命中 | 新 seed `prompt`+`explanation` 含「参考答案要点」= **0**（HEAD 版 = 60） |
| `question_merge --check` | 0 差异（exit 0，「可用 779 道（幂等成立）」） |
| `question_shuffle --check` | 0 差异（exit 0） |
| 冻结基线 | `R13_SEED_BYTES = 191135`、`R13_SEED_SHA256 = 017e6777…4c7` 未变；`test_r12_question_merge.py` 绿（只锚前 260 行存量块，本轮命中全在带 `source` 的新增行） |
| 题量与来源 | 779 道；`seed` 260 / `tiji` 20 / `local100` 100 / `iq380` 379 / `fe-interview` 20；`single` 551 / `multiple` 60 / `judge` 156 / `text` 12 —— 与 r14 逐项一致 |
| 位置与极性 | 单选 A146/B139/C135/D131 = 26.5/25.2/24.5/23.8%，判断 A85/B71 = 54.5/45.5%，按语言各桶均落门禁区间（`SHUFFLE-REPORT.md` §2/§3） |
| 长答案与解析 | >3× **0** 道（2–3× 129、中位 1.46）；`LENGTH_REWRITES` 40 条 stale **0**；解析一致性 406 校验对 / 反向题面 6 / 违规 **0** |
| 整文件指纹 | `seed/questions.json` SHA256 = `6a0fb7e5efc85265cfa7295d51c1bfc9c400d2804cebb13c175d007b4aeb70a3`（725928 B） |

## 4 测试与环境

| 命令 | 结果 |
|---|---|
| `cd backend && python -X utf8 -m pytest -q -p no:cacheprovider` | **535 collected，1 skip，exit 0**（r14 532 + 本轮 3；`--collect-only` 逐文件求和复核 = 535） |
| `pytest tests/test_r12_question_merge.py tests/test_r13_question_shuffle.py tests/test_question_bank.py -q` | **72 passed**（`--write` 之后实跑） |
| 双 `--check` | 两条 exit 0（重生成报表后再跑一次仍 0 差异） |
| `cd frontend && npm run typecheck / lint / test / build` | 本轮前端**零改动**，采信 r14 实跑结论（typecheck 0 / lint 0 error 28 warn / vitest 133 / build 通过），未复跑 |
| `python -m ruff check app tests` | **本机无 `ruff` 模块**（`No module named ruff`，`backend/.venv` 不存在）→ 环境缺失，非本轮缺陷（同 r12/r13/r14 口径） |

## 5 门禁变红证据（先红后绿）

`sanitize_text()` 与门禁先落地、磁盘 seed 尚未重算时，用 `-k "meta_phrase"` 跑 `test_r12_question_merge.py`，**2 条失败（exit 1）**：

1. `test_seed_text_has_no_staging_meta_phrase` —— offenders 列表含 `l100-018` / `l100-019` / `l100-044` / `l100-062` / `l100-064` 等；
2. `test_sanitize_text_only_touches_meta_phrase_in_real_data` —— 对拍在 `l100-018` 报「prompt 与『只把 参考答案要点 换成 要求』不符」。

`--write` 重算落盘后再跑同一组：**3 条全绿**。说明门禁读的是磁盘 seed、对回潮与「顺手改题」都有实际拦截力（第 3 条纯函数测试不读磁盘，清理前后均绿，属设计如此）。

## 6 已知限制与说明

1. **只做固定串替换，不做文案润色**（技术变更单 §3.3）：替换后个别解析仍以「参考要点」作指代（如 `l100-064`「不符合参考要点。」），语义成立但措辞偏内部；进一步润色会把数据清理扩成 779 道重写，另立需求。
2. **存量库需一次启动才刷新**：依赖 r14 的 `refresh_from_seed()`，本需求不新增启动逻辑；未启动的旧库仍显示旧题干。
3. **`ruff` 不可用**：环境缺失，后端 lint 未实跑；不影响 pytest 与前端结论。
4. **全量 pytest 耗时约 24 分钟**（本次 19:04→19:28，题库重算类用例 CPU 密集），单进程串行跑，未与 `--write` 并发（并发会争用 `tests/.tmp` 与 seed）。
5. **报表路径随需求迁移**：`question_merge` / `question_shuffle` 的 `REPORT_PATH` 已指向 r15 夹；r13/r14 夹内报表保持当时生成内容，属历史产物，不追刷。
