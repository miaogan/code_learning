# r103 · llama-index 分块接入 + 按内容类型分词 + 召回反馈闭环

> 2026-11-15。用户三问：①RAG 能否接入 llama-index；②能否按文件类型用不同分词器；
> ③能否加点赞/点踩让用户参与召回率提升。三条都落地，但**接入深度**按工程价值裁剪（见 §2）。

## 1. 交付物

| 层 | 文件 | 要点 |
|---|---|---|
| 分块层 | `backend/app/services/retrieval/chunking.py` | 按内容类型选切分器：`prose`（llama `SentenceSplitter` / 自研句子累加）、`code`（按行，绝不切行）、`table`（行批切 + 每片重复表头）、`question`（整段不切）；`split_tutorial_blocks()` 把教程 block 逐类切分 |
| 配置 | `backend/app/core/config.py` | `RAG_CHUNKER=auto|native|llama`、`RAG_CHUNK_TOKENS=320`、`RAG_CHUNK_OVERLAP=48` |
| 摄取 | `backend/app/services/retrieval/indexer.py` | 小节带 `blocks` 时按类型切子片（`section_id` 加 `#n` 后缀保唯一）；只有 `content` 时退回整段（向后兼容） |
| 契约 | `backend/app/schemas.py` | `RagIngestBlock`（text/list/table/note/code 扁平模型）+ `RagIngestItem.blocks`；反馈三件套 |
| 反馈表 | `backend/app/core/db.py` `rag_feedback` | `(user_id, query, chunk_id)` 唯一 —— 换投票＝覆盖，不重复计票 |
| 排序加权 | `backend/app/services/retrieval/hybrid.py` `_apply_feedback` | `factor = 1 + 0.2×min(up,3) − 0.4×min(down,3)`，钳 [0.2, 2.0]，**乘法**而非加法（RRF 分数量级 1/60，加法会盖过排名信号） |
| 端点 | `backend/app/routers/rag.py` | `POST /api/rag/feedback`（404 校验 chunk 存在）、`GET /api/rag/feedback/summary`（总票数 + 被踩最多，带正文前缀） |
| 前端 | `frontend/src/lib/ragIngest.ts`、`pages/SearchPage.tsx`、`api/*` | 摄取同时传结构化 blocks；检索页每条 RAG 结果带「有用 / 没用」按钮，投完立即按本人投票重排 |
| 依赖 | `backend/requirements.txt` | `llama-index-core>=0.14`（只当 node_parser 用；未装时自研兜底） |

## 2. llama-index 接入深度（为什么只接到「切分」这一层）

**接了什么**：`llama_index.core.node_parser.SentenceSplitter` —— 按 token 计数 + 重叠的
正文切分，业界标准实现；装了就自动启用（`RAG_CHUNKER=auto`），没装/版本不兼容则
日志记一条并退回自研句子累加器，主链路零影响。

**刻意没接什么**：
1. **不接它的向量库/检索器**（`VectorStoreIndex` / `PGVectorStore`）：我们已有的 pgvector
   直连 + RRF 融合 + 离线确定性 embedding + 三态评测门禁是一整套可复跑体系，
   换过去等于把「确定性 embedding、评测门禁、降级路径」全部重写一遍，且引入
   `llama-index-vector-stores-postgres` 的额外依赖与连接管理。
2. **不接它的 embedding 抽象**：`HashingEmbedder` 的确定性是评测可复跑的根基。
3. **不接 `CodeSplitter`**：需要 tree-sitter 语言包（多一套二进制依赖），而「按行累加、
   绝不切在行中间」三十行代码就能做到，收益不抵成本。
4. **不接 `MarkdownNodeParser`**：站内表格是结构化 block（headers + rows），交给它要先
   拼成 markdown 再拆回来，反而丢结构。

一句话：**llama-index 当「文本切分器」用，不当框架用**——检索、融合、评测的确定性不动。

## 3. 按内容类型分词的实际效果

| 内容类型 | 切分策略 | 为什么不能一把梭 |
|---|---|---|
| question | 整段一个 chunk | 题干+解析是一个语义单元，切开丢上下文 |
| prose（正文/列表/note） | llama `SentenceSplitter`（320 tokens / 48 重叠）或自研句子累加 | 滑窗切在句子中间，召回片段是半句话 |
| code | 按行累加，优先空行断开 | 切在语句中间 = 无法阅读也无法检索 |
| table | 按行批切，**每片重复表头** | 丢表头的数据行对检索毫无意义 |

教程小节被切成多片时，`section_id` 加 `#n` 后缀保证 `(kind, ref_id, section_id)` 唯一；
站内跳转锚点只取 `#` 前段（`services/coach/agent.py` 已按此处理）。

## 4. 召回反馈闭环（用户参与召回提升）

- **即时效果（个人）**：投票按 `(user, query, chunk)` 唯一，换票覆盖；本人后续同 query
  检索时按 `factor` 加权重排，notice 如实告知「已按你的反馈调整 N 条」。别人的票不影响你
  （测试钉住）。
- **全局聚合（看板/评测）**：`GET /api/rag/feedback/summary` 给总票数与被踩最多的 chunk
  （带正文前缀，题目 chunk 的 title 只有方向标签）。这是「从真实失败查询里挖难例」的入口：
  **下一步**可把「top-1 被踩」的 query 自动沉淀进 `docs/eval/question-retrieval-gold.json`，
  让评测集随真实使用增长（本轮未做，见 §6）。
- **设计取舍**：先做「个人排序」而不是「全局调权」——全局调权需要跨用户聚合 + 防刷票，
  在样本量还小的时候容易把排序带偏；个人排序让用户**立刻**看到自己的反馈生效，
  数据积累后再做全局聚合。

## 5. 验证

| 项 | 结果 |
|---|---|
| `tests/test_rag_chunking.py`（6 例） | ✅ 题目整段、正文句子边界（不拦腰断）、代码不切行、表格重复表头、混合 block、llama 路径可用 |
| `tests/test_rag_feedback.py`（7 例） | ✅ 换票覆盖、点踩降权（同分翻转）、点赞升权、跨用户隔离、未知 chunk 404、非法态度 422、看板计数与被踩榜首 |
| `tests/test_rag_index.py` 新增 1 例 | ✅ blocks 摄取：长正文/长代码/大表格切成多片，代码行不断、表头不丢 |
| 后端全量 pytest | ✅ 通过（含 r100/r101/r102） |
| 前端 typecheck / lint / test / build | ✅ 507 用例通过、构建成功 |
| ruff | ✅ All checks passed |

## 6. 后续（未做）

- 反馈 → 金标集的自动沉淀（难例挖掘脚本 + 人工复核门禁），让 recall@5 门禁随真实失败增长；
- 反馈看板上「考工」页（本轮只做了 summary 端点与检索页按钮）；
- 若接入真实 embedding 模型，`RAG_CHUNK_TOKENS` 应按该模型上下文重标定。
