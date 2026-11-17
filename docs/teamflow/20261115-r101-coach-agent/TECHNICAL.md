# r101 · 教练 Agent 编排（讲席）

> 2026-11-15。承接 r100 审计结论：用户明确要「在这个项目体现 Agent 编排能力」。
> r83 的太傅是**对话式**工具循环（模型自己决定下一句要不要读料）；本批补的是
> **显式编排**（显式规划 → 执行 → 反思 → 补充执行 → 有引用结论），并把整条轨迹
> 落库可回放——这是「编排」与「调 API」的分水岭。

## 1. 交付物

| 层 | 文件 | 要点 |
|---|---|---|
| 图 | `backend/app/services/coach/agent.py` | LangGraph：`plan → act → reflect ⇄ act → final`；每节点产出都进 `steps` 审计轨迹 |
| 工具 | 同上（`TOOLS` 闭集） | 4 个只读工具：`read_shortfalls`（最近报告短板）/ `search_tutorials`（**复用 r100 RAG 混合检索**）/ `search_questions`（题库，答案永不回传）/ `read_plan`（7 天计划进度） |
| 轨迹表 | `backend/app/core/db.py` `coach_runs` | `id / user_id / question / goal / status / steps(JSON) / answer / citations(JSON) / created_at`，只追加不改写，按账号隔离 |
| 端点 | `backend/app/routers/coach.py` | `POST /api/coach/agent/run`、`GET /api/coach/agent/runs`、`GET /api/coach/agent/runs/{id}`（404 中文 envelope，能力档 light） |
| 契约 | `backend/app/schemas.py` | `CoachPlanDraft / CoachReflectDraft / CoachBriefDraft`（模型输出）+ `CoachAgentRun / CoachCitation / CoachAgentRequest`（HTTP） |
| 前端 | `frontend/src/pages/CoachPage.tsx`（`/coach`，侧栏工具组「讲席」） | 提问 + 目标 → 轨迹时间线（规划/执行/反思/结论四段卡片）→ 结论 + 引用卡片 → 编排历史一键回放 |

## 2. 编排语义（为什么这样设计）

1. **显式规划，不靠模型「想到哪读到哪」**：`plan` 节点一次结构化补全产出 ≤3 步计划
   （工具 + 中文理由 + 参数），闭集外工具直接丢弃；规划失败/空计划走**确定性兜底**
   （读短板 → 检索教程 → 检索题库），轨迹里 `fallback: true` 如实记账——编排不能因为
   一次模型抖动就变成空跑。
2. **执行有界**：单轮 ≤3 步、全场 ≤2 轮（首轮 + 补一轮）、每步材料 ≤3 条、回灌行数 ≤6 行；
   工具失败只记一条 `tool` 轨迹（`ok=false`）不连坐整场。
3. **反思是决策点，不是装饰**：`reflect` 判断「材料是否足够 / 缺什么 / 补哪几步」；
   不足且还有轮次额度才进第二轮，额度耗尽如实标 `exhausted`——避免无限自激。
4. **引用只由工具结果产生**：工具结果自带 ref 令牌（`w1` 薄弱点 / `t1` 教程 / `q1` 题目 /
   `p1` 计划），结论里的 citations 必须是这些令牌的子集，越界丢弃并计 `dropped_citations`
   ——与画像 `source_quote`、太傅引用同一套反幻觉纪律。
5. **轨迹即审计**：`steps` 逐节点记录（plan 的计划与理由、tool 的入参/摘要/条目、reflect
   的判定与缺口、final 的行动项与丢弃数），`GET /runs/{id}` 可回放「它为什么这么答」；
   这是「可解释 Agent」而不是黑盒。
6. **与太傅互不替代**：太傅负责对话式追问与长期记忆；教练 Agent 负责「按问题编排一次
   完整作业」。两者共用 `AIClient`/能力档/引用白名单纪律，但编排形态刻意不同。

## 3. 验证

| 项 | 结果 |
|---|---|
| 后端 `tests/test_coach_agent.py` | ✅ 11 用例：4 个工具的正/反路径、轨迹节点序列（plan→tool×2→reflect→final）、规划兜底、反思补一轮（6 节点）、引用白名单（t1 合法 / t9 丢弃）、404 中文、材料有界 |
| 后端全量 pytest | ✅ 通过（含 r100 全部用例） |
| 前端 typecheck / lint / test / build | ✅ 40 文件 529 用例通过，构建成功 |
| ruff | ✅ All checks passed |
