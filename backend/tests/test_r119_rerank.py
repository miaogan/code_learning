"""r119 rerank 精排单测（零网络）：客户端解析、排列校验、fail-open 与检索接线。

rerank 是可选层：`AI_RERANK_BASE_URL` 留空时检索行为必须与 r100 逐字节一致——
「未配置零行为变化」本身就是这里最重要的用例。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from app.core.config import Settings
from app.services.retrieval import hybrid
from app.services.retrieval.rerank import (
    MAX_RERANK_POOL,
    _order_from_response,
    rerank_order,
    resolve_reranker,
)

# --- resolve_reranker：配置解析 ---------------------------------------------------


def test_resolve_reranker_default_is_off() -> None:
    """留空 = 不精排（返回 None），检索管线零出网。"""
    assert resolve_reranker(Settings(ai_rerank_base_url="")) is None


def test_resolve_reranker_normalizes_and_clamps() -> None:
    runtime = resolve_reranker(Settings(ai_rerank_base_url=" http://rerank:8080/ "))
    assert runtime is not None
    assert runtime.base_url == "http://rerank:8080"
    assert runtime.timeout_s >= 1.0
    assert runtime.pool == MAX_RERANK_POOL  # 超上限一律钳回（容器 2g 限额的约束）


# --- _order_from_response：排列校验 ------------------------------------------------


def test_order_accepts_valid_permutation() -> None:
    assert _order_from_response(
        [{"index": 2, "score": 0.9}, {"index": 0, "score": 0.5}, {"index": 1, "score": 0.1}], 3
    ) == [2, 0, 1]


@pytest.mark.parametrize(
    "rows",
    (
        [{"index": 0}, {"index": 0}],  # 重复
        [{"index": 0}, {"index": 3}],  # 越界
        [{"index": 0}],  # 缺号
        "not-a-list",
        [{"score": 0.5}],  # 缺 index
    ),
)
def test_order_rejects_malformed_responses(rows: Any) -> None:
    with pytest.raises(ValueError):
        _order_from_response(rows, 2)


# --- rerank_order：fail-open 三态 ---------------------------------------------------


def _runtime() -> Any:
    return resolve_reranker(Settings(ai_rerank_base_url="http://rerank:8080"))


def test_rerank_order_success(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_post(url: str, **kwargs: Any) -> Any:
        assert url == "http://rerank:8080/rerank"
        assert kwargs["json"]["query"] == "q"
        assert kwargs["json"]["texts"] == ["a", "b", "c"]
        return httpx.Response(
            200, json=[{"index": 2, "score": 1.0}, {"index": 0, "score": 0.2}, {"index": 1, "score": 0.0}]
        )

    monkeypatch.setattr("app.services.retrieval.rerank.httpx.post", fake_post)
    order, notice = rerank_order("q", ["a", "b", "c"], _runtime())
    assert (order, notice) == ([2, 0, 1], "")


def test_rerank_order_http_error_fails_open(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(url: str, **kwargs: Any) -> Any:
        raise httpx.ConnectError("down")

    monkeypatch.setattr("app.services.retrieval.rerank.httpx.post", boom)
    order, notice = rerank_order("q", ["a", "b"], _runtime())
    assert (order, notice) == ([0, 1], "rerank 精排暂不可用，已按融合排序返回")


def test_rerank_order_bad_status_fails_open(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.retrieval.rerank.httpx.post",
        lambda url, **kwargs: httpx.Response(503, json={}),
    )
    order, notice = rerank_order("q", ["a"], _runtime())
    assert (order, notice) == ([0], "rerank 精排服务返回异常，已按融合排序返回")


def test_rerank_order_malformed_fails_open(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.retrieval.rerank.httpx.post",
        lambda url, **kwargs: httpx.Response(200, json=[{"index": 0}, {"index": 0}]),
    )
    order, notice = rerank_order("q", ["a", "b"], _runtime())
    assert (order, notice) == ([0, 1], "rerank 精排响应异常，已按融合排序返回")


# --- search_chunks 接线：池取宽、精排序、fail-open、keyword 不精排 -------------------


def _lexical_rows(count: int) -> list[dict[str, Any]]:
    return [
        {
            "id": f"question:{i}",
            "kind": "question",
            "ref_id": str(i),
            "section_id": "",
            "title": f"题 {i}",
            "content": f"第 {i} 题的正文",
        }
        for i in range(count)
    ]


def _patch_search(
    monkeypatch: pytest.MonkeyPatch,
    *,
    rerank_result: tuple[list[int], str] | None,
    lexical_count: int,
) -> dict[str, Any]:
    """打桩 repository / 向量后端 / rerank，跑一次 hybrid 检索并返回响应。

    `rerank_result=None` 表示不配置精排（resolve_reranker 返回 None）。
    """
    from app.core.config import get_settings

    settings = Settings(
        ai_rerank_base_url="http://rerank:8080" if rerank_result is not None else ""
    )
    get_settings.cache_clear()
    monkeypatch.setattr(hybrid, "resolve_reranker", lambda: resolve_reranker(settings))
    monkeypatch.setattr(
        hybrid, "resolve_vector_store",
        lambda: SimpleNamespace(store=None, engine="none", ready=False, reason="", mode="sqlite"),
    )
    monkeypatch.setattr(hybrid.repository, "rag_state_get", lambda: {"embedder": "hash-bigram-256", "built_at": "t"})
    monkeypatch.setattr(hybrid.repository, "rag_lexical_search", lambda *a, **k: _lexical_rows(lexical_count))
    monkeypatch.setattr(hybrid.repository, "rag_feedback_weights", lambda *a, **k: {})
    seen: dict[str, Any] = {}

    def fake_rerank_order(query: str, texts: list[str], runtime: Any) -> tuple[list[int], str]:
        seen["texts"] = list(texts)
        assert texts == [row["content"] for row in _lexical_rows(len(texts))]
        return rerank_result if rerank_result is not None else (list(range(len(texts))), "")

    monkeypatch.setattr(hybrid, "rerank_order", fake_rerank_order)
    try:
        return hybrid.search_chunks("查询词", mode="hybrid", top_k=2)
    finally:
        get_settings.cache_clear()


def test_search_hybrid_with_rerank_reorders_and_widens_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """精排启用：池从 top_k=2 取宽到 size*2=4，按精排序输出，reranked=True。"""
    # 语义腿打桩后为空，融合序 = 关键词腿序（0,1,2,3）；精排故意倒序。
    result = _patch_search(
        monkeypatch, rerank_result=([3, 2, 1, 0], ""), lexical_count=4
    )
    assert result["reranked"] is True
    assert [item["chunk_id"] for item in result["items"]] == [
        "question:3", "question:2", "question:1", "question:0"
    ][:2]
    assert result["total"] == 2


def test_search_hybrid_rerank_failure_fails_open(monkeypatch: pytest.MonkeyPatch) -> None:
    """精排失败：融合序原样返回、reranked=False、notice 说清原因，反馈加权照常生效。"""
    result = _patch_search(
        monkeypatch, rerank_result=(list(range(4)), "rerank 精排暂不可用，已按融合排序返回"), lexical_count=4
    )
    assert result["reranked"] is False
    assert "rerank 精排暂不可用" in result["notice"]
    assert [item["chunk_id"] for item in result["items"]] == ["question:0", "question:1"]


def test_search_hybrid_without_rerank_keeps_r100_behavior(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """未配置精排：rerank_order 不被调用，reranked=False，行为与 r100 一致。"""
    result = _patch_search(monkeypatch, rerank_result=None, lexical_count=4)
    assert result["reranked"] is False
    assert [item["chunk_id"] for item in result["items"]] == ["question:0", "question:1"]


def test_keyword_mode_never_reranks(monkeypatch: pytest.MonkeyPatch) -> None:
    """keyword 是纯 ILIKE 对照面：即使配置了精排也不动它。"""
    called: list[str] = []
    settings = Settings(ai_rerank_base_url="http://rerank:8080")
    monkeypatch.setattr(hybrid, "resolve_reranker", lambda: resolve_reranker(settings))
    monkeypatch.setattr(
        hybrid, "rerank_order",
        lambda *a, **k: called.append("called") or ([0], ""),
    )
    monkeypatch.setattr(hybrid.repository, "rag_lexical_search", lambda *a, **k: _lexical_rows(3))
    monkeypatch.setattr(hybrid.repository, "rag_feedback_weights", lambda *a, **k: {})
    result = hybrid.search_chunks("查询词", mode="keyword", top_k=2)
    assert called == []
    assert result["reranked"] is False


# --- r120 DashScope 协议 -----------------------------------------------------------

_DASHSCOPE_URL = "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank"


def _dashscope_runtime(**overrides: Any) -> Any:
    params: dict[str, Any] = {
        "ai_rerank_base_url": _DASHSCOPE_URL,
        "ai_rerank_protocol": "dashscope",
        "ai_rerank_model": "qwen3.7-text-rerank",
    }
    params.update(overrides)
    return resolve_reranker(Settings(**params))


def test_resolve_reranker_dashscope_requires_model() -> None:
    """dashscope 缺 model = 未配置（返回 None），避免每次检索发一个必然 400 的请求。"""
    assert _dashscope_runtime(ai_rerank_model="") is None
    assert _dashscope_runtime() is not None


def test_resolve_reranker_api_key_inherits_embed_tier() -> None:
    """同一云端账号只填一次 Key：rerank 留空时继承 embed 档。"""
    runtime = _dashscope_runtime(ai_embed_api_key="sk-from-embed")
    assert runtime is not None
    assert runtime.api_key == "sk-from-embed"
    assert _dashscope_runtime(ai_rerank_api_key="sk-own").api_key == "sk-own"


def test_resolve_reranker_unknown_protocol_falls_back_to_tei() -> None:
    runtime = resolve_reranker(
        Settings(ai_rerank_base_url="http://rerank:8080", ai_rerank_protocol="grpc")
    )
    assert runtime is not None and runtime.protocol == "tei"


def test_rerank_order_dashscope_success(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_post(url: str, **kwargs: Any) -> Any:
        # dashscope 协议的 base_url 是完整端点，不能再拼 /rerank
        assert url == _DASHSCOPE_URL
        assert kwargs["json"]["model"] == "qwen3.7-text-rerank"
        assert kwargs["json"]["input"] == {"query": "q", "documents": ["a", "b", "c"]}
        assert kwargs["json"]["parameters"] == {"top_n": 3, "return_documents": False}
        assert kwargs["headers"]["Authorization"] == "Bearer sk-x"
        return httpx.Response(
            200,
            json={
                "output": {
                    "results": [
                        {"index": 1, "relevance_score": 0.9},
                        {"index": 2, "relevance_score": 0.5},
                        {"index": 0, "relevance_score": 0.1},
                    ]
                }
            },
        )

    monkeypatch.setattr("app.services.retrieval.rerank.httpx.post", fake_post)
    order, notice = rerank_order("q", ["a", "b", "c"], _dashscope_runtime(ai_rerank_api_key="sk-x"))
    assert (order, notice) == ([1, 2, 0], "")


@pytest.mark.parametrize(
    "payload",
    (
        {"output": {"results": [{"index": 0}, {"index": 0}]}},  # 重复
        {"output": {"results": [{"index": 0}]}},  # 缺号
        {"output": {}},  # 没有 results
        {"results": [{"index": 0}, {"index": 1}]},  # 少一层 output
        [{"index": 0}, {"index": 1}],  # 裸 list（TEI 形态，协议不匹配）
    ),
)
def test_rerank_order_dashscope_malformed_fails_open(
    monkeypatch: pytest.MonkeyPatch, payload: Any
) -> None:
    monkeypatch.setattr(
        "app.services.retrieval.rerank.httpx.post",
        lambda url, **kwargs: httpx.Response(200, json=payload),
    )
    order, notice = rerank_order("q", ["a", "b"], _dashscope_runtime())
    assert order == [0, 1]
    assert notice == "rerank 精排响应异常，已按融合排序返回"
