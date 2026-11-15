"""r102 SSE 小工具：帧格式化 / 心跳 / 断连检测（任务进度流与面试回合流共用）。

帧格式遵循 SSE 规范：`event:` + `data:` + 空行结尾；心跳用注释帧（`: ping`），
浏览器不会把它当事件，代理与负载均衡却会因此保活。
"""

from __future__ import annotations

import json

from fastapi import Request

#: 所有流式响应共用的头：关缓存、关代理缓冲（nginx 默认会攒包，SSE 会被延迟到一批发出）。
SSE_HEADERS: dict[str, str] = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def sse_event(event: str, payload: dict) -> str:
    """一帧事件：data 一律 JSON（中文不转义，便于直接阅读与排障）。"""
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return "event: " + event + "\n" + "data: " + body + "\n\n"


def sse_heartbeat() -> str:
    """注释帧心跳：不触发前端 onmessage，只用于保活。"""
    return ": ping\n\n"


async def client_gone(request: Request) -> bool:
    """客户端是否已断开：长连接必须主动退出，否则任务僵死时链接一直挂着。"""
    try:
        return await request.is_disconnected()
    except RuntimeError:  # 无 ASGI 连接（极少见）：按已断开处理，避免空转
        return True
