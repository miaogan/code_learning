# r12 题库素材合并 · QA 报告（复测第 2 轮）

- 需求：把 `docs/question-bank-staging/` 下 519 道外部素材合并进现有题库（归一化 / 去重 / 标来源），260 → 779，练习与笔试零回归
- 任务夹：`docs/teamflow/20261102-r12-question-bank-merge/`　基线：`docs/teamflow/20261101-r11-practice-question-bank/`
- 测试分支：`feat/dev-skill-coach`（未提交；交付面 5 修改 + 6 新增，其余为本任务夹文档）
- 本轮性质：**修复轮复测**——上轮 1 条 P2（D-1 存量不可变无真门禁）+ 5 条 P3；本轮核验修复面并回归全链路
- 结论：**✅ 通过（可验收）**：D-1、D-3 已修复且有可失败门禁/可复现证据；余 4 条 P3 观察不阻断

## 1 范围与环境

| 面 | 覆盖 |
|---|---|
| 离线工具 | `question_merge --check/--write/--rollback`、幂等、字节级序列化、回滚（含未初始化库 UX） |
| 数据 | 779 条总量 / 5 维分布 / 结构合规 / 去重 / 来源枚举 / 存量 260 行冻结 |
| 运行时 | `/health`、练习四端点、笔试 779 池出卷+提交 |
| 门禁 | 后端全量 pytest、前端 typecheck/lint/vitest/build、r12 三条工程门禁 |
| 修复复核 | D-1 的 sha256 冻结门禁是否真会红、D-3 的中文错误与不建空库 |

环境限制（非交付缺陷）：①`python -m ruff` 本机 `No module named ruff`，未跑；②沙箱不能启动 Chromium，本需求前端零改动（`git status` 无 `frontend/` 条目），UI 用真实 HTTP 实跑替代；③真实 390px 视口走查列入人工补测。

## 2 交付面与架构核查

改动面与 TECH-CHANGE 蓝图一致（数据扩容 + 离线工具，运行时链路零改动）：`question_merge.py`（新增离线工具）+ `repository.py`（唯一 SQL 出口，零删除行）+ `seed/questions.json`（+519 行，纯插入）+ 3 个测试文件 + NOTICE + 工具报表 + 本任务夹文档。

| 核查项 | 结论 |
|---|---|
| 蓝图接口逐条落地 | 52/52 静态检查通过（`check_qa_r12_interface.py`）：10 个常量 + 12 个函数签名与签名表一致，`R12_TOUCHED` 逐条存在 |
| 跨模块调用目标 | 调用 `rules.{OBJECTIVE_KINDS,DIFFICULTIES,DIRECTIONS,LANGUAGES,LANGUAGE_DIRECTION,direction_of_language,essentiality_of}`、`question_bank.{SEED_PATH,load_seed}`、`repository.delete_questions_by_source` 全部真实存在；无幽灵调用 |
| 本轮新增符号一致性 | `RollbackUnavailable` 定义于 `question_merge.py:709`，`rollback()` 两处 `raise`、CLI `main()` 一处 `except` 捕获，测试 `tests/test_r12_question_merge.py:527` 断言 —— 定义/抛出/捕获/断言四点闭合 |
| 方向知识单一出处 | 工具内零方向表、零语言集合字面量，`rules.direction_of_language(language) or 原方向` 一条派生（r11 门禁通过） |
| 序列化单一出处 | `dumps()` 同时服务 `--write` 与 `--check`；未退化到 `json.dump(indent=2)`（测试显式反证） |
| 重复实现 | 无新增重复：`normalize_prompt`（工具）/`_normalize`（r11 测试）跨边界同口径由 `test_normalize_prompt_matches_r11_normalization` 钉住；sha 冻结常量集中一处，无第二套哈希口径 |
| `source` 不进契约 | `PracticeQuestion` / `WrongItem` / `ExamQuestion` / `types.ts` 零改动；纸面响应无 `answer`/`source` 泄漏（运行时时实测） |

无「抽象未抽取」「结构破坏」问题；P1 级架构缺陷 0 条。

## 3 用例与结果

### 3.1 修复复核（本轮重点）

| 项 | 命令 | 实测结果 |
|---|---|---|
| **D-1 修复** 存量 260 行内容级冻结 | `cd backend && python -X utf8 ../logs/teamflow/tf-mvy1bqfh-vtjllw/scripts/check_qa_r12_legacy_pin.py` | **exit 0（PASS）**：对存量 `fe-q1` 题干做**等长**改动后，`--check` 仍 exit 0（自指，设计如此），但 `pytest` exit **1** —— `test_dumps_reproduces_current_seed_bytes` 的 `R11_SEED_SHA256` 断言变红；seed 已自恢复（779 / 729832 字节 / sha256 `a88650396c219588…`） |
| 冻结常量正确 | 未篡改态跑该用例 | 绿（`R11_SEED_BYTES=192393` + `R11_SEED_SHA256=8743a8ba45231c02…` 与实际块一致） |
| **D-3 修复** 未初始化库回滚 | `cd backend && DB_PATH=tests/.tmp/qa-r12-nodb-$$.db python -X utf8 -m app.services.question_merge --rollback` | exit 1，输出中文「无法回滚：库 … 不存在或为 0 字节（尚未初始化），请先启动一次后端再回滚」；**无 Python 栈、未产生 0 字节 db 文件** |
| 回滚仍正确 | 临时库 `init_db()+ensure_seeded()` 后 `--rollback` ×2 | 779 → 删 519 → **260** → 再删 **0** → 260（存量 `'seed'` 行不受影响） |

### 3.2 静态与数据面（全绿）

| 检查 | 命令 | 结果 |
|---|---|---|
| 数据 28 项 | `…/scripts/check_qa_r12_data.py` | **28/28 PASSED**：779 条；kind 551/156/60/12；language `''294 / py86 / java84 / go74 / js46 / react45 / vue342 / css40 / html36 / ts32`；direction 423/267/56/33；difficulty 283/359/137（challenge 17.587% ≤20%）；source 20/100/379/20；存量 260 行与 `git show HEAD:…` 逐行相等、`dumps()` 复现 192393 字节 |
| 报表自证 21 项 | `…/check_qa_r12_report_claims.py` | **21/21 PASSED**：每来源计数、方向冲突 9 条、judge 重建 120 条、12 道抽检、分布行均与种子一致（非手写漂移） |
| 接口/蓝图 52 项 | `…/check_qa_r12_interface.py` | **52/52 PASSED** |
| 报告结构 | `python -X utf8 logs/teamflow/tf-mvy1bqfh-vtjllw/scripts/check_qa_r12_report_md.py` | exit 0「4 条缺陷行、表格列数一致、必需章节齐全」——本文件缺陷表逐行 9 列、严重级 ∈ {P0..P3}，「已关闭」小表单独校验 |
| 幂等 | `cd backend && python -X utf8 -m app.services.question_merge --check` | exit 0「题库 seed 与素材重算逐字节一致：可用 779 道」 |

### 3.3 运行时（779 池实跑）

服务：`cd backend && DB_PATH=tests/.tmp/qa-r12-fix.db AI_API_KEY= python -m uvicorn app.main:app --port 8152`；`curl /health` → 200 `{"status":"ok",…,"ai_configured":false}`。

| 检查 | 命令 | 结果 |
|---|---|---|
| 练习四端点 17 项 | `…/check_qa_r12_runtime.py --port 8152` | **17/17 PASSED**：九语言纸 200 且 100% 命中筛选；python 纸含 6 道 judge；judge 同题 A/B 判分互斥（True/False）并回显 `correct_answer`+`explanation`；答错入错题本；`limit=0` 全量 767 道（含新增 519 道）；非法 language 仍 422；无答案泄漏 |
| 笔试端到端 4 项 | `…/check_qa_r12_exam_e2e.py` | **4/4 PASSED**：779 库、10 卷均 ≥10 题、无答案泄漏、含 judge 11 道、提交判分 `correct 5/8`/total 62.5 |

### 3.4 门禁与回归

| 检查 | 命令 | 结果 |
|---|---|---|
| 后端全量 | `cd backend && AI_API_KEY= python -X utf8 -m pytest -p no:cacheprovider --tb=short -q` | **exit 0**，收 512 用例、0 failed / 0 error（1 skip = `test_live_profile_generation_smoke`，需 `AI_LIVE=1`，非缺陷）；上轮基线 511 → 本轮 +1（sha 冻结用例） |
| r12 定向 5 模块 | `… pytest tests/test_r12_question_merge.py tests/test_question_bank_quality.py tests/test_engineering_gates.py tests/test_exam_filter.py tests/test_r11_contract.py` | exit 0（134 例全绿） |
| 前端 typecheck | `cd frontend && npm run typecheck` | exit 0 |
| 前端 lint | `npm run lint` | exit 0（**0 error / 28 warning** ≤28） |
| 前端单测 | `npm test` | exit 0，133 passed |
| 前端构建 | `npm run build` | exit 0（dist 产出） |
| 后端 lint | `python -m ruff check app tests` | 环境缺失 `No module named ruff`（非代码失败，列入人工补测） |

### 3.5 合规与提交面卫生

- 许可：`docs/question-bank-staging/NOTICE-fe-interview.md` 含 MIT 全文 + `https://github.com/haizlin/fe-interview` 链接 + 改写说明（数据检查项实测通过）；上轮已实拉上游 LICENSE 核对，本轮数据未变，结论沿用。
- `git status --porcelain=v1 -uall`：仅 5 修改（`repository.py` / `seed/questions.json` / 3 个测试文件）+ 6 新增交付文件（`question_merge.py`、`test_r12_question_merge.py`、NOTICE、staging 4 份素材、工具报表）+ 本任务夹 3 份文档；`node_modules/`、`frontend/dist/`、`backend/tests/.tmp/`、`*.db`、`.env` 均被 `.gitignore` 覆盖（逐条 `git check-ignore -v` 命中），**无依赖/构建/缓存/密钥噪声**。
- `docs/question-bank-staging/` 仍为未跟踪目录：它是 `--check` 的可复现输入，**必须随本次交付入库**，否则换机/CI 上 seed 无法重建。

## 4 缺陷表

| 编号 | 严重级(P0/P1/P2/P3) | 功能模块 | 复现步骤 | 期望行为 | 实际行为 | 关联验收项 | 检测命令 | 通过判据 |
|---|---|---|---|---|---|---|---|---|
| D-2 | P3 | 数据质量 | 统计新增 519 题的答案位置与题干自洽性 | 正确项分布大致均衡、题干独立自洽 | judge 正确项 A 87/120=72.5%；single 正确项 A204/B137/C49/D5（A 占 52%）；45 道题干含「…最符合参考答案要点」而学员看不到该参考 | 内容质量（PRD 以 12 道抽检为门槛，结构门禁不覆盖均衡性） | `cd backend && python -X utf8 -c "import json,collections;d=[r for r in json.load(open('app/seed/questions.json',encoding='utf-8')) if r.get('source')];j=[r for r in d if r['kind']=='judge'];print(len(j),collections.Counter(r['answer'][0] for r in j),collections.Counter(r['answer'][0] for r in d if r['kind']=='single'),sum('参考答案要点' in r['prompt'] for r in d))"` | judge 接近 50/50、single 四选项各约 25%、「参考答案要点」计数 0（或产品书面接受现状） |
| D-4 | P3 | 架构/文档 | 对照蓝图 `ID_PREFIX` 与实现 | 蓝图与代码同口径 | TECH-CHANGE 仍写 `iq-NNN`，实现为 `iq380-NNN`（代码更安全，文档未回写） | 架构文档一致性 | `grep -n "iq380-" docs/teamflow/20261102-r12-question-bank-merge/TECH-CHANGE.md`（无输出） | TECH-CHANGE 补一句「实现取 `iq380-`（避开面试 `iq-N` 命名空间）」 |
| D-5 | P3 | 文档同步 | 读 `docs/teamflow/memory.md` r12 收口条目 | 已完成的 ① 标记完成 | 第 39 行仍写在办「需 dev 确认 LICENSE 后回填」，下一轮 agent 会重复调查 | 产品记忆准确性 | `grep -n "r12 两条收口" docs/teamflow/memory.md` | 该条改为「① 已完成（MIT 已核实、NOTICE 已回填）；② 阈值待用户定」 |
| D-6 | P3 | 合规留痕 | 查 01/02/03 三个来源的出处证据 | 仓库内有 per-source 来源记录 | 仅 TECH-CHANGE §3.5 一句「自建或本地生成」，`docs/question-bank-staging/` 只有 fe-interview 的 NOTICE | 团队约定「题库只用自建或 MIT 源」 | `ls docs/question-bank-staging/ \| grep -c PROVENANCE` | 补 `PROVENANCE.md`（三来源：自建/AI 生成 + 方式 + 日期），或书面记录「内部自建，无外部许可义务」 |

**已关闭（本轮实测）**

| 编号 | 上轮级别 | 状态 | 关闭证据 |
|---|---|---|---|
| D-1 | P2 | **已修复** | 探针 `check_qa_r12_legacy_pin.py` exit 0：等长篡改存量行后 `pytest` 变红（sha256 冻结常量 `R11_SEED_SHA256`）；未篡改态全量 512 用例绿 |
| D-3 | P3 | **已修复** | 未初始化库回滚输出中文原因、exit 1、不建 0 字节库文件；`RollbackUnavailable` 有单测（`tests/test_r12_question_merge.py:527`） |

未发现 P0 / P1 缺陷。

## 5 人工补测清单（环境限制，非交付缺陷）

| 项 | 方法 | 工具 | 判据 |
|---|---|---|---|
| 练习页 390px 真实视口 + 键盘走查（题量 3 倍后长选项换行/滚动） | 真机或桌面浏览器 390×844 打开 `/practice`，选 20 题卷、看长选项与解析折叠 | Chrome DevTools 设备模拟 | 无横滚（scrollWidth ≤ clientWidth）、代码块内滚、按钮 ≥40 高可点 |
| 45 道「参考答案要点」题干可读性定稿 | 逐条人工读，判断是否改写为自洽题面 | 人工 + MERGE-REPORT §6 | 产品确认可读或排期改写 |
| 答案/选项分布是否强制均衡 | 产品决策：是否要求 judge 50/50、正确项四选项均衡 | 人工评审（数据见 D-2） | 出决策记录；若要求均衡则另立需求重排 |
| 上游许可法务确认 | 复核 `haizlin/fe-interview` MIT 对改写衍生作品的适用 | 人工/法务 | NOTICE 文本经法务认可 |
| 后端 ruff | 开发机执行 `python -m ruff check app tests` | 本机 Python | 0 error（本机未安装 ruff） |

## 6 验收结论

1. **功能与数据面全部达标**：779 条、分布逐项一致、存量 260 行内容级冻结（sha256 门禁真会红）、离线工具三档幂等、回滚 779→260→0 且未初始化库给中文提示、练习/判分/错题本/笔试在 779 池上实跑全通、许可合规。
2. 上轮唯一阻断项 **D-1 已修复**（sha256 常量 + 断言，成本极低且已验证可变红），D-3 一并修复；余 D-2/D-4/D-5/D-6 为 P3 观察项，**不阻断验收**，建议下一轮或收口时顺手处理 D-5（改一行记忆）。
3. 交付时须把未跟踪的 `docs/question-bank-staging/`（4 份素材 + NOTICE）随本次提交入库。

### 附：本轮复用/新增检查脚本（run 归档）

- `logs/teamflow/tf-mvy1bqfh-vtjllw/scripts/check_qa_r12_data.py`（数据 28 项）
- `…/check_qa_r12_report_claims.py`（报表自证 21 项）
- `…/check_qa_r12_interface.py`（蓝图接口/跨模块调用 52 项）
- `…/check_qa_r12_runtime.py`（练习四端点 17 项，`--port` 参数化）
- `…/check_qa_r12_exam_e2e.py`（笔试 779 池 4 项）
- `…/check_qa_r12_legacy_pin.py`（D-1 探针，自恢复 seed；本轮 exit 0 = 缺陷已关闭）
