# RESUME · 简历话术与面试追问准备

> 原则：**只写能复跑、能被追问的数字**。§1 与 §3 的全部数字都指向仓库里的一条命令或一份产物文件；
> 没有实测来源的数字一律不写。刻意不写「提升」「优化后」这类因果表述，除非确有前后版本对照。
> 修订（r53）：删除早期模板里的 `<...>` 占位符，以及「轨迹回放 / RRF 融合 / 自动降级」等**与代码不符**的能力描述。
> 修订（r54）：在线评测轨道**脚手架**已就位（版本锁定 / 脱敏轨迹 / 双开关），但**真实模型一次都没跑过**；所有在线数字仍不可写。

## 1. 现在就能写（已实测，无占位符）

| 事实 | 证据来源 |
|---|---|
| 题库 1164 道、8 个方向 × 二级方向 × 3 档难度；教程 40 章 | `seed/questions.json`、`content/tutorials/*.ts` |
| 935 条自动化测试（后端 667 passed / 1 skipped + 前端 268 passed），零网络可复跑 | `python -m pytest` / `npm test` |
| 前后端契约双侧同步、错误码闭集、统一中文错误 envelope | `schemas.py` ↔ `api/types.ts`、`core/errors.py` |
| 题库种子「素材重算逐字节一致」幂等门禁 | `question_merge --check`，已进 CI |
| 简历原文不落盘、Key 只存后端 Fernet 密文、错误不含路径/堆栈/端点 | `README.md` 安全边界、`services/ai/user_ai.py` |
| 异步任务 + 断连恢复 + 部分唯一索引幂等 + 卡片死清扫 | `profile_jobs` / `resume_jobs` |
| CI 双 job 在 GitHub Actions 实跑 33 次，最近 `#33`（`1c33046`）成功、#27–#33 连续通过（含 5 个零网络门禁） | [Actions 运行记录](https://github.com/miaogan/code_learning/actions) |
| 离线评测门禁：30 例版本化合成金标集，schema 通过率 93.3%、micro-F1 98.5%、±2pp 波动带 | `scripts/eval_harness.py --check`、`docs/eval/REPORT.md` |
| 模型调用全链路可观测：`ai_call_logs` 落库 + `/eval` 看板（成功率 / p50 / p95 / 失败分类 / 按模型），写库 best-effort 不影响主链路 | `services/ai/ai.py`、`GET /api/eval/summary` |
| 检索增强：40 章教程 bigram + BM25、题库 FTS5 trigram（降级 LIKE）、可点击 citation；教程侧与题目侧各 20 组标注 recall@5 均 100%，Wilson 95% 下界 83.9% | `docs/eval/RETRIEVAL-REPORT.md`、`docs/eval/QUESTION-RETRIEVAL-REPORT.md` |
| SQLite 并发写治理：400 次并发短事务基准下 `busy_timeout` 让成功率 28.2%→100%、消除 287 次 `database is locked` | `docs/eval/PERF-REPORT.md`、`core/db.py::connection()` |
| LLM 可靠性治理：退避+抖动重试、结构化输出修复、可注入三态熔断器；模拟故障注入 55.5%→84.0%、熔断减少 80% 无效上游调用 | `docs/eval/RELIABILITY-REPORT.md`、`services/ai/reliability.py` |
| 日志表 90 天保留期，随登录收口清理 | `repository.prune_ai_call_logs()` |
| 在线评测轨道**脚手架**：版本锁定（prompt/model/rubric/金标 sha256）+ 脱敏轨迹（21 键白名单）+ 真跑双开关；**真实模型未实跑** | `scripts/eval_live.py`、`docs/eval/LIVE-REPORT.md`（标注 DRY-RUN） |

> **⚠️ 别把这几个百分比当能力宣传**：
> - 金标 30 例是合成数据、响应快照与标注同源；检索标注各 20 组且由同一批章节标题 / 题目关键词启发写成，存在**标注泄漏风险**。
> - 可靠性数字来自**模拟故障函数 + 虚拟时钟**，不是真实模型或线上可用性；虚拟 p95 不能与 `PERF-REPORT.md` 的真实基准混用。
> - 它们的用途是**回归检测与实现可用性证明**。被问「指标怎么算的」时，主动说出样本量、同源标注、Wilson 下界与「纯模拟」边界 —— 这比报一个漂亮的 100% 更像高级工程师；把 98.5% / 100% 说成「模型准确率」，一追问分母就会变成减分项。

## 2. 不建议这样写

- ❌ `基于 FastAPI + React 开发 AI 面试教练，实现简历解析、模拟面试、题库练习、学习计划`
  → 全是功能罗列，看不出难点，和一百个 CRUD 项目没区别。
- ❌ `自研 RAG 系统 / 多 Agent 编排平台 / 自研大模型`
  → 代码里没有向量检索、没有编排、没有训练。这三个词会把面试官引向 `recall@k`、chunk 策略、终止判据，一问就穿。
- ❌ `在线质量评测双轨已落地 / 模型准确率提升 X% / 评分 MAE`
  → 在线轨道的**脚手架**（版本锁定 + 脱敏轨迹 + 双开关）已就位，但**真实模型一次都没跑过**；评分 MAE 缺逐例人工打分未实现。轨迹只有 `docs/eval/traces/dry-run.jsonl`（元数据回放），不是真实模型轨迹。如实说法：「脚手架已就位、真跑待用户授权消耗配额」。
- ❌ `RRF 融合生成学习计划` / `计划排程升到 v2`
  → RRF 纯函数已实现并单测，但**未接入计划 UI**（同步排程不引异步 API）；`PLAN_VERSION` 有意保持 1。
- ❌ `超时与限流自动降级且用户无感`
  → 有超时 / 重试 / 结构化输出修复，但**没有熔断自动短路与降级页**；熔断器默认只观测。
- ❌ `准确率 95%`、`性能提升 300%` 之类无分母、无基线的数字
  → 高级岗位面试第一个追问就是「分母是什么、基线怎么来的」。

## 3. 推荐写法（可直接复制，数字全部可复跑）

**项目定位一行**

> Skill Coach · 开发者能力提升教练（Python 3.11 / FastAPI / SQLite / React 18 + TypeScript strict）
> 定位：**LLM 应用的工程化与可靠性**，而非模型研发；简历 → 画像 → 双测评 → 带证据的诊断报告 → 检索增强学习计划。

**Bullet（按岗位挑 3–4 条，不要全堆）**

- `构建 LLM 应用离线评测体系：30 例版本化合成金标集，评分器为纯规则、与被测系统隔离；schema 通过率 93.3%、字段级 micro-F1 98.5%，±2pp 波动带门禁进 CI，指标跌破即红灯（离线回归，不混同模型质量）`
- `模型调用全链路可观测：结构化元数据落库（不含 Key / Prompt / 简历正文）+ 只读聚合看板，按 provider / model / 失败分类拆分；p50/p95 分位与成功率分母固定在后端，写库失败 best-effort 不影响主链路`
- `用 400 次并发短事务基准定位 SQLite 锁竞争：无 busy_timeout 时成功率仅 28.2%（287 次 database is locked），补 PRAGMA 后 100%；日志表按 90 天保留期随登录收口清理`
- `检索增强 + 引用归因：40 章教程前端 BM25（中文 bigram、零第三方依赖）+ 1164 题后端 FTS5 trigram（不可用时降级 LIKE），生成可点击章节锚点；两路各 20 组标注 recall@5 100%、引用有效率 100%（90/90），Wilson 95% 下界 83.9%`
- `LLM 可靠性治理：后台重试加指数退避+抖动、结构化输出修复兜底、可注入三态熔断器；确定性故障注入下成功率 55.5%→84.0%（+28.5pp）、修复救回 34 次、熔断减少 80% 无效上游调用（纯模拟）`
- `935 条测试（pytest 667 + vitest 268）、双 job CI 含 5 个零网络门禁；SQLite 直连、无 ORM / 无向量库的取舍与代价公开在 README 设计取舍`

**面试时的一句话主线**

> 「我不是又做了一个聊天壳子，而是把『AI 输出到底有没有变好』变成可复跑的数据，并且在模型不可用时让系统仍然可用。」

## 4. 必答追问（提前准备到能脱口而出）

| 追问 | 答案要点 | 项目内证据 |
|---|---|---|
| 为什么不用向量数据库 / 为什么这不算 RAG？ | 语料只有 40 章 + 1164 题，BM25 + 元数据过滤已够；引向量库会带来 embedding 版本、索引重建、chunk 评估三份成本，且无法在小样本上给出可信的 recall 提升。命名诚实：检索增强 + 引用归因。 | README 设计取舍、`TECHNICAL.md §4.1/§4.5` |
| 评测的评分器怎么防止「模型给自己打分」？ | 评分逻辑是纯函数 / 规则，人工标注作金标，被测模型只产出被评对象；离线轨道用固定响应快照回放。**在线轨道脚手架已就位（版本锁定 + 脱敏轨迹），但真实模型未实跑**；要谈模型质量必须真跑并人工复核标注。 | `TECHNICAL.md §3.3 / §8`、`ai-eval-harness` 教程章 |
| 指标的分母是什么？CI 会不会 flaky？ | 逐指标写死分母（schema = 响应总数、P/R = 字段集合、recall@5 = 20 组标注查询）；门禁用 ±2pp 波动带 + 固定快照，只有真实劣化才红灯。**评分 MAE 未计入**：金标只标得分区间、没有逐例人工打分，不编造指标。 | `TECHNICAL.md §3.4`、`docs/eval/REPORT.md` |
| 为什么 SQLite 不用 ORM / 不上 Postgres？ | 单进程本地工具，结构化产物以 JSON 文本列存，schema 演进上移到 pydantic 校验；代价是手写 SQL 与自管升级语句，用 `init_db()` 幂等补列 + 单一 SQL 出口门禁兜住。 | `ARCHITECTURE.md §1.1`、`test_engineering_gates.py` |
| 并发写日志会不会锁库？ | 每次连接带 `PRAGMA busy_timeout = 3000`；400 次并发基准下成功率从 28.2% 提到 100%。**不启用 WAL**：单进程本地库，busy_timeout 已消除写失败，WAL 会引入 -wal/-shm 与备份复杂度。 | `core/db.py::connection()`、`docs/eval/PERF-REPORT.md` |
| 熔断器是不是已经在线上生效？ | **不是**。`CircuitBreaker` 是可注入三态状态机，默认只观测、不自动短路主链路（避免把全局状态塞进既有调用链）；故障注入脚本验证的是策略效果，不是线上开关。结构化输出修复与退避重试是默认启用的。 | `services/ai/reliability.py`、`RELIABILITY-REPORT.md §3` |
| 离线评测和在线质量怎么区分？ | 离线用固定响应快照，只能证明「解析 / 校验 / 评分管线没回归」；要证明模型或提示词变好，必须 `AI_LIVE=1` 打真实模型、锁定 prompt/model 版本并留存轨迹。**本项目已有离线门禁 + 在线脚手架（dry-run），但没有真实模型的在线指标**；`LIVE-REPORT.md` 明确标 DRY-RUN。真跑用 `--live` + `AI_LIVE=1` 双开关防误触发消耗配额，**不进 CI**。 | `TECHNICAL.md §8`、`docs/eval/LIVE-REPORT.md` |

## 5. 演示脚本（3 分钟，按这个顺序讲）

1. `docker compose up -d --build` → `/health` → 30 秒展示「能跑」。
2. 上传简历 → 画像每条带 `sourceQuote` → 短板 `Q3 · 4/10` 指回具体题目（**证据可溯源**是产品主线）。
3. **演示数据**：`DB_PATH=/path/to/eval_demo.db python -X utf8 scripts/seed_eval_demo.py --days 7 --count 120`（必须指向独立库，不要污染开发库）→ 打开 `/eval` 看板讲「怎么知道 AI 变好/变坏」。
4. 跑 `python -X utf8 scripts/eval_harness.py --check` → 展示门禁输出与 `docs/eval/REPORT.md` → 讲「怎么防回归」。
5. 报告页点开一条学习计划的 citation → 跳到章节锚点 → 讲「检索与引用归因」。
6. 收尾一句取舍：「没上向量库，因为在这个语料规模下收益不成立，代价我写在 README 里」。

> 第 3 步的看板数据全部是**合成元数据**（provider 标记为 `demo`），演示时要主动说明；真实环境没有模型调用记录时看板会显示「暂无模型调用记录」。
> 不演示「在线真实模型评测 / 模型准确率提升 / RRF 融合」—— 前者需授权消耗配额、后两者未落地。
> 可以演示 `python -X utf8 scripts/eval_live.py --check` 与 `docs/eval/traces/dry-run.jsonl`，讲「版本锁定、脱敏轨迹与双开关怎么防误触发」，并主动说明这是 dry-run。
