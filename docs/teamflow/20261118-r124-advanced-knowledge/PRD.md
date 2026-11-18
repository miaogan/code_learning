# r124 · 学堂 / 演武高阶知识深化（面向熟练后端 + 熟悉前端 + 精通 AI）

- 需求来源：用户「继续补充吧，我希望面向的是一个熟练后端开发、熟悉前端开发、精通 ai 工程的用户」。确认口径为 **AI 重点深化**：学堂 +12 章（AI 6 / 后端 3 / 前端 2 / 中间件 1），演武 +120 道（AI 50 / 后端 30 / 前端 20 / 其他 20）。
- 交付形态：纯内容扩充 + 派生种子重算，**不改契约、不改页面逻辑、不改筛选闭集、不改运行时代码**。
- 规模：学堂 48 → **60 章**；演武 1434 → **1554 道**；教程 RAG 种子 197 → **245 小节**。

## 1. 定位与缺口

上一轮 r123 是八方向均衡铺量，本章程整体仍偏「入门→进阶」：AI 方向虽已有 12 章，但缺少「精通级」主题（上下文工程、高级召回、评测体系、MCP、推理量化、Agent 记忆）；后端与前端也缺少面向熟练工的高阶实战章。本轮按用户画像把深度向 AI 倾斜，同时给后端/前端补上够用的高阶内容。

| 模块 | 扩充前 | 扩充后 | 侧重 |
|---|---|---|---|
| 学堂 | 48 章 | 60 章 | AI 6 章精通级 + 后端 3 + 前端 2 + 中间件 1 |
| 演武 | 1434 道 | 1554 道 | AI 精通 50 + 全栈进阶 70，以 challenge/intermediate + advanced 为主 |

## 2. 新增教程章节（12 章）

### AI 工程（6 章，精通级）

| 章节 id | 子方向 | 难度 | 覆盖点 |
|---|---|---|---|
| `ai-context-engineering` | LLM 与 RAG | 高级 | 上下文预算 / 信息布局 / lost-in-the-middle / 压缩 / 前缀缓存 |
| `ai-rag-advanced-retrieval` | LLM 与 RAG | 高级 | 查询改写 / 混合检索 / RRF 融合 / 重排 / 父子块 / HyDE |
| `ai-llm-eval-judge` | 通用 AI | 高级 | golden set / LLM-as-Judge 偏差 / 回归门禁 / bad case 闭环 |
| `ai-mcp-tools` | Agent | 高级 | MCP host/client/server / 工具风险分级 / 第三方工具攻击面 |
| `ai-inference-quantization` | 部署与推理 | 高级 | KV Cache 显存估算 / 权重量化 / 连续批处理 / PagedAttention |
| `ai-agent-memory` | Agent | 高级 | 记忆分层 / 结构化状态 / 事件回放 / 持久化与脱敏 |

### 后端（3 章）/ 前端（2 章）/ 中间件（1 章）

| 章节 id | 方向 | 子方向 | 难度 | 覆盖点 |
|---|---|---|---|---|
| `be-distributed-consistency` | 后端 | 通用后端 | 高级 | 2PC 代价 / Saga 补偿 / Outbox / 幂等与对账 |
| `be-rate-limit-resilience` | 后端 | 通用后端 | 高级 | 限流算法 / 熔断状态机 / 超时降级 / 雪崩防护 |
| `be-go-concurrency` | 后端 | go | 高级 | goroutine 泄漏 / context 取消 / select / pprof |
| `fe-react-concurrent` | 前端 | react | 高级 | 可中断渲染 / useTransition / Suspense / Effect 竞态 |
| `fe-ts-advanced` | 前端 | ts | 高级 | 可辨识联合 / 泛型约束 / 条件类型 / satisfies |
| `mw-redis-ha` | 中间件与运维 | Redis | 高级 | 主从复制 / 哨兵 / Cluster / 数据丢失窗口 / 缓存一致性 |

全部遵循既有 4 节模板（概念 → 规则/对比 → 可运行示例 → 常见坑与自测），末节带 `qa`；代码块标注真实语言；表格每行列数与表头一致。

**约束遵守**：所有新高级章追加在各方向文件末尾，不改变选章顺序。特别注意两条 r49 fixture 前提——
1. `Prompt 工程` 子方向不新增高级章（r49「目标档位缺失时按难度递降」用例依赖它是 AI 中唯一无高级章的子方向）；
2. `部署与推理` 的新高级章 `ai-inference-quantization` 排在 `ai-inference-serving` 之后（r49「同子方向优先选高级章」用例依赖后者是该子方向首个高级章）。

## 3. 新增题库批次

- 素材 1：`docs/question-bank-staging/17-ai-engineering-mastery.json`，50 道，来源 `ai-mastery`，ID 前缀 `aim-`。分布 LLM 与 RAG 14 / Agent 10 / 部署与推理 10 / 通用 AI 8 / Prompt 工程 8；难度 challenge 30 + intermediate 20；必备度 advanced 29 / must_know 18 / nice_to_know 3。
- 素材 2：`docs/question-bank-staging/18-fullstack-advanced.json`，70 道，来源 `fullstack-adv`，ID 前缀 `fsadv-`。分布后端 30（python 6/go 6/java 5/通用 13）/ 前端 20（react 6/js 4/ts 4/css 3/通用 3）/ 算法 4 / 计基 4 / SQL 4 / 研发 4 / 中间件 4；难度 challenge 38 + intermediate 32。
- 质量口径：题干为具体场景（非模板），解析 ≥30 字且**不引用选项字母**（避免选项轮转后指代失效），语言恒空串，子方向全落既有闭集；正确项与干扰项长度比受 `test_r13_question_shuffle` 门禁约束（≤3x）。
- 合并结果：越界丢弃 0 / 字面重复 0 / 近重复 0；`--check` 逐字节幂等。

**质量修正**：`fsadv-041`（TS 泛型约束题）初稿正确项 64 字、干扰项约 20 字，长度比 3.15x 触发 `test_long_answer_ratio_within_budget`。在原素材文件内压缩正确项至 44 字并补足干扰项至 32–34 字，比例降到 1.4x，不放宽门禁。

## 4. 改动清单

| 文件 | 改动 |
|---|---|
| `frontend/src/content/tutorials/{ai,backend,frontend,middleware}.ts` | 追加 12 章 |
| `backend/app/seed/tutorials_rag.json` | `export_tutorials.mjs` 重导出 197 → 245 小节 |
| `docs/question-bank-staging/17-ai-engineering-mastery.json` | 新增（50 道） |
| `docs/question-bank-staging/18-fullstack-advanced.json` | 新增（70 道） |
| `backend/app/services/assessment/question_merge.py` | SOURCES / STAGING_FILES / ID_PREFIX 三处各登记 2 个新来源 |
| `backend/app/seed/questions.json` | `--write` 重算 1434 → 1554 道 |
| `backend/tests/test_r12_question_merge.py` | 冻结 SHA / EXPECTED_TOTAL / SOURCES / 素材行数 / 回滚注释 |
| `backend/tests/test_question_bank_quality.py` | R12_SOURCES / COUNTS / TOTAL / 测试函数名 |
| `backend/tests/test_r11_practice_service.py` | seed 导入量 / 架构设计筛选 62 → 63（sys-arch 60 + kbx 2 + fsadv 1） |
| `AGENTS.md` | §5 变更记录追加 r124 条目 |
| 合并报表 2 份 | `question_merge --write` 派生更新 |
