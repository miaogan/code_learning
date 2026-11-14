"""r99：用户自带 AI 端点的 SSRF 防护回归。

背景：公网部署实测发现 `POST /api/me/ai/test` 会拿表单里的 `base_url` 直接发 POST，
且该端点不经过 `normalize_ai_settings`，可用来探测内网端口 / 云元数据。
本文件钉住两条入口（保存设置、测试连接）都必须拒绝不可出网地址。
"""

from __future__ import annotations

import asyncio
import socket
from typing import Any

import pytest

from app.core.errors import AppError
from app.services.ai.user_ai import (
    normalize_ai_settings,
    test_connection as run_test_connection,
    validate_public_base_url,
)

PRIVATE_URLS = (
    "http://127.0.0.1:1/v1",
    "http://127.0.0.1/v1",
    "http://localhost:1234/v1",
    "http://169.254.169.254/latest/meta-data",
    "http://10.0.0.5/v1",
    "http://172.16.0.1/v1",
    "http://192.168.1.1/v1",
    "http://0.0.0.0/v1",
    "http://[::1]/v1",
    "http://metadata.google.internal/v1",
)


@pytest.mark.parametrize("url", PRIVATE_URLS)
def test_validate_rejects_private_targets(url: str) -> None:
    with pytest.raises(AppError) as exc:
        validate_public_base_url(url)
    assert exc.value.status == 422
    assert "不允许指向本机" in exc.value.message


@pytest.mark.parametrize("url", PRIVATE_URLS)
def test_save_settings_rejects_private_targets(url: str) -> None:
    with pytest.raises(AppError):
        normalize_ai_settings(base_url=url, model="m", api_key="k", json_mode="json_object")


def test_scheme_still_validated() -> None:
    with pytest.raises(AppError) as exc:
        validate_public_base_url("ftp://example.com/v1")
    assert "http:// 或 https://" in exc.value.message


def test_public_ip_literal_allowed() -> None:
    assert validate_public_base_url("https://1.1.1.1/v1") == "https://1.1.1.1/v1"


def test_unresolvable_host_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    """DNS 解析失败时放行：请求同样发不出去，且离线测试桩要保持可用。"""

    def _no_dns(*_args: object, **_kwargs: object) -> None:
        raise socket.gaierror("no dns")

    monkeypatch.setattr("app.services.ai.user_ai.socket.getaddrinfo", _no_dns)
    assert validate_public_base_url("https://api.example.test/v1") == "https://api.example.test/v1"


def test_test_connection_blocks_private_before_any_request(monkeypatch: pytest.MonkeyPatch) -> None:
    """测试连接端点独立校验；被挡时不得构造 AIClient，更不得出网。"""

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("不应构造 AIClient / 发起网络请求")

    monkeypatch.setattr("app.services.ai.user_ai.AIClient", _boom)
    ok, message = asyncio.run(
        run_test_connection(
            base_url="http://169.254.169.254/v1",
            model="m",
            api_key="k",
            json_mode="json_object",
            stored_key="",
        )
    )
    assert ok is False
    assert "不允许指向本机" in message


def test_test_connection_timeout_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    """连通性探测不能继承 AI_TIMEOUT_S=600，否则一次失败就挂住 10 分钟。"""
    captured: dict[str, float] = {}

    class _FakeClient:
        def __init__(self, runtime: Any) -> None:
            captured["timeout"] = float(runtime.timeout_s)

        async def ping(self) -> None:
            return None

    monkeypatch.setattr("app.services.ai.user_ai.AIClient", _FakeClient)
    ok, _ = asyncio.run(
        run_test_connection(
            base_url="https://1.1.1.1/v1",
            model="m",
            api_key="k",
            json_mode="json_object",
            stored_key="",
        )
    )
    assert ok is True
    assert captured["timeout"] <= 8.0
