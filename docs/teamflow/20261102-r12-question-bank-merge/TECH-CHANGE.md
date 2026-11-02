# 技术变更单 · r12 题库素材合并（519 道并入 → 全库 779）

基线依赖：`docs/teamflow/20261101-r11-practice-question-bank`（r11 PRD/TECHNICAL 是题库与练习契约的唯一功能来源；本单**不改写**其任何 AC）。
性质：技术驱动返工（数据入库 + 去重工具化），**不新增功能 AC**。唯一用户可见变化：题库 260 → 779 道（练习可练题量变大）。

## 1 背景与目标

把 `docs/question-bank-staging/` 的 4 个素材文件（519 道，全为客观题：single 395 / judge 120 / multiple 4）经归一化 + 去重 + 标来源后并入 `backend/app/seed/questions.json`，全库 260 → 779，且练习页 / 笔试卷 / 熟练度零回归。

## 2 影响面

| 文件 / 模块 | 动作 | 说明 |
|---|---|---|
| `backend/app/services/question_merge.py` | 新增 | 离线合并工具（归一化 / 去重 / 落盘 / 报表 / 回滚），**阈值与取舍常量只在此处** |
| `backend/app/seed/questions.json` | 重写 | 779 条；单条 schema 不变，仅新增可选 `source` |
| `backend/tests/test_r12_question_merge.py` | 新增 | 表驱动归一化、去重取舍、幂等、分布与许可门禁 |
| `backend/tests/test_question_bank_quality.py` | 追加 | 只加 r12 断言（source 枚举/计数/总量），**r11 断言一字不改** |
| `docs/question-bank-staging/NOTICE-fe-interview.md` | 新增 | MIT 全文 + 上游 URL + 改写说明 |
| `docs/teamflow/20261102-r12-question-bank-merge/QUESTION-BANK-MERGE-REPORT.md` | 新增 | 导入报表（工具生成，见 §3.3） |
| `question_bank.py` / `repository.py` / `db.py` / `schemas.py` / `types.ts` / 前端 | **零改动** | 依据：`ensure_seeded()` 已每次启动幂等导入；`questions.source` 列已存在（`db.py:90`，DEFAULT `'seed'`）且 `_row_of` 已透传；`source` 不进 HTTP 契约 |

## 3 技术方案（要点）

### 3.1 归一化（逐条做，不整批丢）
- `kind` 闭集 `single/multiple/judge`（素材全部命中）；`answer` 字符串 → list：单选取 1，多选按 `,，、` 与空白切分且 ≥2，判断题 `正确/错误` → `A/B`。
- `judge` 一律重建为 `[{key:"A",text:"正确"},{key:"B",text:"错误"}]`、`answer` 指向其一：`01` 的 4 条 key 是中文（文本已对）→ 换 key；其余 116 条 key 已 A/B 但答案是中文 → 映射。判分仍走 `exam.grade_objective`，零新实现。
- `04-fe-interview20.json` 缺 `direction` → 按 language 推断（html/css/js → 前端）。
- 方向 / 语言冲突 **9 条**按「language 归属为准」纠正（不丢题）：后端+css 5 → 前端；计算机基础+java 2 → 后端；算法+react 1、算法+css 1 → 前端。
- 越界值只走「映射表纠正」或「整条丢弃 + 记账」，禁止静默改；本轮预期丢弃 0 条。
- `source` 枚举 `tiji / local100 / iq380 / fe-interview`；**存量 260 道不写 source**（`_row_of` 缺省 `'seed'`；显式写死会让既有 `app.db` 的旧行分叉，见 §7-④）。

### 3.2 去重（核心，可复跑）
- 字面重复：题干 NFKC + 去空白 + 去 `\W_` + 小写（r11 同口径）后，与**现有 260 道**和本批已保留集全局比对，命中即丢。
- 近重复：字符 2-gram Jaccard ≥ `NEAR_DUP_JACCARD=0.62` 视为候选；常量集中 `NGRAM=2` / `NEAR_DUP_JACCARD` / `SOURCE_PRIORITY=("tiji","local100","iq380","fe-interview")`。
- 取舍：存量 seed 行恒保留（只增不删）→ 候选丢；批内冲突取来源优先级高者，同源取解析更长者，仍相同取题干 sha1 小者（确定性）。
- id：`tiji-NNN` / `l100-NNN` / `iq-NNN` / `fei-NNN`——避开 legacy `fe-/be-/al-/cs-` 与 r11 九个语言前缀，保证 `_is_new()` / `_legacy_rows()` 口径不被污染。
- 实测（离线采样）：字面重复 0、近重复 0；最高相似 0.61（iq380 Python GIL ↔ 存量 py 题）未触发 0.62，见 §7-②。

### 3.3 工具与产物
`python -X utf8 -m app.services.question_merge --check | --write | --rollback`
- `--check`：从 staging 重算并与已提交 seed **逐字节比对**（0 差异＝幂等），CI / QA 用。
- `--write`：写 seed（稳定序：存量原序 + 新增按来源序、源内原序）+ 生成报表。
- `--rollback`：按本批 id 前缀删除 `questions` 行（幂等、只删本批），供 §6 回滚。
- 报表必含：每来源 读入/字面重复/近重复/越界/纠正/新增/合并总数 + 语言·方向·题型·难度分布 + 12 道人工抽检 + 解析长度分布·选项合规率·language 空占比 + 断言改动清单。

### 3.4 入库与兼容
- 存量 `app.db` 下次启动自动 +519（r11 已是「每次启动导入 + 只补空列」口径）；重复执行恒 0 新增，既有 260 行不被覆盖。零 DDL、零迁移。
- `text` 12 道不进练习池、`judge` 复用两选项单选 + 集合相等判分——口径不变。
- 预期合并分布（工具实跑须一致）：language `''294 / python 86 / java 84 / go 74 / js 46 / react 45 / vue3 42 / css 40 / html 36 / ts 32`；kind `single 551 / judge 156 / multiple 60 / text 12`；difficulty `basic 283 / intermediate 359 / challenge 137`（17.6% ≤ 20%）；方向 `前端 267 / 后端 423 / 算法 56 / 计算机基础 33`。

### 3.5 许可
- `fe-interview`（MIT）：`NOTICE-fe-interview.md` 含 MIT 全文 + 上游 URL + AI 改写说明；seed 标 `source=fe-interview`。
- `01/02/03` 自建或本地生成，仅标 `source`；禁止引入 GPL / 无 LICENSE 素材（AIGC-Interview-Book、AgentGuide、CS-Notes 不引入）。

## 4 行为兼容影响

- 题库 260 → 779；练习页按语言筛选可见题量增大（python 86）；`language` 空的 294 道仍只在「全部语言」下出现（既有筛选语义）。
- 笔试卷面结构闸门不变，但同筛选下抽样集合会变（会抽到新题）——非契约变化。
- 熟练度公式与阈值、错题本口径、错题重练、`text` 不进池、`judge` 判分、前端渲染：全部零变化。

## 5 回归与验证计划

verifyScripts（QA 逐条实跑，前端不动但仍要过门禁）：
1. `cd backend && python -X utf8 -m app.services.question_merge --check`
2. `cd backend && python -m pytest -q -p no:cacheprovider`
3. `cd backend && python -m pytest -q -p no:cacheprovider tests/test_r12_question_merge.py tests/test_question_bank_quality.py tests/test_exam_filter.py`
4. `cd backend && python -m ruff check app tests`
5. `cd frontend && npm run typecheck && npm run lint && npm test && npm run build`
6. `cd backend && DB_PATH=tests/.tmp/r12-boot.db AI_API_KEY= python -m uvicorn app.main:app --port 8140` → `curl -sS http://127.0.0.1:8140/health`
7. `curl -sS -X POST http://127.0.0.1:8140/api/practice/paper -H 'Content-Type: application/json' -d '{"language":"python","limit":20}'`（题量 = 20 且全 python）
8. 判断题真判分：同端点 `POST /api/practice/answer` 传 `A`/`B` 各一次，`correct` 与解析回显正确；`curl -sS 'http://127.0.0.1:8140/api/practice/wrong-book'` 出现该题
9. `cd backend && python -X utf8 -c "import json;print(len(json.load(open('app/seed/questions.json',encoding='utf-8'))))"` = 779
10. 二次启动同库：导入恒 0 新增（`ensure_seeded()` 返回 779）

回归地板：pytest ≥ 466 passed + 新增用例、0 failed（基线 466 passed / 1 skipped）；vitest ≥ 133；typecheck 0；lint 0 error / ≤28 warning；build 通过；`/health` 200。
数据不变量：总 779；source 5 类枚举全覆盖（260/20/100/379/20）；四方向 ≥20；解析 ≥10 字 100%；同语言归一化题干重复 0；选项 2–6 且 key 唯一；`answer ⊆ options`；近重复 0。

断言改造清单（逐条说明，**经核查结论与需求假设不同**）：
- 「题量恰好 260 / 每语言恰好 20」类断言在 r11 已收敛为前缀子集（`fe-/be-/al-/cs-` 存量、九个 r11 前缀新增）或按 `len(_seed_rows())` 动态推导 → **合并后 0 处需要改基数**，这是本轮必须如实记录的一条。
- 需眼睛盯的两处：`test_question_bank_quality::test_total_size_and_generic_directions`（依赖 §3.1 的 9 条归属纠正，纠正后 0 越界、断言不动）；`test_exam_filter::test_recent_papers_covering_most_of_bank_still_creates_paper`（`per_paper` 由题库总量推导，779 下 chunk≈257，L4 退回断言须实跑确认）。
- 新增门禁只增不减：source 枚举 + 各来源计数 + 总量 ≥779 + 结构校验 + 近重复 0；若外部脚本（如 r11 归档的 `check_r11_delivery.py`）硬编码 260，一并更新。

## 6 风险与回滚

| 风险 | 应对 |
|---|---|
| 素材由 AI 改写，答案/解析可能错 | 12 道人工抽检（每来源 3 道）；任一来源正确率 <90% **整源剔除**再重跑，不硬塞 |
| 题库规模放大影响选池/极端场景用例 | §5-3 实跑；红了按「不变量不变」修测试前提，不放宽 r6/r11 的 AC |
| 幂等被破坏（重复导入新增） | `--check` 0 差异 + 二次导入恒 0 新增 |
| 许可 URL 无法确认 | 见 §7-①，必要时剔除 20 道（779 → 759） |
| 回滚 | `git revert` 代码后**必须**再跑 `question_merge --rollback`：数据只增不删，仅回退代码不会清理存量 `app.db` 已导入的 519 行 |

实施顺序：T1 合并工具 + 报表 →（T2 落盘 seed + 门禁；T3 许可 NOTICE）并行 → T4 全量回归与练习页实跑。分支 `feat/dev-skill-coach` 原地继续，Agent 不提交。

## 7 假设与待澄清

1. **fe-interview 上游 URL 缺失**：staging 4 个文件都没有 URL 字段，`docs/` 下也没有来源说明。NOTICE 的 URL 需 dev 打开候选仓库确认 LICENSE 为 MIT 后回填（候选如 `haizlin/fe-interview`）。若确认不了，按 §6 剔除该来源（少 20 道）——合规优先，这是用户的取舍。
2. **近重复阈值 0.62** 按用户口径落地；实测最接近的一对是 0.61（Python GIL），按规则不丢。若要做到「GIL 只剩一道」，把常量调到 0.60 即可（预计多丢 1–2 道）；保持 0.62 也完全合规，只是会留这一对近似题。
3. **9 条方向/语言冲突以 language 为准纠正**。若用户认为应以 direction 为准，那 9 条会退化为「语言未知」（language 置空），语言分布相应减少 css 6 / react 1 / java 2。
4. **存量 260 不写 `source`**：既有 `app.db` 的旧行是 `'seed'`，显式写 `seed-r11` 会造成种子与新库/旧库不一致，且违反「既有行不被覆盖」。若坚持统一命名，需要额外一条 UPDATE（越界，需用户点头）。
5. **「计数断言要改基数」的假设不成立**（见 §5），本轮不产生基数改动；若产品另要求「每语言恰好 20 道」的强约束，则与本轮「共 519 道全量并入」直接冲突，需用户二选一。
6. 报表落任务夹 `QUESTION-BANK-MERGE-REPORT.md`（不写宿主 `docs/<role>/`、不落项目根）。
7. 素材的 `uid/source_title/source_file` 不进种子（只留 `source`，原始 staging 文件即可追溯），避免种子 schema 膨胀。
8. 合并后题库不再保持「每语言 20 道」的均匀外观，`/practice` 的筛选与文案无需改动（空态/放宽建议按命中数自然生效），因此不新增前端 AC。
