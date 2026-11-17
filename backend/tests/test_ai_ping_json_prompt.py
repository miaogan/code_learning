"""「测试连接」探测语与 4xx 归因回归（2026-11-14 实测）。

背景：DeepSeek / OpenAI 在 `response_format={"type":"json_object"}` 下要求消息里出现
"json" 字样，否则直接 400（`Prompt must contain the word 'json' in some form`）。
旧的探测语「请只回复 OK 两个字母」不带该字样，Key 完全正确也会报「被拒绝」，
而当时的 4xx 文案又一律说「请检查 API Key 与额度」，用户会一直以为 Key 填错了。

这里钉住两件事：①探测语与请求体必须自带 json 字样；②4xx 按状态码归因，
参数错误不再甩给 Key。用例不出网、不碰数据库（Fake 连接池 + 屏蔽调用日志）。
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.core.config import AiRuntime
from app.core.errors import AppError
from app.services.ai import ai as ai_module
from app.services.ai.ai import PING_SYSTEM, PING_USER, AIClient, _rejected_message


def _runtime(json_mode: str = "json_object") -> AiRuntime:
    return AiRuntime(
        provider="user",
        base_url="https://api.example.test/v1",
        model="m",
        api_key="k",
        json_mode=json_mode,
        timeout_s=8.0,
        max_retries=0,
        ready=True,
    )


class _Response:
    def __init__(self, status_code: int = 200, content: str = '{"ok": true}') -> None:
        self.status_code = status_code
        self._content = content

    def json(self) -> dict[str, Any]:
        return {"choices": [{"message": {"content": self._content}}]}


class _FakePool:
    def __init__(self, response: _Response) -> None:
        self.response = response
        self.payloads: list[dict[str, Any]] = []

    async def post(self, _url: str, **kwargs: Any) -> _Response:
        self.payloads.append(kwargs["json"])
        return self.response


@pytest.fixture()
def fake_pool(monkeypatch: pytest.MonkeyPatch) -> Any:
    def _apply(response: _Response | None = None) -> _FakePool:
        pool = _FakePool(response or _Response())
        monkeypatch.setattr(ai_module, "_shared_client", lambda: pool)
        monkeypatch.setattr(ai_module, "_persist_call_log", lambda *_a, **_kw: None)
        return pool

    return _apply


def _messages_text(payload: dict[str, Any]) -> str:
    return " ".join(str(message["content"]) for message in payload["messages"])


def test_ping_prompt_contains_json_word() -> None:
    """静态门禁：以后谁把探测语改回「请只回复 OK」，这里立刻红。"""
    assert "json" in PING_SYSTEM.lower()
    assert "json" in PING_USER.lower()


def test_ping_request_has_json_word_in_messages(fake_pool: Any) -> None:
    pool = fake_pool()
    asyncio.run(AIClient(runtime=_runtime()).ping())
    payload = pool.payloads[0]
    assert "json" in _messages_text(payload).lower()
    assert payload["response_format"] == {"type": "json_object"}


def test_ping_with_json_mode_none_still_has_json_word(fake_pool: Any) -> None:
    """`none` 模式整键不发 response_format，但探测语口径保持一致。"""
    pool = fake_pool()
    asyncio.run(AIClient(runtime=_runtime("none")).ping())
    payload = pool.payloads[0]
    assert "response_format" not in payload
    assert "json" in _messages_text(payload).lower()


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (400, "请求参数不被模型接受"),
        (401, "API Key 无效"),
        (403, "API Key 无效"),
        (402, "额度不足"),
        (418, "AI 调用被拒绝"),
    ],
)
def test_rejected_message_is_attributed_by_status(status: int, expected: str) -> None:
    message = _rejected_message(_runtime(), status)
    assert expected in message
    if status == 400:
        assert "API Key 与额度" not in message
        assert "模型名" in message
    assert "https://" not in message  # 文案不得带端点


def test_request_400_surfaces_parameter_hint(fake_pool: Any) -> None:
    fake_pool(_Response(status_code=400))
    with pytest.raises(AppError) as exc:
        asyncio.run(AIClient(runtime=_runtime())._request("system", "user"))
    assert "模型名" in exc.value.message
    assert "API Key 无效" not in exc.value.message
