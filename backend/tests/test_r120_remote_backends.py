"""r120：云端 embedding / rerank 带来的两处形态变化。

1. 公网 SaaS 端点不该被 `/health` 探活 —— 它的 `/health` 必然 404，会把 `rag_embedder`
   永久报成 down（误报），还每 60 秒往公网打一次无用请求。
2. 自建 / 内网端点仍然探活（r105 行为不变）。
"""

from __future__ import annotations

from typing import Any

import pytest

from app.core.config import Settings
from app.main import _embedder_probe_state, _probe_target_is_self_hosted


@pytest.mark.parametrize(
    ("base", "expected"),
    (
        ("http://embedder:8080", True),  # compose 服务名（单标签主机名）
        ("http://reranker:8080", True),
        ("http://10.0.12.8:8080", True),  # 私网 IP
        ("http://192.168.1.9", True),
        ("http://127.0.0.1:9000", True),
        ("https://dashscope.aliyuncs.com/compatible-mode", False),  # 公网 SaaS
        ("https://api.deepseek.com/v1", False),
        ("", False),
    ),
)
def test_probe_target_detection(base: str, expected: bool) -> None:
    assert _probe_target_is_self_hosted(base) is expected


def test_probe_skips_public_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    """公网端点：返回 na，且一次网络都不发。"""
    called: list[str] = []

    def boom(*args: Any, **kwargs: Any) -> Any:
        called.append("called")
        raise AssertionError("公网端点不应被探活")

    monkeypatch.setattr("app.main.httpx.get", boom)
    monkeypatch.setattr(
        "app.main.get_settings",
        lambda: Settings(
            ai_embed_model="qwen3.7-text-embedding-flash",
            ai_embed_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        ),
    )
    assert _embedder_probe_state() == "na"
    assert called == []


def test_probe_still_probes_self_hosted(monkeypatch: pytest.MonkeyPatch) -> None:
    """内网自建端点：r105 行为不变，真探一次。"""
    seen: list[str] = []

    def fake_get(url: str, **kwargs: Any) -> Any:
        seen.append(url)
        return type("Resp", (), {"status_code": 200})()

    monkeypatch.setattr("app.main.httpx.get", fake_get)
    monkeypatch.setattr("app.main._EMBEDDER_PROBE", {"state": "na", "checked_at": 0.0})
    monkeypatch.setattr(
        "app.main.get_settings",
        lambda: Settings(ai_embed_model="BAAI/bge-small-zh-v1.5", ai_embed_base_url="http://embedder:8080/v1"),
    )
    assert _embedder_probe_state() == "up"
    assert seen == ["http://embedder:8080/health"]
