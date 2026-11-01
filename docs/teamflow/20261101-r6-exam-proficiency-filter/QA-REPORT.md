# r6 · 模拟笔试熟练度过滤 —— QA 复测报告（第 2 轮）

- 任务夹：`docs/teamflow/20261101-r6-exam-proficiency-filter/`｜分支：`feat/dev-skill-coach`（原地，未提交）
- 测试对象：题库入 SQLite + 四维标签、熟练度滑动窗口、过滤与 6 层兜底、随机与近 3 卷去重、一行透明度文案
- 轮次性质：**修复后复测**（上轮打回 3×P1 + 2×P2；本轮先按原文逐条复跑上轮缺陷的检测命令，再补上轮未覆盖的两个面）
- 测试日期：2026-11-01｜环境：Windows / Python 3.13 / Node 22；`pytest` + FastAPI `TestClient`（HTTP 层）+ 真实 `uvicorn` 启动路径；前端 vitest + esbuild SSR（沙箱内**无法启动真实浏览器**，见 §5）
- **结论：可验收。** 上轮 6 条缺陷（D-1~D-6）逐条按原文检测命令复跑全部关闭，无 P0/P1/P2 开放项；3 条 P3 工艺观察不阻塞。全量门禁 pytest 204/0、vitest 72、typecheck 0、lint 0 error/28 warn、build ok、`/health` 200。

## 1. 缺陷行原文复跑（复测第一优先）

| 上轮缺陷 | round-1 级 | 本轮判定 | 检测命令（原文照跑） | 实测输出 |
|---|---|---|---|---|
| D-1 门禁路径缺 `backend/` 前缀 | P1 | **已关闭** | `cd backend && python -m pytest -p no:cacheprovider -q tests/test_engineering_gates.py -k "closed_sets or direction_literals or contract_mirror"` | exit 0，`3 passed` |
| D-2 `_ordered` 断言误伤 `proficiency.py` | P1 | **已关闭** | `cd backend && python -m pytest -p no:cacheprovider -q tests/test_engineering_gates.py -k single_usable` | exit 0，`1 passed` |
| D-3 缺 `test_question_bank.py` | P1 | **已关闭** | `cd backend && python -m pytest -p no:cacheprovider -q tests/test_question_bank.py` | exit 0，`14 passed`（幂等 80/0 覆盖、双口径难度、essentiality 20/20/40、每方向三档齐） |
| D-4 闭集字面量二次出现 | P2 | **已关闭** | `cd backend && grep -nE "^_(TEXT_KIND\|MUST_KNOW) = \"" app/services/exam_selector.py` | 无匹配（exit 1）；闭集成员已收敛到 `rules.QUESTION_KINDS/TEXT_KIND/MUST_KNOW`，`exam_selector` 全部改为 `rules.*` 引用 |
| D-5 TECHNICAL 难度口径 48/12/8 vs 库 60/12/8 | P2 | **已关闭** | `cd backend && python -X utf8 ../logs/teamflow/tf-mvxehsn0-8z1p4e/scripts/check_r6_contract.py` | exit 0，`13/13 PASS`；C06 同时断言全库 60/12/8 与客观题 48/12/8 双口径 |
| D-6 dev 自检 `check_t5_notice_render.cjs` 不可复跑 | P3 | **已关闭** | `cd frontend && NODE_PATH=$PWD/node_modules node ../logs/teamflow/tf-mvxehsn0-8z1p4e/scripts/check_t5_notice_render.cjs` | exit 0，`PASS（7 档）`（上轮 `MODULE_NOT_FOUND`） |

**类级命中数复算（独立扫描，不复用门禁本身）**：D-1 类（`REPO_ROOT / "app/…"` 缺前缀）`0` 处；D-2 类（全 `app/` 范围命名禁令 `assert not defs.get(...)`）`0` 处；D-3 类（文件缺失）→ 14 例可收集；D-5 类（口径混写）→ 双口径均落文档与自检。四次扫描与修复轮自报一致，**无分歧**。

## 2. 全量门禁与共享检查器复跑

| # | 命令 | 退出码 | 结果 |
|---|---|---|---|
| G1 | `cd backend && python -m pytest -p no:cacheprovider -q` | 0 | **204 passed / 0 failed**（上轮 184 passed / 4 failed） |
| G2 | `cd frontend && npm run typecheck` | 0 | 0 error |
| G3 | `cd frontend && npm run lint` | 0 | 0 error / 28 warning（预算 ≤28，恰用满） |
| G4 | `cd frontend && npm test` | 0 | 5 files / **72 passed** |
| G5 | `cd frontend && npm run build` | 0 | built in 1.21s（index 259.02 kB / gzip 84.99） |
| G6 | `cd backend && DB_PATH=tests/.tmp/qa-boot-r6b.db AI_API_KEY= python -m uvicorn app.main:app --port 8124` → `curl /health` | 0 | `{"status":"ok","version":"0.1.0","ai_configured":false,"db":"sqlite"}`；首启落库 **questions 80 / essentiality 非空 80 / attempts 0**，7 张表，`UNIQUE(question_id,run_id)` 在位 |
| G7 | `cd backend && python -m ruff check app tests` | — | **环境限制**：`No module named ruff`（非交付缺陷，§5） |
| G8 | `check_qa_r6_functional.py`（上轮回归契约） | 0 | `QA_R6_FUNCTIONAL: PASS` **130/0** |
| G9 | `check_qa_r6_ui.cjs`（上轮回归契约） | 0 | `QA_R6_UI: PASS` **17/0** |
| G10 | `check_r6_contract.py`（dev 契约自检） | 0 | **13/13** |
| G11 | `check_gates_selfcheck.py` | 0 | **7/7** |
| G12 | `check_t1_data_layer.py` / `check_t3_proficiency_e2e.py` / `check_t4_question_bank.py` / `check_t7_orchestration.py` | 0 | **57/0** ｜ **24/24** ｜ **41/0** ｜ **47/0**（上轮 T7 有 1 skip，现 0 skip） |

## 3. 本轮新增覆盖（上轮未覆盖的面 + 为什么）

上轮已覆盖 AC 功能面与 UI 结构面，但有两类「全绿也不代表对」的面没测：

| 新增面 | 上轮为何没覆盖 | 本轮探针 | 结果 |
|---|---|---|---|
| 新增门禁**是否真的会失败**（非空转门禁） | 上轮只确认新门禁用例"通过"，没有任何注入失败样本的证明；空转断言同样全绿 | `scripts/check_qa_r6_gate_mutation.py`（内存替换 `R6_TOUCHED` / `APP_DIR` / `_python_defs` 注入故障样本，不改交付文件） | **8/8 PASS**：缺前缀路径→失败并点名；`MUST_KNOW="must_know"` 重绑→失败并点名文件；引用常量/payload 键名→不误报；`exam.py` 复活 `_ordered` →失败；`_usable` 第二份→失败；合规样本→通过 |
| `filtered_count` 的**语义**（不是存在性） | 上轮只断言字段存在、payload 有 stage/filtered_count；若 N 算成「熟练总数」或窗口失效，文案会与卷面自相矛盾而全部断言仍绿 | `scripts/check_qa_r6_filtered_semantics.py`：从原始作答事件**独立重算**熟练集合（不复用 `proficiency.evaluate` / `_filtered_count`），逐卷比对 N，并跑到 L2 兜底极值 | **54/54 PASS**（详见下表） |

`check_qa_r6_filtered_semantics.py` 关键断言（HTTP 端到端，真实 `TestClient`）：

| 场景 | 断言 | 实测 |
|---|---|---|
| 注入 6 题熟练（窗口内 2 次答对、最近正确） | 独立实现熟练集合 == 交付 `proficiency.proficient_ids()` | 一致（6 道） |
| 连续 4 卷 | `filtered_count == \|熟练∩可用\| − \|熟练∩本卷\|`（逐卷） | 每卷 N=6，公式成立；L1 卷面不含熟练题 |
| 全库 68 道客观题全部熟练（L2 兜底极值） | N 必须减去回流进卷面的题，**不得等于熟练总数 68** | N=60 = 68 − 8，stage=L2，HTTP 200，结构恒定（10–12/客观 ≥8/挑战 ≤20%/方向 ≥2） |
| 逐卷 | 响应无 `answer`；payload `filtered_count` 与响应一致；`stage ∈ L1..L6` | 全部成立 |

> 这一面正是 PRD 反面目标「兜底把过滤变成噪音」的可观察点：极值下若报 68 就是文案说谎（卷面明明有 8 道熟练题），实现口径正确。

## 4. 逐验收项结果（本轮）

| AC | 结论 | 证据 |
|---|---|---|
| AC-1 题库入库 + 幂等迁移 | 通过 | G6 首启 80 行、essentiality 80/80；`test_question_bank.py` 两次导入恒 80、二次新增 0、改行不覆盖；`/api/exams` 响应无 `answer` |
| AC-2 标签齐全可复现 | 通过 | 独立复核 seed：kind 48/20/12；difficulty 全库 60/12/8、客观题 48/12/8；essentiality 20/20/40；四方向各 20；每方向 must_know 5 ∈[4,10] 且覆盖 single+text |
| AC-3 闭集单一出处 + 双侧契约 | 通过 | D-4 已收敛到 `rules.py`；`rules.*` == `schemas` Literal 逐字；`types.ts` 有 `filtered_count: number` 与两闭集；typecheck 0；无裸色值 |
| AC-4 熟练度写入零副作用 | 通过 | 提交后事件数 == 客观题数、一题一行；重复提交 400 且零新增；running 卷 0 条（G8 + G12 T7 47/0） |
| AC-5 滑动窗口逐档 | 通过 | `check_t3_proficiency_e2e.py` 24/24（含 30 天边界）；阈值只在 `config.Settings`（30/2/3）；env 覆盖生效 |
| AC-6 必备题不豁免 | 通过 | G8；另 §3 极端场景 L2 回流在卷面中可见 8 道熟练题，N 正确扣除 |
| AC-7 过滤生效与回流 | 通过 | §3 探针：熟练后 L1 卷面不含；篡改超窗 → 回流（G8） |
| AC-8 6 层兜底绝不因过滤 400 | 通过 | §3 极值 2 卷 HTTP 200 + 结构恒定 + stage=L2；G8 两类极端场景 |
| AC-9 随机 + 近 3 卷去重 | 通过 | G8（连续 4 卷互不相同、第 4 卷与前三卷交集空、同种子复现、桶序列恒定） |
| AC-10 既有能力零回归 | 通过 | G1 204 passed（r5 面试 / r3 时间线 / 润色 / 报告）；判分纯本地；G4/G5 全绿 |
| AC-11 门禁只增不减 | **通过** | pytest 204 ≥140 且 0 failed；typecheck 0；lint 0/28；vitest 72 ≥65；build ok；`/health` 200；新增用例覆盖迁移/标签/窗口/过滤/6 层/随机/契约 |
| AC-12 一行透明度文案 | 通过 | G9 17/0；`filteredNotice()` 唯一出处；`filteredNotice(run.filtered_count)` 单一读取点；`notice ? … : null` 零挂载；复用 `.sc-meta-line`+`Chip`，无新 CSS 类/token；§3 证明 N 的数字与卷面自洽 |
| AC-13 错误形态与降级 | 通过 | 未知画像 404 统一 `{error:{code,message,retryable}}` 中文无路径；配置缺省 30/2/3 兜底；旧 payload 读侧默认值；无「因过滤」400 |
| AC-14 文档同步 | 通过 | ARCHITECTURE §3.4 七表；memory.md 只替换同主题行；TECHNICAL §2.4 双口径并行（D-5 已修） |

## 5. 架构与接口一致性核对（M3 / 0a）

- **蓝图遵循**：`question_bank.py / proficiency.py / exam_selector.py` 三模块按蓝图抽出、职责单一；`exam.py` **294 行**（<400）退回编排；旧副本 `_usable / _compose / _ordered / _affinity / _load_questions / SEED_PATH` 在 `exam.py` 已删净。
- **单源实证**（独立扫描）：`CREATE TABLE` 仅 `app/db.py`；SQL 仅 `app/repository.py`；`_usable` 定义 1 处（question_bank）、`build_paper` 1 处（exam_selector）、`_compose` 0 处、`_ordered` 1 处（`proficiency.py` 的作答排序，合法助手 —— 正是 D-2 不得误伤的那一个）；闭集只在 `rules.py`；三阈值只在 `config.Settings`（`exam_selector` 内 0 处 `get_settings`，阈值消费集中在 `exam.py`）。
- **接口一致性（静态）**：按蓝图接口清单逐一核对 35 个跨模块成员（`proficiency.Attempt/Proficiency/window_start/evaluate/to_attempts/attempts_by_question/proficient_ids`、`question_bank.SEED_PATH/load_seed/import_seed/ensure_seeded/load_questions`、`exam_selector.PAPER_STAGES/Paper/rank_pool/build_paper/select_paper`、`repository.insert_question/list_questions/count_questions/insert_attempts/list_attempts/list_recent_exam_question_ids`、`rules.*` 8 项）→ **缺失 0**。(`Settings` 三阈值按 pydantic 语义经 `Settings.model_fields` 与实例值核对 = 30/2/3；`hasattr(Settings, ...)` 为 False 是 pydantic 类属性机制，非缺陷；已用实例化复核排除误报。)
- **签名逐条对齐蓝图**：`create_run(profile_id, *, now=None, rng=None) -> ExamRun`、`select_paper(questions, profile, *, proficient, recent, rng=None) -> Paper|None`、`insert_attempts(rows) -> int`、`list_recent_exam_question_ids(limit) -> list[set[str]]`、`proficient_ids(now=None) -> set[str]`；`rules.PAPER_STAGES == exam_selector.PAPER_STAGES`（True）；`ExamRun` 字段 `{run_id, questions, filtered_count}`，默认 0。
- **重复实现/抽象缺失**：未见。`exam_selector` 的 `PAPER_STAGES` 为 `rules` 的就近重导出（同一元组，非第二份定义）。
- **提交面卫生（0c）**：`git status --porcelain` 无 `node_modules/ dist/ __pycache__/ *.db .env logs/` 等噪音；`.gitignore` 覆盖 `node_modules/ dist/ .env *.db *.db-wal/shm/journal __pycache__/ .venv/ .pytest_cache/ .ruff_cache/ coverage/ backend/tests/.tmp/ logs/teamflow/`；无 `*.pyc` 被跟踪。

## 6. 缺陷表（仅列复测后仍开放项）

| 编号 | 严重级(P0/P1/P2/P3) | 功能模块 | 复现步骤 | 期望行为 | 实际行为 | 关联验收项 | 检测命令 | 通过判据 |
|---|---|---|---|---|---|---|---|---|
| D-7 | P3 | 工艺观察（信息行） | 作答态查看 `[熟练过滤] 本次已过滤 N 道你已熟练掌握的题` | 用户能知道「为什么被过滤 / 怎样让题回流」 | 行内无 tooltip/说明入口，30 天 / 答对 2 次 / 近 3 卷的规则只写在文档；信息缺口，不影响正确性 | AC-12（工艺） | - | - |
| D-8 | P3 | 工艺观察（结果面板） | 提交后查看结果面板 | 复核时可回看本卷为何与前几卷不同 | 该事实只在作答/提交态出现，提交后消失（DESIGN 明确选择结果面板不重复，故仅观察） | AC-12（工艺） | - | - |
| D-9 | P3 | 工艺观察（兜底回流不可见） | 全库客观题熟练（L2 兜底）后出卷 | 用户能理解「为什么卷面里仍出现我已经熟练的题」 | 文案只说「已过滤 60 道」，未提示另有 8 道因保持卷面结构被重新纳入；N 的语义本身正确、无自相矛盾 | AC-8 / AC-12（工艺） | - | - |

**无 P0 / P1 / P2 开放缺陷。**

## 7. 人工补测清单（环境限制，非交付缺陷）

| 项 | 原因 | 方法/工具 |
|---|---|---|
| `python -m ruff check app tests` | 本机 `No module named ruff`（既有环境阻塞） | 开发机执行，期望 0 error |
| 信息行真实可见性与 390px 无横向滚动 | 沙箱内浏览器不可启动（crashpad 需 `PROCESS_ALL_ACCESS`，`--no-sandbox` 无效）；项目无 jsdom/RTL、无布局引擎 | 浏览器/真机 390px 打开笔试页：断言 `.sc-meta-line` 含「本次已过滤 N 道…」、`documentElement.scrollWidth <= clientWidth` |
| 键盘可达性与焦点顺序 | 同上 | Tab 走查；`Chip` 不传 `onClick` → 渲染为 `<span>` 不进 tab 序（源码已确认） |
| 屏幕阅读器播报 | 辅助技术不可用 | NVDA/VoiceOver 复核信息行 |
| 悬停/按压/焦点视觉反馈、动效观感 | 需真实渲染 | 浏览器走查（对应 §6 的 P3 观察） |

## 8. 统计与结论

- 自动化断言合计：**204（pytest）+ 130 + 17 + 13 + 7 + 57 + 24 + 41 + 47 + 8 + 54 + 72（vitest）= 674 条**，失败 0。
- 上轮 6 条缺陷全部关闭；本轮新增 2 个覆盖面（门禁非空转、`filtered_count` 语义极值），未发现新的 P0/P1/P2；新增 1 条 P3 观察（D-9）。
- **判定：可验收。** 上轮打回理由（AC-11「0 failed」不成立、AC-1/AC-2 证据链缺口、闭集与口径漂移）全部消除，蓝图抽出与单源约束经独立扫描确认；剩余 ruff 与浏览器类项目为环境限制，列入 §7 人工补测。
