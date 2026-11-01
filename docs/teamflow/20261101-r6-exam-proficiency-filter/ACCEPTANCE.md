# r6 · 模拟笔试熟练度过滤 —— 产品验收报告

- 任务夹：`docs/teamflow/20261101-r6-exam-proficiency-filter/`｜分支：`feat/dev-skill-coach`（原地，未提交）
- 验收对象：题库入 SQLite + 四维标签、熟练度滑动窗口、组卷过滤与 6 层兜底、随机与近 3 卷去重、一行透明度文案
- 验收依据：PRD §7（14 条 AC，P0 12 / P1 2）、TECHNICAL 蓝图、QA-REPORT（第 2 轮，可验收）
- 验收方式：**不采信任何一方自报**——全量门禁亲自复跑 + 另写一份与 dev/QA 无关的独立检查器（自带判定逻辑）复核 AC 真值，并对架构蓝图做 M3 结构核对
- 日期：2026-11-01｜环境：Windows / Python 3.13 / Node 22

## 1. 结论

**✅ 通过。** 14 条 AC 全部达成，其中 12 条 P0 有可复核的执行证据；蓝图抽取（`question_bank` / `proficiency` / `exam_selector` 三模块）按计划落地、`exam.py` 退回 294 行编排、关键逻辑单源且无重复实现；门禁 204 pytest / 72 vitest / typecheck 0 / lint 0 error / build 全绿，`/health` 200。剩余 3 条 P3 工艺观察与 2 类环境受限人工补测项不阻断。

## 2. 门禁复跑（本阶段亲自执行，非转抄）

| # | 命令 | 退出码 | 实测 |
|---|---|---|---|
| G1 | `cd backend && python -m pytest -p no:cacheprovider -q` | 0 | **204 passed / 0 failed**（基线 140，只增不减）|
| G2 | `cd frontend && npm run typecheck` | 0 | 0 error |
| G3 | `cd frontend && npm run lint` | 0 | 0 error / 28 warning（预算 ≤28，恰用满）|
| G4 | `cd frontend && npm test` | 0 | 5 files / **72 passed**（基线 65）|
| G5 | `cd frontend && npm run build` | 0 | built 1.21s，index 259.02 kB / gzip 84.99 |
| G6 | `/health`（TestClient 启动路径） | 200 | `{"status":"ok","version":"0.1.0","ai_configured":false,"db":"sqlite"}` |

共享检查器（沿用本 run 既有 checker，未重建）：`check_r6_contract.py` **13/13**、`check_qa_r6_functional.py` **130/0**、`check_qa_r6_filtered_semantics.py` **54/0**、`check_qa_r6_gate_mutation.py` **8/0**、`check_qa_r6_ui.cjs` **17/0**、`check_t5_notice_render.cjs` **7 档 PASS**。

## 3. 独立复核（本轮新增，`scripts/check_acc_r6_independent.py` 94/94）

不 import dev/QA 的 checker，自带判定逻辑重算 AC 真值：

| AC | 独立手法 | 结果 |
|---|---|---|
| AC-2 | **直接读 `seed/questions.json`**（不经 DB、不经 rules 常量）重算分布 | 80 题、四方向 20×4、kind 48/20/12、difficulty 三档非空且 challenge=8、essentiality 三档非空、每方向 must_know∈[4,10]、must_know 覆盖 ≥2 kind、TECHNICAL 含 id 级映射（80/80 可寻）与 L1–L6 阶梯表 |
| AC-1 | 启动两次 + 脚本导入两次，独立 `sqlite3` 计数 | 首启 **questions 80 / essentiality 非空 80**；二次启动仍 80；`import_seed()` 两次均新增 **0**；7 张表 + `UNIQUE(question_id,run_id)` + 两索引在位；响应无 `answer` |
| AC-1/AC-3 | AST 级扫描全部 `app/**.py` | `CREATE TABLE/INDEX` 仅 `db.py`；`INSERT/SELECT/UPDATE/DELETE` 仅 `repository.py`；闭集常量仅 `rules.py`（`exam_selector.PAPER_STAGES = rules.PAPER_STAGES` 为别名非第二份定义）；`Literal[` 仅 `rules.py`/`schemas.py`；`types.ts` 有 `filtered_count: number` 与两组闭集 |
| AC-5 | **自实现窗口谓词**（`now-30d` 含边界、窗口内答对 ≥2 且末次正确）与交付 `proficiency.evaluate` 逐档比对 8 档 | 0 次 / 1 次 / 2 次命中 / 2 次末次错 / 两次都在 31 天前 / **恰好 30 天边界** / 1 次窗口内+1 次超窗 / 乱序输入 —— 8/8 与自算一致；`window_start` 边界精确；注入 2026 年 `now` 结论与真实时钟无关（纯函数）；服务层无 `= 30 / days=30` 散落魔数，阈值经 `settings.proficiency_*` 消费 |
| AC-6 | 注入的熟练题**刻意选 `must_know`** | 5 次出卷均不含（stage=L1），证明必备题不豁免 |
| AC-7 | 独立 `repository.insert_attempts()` 注入「30 天内答对 2 次、末次正确」后连续 5 次出卷；再把作答时间改到 31 天前 | 5/5 卷面不含且 stage=L1；超窗后 `proficient_ids` 不再含该题，8 卷内**回流可考** |
| AC-8 | 逐卷核对 payload + 结构断言 | 5+4+1 卷全部 HTTP **200**、10–12 题、客观 ≥8、挑战 ≤20%、方向 ≥2、`stage∈L1..L6`、payload 记 `stage/filtered_count/backfill` |
| AC-9 | 连续 4 卷 | 两两不相同；**第 4 卷与前 3 卷题 id 交集 = ∅**；每卷结构恒定（随机未破坏闸门）|
| AC-12 | 独立按公式重算 `N = |熟练∩可用| − |熟练∩本卷|` 并与响应/payload 双向比对 | 逐卷自洽（含 L2 极值口径正确扣除回流题）|
| AC-4 | 真实提交 + 重复提交 | 事件数 = 客观题数、无 `text` 题事件、running 卷零事件；重复提交 400 且零新增 |
| AC-13 | 未知画像请求 | `404 {"error":{"code":"NOT_FOUND","message":"找不到该画像，请先上传简历生成画像","retryable":false}}`——中文、无路径/堆栈 |

## 4. 架构一致性核对（M3 · 强制门）

| 检查项 | 结论 |
|---|---|
| 蓝图模块抽取 | `question_bank.py`(141) / `proficiency.py`(172) / `exam_selector.py`(416) 三模块按蓝图存在，成员（`SEED_PATH`/`load_seed`/`import_seed`/`ensure_seeded`/`load_questions`、`Attempt`/`Proficiency`/`window_start`/`evaluate`/`to_attempts`/`attempts_by_question`/`proficient_ids`、`PAPER_STAGES`/`Paper`/`rank_pool`/`build_paper`/`select_paper`）**缺失 0** |
| 编排层收口 | `exam.py` **294 行 < 400**，职责只剩编排；旧副本 `_usable`/`_compose`/`_ordered`/`_affinity`/`_load_questions`/`SEED_PATH`/`DIRECTION_KEYWORDS` 已删净（逐个断言）|
| 单源无重复实现 | `_usable`/`build_paper`/`select_paper`/`import_seed`/`proficient_ids`/`evaluate` 各 **1 处定义**；全库无第二份 `_compose`；阈值不直接读进 `exam_selector`（由编排层消费后注入）|
| 阶梯与闸门 | `L1..L6` 齐备且只在 `exam_selector`；结构闸门单一校验点；`filtered_count` 语义只在选池层定义一次，前端只用 `filteredNotice()` 解读 |
| 分层约束 | DDL 只在 `db.py`、SQL 只在 `repository.py`、路由未改（`filtered_count` 由 `ExamRun` 模型自带）—— 与 AGENTS.md §4 硬约束一致 |
| 结论 | **未见偏离蓝图、未见重复实现、未见既有结构破损**，无需架构返工。 |

## 5. 逐条验收判定

| AC | 优先级 | 判定 | 关键证据 |
|---|---|---|---|
| AC-1 题库入库 + 幂等迁移 | P0 | 通过 | §3 行 2（80/80、二次启动 80、导入新增 0、DDL/SQL 单源、无 answer）|
| AC-2 标签齐全可复现 | P0 | 通过 | §3 行 1（seed 真值独立重算全部成立 + TECHNICAL 映射表）|
| AC-3 闭集单源 + 双侧契约 | P0 | 通过 | §3 行 3 + typecheck 0 + 无裸色值门禁（pytest 内）|
| AC-4 熟练度写入零副作用 | P0 | 通过 | §3 行 10 + `test_exam_filter.py` 异常路径用例 |
| AC-5 滑动窗口逐档 | P0 | 通过 | §3 行 4（8 档自算比对 + 30 天边界 + 阈值单源）|
| AC-6 必备题不豁免 | P0 | 通过 | §3 行 5（注入的恰是 must_know）|
| AC-7 过滤生效与回流 | P0 | 通过 | §3 行 6（5 卷不含 + 超窗回流）|
| AC-8 6 层兜底绝不 400 | P0 | 通过 | §3 行 7 + QA 极值（68 道客观题全熟练 → L2，N=60 自洽）|
| AC-9 随机 + 近 3 卷去重 | P0 | 通过 | §3 行 8 + functional 130/0（桶序跨种子恒定、桶内确实洗牌）|
| AC-10 既有能力零回归 | P0 | 通过 | pytest 204（含 r5 面试、r3 时间线、润色、报告）+ 判分纯本地 |
| AC-11 门禁只增不减 | P0 | 通过 | G1–G6 全绿，新增用例覆盖迁移/标签/窗口/过滤/6 层/随机/契约 |
| AC-13 错误形态与降级 | P0 | 通过 | §3 行 11 + 空库自动种子（不会出现空池白屏）+ 旧 payload 默认值 |
| AC-12 一行透明度文案 | P1 | 通过 | `filteredNotice()` 唯一出处、`filtered_count>0` 才挂载（0/NaN/负数/null 零挂载 7 档）、复用 `.sc-meta-line`+`Chip`、无新 CSS 类/token、17/0 + 7 档 PASS |
| AC-14 文档同步 | P1 | 通过 | ARCHITECTURE §数据层：「`questions` r6 题库承载 11 列 / seed JSON 退为唯一导入源」；memory.md 只替换数据落盘基线行 + 新增「笔试组卷与熟练度约定」一行，无 changelog；TECHNICAL 含映射表与阶梯表 |

**合计：14/14 通过（P0 12/12，P1 2/2）。无 P0/P1/P2 开放缺陷。**

## 6. 遗留与人工补测（不阻断）

| 项 | 性质 | 说明 |
|---|---|---|
| D-7 / D-8 / D-9（P3）| 工艺观察 | 信息行无 tooltip 解释「怎样才能回流」；结果面板不复显过滤事实；L2 兜底时文案不提示「另有 N 道因结构被重新纳入」。N 的语义本身正确，不影响正确性，已登记 memory 待办 |
| `python -m ruff check app tests` | 环境受限 | 本机 `No module named ruff`，需开发机复跑（期望 0 error）；**未记为通过** |
| 390px 真实视口 / 键盘走查 / 屏幕阅读器 | 环境受限 | 沙箱浏览器不可启动；实现零新增 CSS 类、复用既有 `.sc-meta-line` 与 `Chip`（`Chip` 不传 `onClick` → `<span>` 不进 tab 序，源码已核），布局风险极低，仍需真机确认一次 |

## 7. 验收意见

1. 本轮把「过滤」做成了有据可查的数据管道，且**没有把过滤变成新的故障源**——六层阶梯在极值下仍返回 200 且结构恒定，`filtered_count` 的净过滤语义在极值下也自洽（不会出现「卷面明明有熟练题却报全量」的文案说谎），PRD §4 的四条反面目标均未出现。
2. 工艺上值得肯定的一点：dev 的静态门禁被 QA 用**故障注入**证明不是空转门禁（`check_qa_r6_gate_mutation.py` 8/8），这比「用例全绿」更有说服力；本阶段又用一份独立检查器规避了「同一份错误断言自我印证」的风险。
3. 下一轮若要继续提升可解释性，优先级建议：D-9（兜底回流的可见说明）> D-7（回流规则入口）> D-8，三者可合并为一个「熟练度说明」小需求。

验收结论：✅ 通过
