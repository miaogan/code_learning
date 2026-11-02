# r13 验收报告：题库答案位置偏置修复（选项打乱 + 判断题极性改写）

- 任务夹：`docs/teamflow/20261102-r13-answer-bias-shuffle/`（基线依赖 `docs/teamflow/20261102-r12-question-bank-merge`）
- 验收对象：分支 `feat/dev-skill-coach` 的工作区未提交改动 —— 新增 `backend/app/services/question_shuffle.py`、`backend/tests/test_r13_question_shuffle.py`；改动 `question_merge.py`（接线/报表路径/write 增参）、`backend/app/seed/questions.json`（重算）、`test_r12_question_merge.py`（冻结基线迁移）、`test_engineering_gates.py`（离线工具白名单 + 反向断言）、`docs/teamflow/memory.md`（1 约定 + 1 待办）；本夹 `SHUFFLE-REPORT.md` / `QUESTION-BANK-MERGE-REPORT.md`（工具生成）。按团队约定 Agent 不提交。
- 验收口径来源：本轮为 tech-driven rework，`TECH-CHANGE.md` 明确「不新增/不改功能性 AC」，只关闭 r12 QA-REPORT 的 D-2 数据质量观察；故验收判据 = 变更单 §6 门禁口径 + §9 交付要点 + 不回归既有 AC（r11/r12 的 20 条）。

## 1 判据逐条核对（全部由验收侧独立复跑，未复用开发/QA 断言）

| # | 判据 | 实测结果 | 结论 |
|---|---|---|---|
| 1 | 单选答案位置落 20%–32% | **A139/B138/C137/D137 = 25.2/25.0/24.9/24.9%（n=551）**；对照 r12 基线 A323＝58.6%（偏置源确证存在） | 通过 |
| 2 | 判断「正确」占比落 40%–60% | **A78/B78 = 50.0%（n=156）**；基线 A107＝68.6% | 通过 |
| 3 | 判断题只改陈述、不动选项 | 156/156 行选项恒 `A.正确/B.错误` | 通过 |
| 4 | 29 条极性改写事实正确 | flip 表 29 条无重复 id；**逐条人工通读 29 组「原句→新句」**，新句均为可判定为假的反命题，答案 `["B"]` 正确；落盘 prompt/explanation 与表逐项吻合；未翻转的 127 道整行与基线逐字节一致 | 通过 |
| 5 | 解析字母引用不指向错项 | 验收侧自写口径复算（`X 项错误 ⇔ X∉answer`、`X 项正确 ⇒ X∈answer`、`正确项为 …` 集合==answer，含反向题面）：**95 校验对 0 违规**；工具侧指标 406 对 0 违规、反向题面 6 道 | 通过 |
| 6 | 不得改题（内容保持） | 738 行（551 单选 + 60 多选 + 127 未翻转判断）题干逐字相同、选项文本多重集相同、正确项文本集合相同、解析「字母掩码后」文本相同 —— **0 漂移**；12 道 `text` 行整行未变 | 通过 |
| 7 | 判角不可靠题保持原序 | 跳过清单 106 道，**106/106 整行与 r12 基线逐字节相同** | 通过 |
| 8 | 结构不变量 | key 序列恒 `A..` 位置序、`answer ⊆ options` 且非空、单选恰 1/多选≥2/判断恰 2 选项恰 1 答案、解析≥10 字 —— **0 违规**（779 行） | 通过 |
| 9 | 幂等与确定性 | `merge --check` exit 0（779 道 0 差异）；`shuffle --check` exit 0；`apply(磁盘)+dumps()` 逐字节复现 seed（**728780 B**）；`apply` 二次幂等；**从 r12 基线跑一次变换 == 磁盘** | 通过 |
| 10 | 常驻门禁齐备 | 新建 r13 门禁 13 条；r12 冻结基线由 `R11_*` **迁移**为 `R13_*`（`192073`/`9cc60b1b…`，验收侧实测与常量逐位相等；全仓 `R11_SEED` 0 命中，未并存）；工程门禁 `OFFLINE_TOOLS` 双工具白名单 + 独立反向断言 | 通过 |
| 11 | 门禁可变红 | 注入「全部单选答案挪到 A」的变异 seed（`R13_SEED_PATH`）→ `test_committed_seed_is_already_balanced`、`test_explanation_refs_stay_consistent_with_answers`、`test_seed_bytes_are_reproducible` **3 条红** | 通过 |
| 12 | 地板只增不减 | 全量 `pytest` **527 collected、exit 0**（≥522 地板，且 ≥512 基线）；r13 定向用例绿 | 通过 |
| 13 | 零运行时改动 | `git status` 无 `exam*`/`practice*`/`proficiency`/`repository`/`db`/`schemas.py`/`frontend/**` 改动；`app/**.py` 中 `question_shuffle` 仅被 `question_merge`（离线工具）引用 → 启动路径零污染 | 通过 |
| 14 | 报表与数据同源、路径正确 | `SHUFFLE-REPORT.md` 9 节齐全（前后分布 / 29 条对照 / 长度比与 >3× 清单 / 106 跳过 / 双校验 / 幂等证据 / 运行时不受影响），数字与验收侧复算一致；两 `REPORT_PATH` 均指 r13 夹，`git status` 无 r12 夹改动 | 通过 |
| 15 | 单写入者、单一序列化出口 | `question_shuffle` 内 **0** 处 `write_text/write_bytes`（`--write` 委托合并工具）；`dumps` 全仓仅 2 处且其一为历史 `question_backfill`（仅测试比对用），**无第三份** | 通过 |
| 16 | 运行时主路径可用（新 seed 实跑） | TestClient 冒烟：`/health` 200 且 `ai_configured=false`；python 题单 20 道、题型 ⊂ {single,multiple,judge}、**不含 answer**、选项顺序/题干与落盘 seed **20/20** 一致；正确键 20/20 判 True、错键判 False 且回显 answer/解析；翻转判断题（`iq380-155`）判 True；无命中 200+空列表 | 通过 |
| 17 | 存量库行为已声明 | `import_seed` 为 `ON CONFLICT DO NOTHING` → 已部署 `app.db` 不刷新（变更单 §4/§7 显式接受，库内自洽、判分与历史 attempts 不错位），已记为待办 | 通过（已知限制） |

## 2 架构一致性（蓝图 → 实测）

| 蓝图要求 | 实测 | 结论 |
|---|---|---|
| 抽出离线变换库 `question_shuffle.py`（纯函数/无 IO/无模块级状态） | 顶层仅标准库 import；无模块级 IO/可变状态；`apply` 深拷贝后返回，内存指标 | 符合 |
| 唯一接线点 `build_seed()` 末尾 | `merged, stats["shuffle"] = question_shuffle.apply(merged)`（r12 的单写入者/序列化契约因此保持） | 符合 |
| 单写入者 + 单一序列化出口 | 见判据 15 | 符合 |
| 惰性导入防环 | `question_shuffle` 顶层不 import `question_merge`；`check()/main()` 内（缩进处）才 `from app.services import question_merge` | 符合 |
| 运行时不得 import 离线工具 | 双工具白名单 + 两条独立反向断言（失败可归因） | 符合 |
| 报表路径迁 r13、冻结常量迁移而非新增 | 见判据 10/14 | 符合 |
| 门禁口径从工具派生（不复制正则/统计器） | r13 测试 import `apply/KEYS/JUDGE_FLIPS/classify_refs`、`question_merge.JUDGE_OPTIONS`；`grep` 未见第二份正则或第二套统计器 | 符合 |
| 无重复实现 / 结构未破损 | `classify_refs`、`dumps`、`JUDGE_OPTIONS`、冻结基线常量均单一出处；无并列实现 | 符合 |

**结论：实现与蓝图逐项一致，无需架构返工。**（说明：开发侧 state 曾记录 dt-1/dt-3 未产出而被 dt-2 补齐，验收以最终落盘代码为准，实测上面各项均成立。）

## 3 独立复跑命令（验收侧）

```bash
python -X utf8 logs/teamflow/tf-mvyisvii-93ivpi/scripts/ac_r13_verify.py        # 22 项，RESULT PASS
python -X utf8 logs/teamflow/tf-mvyisvii-93ivpi/scripts/ac_r13_refs.py           # 95 校验对 0 违规 PASS
python -X utf8 logs/teamflow/tf-mvyisvii-93ivpi/scripts/ac_r13_http_smoke.py      # 12 项 PASS（新 seed 实跑）
cd backend && python -X utf8 -m app.services.question_merge --check               # exit 0
cd backend && python -X utf8 -m app.services.question_shuffle --check             # exit 0
cd backend && AI_API_KEY= python -X utf8 -m pytest -q -p no:cacheprovider         # 527 collected, exit 0
cd backend && R13_SEED_PATH=<变异 seed> pytest tests/test_r13_question_shuffle.py # 必须红（实测 3 failed）
```

前端本轮零改动（`git status` 无 `frontend/**`），QA 已实跑 typecheck 0 / lint 0 error ≤28 warn / vitest 133 / build OK，故按「零改动 + 上轮基线」采信。

## 4 遗留（全为 P3，均不阻断）与后续建议

| 编号 | 内容 | 处置建议 |
|---|---|---|
| P3-1 | **按语言筛选的子集仍偏**：单选 A 占比 python 36.1%(n=61)、js 38.7%(n=31)、vue3 9.4%(n=32)；判断 A 占比 go 70.6%(n=17)、html/vue3 16.7%。变更单 §6 只定义全局口径，故契约上不违规，但练习页恒按语言筛选（「全选 A」在 python 卷可拿约 40%） | 后续需求：轮转分配按 `language` 分桶 + 门禁按语言分组复算（本轮口径不扩） |
| P3-2 | 变更单 §3.1 记「实测 A138/B138/C138/D137」，落盘为 **139/138/137/137**（差 1 道，均在区间内）。报表、seed、`memory.md` 均为 139 口径 | 以 seed/报表为唯一事实源；本夹 `TECH-CHANGE.md` 属已交付文档，不在验收阶段改写，仅在此留痕 |
| P3-3 | 106 道（19%）解析判角不可靠 → 保持原序，其自身偏置由其余题补偿（变更单 §3.2 显式接受） | 另立「逐题人工改写解析」需求后收口 |
| P3-4 | 存量 `app.db` 不刷新，线上练习仍为旧顺序（变更单 §4/§7 显式接受） | 另立需求：`repository.py` 增覆写既有行 + 评估历史 `question_attempts` 的 key 语义 |
| — | 环境缺失：`ruff` 不在本机（`No module named ruff`），lint 以 frontend 侧为准 | 与 r12 同口径记录，非本轮交付缺陷 |

## 5 验收判定说明

- 功能性：全部判据达成（分布 25%/50%、内容 0 漂移、29 条极性逐条事实正确、解析双校验 0 违规、两条 CLI 幂等 0 差异、527 用例全绿、新 seed HTTP 实跑正确）。
- 结构性：与架构蓝图逐项一致，无重复实现、无适配漂移、无该抽未抽；单写入者与单一序列化出口这两个 r12 契约不变量被显式保住。
- 因此判 **通过**；4 条 P3 为已知限制/文档留痕，不构成返工条件，已同步到 `docs/teamflow/memory.md` 的 r13 收口待办。

验收结论：✅ 通过
