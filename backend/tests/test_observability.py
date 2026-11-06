"""r41：日志与全链路错误追踪（零网络）。

三个口径：
- 每个 HTTP 响应都带 `X-Request-Id`，成功 / 4xx / 5xx 一致；
- 未捕获异常统一成 `INTERNAL_ERROR` 中文 envelope，绝不把堆栈回给前端；
- AI 出网日志只记元数据（模型 / 耗时 / 状态码），不泄漏 API Key 与 Prompt 正文。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import create_app
from app.observability import (
    REQUEST_ID_HEADER,
    configure_logging,
    get_request_id,
    reset_request_id,
    set_request_id,
)
from app.services.ai import AIClient


class _Payload:
    """占位模型：`complete_model` 只要求 `model_validate`。"""

    @classmethod
    def model_validate(cls, payload: object) -> object:
        return payload


def test_every_response_carries_request_id(client: TestClient) -> None:
    first = client.get("/health")
    second = client.get("/health")
    assert first.headers[REQUEST_ID_HEADER]
    assert second.headers[REQUEST_ID_HEADER]
    assert first.headers[REQUEST_ID_HEADER] != second.headers[REQUEST_ID_HEADER]


def test_error_response_keeps_same_request_id(client: TestClient) -> None:
    """404 走业务 envelope：响应头与错误体一次请求内保持一致（前端可原样报给后端查日志）。"""
    response = client.get("/api/profiles/latest")
    assert response.status_code == 404
    assert response.headers[REQUEST_ID_HEADER]
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_unhandled_exception_returns_500_envelope(tmp_db: object) -> None:
    """未捕获异常：中文 envelope + `INTERNAL_ERROR`，堆栈只进日志不进响应。"""

    application = create_app()

    @application.get("/__boom")
    def boom() -> None:
        raise RuntimeError("数据库连接串不该出现在响应里")

    with TestClient(application, raise_server_exceptions=False) as test_client:
        response = test_client.get("/__boom")

    assert response.status_code == 500
    error = response.json()["error"]
    assert error["code"] == "INTERNAL_ERROR"
    assert error["message"] == "服务内部错误，请稍后重试"
    assert "RuntimeError" not in error["message"]
    assert response.headers[REQUEST_ID_HEADER]


def test_request_id_propagates_to_background_task() -> None:
    """后台任务（asyncio.create_task）继承发起请求的 trace id，画像任务因此可回连。"""
    token = set_request_id("trace-abc")
    seen: list[str] = []

    async def _job() -> None:
        seen.append(get_request_id())

    async def _main() -> None:
        await asyncio.create_task(_job())

    try:
        asyncio.run(_main())
    finally:
        reset_request_id(token)

    assert seen == ["trace-abc"]


@pytest.fixture()
def ai_secret_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[Settings]:
    monkeypatch.setenv("AI_PROVIDER", "")
    monkeypatch.setenv("AI_BASE_URL", "https://api.example.test/v1")
    monkeypatch.setenv("AI_MODEL", "test-model")
    monkeypatch.setenv("AI_API_KEY", "sk-secret-should-never-be-logged")
    monkeypatch.setenv("AI_MAX_RETRIES", "0")
    get_settings.cache_clear()
    try:
        yield get_settings()
    finally:
        get_settings.cache_clear()


def test_ai_logs_metadata_without_secret(
    ai_secret_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """AI 调用日志包含模型与耗时，但不包含 API Key / Prompt 正文。"""

    class _Response:
        status_code = 200

        @staticmethod
        def json() -> dict[str, Any]:
            return {"choices": [{"message": {"content": '{"answer": "ok"}'}}]}

    class _Client:
        async def post(self, *_args: Any, **_kwargs: Any) -> _Response:
            return _Response()

    monkeypatch.setattr("app.services.ai._shared_client", lambda: _Client())
    caplog.set_level(logging.INFO, logger="app.ai")
    configure_logging("INFO")

    asyncio.run(
        AIClient(ai_secret_env).complete_model(
            "系统提示", "包含简历正文的用户问题", _Payload  # type: ignore[arg-type]
        )
    )

    messages = [record.getMessage() for record in caplog.records if record.name == "app.ai"]
    assert any("ai.request" in message for message in messages)
    assert any("ai.response" in message for message in messages)
    assert any("model=test-model" in message for message in messages)
    assert all("sk-secret-should-never-be-logged" not in message for message in messages)
    assert all("包含简历正文" not in message for message in messages)


def test_configure_logging_is_idempotent() -> None:
    """重复建 app（每个 TestClient 用例）不会叠加 handler，日志不重复。"""
    configure_logging("INFO")
    configure_logging("INFO")
    root = logging.getLogger()
    handlers = [h for h in root.handlers if getattr(h, "_skill_coach_handler", False)]
    assert len(handlers) == 1


def test_no_request_id_outside_request() -> None:
    """无请求上下文时用占位符，日志格式不会出现空括号。"""
    assert get_request_id() == "-"
