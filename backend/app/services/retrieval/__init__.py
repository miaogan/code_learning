"""r100 RAG 检索域：embedding → 分块入库 → 向量/混合检索 → 有引用的生成。

分工（写死后别漂）：
- `embeddings.py`：embedding provider 抽象（离线确定性 `HashingEmbedder` / OpenAI 兼容
  `RemoteEmbedder`），与 `Settings.resolve_embedder()` 同为唯一解析出口；
- `indexer.py`：题库重建 + 教程小节摄取，`content_sha` 幂等；
- `hybrid.py`：向量 / 关键词 / RRF 融合三态检索（mode 闭集唯一出处）；
- `answer.py`：检索增强生成 + 引用白名单校验 + LLM-as-judge（供评测脚本复用）。
"""
