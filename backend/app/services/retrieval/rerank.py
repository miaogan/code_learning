"""r119 rerank 精排层：TEI `/rerank` 端点的**可选**精排（默认不配置 = 完全零出网）。

与 `embeddings.py` 同构的三条铁律：

1. **配置不存在 ≠ 报错**：`AI_RERANK_BASE_URL` 留空时 `resolve_reranker()` 返回 None，
   检索管线与 r100 行为逐字节一致——rerank 是锦上添花，不是依赖。
2. **失败 fail-open**：精排服务抖了 / 超时 / 响应畸形，一律返回原序 + 中文 notice，
   绝不 500——「少一层精排」比「整个检索挂掉」可用得多；也绝不静默（notice 必须说清）。
3. **响应必须校验**：TEI 返回 `[{index, score}]`，index 必须恰好是输入下标的**排列**；
   不是排列（服务错乱 / 版本不符）按失败处理，不让错位映射污染排序。

出网登记：本文件是 r115 `_OUTBOUND_CALL_SITES` 的登记项之一（内网自建 TEI 是主用
形态，端点来自服务端配置 `AI_RERANK_*`，不受 SSRF 门禁约束——与 `AI_EMBED_*` 同口径）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from app.core.config import Settings, get_settings

logger = logging.getLogger("app.rag.rerank")

#: 候选池的硬上限：reranker 容器内存限额 2g（r118），候选更多会撞 cgroup 上限。
MAX_RERANK_POOL = 20


@dataclass(frozen=True)
class RerankRuntime:
    """一次解析出的 rerank 运行期口径（`resolve_reranker` 的返回值）。"""

    base_url: str
    timeout_s: float
    pool: int


def resolve_reranker(settings: Settings | None = None) -> RerankRuntime | None:
    """唯一解析出口：`AI_RERANK_BASE_URL` 空 → None（不精排）；非空 → 精排口径。"""
    current = settings or get_settings()
    base_url = current.ai_rerank_base_url.strip()
    if not base_url:
        return None
    return RerankRuntime(
        base_url=base_url.rstrip("/"),
        timeout_s=max(1.0, float(current.ai_rerank_timeout_s)),
        pool=max(1, min(int(current.ai_rerank_pool), MAX_RERANK_POOL)),
    )


def _order_from_response(rows: object, count: int) -> list[int]:
    """TEI 响应 → 输入下标的重排顺序。非排列（缺号 / 越界 / 重复）一律抛 ValueError。"""
    if not isinstance(rows, list) or len(rows) != count:
        raise ValueError("rerank 响应条数与候选不一致")
    seen: set[int] = set()
    order: list[int] = []
    for row in rows:  # TEI 按 score 降序返回；只认下标，不引入它的分数量纲。
        if not isinstance(row, dict) or "index" not in row:
            raise ValueError("rerank 响应行缺少 index")
        index = int(row["index"])
        if not 0 <= index < count or index in seen:
            raise ValueError("rerank 响应的 index 不是候选下标的排列")
        seen.add(index)
        order.append(index)
    return order


def rerank_order(query: str, texts: list[str], runtime: RerankRuntime) -> tuple[list[int], str]:
    """调精排端点，返回 `(重排后的下标顺序, notice)`。

    - 成功：`(排列, "")`；
    - 失败 / 超时 / 畸形响应：`(原序, 中文 notice)` —— fail-open，绝不抛到检索层之上。
    """
    identity = list(range(len(texts)))
    try:
        response = httpx.post(
            runtime.base_url + "/rerank",
            json={"query": query, "texts": texts, "truncate": True},
            timeout=runtime.timeout_s,
        )
    except httpx.HTTPError as exc:
        logger.warning("rag.rerank.unavailable error=%s", type(exc).__name__)
        return identity, "rerank 精排暂不可用，已按融合排序返回"
    if response.status_code != 200:
        logger.warning("rag.rerank.http_error status=%s", response.status_code)
        return identity, "rerank 精排服务返回异常，已按融合排序返回"
    try:
        order = _order_from_response(response.json(), len(texts))
    except (ValueError, TypeError) as exc:
        logger.warning("rag.rerank.malformed_response detail=%s", exc)
        return identity, "rerank 精排响应异常，已按融合排序返回"
    return order, ""
