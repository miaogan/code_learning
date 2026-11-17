# r121 · 精排后的 score 口径修正

- 来源：r120 验收报告「已知遗留」第 2 条——精排后 `score` 仍是 RRF 融合分，与名次不一致。
- 现象（r120 生产实测，query「Redis 缓存击穿怎么解决」）：

```
0.0156 tutorial  缓存与失效策略 · TTL、淘汰与三类异常   ← 第 1 名
0.0161 question  研发工程实践 · 架构设计
0.0152 question  研发工程实践 · 架构设计
0.0164 question  中间件与运维 · Redis                  ← 第 4 名，分数却是最高
```

## 为什么会这样

这是 r119 的一个**取舍失误**，不是 bug 的巧合：

1. r100 的 `score` 是「该模式引擎的原始分」——keyword 恒 1.0、semantic 余弦、hybrid 是
   **RRF 分**（`1/(60+rank)` 累加，量级 ~0.016）。
2. RRF 分的含义是「**名次折算**」，它只在融合那一步有效：两条腿的余弦与 ILIKE 命中了不可比，
   所以用名次代替分数。
3. r119 加精排时，为了「不引入第三套分数量纲」，只取精排返回的**名次**、丢弃分数，
   `score` 字段保留融合分。结果就是排序换了、分数没换 → **分数与排名失去单调关系**。
4. 当时的辩护是「前端不展示 score」。但这只是把矛盾藏起来：任何 API 消费者（包括
   `/answer` 的引用排序、将来的评测脚本）读到 `score` 都会得到错误信号。

## 业界怎么处理

RAG 链路的通行口径是**「展示分 = 当前排序依据的分数」**：

| 方案 | 做法 | 评价 |
|---|---|---|
| **精排分直接作为最终分**（Cohere Rerank / BGE reranker / DashScope 官方示例） | 召回阶段用 RRF，精排后用 cross-encoder 的 relevance score 覆盖 | **本项目采用**；分数自带「这条有多相关」的语义 |
| 只用 RRF 分、不看精排分 | 精排仅做过滤/截断 | 分数仍与排名脱节，不可取 |
| 精排分做 min-max 归一 | 批内相对分，第一名恒 1.0 | 跨查询不可比，且小批量下区分度被放大 |

关键点：**召回分与精排分不能混在一批结果里**。本项目精排覆盖整个候选池再截 top_k，
所以最终 top_k 的分数全部来自精排，量纲一致——这是可以直接用精排分的前提。

## 实现

1. `rerank.py::rerank_order` 返回值从 `(list[int], str)` 改为
   `(list[tuple[int, float]], str)`：下标 + **归一化后的精排分**。
2. 归一化 `_normalize_score(protocol, raw)`：
   - `dashscope`：`relevance_score` 文档口径就是 [0,1] 的相关性分，原值透传；
   - `tei`：`score` 是交叉编码器的 **logit**（可负、可远大于 1），过 sigmoid 映射到 (0,1)；
   - 越界值（协议假设被打破）统一走 sigmoid 兜底，clamp ±60 防 `math.exp` 溢出。
3. `hybrid.search_chunks`：精排成功后 `score` 用精排分覆盖，再截 top_k。
4. fail-open 时行为不变：仍返回融合序 + 原融合分 + notice（此时「排序依据」确实是融合分，
   口径自洽）。keyword 模式不精排，恒 1.0，不变。
5. 契约注释同步：`schemas.py::RagChunkItem` 与 `frontend/src/api/types.ts` 都改成
   「本次结果真实排序依据的分数」。

## 影响面

- `score` 的量纲在 `reranked=true` 时从 ~0.016 变成 0~1。前端不渲染该字段，无 UI 影响；
  任何按分数阈值过滤的调用方需知会（当前仓库内无此用法，已 grep 确认）。
- 排序结果本身不变（仍是精排顺序），只是分数跟上。
- r103 反馈加权仍在精排时让位（`_apply_feedback` 按 score 重排会毁掉精排序），逻辑未动。

## 验收

- [x] `_normalize_score` 单测：dashscope 透传 / tei sigmoid / 越界兜底
- [x] 精排成功时 `score` 被替换且与排名单调（`test_search_hybrid_with_rerank_reorders_and_widens_pool`）
- [x] fail-open 三态（HTTP 错 / 非 200 / 畸形响应）断言同步更新，行为不变
- [x] 后端全量 + ruff + 前端 typecheck
- [x] 生产验证：`reranked=true` 时分数严格递减且落在 0~1（见 `verify.md`）
