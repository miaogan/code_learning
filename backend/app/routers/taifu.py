"""r77 太傅端点：`POST /api/taifu/chat` / `GET|DELETE /api/taifu/thread` / `GET|DELETE /api/taifu/memories`。

分工：
- 路由只做「空问句 / 空档案的零成本短路」与依赖装配；
- 档案摘要、提示词、引用白名单、会话读写全在 `services/taifu/` 与 `core/repository.py`。

**只读承诺**：本路由唯一的写操作是太傅自己的三张表（`taifu_messages` / `taifu_threads` /
`taifu_memories`），不碰画像 / 报告 / 测评 / 练习 / 学习进度任何一张业务表。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core import repository
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
from app.services.taifu import policy, taifu

router = APIRouter(prefix="/api/taifu", tags=["taifu"], dependencies=[Depends(current_user)])

THREAD_DEFAULT = 20
THREAD_MIN = 1
THREAD_MAX = 50


@router.post("/chat", response_model=TaifuReply, summary="问太傅：基于站内档案的只读回答")
async def chat(payload: TaifuChatRequest, user: CurrentUser) -> TaifuReply:
    # 先清洗再判断：空问句不查库；空档案不建客户端 —— 两条都不消耗额度。
    question = policy.sanitize_question(payload.question)
    if not question:
        return taifu.missing_question_reply()
    sections = taifu.gather_sections()
    if not sections:
        return taifu.empty_reply()
    # 页面只用于消解「这里 / 这条」的指代：闭集校验后进提示词，不进引用白名单。
    page = policy.sanitize_page(payload.page)
    client = user_ai.client_for(user, "light")
    return await taifu.answer(question, sections, page=page, client=client)


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
