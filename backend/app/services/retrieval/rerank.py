"""r119/r120 rerank 精排层：TEI 与 DashScope 两种协议的可选精排（默认不配置 = 零出网）。

与 `embeddings.py` 同构的三条铁律：

1. **配置不存在 ≠ 报错**：`AI_RERANK_BASE_URL` 留空时 `resolve_reranker()` 返回 None，
   检索管线与 r100 行为逐字节一致——rerank 是锦上添花，不是依赖。
2. **失败 fail-open**：精排服务抖了 / 超时 / 响应畸形，一律返回原序 + 中文 notice，
   绝不 500——「少一层精排」比「整个检索挂掉」可用得多；也绝不静默（notice 必须说清）。
3. **响应必须校验**：两种协议返回的行都必须含 `index`，且 index 必须恰好是输入下标的
   **排列**；不是排列（服务错乱 / 版本不符 / top_n 截断）按失败处理，不让错位映射污染排序。

**分数口径（r121 修正）**：精排生效时 `score` 直接取精排模型的相关性分（归一化到 0~1），
因为精排分才是这次结果的真实排序依据——沿用融合分会出现「第一名分数低于第四名」的
自相矛盾。归一化按协议：`dashscope` 的 `relevance_score` 文档口径已在 [0,1]，原值透传；
`tei` 的 `score` 是交叉编码器原始 logit（可负、可远大于 1），过 sigmoid 映射到 (0,1)。
未启用精排 / fail-open 时 `score` 仍是该模式的引擎原分（余弦 / RRF / 1.0），行为不变。

两种协议的差异（`AI_RERANK_PROTOCOL` 闭集，r120）：

| 协议 | 端点 | 请求 | 响应 |
|---|---|---|---|
| `tei`（r118 自建容器） | `{base}/rerank` | `{query, texts, truncate}` | `[{index, score}]` |
| `dashscope`（阿里云百炼） | `AI_RERANK_BASE_URL` 完整 URL | `{model, input:{query,documents}, parameters}` | `{output:{results:[{index, relevance_score}]}}` |

分数一律**不引入**：只按服务返回的名次取下标，避免两套分数量纲污染融合结果。

出网登记：本文件是 r115 `_OUTBOUND_CALL_SITES` 的登记项之一（端点来自服务端配置
`AI_RERANK_*`，不受 SSRF 门禁约束——与 `AI_EMBED_*` 同口径）。公网 SaaS 与内网自建
都走这一条登记，内网/气隙部署把 `AI_RERANK_BASE_URL` 留空即可完全关闭。
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

import httpx

from app.core.config import Settings, get_settings

logger = logging.getLogger("app.rag.rerank")

#: 候选池的硬上限：自建 reranker 容器内存限额 2g（r118），候选更多会撞 cgroup 上限；
#: 云端 SaaS 虽无内存问题，但精排 token 成本随候选数线性涨，同一上限同时是成本闸门。
MAX_RERANK_POOL = 20

#: 协议闭集：新增协议必须同时补 `_payload_for` / `_extract_rows` 与单测。
RERANK_PROTOCOLS = ("tei", "dashscope")


@dataclass(frozen=True)
class RerankRuntime:
    """一次解析出的 rerank 运行期口径（`resolve_reranker` 的返回值）。"""

    base_url: str
    timeout_s: float
    pool: int
    protocol: str = "tei"
    model: str = ""
    api_key: str = ""


def resolve_reranker(settings: Settings | None = None) -> RerankRuntime | None:
    """唯一解析出口：`AI_RERANK_BASE_URL` 空 → None（不精排）；非空 → 精排口径。

    解析**永不 raise**（与 `resolve_embedder` 同款）：协议写错按 `tei` 兜底并记 warning；
    `dashscope` 协议缺 model 视为未配置（返回 None），让检索静默保持 r100 行为，
    而不是每次检索都发一个必然 400 的请求。
    """
    current = settings or get_settings()
    base_url = current.ai_rerank_base_url.strip()
    if not base_url:
        return None
    protocol = str(current.ai_rerank_protocol or "tei").strip().lower()
    if protocol not in RERANK_PROTOCOLS:
        logger.warning("rag.rerank.unknown_protocol value=%s fallback=tei", protocol)
        protocol = "tei"
    model = current.ai_rerank_model.strip()
    if protocol == "dashscope" and not model:
        logger.warning("rag.rerank.missing_model protocol=dashscope disabled=true")
        return None
    api_key = (
        current.ai_rerank_api_key.strip()
        or current.ai_embed_api_key.strip()
        or current.resolve_ai().api_key
    )
    return RerankRuntime(
        base_url=base_url.rstrip("/"),
        timeout_s=max(1.0, float(current.ai_rerank_timeout_s)),
        pool=max(1, min(int(current.ai_rerank_pool), MAX_RERANK_POOL)),
        protocol=protocol,
        model=model,
        api_key=api_key,
    )


def _payload_for(protocol: str, query: str, texts: list[str]) -> dict[str, object]:
    """按协议组装请求体。"""
    if protocol == "dashscope":
        return {
            "model": "",  # 由调用方在 rerank_order 里填入 runtime.model
            "input": {"query": query, "documents": list(texts)},
            # top_n 取满候选数 = 要全排列；不要文档正文，省带宽也省解析。
            "parameters": {"top_n": len(texts), "return_documents": False},
        }
    return {"query": query, "texts": list(texts), "truncate": True}


def _extract_rows(payload: object, protocol: str) -> object:
    """从响应体里取出「命中的行列表」；结构不符返回 None（由调用方按畸形处理）。"""
    if protocol != "dashscope":
        return payload
    if not isinstance(payload, dict):
        return None
    output = payload.get("output")
    if not isinstance(output, dict):
        return None
    return output.get("results")


def _normalize_score(protocol: str, raw: float) -> float:
    """精排原始分 → [0, 1]（r121）。

    - `dashscope`：`relevance_score` 文档口径就是 [0,1] 的相关性分，原值透传；
    - `tei`：`score` 是交叉编码器的 **logit**（可负、可远大于 1），过 sigmoid 映射。
    越界值（协议假设被打破）统一走 sigmoid 兜底，clamp 到 ±60 防 `math.exp` 溢出。
    """
    if protocol == "dashscope" and 0.0 <= raw <= 1.0:
        return round(raw, 6)
    clamped = max(-60.0, min(60.0, raw))
    return round(1.0 / (1.0 + math.exp(-clamped)), 6)


def _parse_rows(rows: object, count: int) -> list[tuple[int, float]]:
    """响应行 → `[(输入下标, 原始分)]`，保持服务返回的顺序（正常即分数降序）。

    非排列（缺号 / 越界 / 重复）一律抛 ValueError；两种协议的分数键名不同，
    统一按 `score` → `relevance_score` 取值。
    """
    if not isinstance(rows, list) or len(rows) != count:
        raise ValueError("rerank 响应条数与候选不一致")
    seen: set[int] = set()
    parsed: list[tuple[int, float]] = []
    for row in rows:
        if not isinstance(row, dict) or "index" not in row:
            raise ValueError("rerank 响应行缺少 index")
        index = int(row["index"])
        if not 0 <= index < count or index in seen:
            raise ValueError("rerank 响应的 index 不是候选下标的排列")
        seen.add(index)
        try:
            score = float(row.get("score", row.get("relevance_score", 0.0)))
        except (TypeError, ValueError):
            raise ValueError("rerank 响应行的分数不可解析") from None
        parsed.append((index, score))
    return parsed


def _order_from_response(rows: object, count: int) -> list[int]:
    """只取重排顺序（r119 调用点 / 单测用）：`_parse_rows` 的薄封装。"""
    return [index for index, _ in _parse_rows(rows, count)]


def rerank_order(
    query: str, texts: list[str], runtime: RerankRuntime
) -> tuple[list[tuple[int, float]], str]:
    """调精排端点，返回 `([(输入下标, 归一化后的精排分)], notice)`。

    - 成功：`(按精排分降序的列表, "")` —— 分数已归一到 0~1，调用方应据此重写 `score`；
    - 失败 / 超时 / 畸形响应：`(原序且分数全 0 的列表, 中文 notice)` —— fail-open，
      绝不抛到检索层之上；此时调用方保留原有分数（见 `hybrid.search_chunks`）。
    """
    identity = [(index, 0.0) for index in range(len(texts))]
    protocol = runtime.protocol
    url = runtime.base_url if protocol == "dashscope" else runtime.base_url + "/rerank"
    payload = _payload_for(protocol, query, texts)
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if protocol == "dashscope":
        payload["model"] = runtime.model
        if runtime.api_key:
            headers["Authorization"] = f"Bearer {runtime.api_key}"
    try:
        response = httpx.post(url, json=payload, headers=headers, timeout=runtime.timeout_s)
    except httpx.HTTPError as exc:
        logger.warning("rag.rerank.unavailable protocol=%s error=%s", protocol, type(exc).__name__)
        return identity, "rerank 精排暂不可用，已按融合排序返回"
    if response.status_code != 200:
        logger.warning("rag.rerank.http_error protocol=%s status=%s", protocol, response.status_code)
        return identity, "rerank 精排服务返回异常，已按融合排序返回"
    try:
        parsed = _parse_rows(_extract_rows(response.json(), protocol), len(texts))
    except (ValueError, TypeError) as exc:
        logger.warning("rag.rerank.malformed_response protocol=%s detail=%s", protocol, exc)
        return identity, "rerank 精排响应异常，已按融合排序返回"
    return [(index, _normalize_score(protocol, raw)) for index, raw in parsed], ""
