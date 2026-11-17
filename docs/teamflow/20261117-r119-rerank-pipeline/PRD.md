# r119 · 检索管线接入 rerank 精排

## 背景与结论

r118 已在生产部署 reranker 容器（TEI + `BAAI/bge-reranker-base`，`POST /rerank` 冒烟通过）。本需求把精排接进 r100 检索管线：**semantic / hybrid 模式在融合池上先精排再截回 top_k**；`AI_RERANK_BASE_URL` 留空（默认）时行为与 r100 逐字节一致。

## 设计

### 管线位置与池宽

```
双腿召回（各 top_k×2） → RRF 融合（池取宽到 pool） → 精排（TEI /rerank） → 截回 top_k → 响应（reranked 字段）
```

- 池宽 `pool = max(size, min(AI_RERANK_POOL(默认 20), size×2))`——腿只取了 size×2，pool 不会超过它；上限 20 是 reranker 容器 2g 内存限额的约束（r118 verify.md）。
- **keyword 模式不精排**：它是纯 ILIKE 对照面，保持与既有引擎同一口径。
- 响应新增 `reranked: bool`（schemas.py + frontend types.ts 已同步）：本次结果是否真的经过精排（未配置 / 失败时 False）。

### 两个关键取舍

1. **失败 fail-open**：精排超时 / 非 200 / 响应畸形 → 原融合序返回 + 中文 notice，检索永不因精排 500。响应校验要求 TEI 的 `[{index, score}]` 的 index 恰好是候选下标的排列，否则按失败处理（防错位映射污染排序）。
2. **精排启用时 r103 反馈加权让位**：`_apply_feedback` 按 RRF 分重排，若在精排后执行会毁掉精排结果；交叉编码器语义信号远强于个人投票，这是有意取舍。精排失败 fail-open 时反馈照常生效（r103 行为完整保留）。

### 配置（backend/.env，服务端配置不受 SSRF 门禁约束）

```
AI_RERANK_BASE_URL=http://reranker:8080   # 留空 = 不精排
AI_RERANK_TIMEOUT_S=8
AI_RERANK_POOL=20
```

### r115 登记制

`app/services/retrieval/rerank.py` 是新增 httpx 出网点，已登记进 `test_r115_intranet.py::_OUTBOUND_CALL_SITES`（第 5 类）。留空配置时零出网。

## 验证

- 专项 `test_r119_rerank.py` 13 例（解析归一 / 排列校验五态 / fail-open 三态 / 池取宽 / keyword 不精排 / 未配置零行为）+ r115 登记 + 既有 RAG 测试全绿；后端全量 exit 0；ruff 全过。
- 前端 typecheck + 582 tests 全绿（契约只加字段，UI 零改动）。
- 生产接入与真实链路验证见 `verify.md`。
