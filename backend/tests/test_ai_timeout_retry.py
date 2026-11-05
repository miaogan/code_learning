"""r34：画像生成超时治理的行为用例（零网络）。

两个口径：
- `complete_model(retry_unavailable=True)` 只在调用点显式开启时重试「可重试」失败
  （超时 / 5xx / 429）；不可重试（鉴权 / 额度）即使开启也不重试，避免重复扣配额。
- `generate_profile` 必须用专用长超时（`PROFILE_TIMEOUT_S`）：生成是后台任务，
  长简历输出大 JSON 远超通用 20s 超时，用户实测报「AI 服务响应超时」。
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from pydantic import BaseModel

from app.config import Settings, get_settings
from app.errors import AI_UNAVAILABLE, AppError
from app.services import profile as profile_service
from app.services.ai import AIClient
from app.services.profile import PROFILE_TIMEOUT_S, generate_profile


class _Payload(BaseModel):
    answer: str


class _Transport:
    """按队列决定第 N 次出网是超时、拒绝还是正常返回。"""

    def __init__(self) -> None:
        self.calls = 0
        self.timeouts = 0
        self.status_code = 200
        self.content = '{"answer": "ok"}'

    def will_timeout(self, count: int) -> _Transport:
        self.timeouts = count
        return self

    def will_reject(self, status_code: int) -> _Transport:
        self.status_code = status_code
        return self


@pytest.fixture()
def transport(monkeypatch: pytest.MonkeyPatch) -> _Transport:
    state = _Transport()

    class _Response:
        def __init__(self) -> None:
            self.status_code = state.status_code
            self._content = state.content

        def json(self) -> dict[str, Any]:
            return {"choices": [{"message": {"content": self._content}}]}

    class _Client:
        def __init__(self, *_args: Any, **kwargs: Any) -> None:
            self._timeout = kwargs.get("timeout")

        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *_exc: object) -> bool:
            return False

        async def post(self, *_args: Any, **_kwargs: Any) -> _Response:
            state.calls += 1
            if state.timeouts > 0:
                state.timeouts -= 1
                raise httpx.ConnectTimeout("timed out")
            return _Response()

    monkeypatch.setattr("app.services.ai.httpx.AsyncClient", _Client)
    return state


@pytest.fixture()
def ai_settings(monkeypatch: pytest.MonkeyPatch, neutral_ai_env: None) -> Callable[..., Settings]:
    def _apply(**values: str) -> Settings:
        for name, value in values.items():
            monkeypatch.setenv(name, value)
        get_settings.cache_clear()
        return get_settings()

    return _apply


def _complete(settings: Settings, *, retry_unavailable: bool) -> _Payload:
    return asyncio.run(
        AIClient(settings).complete_model(
            "系统提示", "用户问题", _Payload, retry_unavailable=retry_unavailable
        )
    )


def test_timeout_retried_once_when_enabled(
    transport: _Transport, ai_settings: Callable[..., Settings]
) -> None:
    """后台任务口径：第一次超时，自动重来一次并成功。"""
    transport.will_timeout(1)
    settings = ai_settings(
        AI_BASE_URL="https://api.example.com/v1",
        AI_MODEL="m",
        AI_API_KEY="k",
        AI_MAX_RETRIES="1",
    )

    assert _complete(settings, retry_unavailable=True).answer == "ok"
    assert transport.calls == 2


def test_timeout_not_retried_for_interactive_calls(
    transport: _Transport, ai_settings: Callable[..., Settings]
) -> None:
    """前台交互口径不变：不开启时一次超时立即失败，不让用户等待翻倍。"""
    transport.will_timeout(1)
    settings = ai_settings(
        AI_BASE_URL="https://api.example.com/v1",
        AI_MODEL="m",
        AI_API_KEY="k",
        AI_MAX_RETRIES="1",
    )

    with pytest.raises(AppError) as excinfo:
        _complete(settings, retry_unavailable=False)

    assert excinfo.value.code == AI_UNAVAILABLE
    assert excinfo.value.message == "AI 服务响应超时，请稍后重试"
    assert transport.calls == 1


def test_non_retryable_rejection_not_retried(
    transport: _Transport, ai_settings: Callable[..., Settings]
) -> None:
    """鉴权 / 额度类拒绝（retryable=False）即使开启重试也不重发，避免重复扣配额。"""
    transport.will_reject(401)
    settings = ai_settings(
        AI_BASE_URL="https://api.example.com/v1",
        AI_MODEL="m",
        AI_API_KEY="k",
        AI_MAX_RETRIES="1",
    )

    with pytest.raises(AppError) as excinfo:
        _complete(settings, retry_unavailable=True)

    assert excinfo.value.retryable is False
    assert transport.calls == 1


def test_generate_profile_uses_dedicated_long_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """画像生成必须显式传长超时且开启重试 —— 通用 20s 对真实简历不够。"""
    captured: dict[str, Any] = {}

    class _Client:
        async def complete_model(self, *_args: Any, **kwargs: Any) -> Any:
            captured.update(kwargs)
            raise AppError(AI_UNAVAILABLE, "提前返回，只验参", status=503)

    with pytest.raises(AppError):
        asyncio.run(generate_profile("res-1", "技能：Python", client=_Client()))  # type: ignore[arg-type]

    assert captured["timeout_s"] == PROFILE_TIMEOUT_S
    assert captured["retry_unavailable"] is True
    assert PROFILE_TIMEOUT_S >= 60, "长简历生成远超 20s，专用超时必须显著大于通用值"
    assert profile_service.PROFILE_TIMEOUT_S is PROFILE_TIMEOUT_S
