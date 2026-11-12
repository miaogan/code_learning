"""r83 AI SDK UI Message Stream v1 编码器。

前端用 `@ai-sdk/react` 的 `useChat` 消费，所以这里必须严格按它的协议输出，
而不是自定义一套事件名。协议要点（对照 ai-sdk 官方 stream-protocol 文档）：

- 头 `x-vercel-ai-ui-message-stream: v1`，body 是 SSE；
- 每帧 `data: {json}\\n\\n`，最后一行固定 `data: [DONE]`；
- 文本按 `text-start` / `text-delta` / `text-end` 三段式，靠 `id` 归组；
- 工具调用按 `tool-input-available`（入参完整）/ `tool-output-available`（结果）两帧；
- 自定义数据用 `data-<name>` 前缀，前端拿到 `part.type === 'data-<name>'`、`part.data`。

本模块是纯函数 + 一个有状态编码器，不读库、不碰网络，可直接单测。
"""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

#: 协议版本头：缺了它 `useChat` 会按旧版 text 协议解析，工具卡与 data part 全部丢失。
STREAM_HEADER = "x-vercel-ai-ui-message-stream"
STREAM_VERSION = "v1"

#: 流终止标记：必须且只能出现一次。
DONE_FRAME = "data: [DONE]\n\n"


def new_message_id() -> str:
    """每次请求一个**唯一**的 message id。

    协议里的 `start.messageId` 会成为这条助手消息的 `id`，而 `useChat` 收到新消息时是按
    id 归位的：`messages.findLastIndex(m => m.id === 新消息.id)` 命中就 **replace**，不命中才
    追加。若两条回答共用一个常量 id，第二条会原地覆盖第一条 —— 界面上看起来像「回答被吞了 /
    串到下一条」，`key` 也会撞。所以 id 必须逐次不同（r83 交付后修复的正是这一处）。
    """
    return f"msg_{uuid4().hex[:16]}"


def frame(payload: dict[str, Any]) -> str:
    """一个 SSE 数据帧。`ensure_ascii=False` 让人在浏览器 devtools 里能直接读中文。"""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


class StreamEncoder:
    """把图的内部事件编码成协议帧。

    有状态的只有两件事：文本块是否已经开了（`text-start` 只能发一次），以及本次流的消息 id。
    其余事件都是无状态映射，所以整个类可以逐事件喂、不需要缓冲。
    """

    def __init__(self, message_id: str | None = None) -> None:
        self.message_id = message_id or new_message_id()
        self.text_id = f"text_{self.message_id}"
        self._text_open = False
        self._closed = False

    def start(self) -> list[str]:
        return [frame({"type": "start", "messageId": self.message_id})]

    def encode(self, event: dict[str, Any]) -> list[str]:
        """一个内部事件 → 若干帧。已收尾后再来的事件一律丢弃（不让 `[DONE]` 之后还有数据）。"""
        if self._closed:
            return []
        kind = str(event.get("type") or "")
        if kind == "token":
            delta = str(event.get("delta") or "")
            if not delta:
                return []
            frames: list[str] = []
            if not self._text_open:
                self._text_open = True
                frames.append(frame({"type": "text-start", "id": self.text_id}))
            frames.append(
                frame({"type": "text-delta", "id": self.text_id, "delta": delta})
            )
            return frames
        if kind == "meta":
            return [frame({"type": "data-meta", "data": _meta_payload(event)})]
        if kind == "tool_start":
            call_id = str(event.get("id") or "")
            name = str(event.get("name") or "")
            return [
                frame({"type": "tool-input-start", "toolCallId": call_id, "toolName": name}),
                frame(
                    {
                        "type": "tool-input-available",
                        "toolCallId": call_id,
                        "toolName": name,
                        "input": {
                            "label": str(event.get("label") or ""),
                            "arguments": event.get("input") or {},
                        },
                    }
                ),
            ]
        if kind == "tool_end":
            return [
                frame(
                    {
                        "type": "tool-output-available",
                        "toolCallId": str(event.get("id") or ""),
                        # 读不到也是一条结果（`ok=False`），不冒充成功、也不当异常抛。
                        "output": {
                            "ok": bool(event.get("ok")),
                            "label": str(event.get("label") or ""),
                            "summary": str(event.get("summary") or ""),
                        },
                    }
                )
            ]
        if kind == "citations":
            return [frame({"type": "data-citations", "data": {"items": event.get("items") or []}})]
        if kind == "capped":
            return [frame({"type": "data-capped", "data": {"capped": True}})]
        if kind == "done":
            return [
                frame(
                    {
                        "type": "data-done",
                        "data": {
                            "notice": str(event.get("notice") or ""),
                            "memoriesAdded": int(event.get("memories_added") or 0),
                            "createdAt": str(event.get("created_at") or ""),
                        },
                    }
                )
            ]
        if kind == "error":
            return [frame({"type": "error", "errorText": str(event.get("message") or "生成失败")})]
        return []

    def finish(self) -> list[str]:
        """收尾：补 `text-end`（如果开过）→ `finish` → `[DONE]`。重复调用返回空列表。"""
        if self._closed:
            return []
        self._closed = True
        frames: list[str] = []
        if self._text_open:
            frames.append(frame({"type": "text-end", "id": self.text_id}))
        frames.append(frame({"type": "finish"}))
        frames.append(DONE_FRAME)
        return frames


def _meta_payload(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "materials": int(event.get("materials") or 0),
        "focusKind": str(event.get("focus_kind") or ""),
        "memoriesUsed": int(event.get("memories_used") or 0),
        "summaryUsed": bool(event.get("summary_used")),
    }


def headers() -> dict[str, str]:
    """流式响应头：禁缓存、禁压缩缓冲，否则代理会把 token 攒成一批才吐。"""
    return {
        "Cache-Control": "no-cache, no-transform",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
        STREAM_HEADER: STREAM_VERSION,
    }
