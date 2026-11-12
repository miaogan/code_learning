"""r83 太傅编排：`agent ⇄ tools` 循环。

```
START → prepare → agent ──(有 tool_calls 且未达上限)──→ tools ──→ agent
                     └──(无 tool_calls / 已达上限)────→ finalize → END
```

三条不可越的边界：
1. **出网只经 `AIClient`**：图里不出现 `ChatOpenAI`、不出现 `langchain_core` 的消息类型，
   所有消息都是 OpenAI 的 dict 形状 —— 配额、调用日志、隐私边界、退避口径全部沿用既有实现；
2. **取料只经 `tools`**：节点不直接查库拿明细，模型也不能越过工具看到别的东西；
3. **引用只由工具结果产生**：模型没有通道去编引用，`dropped_citations` 因此恒为 0。

事件（`get_stream_writer()` 发出）与前端协议解耦：本模块不知道 SSE、不知道 AI SDK，
只产出 `meta` / `tool_start` / `tool_end` / `token` / `citations` / `done` / `error`。
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any, TypedDict

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph

from app.core import repository
from app.schemas import TaifuReply
from app.services.ai.ai import AIClient
from app.services.taifu import brief, policy, tools

logger = logging.getLogger("app.taifu")

#: 工具轮次硬上限：模型连续要读料时不无限循环。到顶后强制生成，并在 meta 里如实标注。
MAX_TOOL_ROUNDS = 3
#: 一次回答最多列几条引用：只列有具体指向的明细，摘要段不进引用（见 PRD）。
CITATION_LIMIT = 5
#: 回答的自然语言短文用 120s；摘要是一次短补全，45s 足够，不该跟主回答一起等。
TAIFU_TIMEOUT_S = 120
SUMMARY_TIMEOUT_S = 45


class TaifuState(TypedDict, total=False):
    question: str
    page: dict[str, str] | None
    focus: dict[str, Any] | None
    sections: list[dict[str, Any]]
    dialogue: list[dict[str, Any]]
    pending: list[dict[str, Any]]
    citations: list[dict[str, str]]
    rounds: int
    agent_text: str
    reply: str
    memories_added: int
    created_at: str
    capped: bool
    blocked: str
    #: `tools.ToolContext`：本轮取料上下文（懒加载正文、累计记忆）。不序列化，图也不带 checkpointer。
    context: Any
    #: 归档信息：finalize 写库与摘要用。
    overflow: bool
    history: list[dict[str, Any]]
    summary_before: str


def _emit(payload: dict[str, Any]) -> None:
    """把内部事件推给 `astream` 的消费方。没有流上下文时（`invoke`）是 no-op。"""
    get_stream_writer()(payload)


def _input_hint(arguments: str) -> dict[str, Any]:
    """工具入参的界面摘要：原样给出会让卡片塞满一大段 JSON，只留前两个短字段。"""
    try:
        payload = json.loads(arguments or "{}")
    except ValueError:
        return {}
    if not isinstance(payload, dict):
        return {}
    hint: dict[str, Any] = {}
    for key, value in list(payload.items())[:2]:
        hint[str(key)] = brief.clip(value, 40)
    return hint


def _prepare(state: TaifuState) -> dict[str, Any]:
    """读档案摘要、历史、摘要与记忆，拼首轮提示词；明细**不在这里读**，交给工具。"""
    profile = repository.latest_profile()
    report = repository.latest_report()
    attempts = repository.list_attempts()
    sections = brief.build_sections(
        profile=profile,
        report=report,
        runs=repository.history_rows(limit=brief.MAX_RUNS),
        attempts=attempts,
        learn=repository.get_learn_progress(),
    )
    focus = state.get("focus")
    if not sections:
        # 空档案不调模型：零成本、零等待、不要求配 Key。
        _emit({"type": "meta", "materials": 0, "focus_kind": "", "memories_used": 0, "summary_used": False})
        return {"blocked": policy.EMPTY_BRIEF_NOTICE, "sections": []}

    # 多取一条只为判断「有没有被窗口挤掉的消息」：溢出才需要压摘要。
    recent = repository.list_taifu_messages(limit=policy.HISTORY_LIMIT + 1)
    overflow = len(recent) > policy.HISTORY_LIMIT
    history = recent[-policy.HISTORY_LIMIT:]
    summary = repository.get_taifu_summary()
    memories = repository.list_taifu_memories()
    prompt = policy.build_agent_prompt(
        sections,
        history,
        state["question"],
        state.get("page"),
        summary=summary,
        memories=[item["content"] for item in memories],
        focus=focus,
    )
    context = tools.ToolContext(
        profile=profile,
        report=report,
        attempts=attempts,
        memories=[item["content"] for item in memories],
    )
    _emit(
        {
            "type": "meta",
            "materials": len(sections),
            "focus_kind": str((focus or {}).get("kind") or ""),
            "memories_used": len(memories),
            "summary_used": bool(summary),
        }
    )
    return {
        "sections": sections,
        "dialogue": [{"role": "user", "content": prompt}],
        "context": context,
        "overflow": overflow,
        "history": history,
        "summary_before": summary,
        "citations": [],
        "rounds": 0,
        "reply": "",
    }


async def _agent(state: TaifuState, client: AIClient) -> dict[str, Any]:
    """流式生成一轮：正文边流边推；这一轮如果带 tool_calls，交给 tools 节点去执行。"""
    chunks: list[str] = []
    pending: list[dict[str, Any]] = []
    async for event in client.stream_chat(
        policy.TAIFU_AGENT_SYSTEM,
        list(state.get("dialogue") or []),
        tools=tools.TOOL_SPECS,
        timeout_s=TAIFU_TIMEOUT_S,
    ):
        if event["kind"] == "text":
            text = str(event.get("text") or "")
            if text:
                chunks.append(text)
                _emit({"type": "token", "delta": text})
        elif event["kind"] == "tool_call":
            pending.append(
                {
                    "id": str(event.get("id") or ""),
                    "name": str(event.get("name") or ""),
                    "arguments": str(event.get("arguments") or "{}"),
                }
            )
    text = "".join(chunks)
    reply = state.get("reply") or ""
    if text:
        # 多轮的过渡话也保留：存库内容与用户当场看到的一致，刷新后不会「少一段」。
        reply = f"{reply}\n\n{text}".strip() if reply else text
    rounds = int(state.get("rounds") or 0)
    return {
        "agent_text": text,
        "pending": pending,
        "reply": reply,
        "rounds": rounds + 1 if pending else rounds,
    }


def _route_after_prepare(state: TaifuState) -> str:
    return "finalize" if state.get("blocked") else "agent"


def _route_after_agent(state: TaifuState) -> str:
    if not state.get("pending"):
        return "finalize"
    if int(state.get("rounds") or 0) > MAX_TOOL_ROUNDS:
        # 已达上限：不再执行这一轮工具，直接生成 —— 界面会显示「已达取料上限」。
        return "finalize"
    return "tools"


async def _tools(state: TaifuState) -> dict[str, Any]:
    """并发执行本轮工具调用，逐个发事件，结果回灌给下一轮 agent。"""
    context: tools.ToolContext = state["context"]
    calls = list(state.get("pending") or [])
    runnable = [call for call in calls if str(call.get("name")) in tools.TOOL_NAMES]
    for call in runnable:
        name = str(call["name"])
        _emit(
            {
                "type": "tool_start",
                "id": call["id"],
                "name": name,
                "label": tools.TOOL_LABELS[name],
                "input": _input_hint(call["arguments"]),
            }
        )
    results = await asyncio.gather(
        *[tools.run(str(call["name"]), str(call["arguments"]), context) for call in runnable]
    )

    citations = list(state.get("citations") or [])
    seen = {item["href"] for item in citations}
    dialogue = list(state.get("dialogue") or [])
    if runnable:
        dialogue.append(
            {
                "role": "assistant",
                # OpenAI 允许 content 为 null；给空串会被部分实现当作「空回复」拒掉。
                "content": state.get("agent_text") or None,
                "tool_calls": [
                    {
                        "id": call["id"],
                        "type": "function",
                        "function": {
                            "name": call["name"],
                            "arguments": call["arguments"] or "{}",
                        },
                    }
                    for call in runnable
                ],
            }
        )
    for call, result in zip(runnable, results, strict=True):
        label = result["label"] or tools.TOOL_LABELS[str(call["name"])]
        _emit(
            {
                "type": "tool_end",
                "id": call["id"],
                "ok": bool(result["ok"]),
                "label": label,
                "summary": result["summary"],
            }
        )
        dialogue.append(
            {
                "role": "tool",
                "tool_call_id": call["id"],
                "content": "\n".join(result["content"]),
            }
        )
        href = result.get("href")
        if href and href not in seen and len(citations) < CITATION_LIMIT:
            seen.add(href)
            citations.append({"label": label, "href": href})
    return {"dialogue": dialogue, "citations": citations, "pending": []}


async def _summarize(
    client: AIClient, existing: str, history: list[dict[str, Any]]
) -> str:
    """窗口溢出时重写线程摘要。失败不影响主流程：摘要丢一轮，下一轮还能再压。"""
    try:
        draft = await client.complete_model(
            policy.SUMMARY_SYSTEM,
            policy.build_summary_prompt(existing, history),
            policy.TaifuSummary,
            timeout_s=SUMMARY_TIMEOUT_S,
        )
    except Exception as exc:  # noqa: BLE001 - 摘要是可选增强，任何失败都不该让回答失败
        logger.warning("taifu.summary.failed error=%s", type(exc).__name__)
        return ""
    return policy.sanitize_summary(draft.summary)


async def _finalize(state: TaifuState, client: AIClient) -> dict[str, Any]:
    """收尾：空回答给中文提示，有回答才写历史；溢出时补一次摘要。"""
    blocked = state.get("blocked") or ""
    if blocked:
        _emit({"type": "done", "reply": "", "notice": blocked, "memories_added": 0, "created_at": ""})
        return {"created_at": ""}

    reply = policy.normalize_reply(state.get("reply") or "")
    context: tools.ToolContext = state["context"]
    citations = list(state.get("citations") or [])
    capped = int(state.get("rounds") or 0) > MAX_TOOL_ROUNDS
    if capped:
        _emit({"type": "capped"})
    if not reply:
        _emit(
            {
                "type": "done",
                "reply": "",
                "notice": policy.EMPTY_REPLY_NOTICE,
                "memories_added": context.memories_added,
                "created_at": "",
            }
        )
        return {"created_at": ""}

    _emit({"type": "citations", "items": citations})
    repository.insert_taifu_message(role="user", content=state["question"])
    row = repository.insert_taifu_message(role="assistant", content=reply, citations=citations)

    if state.get("overflow"):
        history = list(state.get("history") or [])
        history.append({"role": "user", "content": state["question"]})
        history.append({"role": "assistant", "content": reply})
        summary = await _summarize(
            client, str(state.get("summary_before") or ""), history
        )
        if summary:
            repository.save_taifu_summary(summary)

    _emit(
        {
            "type": "done",
            "reply": reply,
            "notice": "",
            "memories_added": context.memories_added,
            "created_at": str(row.get("created_at") or ""),
        }
    )
    return {
        "created_at": str(row.get("created_at") or ""),
        "memories_added": context.memories_added,
        "capped": capped,
    }


def build(client: AIClient):
    """编译图。`client` 由调用方注入 —— 图不认识 `user_ai`，也不自己造客户端。

    节点签名统一是 `(state)`，客户端用闭包绑：把它塞进 State 会让「编排」和「出网」
    在数据结构上也耦合起来，测试时还得先造一个假客户端塞进初始 state。
    """
    graph = StateGraph(TaifuState)
    # 必须是真的 `async def`：langgraph 用 `iscoroutinefunction` 判断节点，lambda 返回协程不算。
    async def agent_node(state: TaifuState) -> dict[str, Any]:
        return await _agent(state, client)

    async def finalize_node(state: TaifuState) -> dict[str, Any]:
        return await _finalize(state, client)

    graph.add_node("prepare", _prepare)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", _tools)
    graph.add_node("finalize", finalize_node)
    graph.add_edge(START, "prepare")
    graph.add_conditional_edges(
        "prepare", _route_after_prepare, {"agent": "agent", "finalize": "finalize"}
    )
    graph.add_conditional_edges(
        "agent", _route_after_agent, {"tools": "tools", "finalize": "finalize"}
    )
    graph.add_edge("tools", "agent")
    graph.add_edge("finalize", END)
    return graph.compile()


async def run_events(
    question: str,
    *,
    page: dict[str, str] | None,
    focus: dict[str, Any] | None,
    client: AIClient,
) -> AsyncIterator[dict[str, Any]]:
    """跑一遍图，逐条产出内部事件。异常原样抛给调用方（流式端点据此发 error 帧）。"""
    app = build(client)
    initial: TaifuState = {"question": question, "page": page, "focus": focus, "rounds": 0}
    async for _mode, payload in app.astream(initial, stream_mode=["custom"]):
        if isinstance(payload, dict) and payload.get("type"):
            yield payload


async def run_collect(
    question: str,
    *,
    page: dict[str, str] | None,
    focus: dict[str, Any] | None,
    client: AIClient,
) -> TaifuReply:
    """非流式出口：把同一张图的事件聚合成 `TaifuReply`（旧契约，字段不变）。"""
    reply = ""
    citations: list[dict[str, str]] = []
    materials = 0
    memories_used = 0
    memories_added = 0
    notice = ""
    created_at = ""
    summary_used = False
    async for event in run_events(question, page=page, focus=focus, client=client):
        kind = event["type"]
        if kind == "token":
            reply += str(event.get("delta") or "")
        elif kind == "meta":
            materials = int(event.get("materials") or 0)
            memories_used = int(event.get("memories_used") or 0)
            summary_used = bool(event.get("summary_used"))
        elif kind == "citations":
            citations = list(event.get("items") or [])
        elif kind == "done":
            notice = str(event.get("notice") or "")
            memories_added = int(event.get("memories_added") or 0)
            created_at = str(event.get("created_at") or "")
            # `done.reply` 是 finalize 过 `normalize_reply` 的**权威值**，无条件覆盖累积 token：
            # 纯空白的草稿会被清成空串，靠拼 token 拼不出来这个结果。
            reply = str(event.get("reply") or "")
    return TaifuReply(
        reply=reply,
        citations=citations,
        materials_used=materials,
        dropped_citations=0,
        summary_used=summary_used,
        memories_used=memories_used,
        memories_added=memories_added,
        notice=notice,
        created_at=created_at,
    )
