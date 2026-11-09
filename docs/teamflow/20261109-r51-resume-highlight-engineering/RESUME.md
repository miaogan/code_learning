# RESUME · 简历话术与面试追问准备

> 原则：**只写能复跑、能被追问的数字**。本文件所有 `<...>` 都是占位符，落地后由命令输出替换；
> 任何没有实测来源的数字都不许写进简历。

## 1. 现在就能写（已实测，无占位符）

| 事实 | 证据来源 |
|---|---|
| 题库 1164 道、8 个方向 × 二级方向 × 3 档难度；教程 40 章 | `seed/questions.json`、`content/tutorials/*.ts` |
| 883 条自动化测试（后端 633 passed / 1 skipped + 前端 250 passed），零网络可复跑 | `pytest -q` / `npm test` |
| 前后端契约双侧同步、错误码闭集、统一中文错误 envelope | `schemas.py` ↔ `api/types.ts`、`core/errors.py` |
| 题库种子「素材重算逐字节一致」幂等门禁 | `question_merge --check`，已进 CI |
| 简历原文不落盘、Key 只存后端 Fernet 密文、错误不含路径/堆栈/端点 | `README.md` 安全边界、`services/ai/user_ai.py` |
| 异步任务 + 断连恢复 + 部分唯一索引幂等 + 卡片死清扫 | `profile_jobs` / `resume_jobs` |
| CI 双 job 在 GitHub Actions 实跑 31 次，最近 5 次连续通过（含历史红灯修复痕迹） | [Actions 运行记录](https://github.com/miaogan/code_learning/actions) |

## 2. 不建议这样写

- ❌ `基于 FastAPI + React 开发 AI 面试教练，实现简历解析、模拟面试、题库练习、学习计划`
  → 全是功能罗列，看不出难点，和一百个 CRUD 项目没区别。
- ❌ `自研 RAG 系统 / 多 Agent 编排平台 / 自研大模型`
  → 代码里没有向量检索、没有编排、没有训练。这三个词会把面试官引向 `recall@k`、chunk 策略、终止判据，一问就穿。
- ❌ `准确率 95%`、`性能提升 300%` 之类无分母、无基线的数字
  → 高级岗位面试第一个追问就是「分母是什么、基线怎么来的」。

## 3. 推荐写法（模板，数字待实测）

**项目定位一行**

> Skill Coach · 开发者能力提升教练（Python 3.11 / FastAPI / SQLite / React 18 + TypeScript strict）
> 定位：**LLM 应用的工程化与可靠性**，而非模型研发；简历 → 画像 → 双测评 → 带证据的诊断报告 → 检索增强学习计划。

**Bullet 模板（M1 + M2 落地后）**

- `构建 LLM 应用离线评测体系：<N> 例版本化金标集 + 轨迹回放，评分器与被测系统隔离；schema 通过率 <A>%→<B>%、字段级 micro-F1 <C>，指标跌破波动带即 CI 红灯（离线回归，不混同模型质量）`
- `模型调用全链路可观测：结构化日志落库 + 只读聚合看板，按 provider / model / 失败分类拆分；定位到 <根因> 后 p95 由 <X>ms 降至 <Y>ms，超时与限流自动降级且用户无感`
- `883 条测试（pytest 633 + vitest 250）、双 job CI + 题库字节级幂等门禁；SQLite 直连、无 ORM / 无向量库的取舍与代价公开在 README Design decisions`

**Bullet 模板（M3 落地后追加）**

- `把 40 章教程 + 1164 题做成可检索知识资产：教程侧前端 BM25 + 题目侧 SQLite FTS5，RRF 融合并生成可点击 citation；20 组人工标注上 recall@5 <D>（硬编码基线 <E>），FTS5 不可用时自动降级为闭集筛选`
- `诊断短板到学习计划全链路证据可溯源：每条任务标明依据章节与小节锚点，检索无命中静默回落确定性排程，旧报告 / 旧计划零破坏`

**面试时的一句话主线**

> 「我不是又做了一个聊天壳子，而是把『AI 输出到底有没有变好』变成可复跑的数据，并且在模型不可用时让系统仍然可用。」

## 4. 三个必答追问（提前准备到能脱口而出）

| 追问 | 答案要点 | 项目内证据 |
|---|---|---|
| 为什么不用向量数据库 / 为什么这不算 RAG？ | 语料只有 40 章 + 1164 题，BM25 + 元数据过滤已够；引向量库会带来 embedding 版本、索引重建、chunk 评估三份成本，且无法在小样本上给出可信的 recall 提升。命名诚实：检索增强 + 引用归因。 | README Design decisions、`TECHNICAL.md §4.1/§4.5` |
| 评测的评分器怎么防止「模型给自己打分」？ | 评分逻辑是纯函数 / 规则，人工标注作金标，被测模型只产出被评对象；离线轨道用固定响应快照回放，在线轨道锁定 prompt/model 版本并留存轨迹；小样本给 Wilson 区间而非裸百分比。 | `TECHNICAL.md §3.3/§3.4`、`ai-eval-harness` 教程章 |
| 指标的分母是什么？CI 会不会 flaky？ | 逐指标写死分母（schema = 响应总数、P/R = 字段集合、MAE = 标注样本数、recall@5 = 20 组标注查询）；门禁用 ±2pp 波动带 + 固定快照，只有真实劣化才红灯。 | `TECHNICAL.md §3.4` |
| 为什么 SQLite 不用 ORM / 不上 Postgres？ | 单进程本地工具，结构化产物以 JSON 文本列存，schema 演进上移到 pydantic 校验；代价是手写 SQL 与自管升级语句，用 `init_db()` 幂等补列 + 单一 SQL 出口门禁兜住。 | `ARCHITECTURE.md §1.1`、`test_engineering_gates.py` |
| 并发写日志会不会锁库？ | 日志写入是短事务 + best-effort，失败只 warning 不影响主链路；补 `busy_timeout`，必要时再评估 WAL。 | `TECHNICAL.md §3.1` |

## 5. 演示脚本（3 分钟，按这个顺序讲）

1. `docker compose up -d --build` → `/health` → 30 秒展示「能跑」。
2. 上传简历 → 画像每条带 `sourceQuote` → 短板 `Q3 · 4/10` 指回具体题目（**证据可溯源**是产品主线）。
3. 打开 `/eval` 看板：失败分类分布 + p95 趋势 → 讲「怎么知道 AI 变好/变坏」。
4. 跑 `python -X utf8 scripts/eval_harness.py --check` → 展示红灯/绿灯与报告 → 讲「门禁怎么防回归」。
5. 报告页点开一条学习计划的 citation → 跳到章节锚点 → 讲「检索与引用归因」。
6. 收尾一句取舍：「没上向量库，因为在这个语料规模下收益不成立，代价我写在 README 里」。

> 演示第 3–5 步依赖 M2 / M3 落地；未落地前不要演示，改用「已规划、方案见 docs」如实说明。
