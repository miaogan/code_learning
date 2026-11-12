"""r83 太傅 agent 化：流式出网、工具取料、图编排、AI SDK 协议。

覆盖四层，每层只测自己那一层：
- `ai_sdk`：纯函数编码，不需要网络与库；
- `AIClient.stream_chat`：喂假 SSE 文本，验证分片 tool_calls 的拼接与非 SSE 回退；
- `tools`：命中 / 未命中的取料口径，`remember` 的上限；
- `graph` + 端点：工具轮次、引用来源、协议帧序列。

异步用例统一 `asyncio.run`（与 `tests/test_ai_timeout_retry.py` 同一写法）：本项目没装 anyio。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core import repository
from app.core.config import get_settings
from app.schemas import ResumeMeta
from app.services.ai.ai import AIClient
from app.services.taifu import ai_sdk, graph, policy, tools

RESUME_TEXT = "负责接口开发，维护订单系统。\n负责线上问题排查，日均处理 20 个工单。"


# --- 编码器 -----------------------------------------------------------------


def test_encoder_emits_protocol_frames_in_order() -> None:
    encoder = ai_sdk.StreamEncoder("msg_1")

    frames = encoder.start()
    frames += encoder.encode({"type": "meta", "materials": 3, "memories_used": 1})
    frames += encoder.encode({"type": "token", "delta": "先补"})
    frames += encoder.encode({"type": "token", "delta": "部署。"})
    frames += encoder.finish()

    types = [json.loads(item[len("data: ") :])["type"] for item in frames[:-1]]
    assert types == [
        "start",
        "data-meta",
        "text-start",
        "text-delta",
        "text-delta",
        "text-end",
        "finish",
    ]
    # 文本块只开一次：`useChat` 按 id 归组，重复 text-start 会切成两段。
    assert types.count("text-start") == 1
    assert frames[-1] == ai_sdk.DONE_FRAME


def test_encoder_terminates_exactly_once() -> None:
    encoder = ai_sdk.StreamEncoder()
    encoder.start()
    first = encoder.finish()
    second = encoder.finish()

    assert first[-1] == ai_sdk.DONE_FRAME
    assert second == []
    # 收尾后的事件一律丢弃：`[DONE]` 之后再有帧，`useChat` 会把它们当成新消息。
    assert encoder.encode({"type": "token", "delta": "迟到"}) == []


def test_encoder_maps_tool_events_to_protocol_parts() -> None:
    encoder = ai_sdk.StreamEncoder()
    frames = encoder.encode(
        {
            "type": "tool_start",
            "id": "c1",
            "name": "read_question_detail",
            "label": "错题明细",
            "input": {"question_id": "q-1"},
        }
    )
    frames += encoder.encode(
        {"type": "tool_end", "id": "c1", "ok": False, "label": "错题明细", "summary": "没有作答记录"}
    )

    parts = [json.loads(item[len("data: ") :]) for item in frames]
    assert [part["type"] for part in parts] == [
        "tool-input-start",
        "tool-input-available",
        "tool-output-available",
    ]
    assert parts[1]["input"]["arguments"] == {"question_id": "q-1"}
    # 读不到也是一条结果：`ok=False` 送到前端，卡片显示「没读到」，而不是当异常吞掉。
    assert parts[2]["output"]["ok"] is False


def test_encoder_reports_errors_as_error_part() -> None:
    encoder = ai_sdk.StreamEncoder()
    frames = encoder.encode({"type": "error", "message": "AI 服务响应超时，请稍后重试"})

    payload = json.loads(frames[0][len("data: ") :])
    assert payload == {"type": "error", "errorText": "AI 服务响应超时，请稍后重试"}


# --- stream_chat ------------------------------------------------------------


class _FakeResponse:
    def __init__(self, lines: list[str], *, content_type: str = "text/event-stream") -> None:
        self.status_code = 200
        self.headers = {"content-type": content_type}
        self._lines = lines

    async def aiter_lines(self) -> Any:
        for line in self._lines:
            yield line

    async def aread(self) -> bytes:
        return "\n".join(self._lines).encode()

    async def __aenter__(self) -> _FakeResponse:
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        return None


class _FakeHttpClient:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response

    def stream(self, *_args: Any, **_kwargs: Any) -> _FakeResponse:
        return self._response

    async def aclose(self) -> None:
        return None


@pytest.fixture()
def live_client(monkeypatch: pytest.MonkeyPatch, tmp_db: Any) -> Any:
    """一个「配置齐全」的 AIClient：`ready` 为真，出网由 `_install_stream` 换成假实现。"""
    monkeypatch.setenv("AI_API_KEY", "test-key-not-a-real-secret")
    get_settings.cache_clear()
    yield AIClient()
    get_settings.cache_clear()


def _install_stream(monkeypatch: pytest.MonkeyPatch, response: _FakeResponse) -> None:
    monkeypatch.setattr("app.services.ai.ai._shared_client", lambda: _FakeHttpClient(response))


async def _collect(client: AIClient, **kwargs: Any) -> list[dict[str, Any]]:
    return [
        event
        async for event in client.stream_chat(
            "系统", [{"role": "user", "content": "问"}], **kwargs
        )
    ]


def test_stream_chat_joins_fragmented_tool_calls(
    monkeypatch: pytest.MonkeyPatch, live_client: AIClient
) -> None:
    """真实上游把 tool_calls 拆成多片下发：`id` / `name` 只在首片，`arguments` 逐片拼。"""
    lines = [
        'data: {"choices":[{"delta":{"content":"我看看"}}]}',
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_a","function":'
        '{"name":"read_weakness_detail","arguments":"{\\"poi"}}]}}]}',
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":'
        '{"arguments":"nt\\":\\"事件循环\\"}"}}]}}]}',
        'data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}]}',
        "data: [DONE]",
    ]
    _install_stream(monkeypatch, _FakeResponse(lines))

    events = asyncio.run(_collect(live_client, tools=tools.TOOL_SPECS))

    assert events[0] == {"kind": "text", "text": "我看看"}
    assert events[1] == {
        "kind": "tool_call",
        "index": 0,
        "id": "call_a",
        "name": "read_weakness_detail",
        "arguments": '{"point":"事件循环"}',
    }
    assert events[-1]["kind"] == "done"


def test_stream_chat_falls_back_when_upstream_ignores_stream(
    monkeypatch: pytest.MonkeyPatch, live_client: AIClient
) -> None:
    """自建端点常忽略 `stream: true`：整包返回也要摊成同样的事件形状。"""
    body = {
        "choices": [
            {
                "message": {
                    "content": "按档案说。",
                    "tool_calls": [
                        {
                            "id": "call_b",
                            "type": "function",
                            "function": {"name": "compare_reports", "arguments": "{}"},
                        }
                    ],
                }
            }
        ]
    }
    _install_stream(
        monkeypatch, _FakeResponse([json.dumps(body)], content_type="application/json")
    )

    events = asyncio.run(_collect(live_client, tools=tools.TOOL_SPECS))

    assert events[0] == {"kind": "text", "text": "按档案说。"}
    assert events[1]["name"] == "compare_reports"
    assert events[-1]["kind"] == "done"


# --- 工具 -------------------------------------------------------------------


def _context(
    profile: Any, report: Any = None, attempts: list[dict[str, Any]] | None = None
) -> tools.ToolContext:
    return tools.ToolContext(
        profile=profile, report=report, attempts=attempts or [], memories=[]
    )


def test_tool_reports_missing_weakness_instead_of_guessing(profile_factory: Any) -> None:
    result = asyncio.run(
        tools.run("read_weakness_detail", '{"point":"不存在的分组"}', _context(profile_factory()))
    )

    assert result["ok"] is False
    assert result["href"] is None
    assert "未读到" in result["content"][0]


def test_tool_reads_resume_anchor_from_the_document(
    profile_factory: Any, tmp_db: Any
) -> None:
    # `tmp_db` 必须显式注入：`profile_factory` 只在内存里造对象，不碰库，
    # 缺了它这条用例会写进默认 DB_PATH 的持久库——首跑写进 `res-r83`，之后每次都撞主键。
    repository.insert_document(
        ResumeMeta(resume_id="res-r83", file_name="简历.txt", chars=len(RESUME_TEXT), sections=2),
        RESUME_TEXT,
    )
    result = asyncio.run(
        tools.run(
            "read_resume_anchor",
            '{"anchor_text":"负责接口开发"}',
            _context(profile_factory(resume_id="res-r83")),
        )
    )

    assert result["ok"] is True
    assert result["href"] == "/polish"
    assert any("负责接口开发" in line for line in result["content"])


def test_tool_refuses_unknown_tool_name() -> None:
    result = asyncio.run(tools.run("drop_database", "{}", _context(None)))

    assert result["ok"] is False
    assert "没有这个工具" in result["summary"]


def test_remember_is_capped_and_deduplicated() -> None:
    context = tools.ToolContext(profile=None, report=None, attempts=[], memories=[])

    async def _run_all() -> list[dict[str, Any]]:
        return [
            await tools.run("remember", '{"content":"只能周末学习，工作日要上班"}', context),
            await tools.run("remember", '{"content":"只能周末学习"}', context),
            await tools.run("remember", '{"content":"更想留在杭州"}', context),
            await tools.run("remember", '{"content":"已经排除算法岗"}', context),
        ]

    first, repeat, third, overflow = asyncio.run(_run_all())

    assert first["ok"] is True
    assert repeat["ok"] is False  # 互相包含即同一件事，不重复记
    assert third["ok"] is True
    assert overflow["ok"] is False  # 每轮上限 2 条
    assert context.memories_added == 2


# --- 图 ---------------------------------------------------------------------


class _ScriptedClient:
    """按脚本逐轮产出事件的假客户端：不联网、不依赖 model_cls。"""

    def __init__(self, rounds: list[list[dict[str, Any]]]) -> None:
        self._rounds = rounds
        self.calls = 0

    async def stream_chat(self, *_args: Any, **_kwargs: Any) -> Any:
        events = self._rounds[min(self.calls, len(self._rounds) - 1)]
        self.calls += 1
        for event in events:
            yield event

    async def complete_model(self, *_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("这一轮不该触发摘要补全")


def _text(value: str) -> list[dict[str, Any]]:
    return [{"kind": "text", "text": value}, {"kind": "done", "finish_reason": "stop"}]


def _tool(name: str, arguments: str = "{}") -> list[dict[str, Any]]:
    return [
        {
            "kind": "tool_call",
            "index": 0,
            "id": "call_0",
            "name": name,
            "arguments": arguments,
        },
        {"kind": "done", "finish_reason": "tool_calls"},
    ]


async def _events(
    question: str, client: Any, *, page: Any = None, focus: Any = None
) -> list[dict[str, Any]]:
    return [
        event
        async for event in graph.run_events(question, page=page, focus=focus, client=client)
    ]


def test_graph_answers_without_any_tool(profile_factory: Any) -> None:
    repository.insert_profile(profile_factory())
    client = _ScriptedClient([_text("先补部署。")])

    events = asyncio.run(_events("我先补什么", client))

    kinds = [event["type"] for event in events]
    assert kinds[0] == "meta"
    assert "tool_start" not in kinds
    assert kinds[-1] == "done"
    assert events[-1]["reply"] == "先补部署。"
    assert client.calls == 1


def test_graph_cites_only_what_the_tool_actually_read(profile_factory: Any) -> None:
    repository.insert_profile(profile_factory())
    client = _ScriptedClient(
        [_tool("read_weakness_detail", '{"point":"事件循环"}'), _text("错在微任务顺序。")]
    )

    events = asyncio.run(_events("这条怎么补", client))

    kinds = [event["type"] for event in events]
    assert kinds.count("tool_start") == 1
    assert kinds.count("tool_end") == 1
    # 没插报告时工具读不到料 → 不该凭空产生引用。
    failed = next(event for event in events if event["type"] == "tool_end")
    assert failed["ok"] is False
    citations = next(event for event in events if event["type"] == "citations")
    assert citations["items"] == []
    assert client.calls == 2


def test_graph_stops_after_the_tool_round_cap(profile_factory: Any) -> None:
    repository.insert_profile(profile_factory())
    # 模型每轮都要读料：不允许无限循环。
    client = _ScriptedClient([_tool("read_weakness_detail", '{"point":"事件循环"}')] * 5)

    events = asyncio.run(_events("这条怎么补", client))

    kinds = [event["type"] for event in events]
    assert kinds.count("tool_start") == graph.MAX_TOOL_ROUNDS
    assert "capped" in kinds
    # 到顶后仍再调一次模型（总要说句话），但不会执行第 4 轮工具。
    assert client.calls == graph.MAX_TOOL_ROUNDS + 1


def test_graph_skips_model_when_there_is_no_record(tmp_db: Any) -> None:
    client = _ScriptedClient([_text("不该被调用")])

    events = asyncio.run(_events("我先补什么", client))

    assert client.calls == 0
    assert events[-1]["notice"] == policy.EMPTY_BRIEF_NOTICE


# --- 端点 -------------------------------------------------------------------


def _frames(text: str) -> list[dict[str, Any]]:
    parsed: list[dict[str, Any]] = []
    for line in text.splitlines():
        if not line.startswith("data: "):
            continue
        raw = line[len("data: ") :].strip()
        if raw == "[DONE]":
            parsed.append({"type": "[DONE]"})
            continue
        parsed.append(json.loads(raw))
    return parsed


def test_encoder_gives_each_stream_its_own_message_id() -> None:
    """逐次唯一的 message id：共用一个常量会让第二条回答覆盖第一条。

    `useChat` 收到新消息是按 id 归位的（`findLastIndex(m => m.id === 新 id)` 命中就 replace），
    所以 id 撞了不是"显示两条"，而是**第一条被第二条顶掉**；React key 也会重复。
    """

    first = json.loads(ai_sdk.StreamEncoder().start()[0][len("data: ") :])
    second = json.loads(ai_sdk.StreamEncoder().start()[0][len("data: ") :])

    assert first["messageId"].startswith("msg_")
    assert first["messageId"] != second["messageId"]
    # 显式指定仍然生效：续流 / 重放要复用同一个 id，不能被随机值顶掉。
    fixed = json.loads(ai_sdk.StreamEncoder("msg_fixed").start()[0][len("data: ") :])
    assert fixed["messageId"] == "msg_fixed"


def test_stream_endpoint_emits_ai_sdk_frames(
    client: TestClient, patch_ai: Any, profile_factory: Any
) -> None:
    repository.insert_profile(profile_factory())
    patch_ai(lambda _model_cls, _user: {"reply": "先补部署。", "citations": ["/report"]})

    response = client.post("/api/taifu/chat/stream", json={"question": "我先补什么"})

    assert response.status_code == 200
    # 没有这个头，`useChat` 会按旧版 text 协议解析，工具卡与 data part 全部丢失。
    assert response.headers["x-vercel-ai-ui-message-stream"] == "v1"
    frames = _frames(response.text)
    assert frames[0]["type"] == "start"
    assert frames[-1]["type"] == "[DONE]"
    assert sum(1 for item in frames if item["type"] == "[DONE]") == 1
    assert any(item["type"] == "text-delta" for item in frames)
    # 模型自述的 `/report` 不进引用：这一轮没有任何工具调用。
    citations = next(item for item in frames if item["type"] == "data-citations")
    assert citations["data"]["items"] == []


def test_stream_endpoint_gives_each_reply_a_distinct_message_id(
    client: TestClient, patch_ai: Any, profile_factory: Any
) -> None:
    """连问两次：两条回答必须是两条消息，而不是第二条把第一条替换掉。"""

    repository.insert_profile(profile_factory())
    patch_ai(lambda _model_cls, _user: {"reply": "先补部署。", "citations": []})

    first = _frames(client.post("/api/taifu/chat/stream", json={"question": "我先补什么"}).text)
    second = _frames(client.post("/api/taifu/chat/stream", json={"question": "再然后呢"}).text)

    assert first[0]["type"] == "start"
    assert second[0]["type"] == "start"
    assert first[0]["messageId"] != second[0]["messageId"]


def test_stream_endpoint_short_circuits_without_records(
    client: TestClient, patch_ai: Any
) -> None:
    def _boom(_model_cls: type[Any], _user: str) -> dict[str, Any]:
        raise AssertionError("空档案不应调用模型")

    patch_ai(_boom)
    response = client.post("/api/taifu/chat/stream", json={"question": "我先补什么"})

    assert response.status_code == 200
    frames = _frames(response.text)
    assert [item["type"] for item in frames] == ["start", "data-done", "finish", "[DONE]"]
    assert "站内记录还是空的" in frames[1]["data"]["notice"]
    # 前端据此给「去上传简历 / 先做几道练习 / 去看诊断报告」三个入口。
    assert frames[1]["data"]["reason"] == "no_records"


def test_stream_endpoint_marks_a_missing_answer_as_empty_reply(
    client: TestClient, patch_ai: Any, profile_factory: Any
) -> None:
    """模型没生成出正文：给 `empty_reply`，前端只提示重问，不给「去补数据」的入口。"""

    repository.insert_profile(profile_factory())
    # 只有空白也要算「没生成出回答」：`normalize_reply` 会 strip 成空串。
    # 注意这时上游**确实流了**空白 delta，所以前端判「有没有正文」必须 trim，
    # 否则会留下一个空白气泡、把 notice 挡在外面。
    patch_ai(lambda _model_cls, _user: {"reply": "   ", "citations": []})

    frames = _frames(client.post("/api/taifu/chat/stream", json={"question": "我先补什么"}).text)

    done = next(item for item in frames if item["type"] == "data-done")
    assert done["data"]["reason"] == "empty_reply"
    assert done["data"]["notice"] == policy.EMPTY_REPLY_NOTICE


def test_stream_endpoint_rejects_blank_question(client: TestClient, patch_ai: Any) -> None:
    patch_ai(lambda _model_cls, _user: {"reply": "不该到这", "citations": []})
    response = client.post("/api/taifu/chat/stream", json={"question": "   "})

    frames = _frames(response.text)
    assert frames[1]["type"] == "data-done"
    assert frames[1]["data"]["notice"] == policy.EMPTY_QUESTION_NOTICE
    # 空问句不是「没数据」：不该弹「去上传简历」那三个入口。
    assert frames[1]["data"]["reason"] == "empty_question"
    assert frames[-1]["type"] == "[DONE]"
