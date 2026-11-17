# r120 · 云端 embedding / rerank 切换（阿里云百炼）

- 需求来源：用户要求把 RAG 的 embedding 与 rerank 从「本机自建模型」换成阿里云百炼托管服务，并
  **关掉云服务器上的本地模型容器**（r104 embedder / r118 reranker 常驻吃掉近 2.2G 内存，宿主已到顶）。
- 模型：`qwen3.7-text-embedding-flash`（1024 维，默认值；可选 256/512/768）、`qwen3.7-text-rerank`。

## 为什么不是「改个 .env 就行」

| 环节 | 现状（r104 / r118 / r119） | 阿里云形态 | 结论 |
|---|---|---|---|
| embedding | OpenAI 兼容 `POST {base}/embeddings` | compatible-mode `/embeddings` 同协议 | **零代码改动**，只配 `.env` |
| rerank | TEI `POST {base}/rerank`，`{query,texts}` → `[{index,score}]` | DashScope `POST {完整端点}`，`{model,input:{query,documents},parameters}` → `output.results[].relevance_score` | **必须加协议分支** |
| `/health` 探针 | `GET {base}/health`，内网 TEI 返回 200 | 公网 SaaS 的 `/health` 必然 404 | **会把 `rag_embedder` 永久误报 down，且每 60s 打公网** |

实测确认（本地直连，不经过服务器）：

- `POST https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings` → 200，`qwen3.7-text-embedding-flash`
  返回 **1024 维**。
- `POST https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank` → 200，
  排序质量干净（0.9024 / 0.00099 / 0.00008：Docker 题目断层第一，天气干扰项接近 0）。
- `POST https://dashscope.aliyuncs.com/compatible-api/v1/reranks` → **400**（该 compatible 端点不支持
  `qwen3.7-text-rerank`），所以只能用 services 原生端点。

## 设计

### 1. `AI_RERANK_PROTOCOL` 闭集（`tei` / `dashscope`）

- `tei`（默认，向后兼容）：`AI_RERANK_BASE_URL=http://reranker:8080`，代码拼 `/rerank`。
- `dashscope`：`AI_RERANK_BASE_URL` 是**完整端点 URL**（不再拼后缀），必填 `AI_RERANK_MODEL`。
- 协议写错 → 按 `tei` 兜底 + warning（配置错不阻断启动）；`dashscope` 缺 model → `resolve_reranker()`
  返回 `None`（视为未配置），避免每次检索都发一个必然 400 的请求。
- Key 继承链：`AI_RERANK_API_KEY` → `AI_EMBED_API_KEY` → 主档 `AI_API_KEY`（同一云端账号只填一次）。

### 2. 响应校验口径不变

两种协议的响应都归一到「行列表」再走同一套**排列校验**：`index` 必须恰好是输入下标的排列，
缺号 / 越界 / 重复 / 结构不符一律 fail-open（原融合序 + 中文 notice）。分数照旧**不引入**
（只取名次，避免两套分数量纲污染 RRF 结果）。

### 3. `/health` 探针只在自建端点生效

新增 `_probe_target_is_self_hosted()`：私网 IP / 回环 / 单标签主机名（compose 服务名）才探活；
多标签公网域名直接返回 `na`。这样云端部署下 `rag_embedder` 不再永久误报 down，也不再每 60s
往公网发一个必然 404 的请求。内网自建（r105 口径）行为不变。

### 4. 索引必须重建（换模型 = 换索引）

`content_sha = sha256(embedder + NUL + content)`，embedder 名从 `remote:BAAI/bge-small-zh-v1.5` 变成
`remote:qwen3.7-text-embedding-flash` 后所有 chunk 指纹失效；维度 512 → 1024 会触发 `init_db()` 清空
并重建向量列，`status` 回到「未构建」。生产切换后必须在考工页重建一次索引。

## 影响面

- 出网点：embedding / rerank 由「内网容器」变成「公网 SaaS」，两者早已在 r115 `_OUTBOUND_CALL_SITES`
  登记（`embeddings.py` / `rerank.py`），登记制无需改动；内网 / 气隙部署保持 `AI_EMBED_MODEL` 留空 +
  `AI_RERANK_BASE_URL` 留空 = 零出网，口径不变。
- 成本：embedding 0.125 元/百万 tokens（题库 1284 道 + 教程 ≈ 一次性重建开销），rerank 0.5 元/百万 tokens
  （每次语义检索 ≤20 条候选，按需计费）。
- 延迟：公网往返取代内网容器。embedding 单批 16 条一次往返；rerank 20 条候选一次往返。
- 内存：停掉 embedder（限 1G，实占 166M）+ reranker（限 2G，实占 1.999G）后，宿主 available 从 ~511Mi
  回到约 2.5G，给后续部署留出余量。

## 验收标准

- [x] `dashscope` 协议单测三态（成功 / 畸形 / 缺 model）+ Key 继承 + 未知协议兜底
- [x] 探针：公网端点 `na` 且零网络请求；内网端点仍探活
- [x] 后端全量测试 + ruff + 前端门禁
- [ ] 生产 `.env` 切换、停本地模型容器、重建索引、真实 `/api/rag/search` 返回 `reranked=true`
