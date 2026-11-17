"""r100 RAG 检索域端点：索引状态 / 重建 / 教程摄取 / 三态检索 / 有引用的生成。

- 全部登录态（`current_user`）；chunk 是共享语料，因此检索结果不分属主
  （与题库 `/api/search/questions` 同口径，不含任何用户简历数据）；
- 业务在 `services/retrieval/`，路由只做参数归一与 pydantic 投影；
- `/answer` 走 `user_ai.client_for(user, "light")` 能力档（与教练同一档：生成类），
  未配置自带 Key 且内置 Key 缺失时按既有 `AI_KEY_REQUIRED` 503 降级，不新增错误码。
"""

from fastapi import APIRouter, Depends

from app.core import repository
from app.core.errors import NOT_FOUND, AppError
from app.deps import CurrentUser, current_user
from app.schemas import (
    RagAnswerRequest,
    RagAnswerResponse,
    RagChunkItem,
    RagFeedbackRequest,
    RagFeedbackResult,
    RagFeedbackSummary,
    RagIngestRequest,
    RagRebuildResult,
    RagSearchRequest,
    RagSearchResponse,
    RagStatus,
)
from app.services.ai import user_ai
from app.services.retrieval import indexer
from app.services.retrieval.answer import generate_answer, retrieve_for_answer
from app.services.retrieval.hybrid import search_chunks

router = APIRouter(prefix="/api/rag", tags=["rag"], dependencies=[Depends(current_user)])


@router.get("/status", response_model=RagStatus, summary="RAG 索引状态（embedder / 引擎 / chunk 计数）")
def rag_status() -> RagStatus:
    return RagStatus(**indexer.index_status())


@router.post(
    "/rebuild",
    response_model=RagRebuildResult,
    summary="重建题库向量索引（全量替换）",
)
def rag_rebuild() -> RagRebuildResult:
    return RagRebuildResult(**indexer.rebuild_question_index())


@router.post(
    "/ingest",
    response_model=RagRebuildResult,
    summary="整份推送教程正文（小节 chunk 全量替换）",
)
def rag_ingest(payload: RagIngestRequest) -> RagRebuildResult:
    items = [item.model_dump() for item in payload.items]
    return RagRebuildResult(**indexer.ingest_tutorial_chunks(items))


@router.post("/search", response_model=RagSearchResponse, summary="RAG 检索：关键词 / 语义 / 混合三态")
def rag_search(payload: RagSearchRequest) -> RagSearchResponse:
    return RagSearchResponse(
        **search_chunks(
            payload.query, mode=payload.mode, top_k=payload.limit, kinds=payload.kinds
        )
    )


@router.post(
    "/answer",
    response_model=RagAnswerResponse,
    summary="检索增强生成：答案只基于检索命中，引用必须可回指 chunk",
)
async def rag_answer(payload: RagAnswerRequest, user: CurrentUser) -> RagAnswerResponse:
    retrieved = retrieve_for_answer(payload.query, mode=payload.mode, top_k=payload.top_k)
    chunks = list(retrieved["items"])
    if not chunks:
        return RagAnswerResponse(
            answer="没有检索到与问题相关的材料，暂时无法回答。",
            citations=[],
            retrieved_count=0,
            mode=retrieved["mode"],
            engine=retrieved["engine"],
            notice=retrieved["notice"] or "两条检索腿都没有命中",
        )
    client = user_ai.client_for(user, "light")
    draft = await generate_answer(payload.query, chunks, client)
    by_id = {chunk["chunk_id"]: chunk for chunk in chunks}
    citations = [RagChunkItem(**by_id[cid]) for cid in draft.citations if cid in by_id]
    return RagAnswerResponse(
        answer=draft.answer,
        citations=citations,
        retrieved_count=len(chunks),
        dropped_citations=draft.dropped_citations,
        mode=retrieved["mode"],
        engine=retrieved["engine"],
        notice=retrieved["notice"],
    )


@router.post(
    "/feedback",
    response_model=RagFeedbackResult,
    summary="对检索结果点赞 / 点踩（同查询同 chunk 只保留最新一票）",
)
def rag_feedback(payload: RagFeedbackRequest) -> RagFeedbackResult:
    """r103：反馈是**个人排序信号**——投票立即参与该用户后续同 query 的排序加权。

    chunk 必须真实存在（索引重建过一次的旧 id 会 404）：不让反馈落到不存在的材料上，
    否则「被踩最多的 chunk」看板会掺进幽灵行。
    """
    chunk_id = payload.chunk_id.strip()
    if not repository.rag_fetch_chunks([chunk_id]):
        raise AppError(NOT_FOUND, "这条材料不存在或索引已重建，请刷新后重试", status=404)
    return RagFeedbackResult(
        **repository.rag_feedback_upsert(
            query=payload.query.strip(),
            chunk_id=chunk_id,
            verdict=payload.verdict,
            surface=payload.surface,
        )
    )


@router.get(
    "/feedback/summary",
    response_model=RagFeedbackSummary,
    summary="反馈看板：总票数 + 被踩最多的 chunk（评测挖掘入口）",
)
def rag_feedback_summary() -> RagFeedbackSummary:
    return RagFeedbackSummary(**repository.rag_feedback_summary())
