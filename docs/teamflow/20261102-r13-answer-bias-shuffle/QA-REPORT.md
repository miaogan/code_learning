# r13 QA 报告：题库答案位置偏置修复（选项打乱 + 判断题极性改写）

- 任务夹：`docs/teamflow/20261102-r13-answer-bias-shuffle/`（基线依赖 `docs/teamflow/20261102-r12-question-bank-merge`）
- 被测提交：工作区未提交改动（分支 `feat/dev-skill-coach`）：`backend/app/services/question_shuffle.py`（新）、`question_merge.py`、`backend/app/seed/questions.json`、`backend/tests/test_r13_question_shuffle.py`（新）、`test_r12_question_merge.py`、`test_engineering_gates.py`、`docs/teamflow/memory.md`
- 结论：**可验收（无 P0/P1/P2 阻断）**；4 条 P3 观察不阻断（见 §4）

## 1 范围与环境

- 范围：离线变换库 `question_shuffle`（分布均衡 / 判断极性 / 解析字母重映射 / 报表）+ `question_merge.build_seed()` 唯一接线 + 重算落盘的 779 行 seed + 常驻门禁三件（r13 新建 / r12 冻结基线迁移 / 工程门禁放宽与反向断言）。运行时、判分、契约、前端**零改动**（`git status` 无 frontend / schemas / router 变更，已核）。
- 环境：Windows + Python 3.13 + Node；后端 `python -X utf8`；服务实跑 `DB_PATH=tests/.tmp/qa-r13-e2e.db AI_API_KEY= uvicorn --port 8157`（`/health` 200、`ai_configured=false`，证明零 AI 路径成立）。
- 环境限制（非交付缺陷）：沙箱内无法启动真实浏览器（宿主 token 限制，`--no-sandbox` 亦无效），故视觉项进 §5 人工补测。

## 2 功能验证结果（全部实跑）

| # | 用例 | 命令/方法 | 结果 |
| --- | --- | --- | --- |
| 1 | 单选位置分布落 20%–32% | `qa_r13_data_check.py`（独立复算，不复用开发者断言） | **通过** A139/B138/C137/D137＝25.2/25.0/24.9/24.9%；r12 基线实测 A323＝58.6%（证明修复对象存在） |
| 2 | 判断题极性落 40%–60% | 同上 | **通过** A78/B78＝50.0/50.0%（基线 A107＝68.6%） |
| 3 | 判断题选项未被改写 | 同上（逐行断言选项恒 `A.正确/B.错误`） | **通过** 156/156 |
| 4 | 29 条极性改写事实正确 | 逐条人工复核（报表原句→新句对照表 29 行，脚本核对落盘 prompt/answer/解析 == 表内条目） | **通过** 29/29 新陈述均为真否定命题、答案 B 正确；未翻转的 127 道判断题与基线逐字节一致 |
| 5 | 内容保持（不得改题） | 同上：605 道选择题的选项文本集合、正确项文本集合、题干、解析「去字母后」文本逐题比对基线 | **通过** 0 处漂移 |
| 6 | 106 道判角不可靠题保持原序 | 同上：整行 JSON 与 r12 基线逐字节比对 | **通过** 106/106 完全一致 |
| 7 | 结构不变量（key 顺序=位置序 / answer⊆options / 解析≥10 字 / 单选唯一 / 多选≥2） | 同上 | **通过** 0 违规（选项数分布 4×611 + 2×156 + 0×12text） |
| 8 | 解析字母引用不出错 | 双校验（`X 项错误 ⇔ X∉answer`、`正确项集合==answer`、反向题面极性反转） | **通过** 406 处校验、违规 0、反向题面 6 道 |
| 9 | 幂等/确定性/不改入参 | `apply(HEAD seed)+dumps()` 与磁盘逐字节相等（728780 B）；`apply(apply(x))==apply(x)`；入参快照不变 | **通过**；`build_seed()` 重算 == 磁盘 |
| 10 | CLI 幂等契约（单写入者） | `python -X utf8 -m app.services.question_merge --check`；`-m app.services.question_shuffle --check` | **通过** 两条 exit 0（「逐字节一致，可用 779 道」/「逐字节一致」） |
| 11 | 报表与数据同源 | `render_report(metrics)` 与 `SHUFFLE-REPORT.md` 逐字一致；报表跳过清单 106 道、>3× 清单 40 条（id+比值）、极性表 29 行与指标逐项相同 | **通过** 40 项 |
| 12 | 练习主路径（真实 HTTP） | `qa_r13_e2e.py --port 8157`：题单 20 题全 python、只含 single/multiple/judge、**不含 answer**；逐题选项顺序/key/题干 == 落盘 seed（20/20） | **通过** |
| 13 | 判分正确性（单/多/判断） | 同上：正确键 True、错键 False、`correct_answer`/解析回显 == seed（单、判断、多选全集/子集） | **通过** 27 项 |
| 14 | 错题本进/出 | 同上：答错进本、**新会话**答对移出（同会话重复提交受 `UNIQUE(question_id,run_id)` 兜底属既有契约） | **通过** |
| 15 | 错误契约（未作答/非客观题） | 同上：均 400 + 统一 `{error:{code,message,retryable}}` 中文 | **通过** |
| 16 | 筛选与空态 | java 筛选全 java；`算法与数据结构+basic+advanced` → 200 + 空列表 + 中文「该组合下没有题目，试试放宽难度或必备度」 | **通过** |
| 17 | 全选 A 对抗 | 数据层确定性口径：整库 30.7%（基线 58.6%）；HTTP 20 题样本 7/19 | **通过**（子集口径见 P3-1） |
| 18 | 存量库不刷新（已接受行为的核实） | `check_r13_db_not_refreshed.py` | **通过** r13 启动新增 0 条、779/779 行停在 r12 序 |
| 19 | 常驻门禁全绿（后端地板） | `AI_API_KEY= pytest -q -p no:cacheprovider` | **通过** 收集 **527**（≥522 地板）、exit 0、1 条 skipif |
| 20 | 定向回归 | `pytest tests/test_r13_question_shuffle.py test_r12_question_merge.py test_engineering_gates.py test_question_bank_quality.py test_question_bank.py test_r11_practice_api.py test_exam_filter.py` | **通过** 170 passed |
| 21 | 门禁可变红（变红证据） | `R13_SEED_PATH=<变异 seed> pytest tests/test_r13_question_shuffle.py`：①全单选改 A → 落盘分布/解析一致/字节复现 3 红；②判断题答案全 A → 极性/落盘分布 红 | **通过** 变异输入必红、正常输入绿 |
| 22 | 前端地板（零改动，回归） | `npm run typecheck` / `npm run lint` / `npx vitest run` / `npm run build` | **通过** typecheck 0、lint 0 error/28 warn、vitest 133、build OK |

## 3 架构核对（蓝图对照）与接口一致性

| 蓝图要求 | 实测 | 结论 |
| --- | --- | --- |
| 抽出离线变换库 `question_shuffle.py`（纯函数/无 IO/无模块级状态） | 823 行、顶层仅标准库 import；`apply` 深拷贝后返回，无 IO | 符合 |
| 唯一接线点 `build_seed()` 末尾（`--check`/`--write` 共用同一重算路径） | `build_seed` 末尾 `merged, stats["shuffle"] = question_shuffle.apply(merged)`；实测重算==磁盘 | 符合 |
| 单写入者 + 单一序列化出口 | `write_bytes` 仅出现于 `question_merge.write()`；`dumps()` 仍是唯一格式知识；`question_backfill.dumps` 未被用于写 seed（grep 0 命中） | 符合 |
| 惰性导入（防循环依赖） | `question_shuffle` 顶层不 import `question_merge`；`check()/main()` 内 3 处 `from app.services import question_merge` | 符合 |
| 运行时永不 import 该工具 | `grep question_shuffle app/**.py` 仅 `question_merge`（同属离线工具）；工程门禁反向断言在 | 符合 |
| 报表路径迁移 r13（r12 夹只读） | 两 `REPORT_PATH` 均指 `docs/teamflow/20261102-r13-answer-bias-shuffle/`；`git status` 无 r12 夹改动 | 符合 |
| 冻结基线常量迁移（不得并存） | `R11_SEED_*` 全仓 0 命中；`R13_SEED_BYTES=192073` / `R13_SEED_SHA256=9cc60b…`（实测前 260 行口径一致） | 符合 |
| 工程门禁放宽 + 反向断言 | `OFFLINE_TOOLS=(merge, shuffle)`；新增 `test_r13_shuffle_tool_not_imported_by_runtime`（失败可归因单侧） | 符合 |
| 门禁口径从工具派生（不复制正则/不另写统计器） | 测试 import `question_shuffle.apply/KEYS/JUDGE_FLIPS/classify_refs`、`question_merge.JUDGE_OPTIONS`；全仓无第二份 `_EXPLICIT/_LIST` 正则 | 符合 |
| 无重复实现 / 无结构破损 | `classify_refs`、`dumps`、`JUDGE_OPTIONS`、冻结基线常量均单一出处；未发现并列实现 | 通过 |

**接口一致性（静态 + 实跑双重验证）**：`question_merge` 对 shuffle 的 4 处调用（`apply` / `REPORT_PATH` / `render_report` / 惰性 import）符号全部存在且参数形状与蓝图一致（`apply(Sequence)->tuple`、`render_report(metrics)->str`、`write(...shuffle_report_path=...)` 返回值含 `shuffle_report_path`）；`check(seed_path=None, staging_dir=None)`、`main(argv=None)`、`KEYS/JUDGE_FLIPS/classify_refs` 均与蓝图 `api` 逐项吻合。调用不是「存在性」层面通过——`build_seed()`、两个 CLI `--check`、527 条用例与 27 项 HTTP 断言都是**执行过的**。

## 4 缺陷表

| 编号 | 严重级(P0/P1/P2/P3) | 功能模块 | 复现步骤 | 期望行为 | 实际行为 | 关联验收项 | 检测命令 | 通过判据 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| O-1 | P3 | 题库数据（子集口径） | 运行 `python -X utf8 logs/teamflow/tf-mvyisvii-93ivpi/scripts/qa_r13_data_check.py`，看 `[info]` 分语言行 | 若按语言/方向筛选视为独立试卷，则子集也应接近均衡（单选 20%–32%、判断 40%–60%） | 整库达标但子集漂移：单选 A 占比 python 36.1%、js 38.7%、vue3 9.4%；判断 A 占比 go 70.6%、js/vue3 16.7%；python 卷「全选 A」确定性得分 40.7%（整库 30.7%、旧基线 58.6%） | TECH-CHANGE §6 仅定义全局口径（子集未纳入 AC） | `python -X utf8 logs/teamflow/tf-mvyisvii-93ivpi/scripts/qa_r13_data_check.py` | 不阻断；若要纳入，须使每个语言子集单选 A ∈[0.20,0.32]、判断 A ∈[0.40,0.60]（建议在门禁按 language 分组复算并让轮转分配按语言分桶） |
| O-2 | P3 | 文档一致性 | 对比 `TECH-CHANGE.md` §3.1「实测 A 138 / B 138 / C 138 / D 137」与落盘 seed / `SHUFFLE-REPORT.md` §2 | 技术变更单数字与最终落盘一致 | 落盘为 **139/138/137/137**（差 1 道）；报表与 `memory.md` 已写 139，仅 TECH-CHANGE 未同步 | 交付物数字自洽 | - | 不阻断；改 TECH-CHANGE §3.1 为 139/138/137/137（历史夹不可改，但本夹 TECH-CHANGE 属本轮产物可更新） |
| O-3 | P3 | 题库数据（覆盖度） | 读 `SHUFFLE-REPORT.md` §7 | 全部题目都参与均衡 | 106 道（19%）解析判角不可靠 → 按安全优先保持原序，其自身 A 偏置仍在（整体由其余题补偿） | TECH-CHANGE §3.2 已显式接受 | - | 不阻断；建议另立「逐题人工改写解析」需求后纳入 |
| O-4 | P3 | 运维（存量库） | 用 r12 基线建的 `app.db` 启动 r13 → `check_r13_db_not_refreshed.py` | 线上练习的偏置也被修复 | `import_seed` 为 `ON CONFLICT DO NOTHING`：存量库 0 新增、779 行仍是 r12 的选项顺序/key（库内自洽、历史 attempts 不错位） | TECH-CHANGE §4/§7；memory.md r13 收口① | - | 不阻断（已验收为已知限制）；若要线上生效须另立需求改 `repository.py` |

**未发现 P0/P1/P2 缺陷。**

## 5 人工补测清单（环境限制，非交付缺陷）

| # | 项目 | 验收判据 | 方法/工具 |
| --- | --- | --- | --- |
| M1 | 练习页渲染顺序与落盘 seed 一致（可见变化：选项顺序/字母标签、29 道判断题否定式题面） | 抽 3 题（含 1 道翻转判断题、1 道多选）与 `backend/app/seed/questions.json` 对照，选项文本顺序与字母标签一致 | Chrome + DevTools（沙箱内浏览器不可启动，本次以 HTTP 契约逐题比对 20/20 替代） |
| M2 | 判分/解析/错题本 UI 无回归（本轮零前端改动） | 答对/答错各 1 题，对错标记、正确答案、解析折叠、错题本列表正常 | Chrome（390px + 桌面各一遍） |
| M3 | 存量线上库仍显示旧顺序（O-4） | 产品确认是否接受「新建库生效、存量库保留」 | 产品/运维评审 |

## 6 复跑命令与证据

```bash
python -X utf8 logs/teamflow/tf-mvyisvii-93ivpi/scripts/qa_r13_data_check.py   # 40 项，RESULT PASS
python -X utf8 logs/teamflow/tf-mvyisvii-93ivpi/scripts/qa_r13_e2e.py --port 8157  # 27 项，RESULT PASS
cd backend && python -X utf8 -m app.services.question_merge --check            # exit 0
cd backend && python -X utf8 -m app.services.question_shuffle --check          # exit 0
cd backend && AI_API_KEY= python -X utf8 -m pytest -q -p no:cacheprovider      # 527 collected，exit 0
cd backend && R13_SEED_PATH=../logs/teamflow/tf-mvyisvii-93ivpi/probe/r13-mut-all-a.json \
  AI_API_KEY= python -X utf8 -m pytest -q -p no:cacheprovider tests/test_r13_question_shuffle.py  # 必须红
cd frontend && npm run typecheck && npm run lint && npx vitest run && npm run build
```

关键证据：seed **728780 字节**、`sha256=fdb367116abedb9e…`（两次重算完全相同，确定性）；`apply(HEAD 基线)+dumps()` 逐字节复现磁盘 → 单序列化/单写入者成立；`/health` 200 且 `ai_configured=false`（零 AI 主路径）。

## 7 验收结论

**可验收。** 全局口径达成（单选 25%/判断 50%）、605 道选择题内容零漂移、29 条极性改写逐条事实正确、解析双校验 406 处零违规、两条 CLI 幂等 0 差异、527 用例全绿（≥522 地板）、前端四关卡全过；架构与蓝图逐项一致（模块抽出/唯一接线/单写入者/惰性导入/运行时零导入/常量迁移/门禁反向断言）。4 条 P3 观察（子集偏置、TECH-CHANGE 数字差 1、106 题保持原序、存量库未刷新）不阻断，其中子集偏置建议后续按语言分桶扩展门禁。
