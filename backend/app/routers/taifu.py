"""r83 太傅端点：`POST /chat`（非流式）/ `POST /chat/stream`（AI SDK 流式）/ 线程与记忆。

分工：
- 路由只做「空问句 / 空档案的零成本短路」、协议选择与依赖装配；
- 编排在 `services/taifu/graph.py`（LangGraph），取料在 `tools.py`，编码在 `ai_sdk.py`。

**一个图两个出口**：流式端点转发图的事件，非流式端点把同一批事件聚合成 `TaifuReply`。
两条路的业务逻辑只有一份，回归面因此收敛在「协议层」而不是「整个太傅」。

**只读承诺**：本路由唯一的写操作是太傅自己的三张表（`taifu_messages` / `taifu_threads` /
`taifu_memories`），不碰画像 / 报告 / 测评 / 练习 / 学习进度任何一张业务表。
"""

import logging
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from app.core import repository
from app.core.errors import AppError
from app.deps import CurrentUser, current_user
from app.schemas import (
    TaifuChatRequest,
    TaifuClearResult,
    TaifuMemories,
    TaifuMemoryResult,
    TaifuReply,
    TaifuThread,
)
from app.services.ai import user_ai
from app.services.taifu import ai_sdk, graph, policy, taifu

logger = logging.getLogger("app.taifu")

router = APIRouter(prefix="/api/taifu", tags=["taifu"], dependencies=[Depends(current_user)])

THREAD_DEFAULT = 20
THREAD_MIN = 1
THREAD_MAX = 50


def _has_any_record() -> bool:
    """轻量探针：有没有任何能投影成档案段的记录。

    空档案**不建客户端**（零配额、零等待、不要求配 Key）—— 这是 r77 起就有的性质。
    图里 `prepare` 还会再判一次，那次是权威口径；这里只为「不要白扣一次配额」。
    """
    return (
        repository.latest_profile() is not None
        or repository.latest_report() is not None
        or bool(repository.list_attempts())
    )


@router.post("/chat", response_model=TaifuReply, summary="问太傅：基于站内档案的只读回答")
async def chat(payload: TaifuChatRequest, user: CurrentUser) -> TaifuReply:
    # 先清洗再判断：空问句不查库；空档案不建客户端 —— 两条都不消耗额度。
    question = policy.sanitize_question(payload.question)
    if not question:
        return taifu.missing_question_reply()
    if not _has_any_record():
        return taifu.empty_reply()
    # 页面与焦点都只用于消解指代 / 提示模型去哪读，不进引用白名单。
    page = policy.sanitize_page(payload.page)
    focus = policy.sanitize_focus(payload.focus)
    client = user_ai.client_for(user, "light")
    return await graph.run_collect(question, page=page, focus=focus, client=client)


@router.post("/chat/stream", summary="问太傅（流式）：AI SDK UI Message Stream v1")
async def chat_stream(payload: TaifuChatRequest, user: CurrentUser) -> StreamingResponse:
    """流式出口。协议细节见 `services/taifu/ai_sdk.py`。

    客户端在这里建、而不是在生成器里：没配 Key / 额度不足要拿到真正的 403 JSON，
    前端据此弹「去设置」——塞进 200 的流里只会变成一句看不懂的错误文本。
    """
    question = policy.sanitize_question(payload.question)
    page = policy.sanitize_page(payload.page)
    focus = policy.sanitize_focus(payload.focus)
    encoder = ai_sdk.StreamEncoder()
    if not question:
        return _stream(_notice_stream(encoder, policy.EMPTY_QUESTION_NOTICE, "empty_question"))
    if not _has_any_record():
        return _stream(_notice_stream(encoder, policy.EMPTY_BRIEF_NOTICE, "no_records"))
    client = user_ai.client_for(user, "light")

    async def events() -> AsyncIterator[str]:
        for chunk in encoder.start():
            yield chunk
        try:
            async for event in graph.run_events(
                question, page=page, focus=focus, client=client
            ):
                for chunk in encoder.encode(event):
                    yield chunk
        except AppError as exc:
            # 已经流出正文时上游才失败：保留已发出的内容，补一条错误让用户知道没说完。
            logger.warning("taifu.stream.failed code=%s", exc.code)
            for chunk in encoder.encode({"type": "error", "message": exc.message}):
                yield chunk
        except Exception:
            logger.exception("taifu.stream.crashed")
            for chunk in encoder.encode(
                {"type": "error", "message": "生成中断了，可以再问一次"}
            ):
                yield chunk
        for chunk in encoder.finish():
            yield chunk

    return _stream(events())


async def _notice_stream(
    encoder: ai_sdk.StreamEncoder, notice: str, reason: str
) -> AsyncIterator[str]:
    """零成本短路也要走同一条协议：前端只认一套帧，不为「没档案」写分支。

    `reason` 是给前端的机器可读分支依据（`empty_question` / `no_records`）——没有档案时
    要给「去补数据」的三个入口，空问句时不该给，靠 notice 中文反推太脆。
    """
    for chunk in encoder.start():
        yield chunk
    for chunk in encoder.encode(
        {
            "type": "done",
            "notice": notice,
            "reason": reason,
            "memories_added": 0,
            "created_at": "",
        }
    ):
        yield chunk
    for chunk in encoder.finish():
        yield chunk


def _stream(body: AsyncIterator[str]) -> StreamingResponse:
    return StreamingResponse(
        body, media_type="text/event-stream", headers=ai_sdk.headers()
    )


@router.get("/thread", response_model=TaifuThread, summary="读取太傅对话历史（时间升序）")
def read_thread(
    limit: Annotated[int, Query(ge=THREAD_MIN, le=THREAD_MAX, description="最多返回条数")] = (
        THREAD_DEFAULT
    ),
) -> TaifuThread:
    return TaifuThread(messages=repository.list_taifu_messages(limit=limit))


@router.delete("/thread", response_model=TaifuClearResult, summary="清空太傅对话（不动业务数据与长期记忆）")
def clear_thread() -> TaifuClearResult:
    return TaifuClearResult(deleted=repository.delete_taifu_messages())


@router.get("/memories", response_model=TaifuMemories, summary="查看太傅记住的长期事实（可审计）")
def list_memories() -> TaifuMemories:
    # 记忆必须可查看：用户有权知道自己被「记住」了什么，才能决定要不要忘掉。
    return TaifuMemories(items=repository.list_taifu_memories())


@router.delete(
    "/memories/{memory_id}", response_model=TaifuMemoryResult, summary="忘掉一条长期记忆"
)
def forget_memory(memory_id: str) -> TaifuMemoryResult:
    return TaifuMemoryResult(deleted=repository.delete_taifu_memory(memory_id))


@router.delete("/memories", response_model=TaifuMemoryResult, summary="忘掉全部长期记忆")
def forget_all_memories() -> TaifuMemoryResult:
    return TaifuMemoryResult(deleted=repository.delete_taifu_memories())
