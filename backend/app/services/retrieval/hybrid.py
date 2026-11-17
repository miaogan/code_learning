"""r100 混合检索：向量 / 关键词 / RRF 融合三态（mode 闭集唯一出处）。

三态语义：
- `keyword`：chunk 正文的 ILIKE 子串匹配（与既有 `search_questions` 同一引擎口径，
  作为融合的基线，也是评测里「关键词腿」的对照面）；
- `semantic`：纯向量 top-K（pgvector 索引内 `<=>` 余弦；无扩展时全量取回 +
  Python 余弦，`engine` 字段如实报告降级）；
- `hybrid`：两条腿各自 top-K 后 **RRF（Reciprocal Rank Fusion, k=60）** 融合。
  不用分数加权——向量余弦与 ILIKE 命中的分数量纲不可比，RRF 只看名次，
  天然免疫两套分数的分布漂移（这是「不调参的融合」能稳定赢单腿的原因）。

r119 精排（可选）：`AI_RERANK_BASE_URL` 配置后，semantic / hybrid 在融合池上
先精排再截回 top_k，`reranked` 字段如实报告；未配置时行为与 r100 逐字节一致。
精排启用时 r103 反馈加权不再参与最终序（它会按 RRF 分重排，会毁掉精排结果），
这是有意取舍：交叉编码器的语义信号远强于个人投票。
**r121**：精排生效时 `score` 换成精排相关性分（0~1），与最终排名自洽；未精排 / fail-open
时仍是该模式的引擎原分（keyword 1.0 / semantic 余弦 / hybrid RRF）。

诚实边界：默认 `HashingEmbedder` 的「语义」是字符 bigram 重叠（模糊关键词基座），
接真实语义模型只需配 `AI_EMBED_MODEL`，管线零改动；评测报告按 embedder 名如实标注。
"""

from __future__ import annotations

import logging
from typing import Any

from app.core import repository
from app.services.retrieval.embeddings import resolve_embedder
from app.services.retrieval.rerank import rerank_order, resolve_reranker
from app.services.retrieval.vector_backends import resolve_vector_store

logger = logging.getLogger("app.rag.hybrid")

#: 检索模式闭集（唯一出处；HTTP 层的 Literal 与前端文案都从这里对齐）。
RAG_SEARCH_MODES: tuple[str, ...] = ("keyword", "semantic", "hybrid")

#: RRF 常数：`score = Σ 1 / (k + rank)`，k=60 是原论文（Cormack et al., 2009）推荐值。
RRF_K = 60

#: RAG 检索条数上限（与既有题目检索 `limit ≤ 20` 同一克制）。
MAX_TOP_K = 20

#: 融合腿的取宽倍数：两条腿各取 top_k × 2，保证融合后 top_k 内有足够候选。
_LEG_WIDEN = 2

#: r103 反馈加权：`factor = 1 + UP × min(up,3) − DOWN × min(down,3)`，钳到 [0.2, 2.0]。
#: 为什么用乘法而不是加法：RRF 分数量级是 1/60 ≈ 0.017，加法会直接盖过排名信号；
#: 乘法按比例缩放，保留「两条腿都命中仍占优」的结构。票数封顶 3 票，防止刷票式支配。
FEEDBACK_UP_BOOST = 0.2
FEEDBACK_DOWN_PENALTY = 0.4
_FEEDBACK_FACTOR_MIN = 0.2
_FEEDBACK_FACTOR_MAX = 2.0


def _apply_feedback(
    items: list[dict[str, Any]], query: str
) -> tuple[list[dict[str, Any]], int]:
    """按**当前用户对这条 query** 的投票给结果加权重排（r103）。

    返回 `(新列表, 被调整的条数)`；没有票时原样返回，零开销。
    语义边界：只认本人的票（别人的点踩不影响你的结果），换投票立即生效。
    """
    if not items:
        return items, 0
    weights = repository.rag_feedback_weights(
        query, [str(item["chunk_id"]) for item in items]
    )
    if not weights:
        return items, 0
    adjusted: list[dict[str, Any]] = []
    touched = 0
    for item in items:
        net = weights.get(str(item["chunk_id"]), 0)
        if net == 0:
            adjusted.append(item)
            continue
        factor = 1 + FEEDBACK_UP_BOOST * min(max(net, 0), 3) - FEEDBACK_DOWN_PENALTY * min(
            max(-net, 0), 3
        )
        factor = min(_FEEDBACK_FACTOR_MAX, max(_FEEDBACK_FACTOR_MIN, factor))
        adjusted.append({**item, "score": round(float(item["score"]) * factor, 6)})
        touched += 1
    adjusted.sort(key=lambda row: (-row["score"], row["chunk_id"]))
    return adjusted, touched


def rrf_fuse(ranked_lists: list[list[str]], *, top_k: int, k: int = RRF_K) -> list[tuple[str, float]]:
    """RRF 融合：多腿排名 → 融合分（只看名次不看原始分）。

    返回按融合分降序的 `(chunk_id, score)`；同一 id 出现在多腿会累加得分
    （这正是融合的收益：两条腿都排前的 chunk 稳居榜首）。
    """
    scores: dict[str, float] = {}
    for ranked in ranked_lists:
        for rank, chunk_id in enumerate(ranked, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
    fused = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    return fused[:top_k]


def _semantic_leg(
    query: str, *, embedder_name: str, dim: int, top_k: int, kinds: list[str] | None = None
) -> tuple[list[dict[str, Any]], str, str]:
    """向量腿：分派给 `VECTOR_MODE` 选中的后端（r117）。

    返回 `(rows, engine, notice)`。`engine` 是**配置的**引擎名（pgvector / python-cosine /
    faiss / milvus），即使没就绪也如实报告「配的是什么」；`notice` 非空 = 语义腿没跑成，
    上层必须把它带进响应（「能明确说清为什么没有结果」比「抛错」可用）。
    """
    runtime = resolve_embedder()
    query_vec = runtime.embedder.embed([query])[0]
    handle = resolve_vector_store()
    store = handle.store
    if store is None or not handle.ready:
        return [], handle.engine, handle.reason
    rows = store.search(
        query_vec,
        embedder=embedder_name,
        dim=dim,
        top_k=top_k,
        kinds=kinds,
    )
    return rows, handle.engine, store.notice(embedder=embedder_name, dim=dim)


def _item(chunk: dict[str, Any], score: float, *, snippet_chars: int = 160) -> dict[str, Any]:
    return {
        "chunk_id": str(chunk["id"]),
        "kind": str(chunk["kind"]),
        "ref_id": str(chunk["ref_id"]),
        "section_id": str(chunk.get("section_id") or ""),
        "title": str(chunk.get("title") or ""),
        "content": str(chunk.get("content") or ""),
        "snippet": str(chunk.get("content") or "")[:snippet_chars],
        "score": round(float(score), 6),
    }


def search_chunks(
    query: str,
    *,
    mode: str = "hybrid",
    top_k: int = 5,
    kinds: list[str] | None = None,
) -> dict[str, Any]:
    """RAG 检索主入口（同步：路由跑线程池，embedding 是本地哈希或单次远端调用）。

    未建索引 / 索引与当前 embedder 不一致时不 500：返回空集 + 中文 `notice`，
    `mode` 与 `engine` 仍如实报告——「能明确说清为什么没有结果」比「抛错」可用。
    r119：配置了 `AI_RERANK_BASE_URL` 时 semantic / hybrid 先精排再截断，
    `reranked` 字段报告是否真的精排过（精排失败 fail-open 并给 notice）。
    """
    needle = str(query or "").strip()
    size = max(1, min(int(top_k or 5), MAX_TOP_K))
    if mode not in RAG_SEARCH_MODES:
        mode = "hybrid"
    if not needle:
        return {
            "items": [], "total": 0, "mode": mode, "engine": "", "reranked": False,
            "notice": "请输入检索关键词"
        }
    runtime = resolve_embedder()
    stage = resolve_reranker()
    state = repository.rag_state_get()
    notices: list[str] = []
    engine = "sql-ilike"

    # r119：精排启用时把候选池取宽到 pool 条（两条腿本来就各取 size*2，pool 不会超过它），
    # 精排后截回 size；未启用时 pool_k == size，融合序即最终序，行为与 r100 一致。
    pool_k = size
    if stage is not None and mode in ("semantic", "hybrid"):
        pool_k = max(size, min(stage.pool, size * _LEG_WIDEN))

    if mode in ("semantic", "hybrid"):
        if state is None:
            return {
                "items": [], "total": 0, "mode": mode, "engine": "", "reranked": False,
                "notice": "RAG 索引尚未构建，请先在「考工」页重建索引",
            }
        if state["embedder"] != runtime.name:
            notices.append(
                "索引是按 "
                + state["embedder"]
                + " 构建的，与当前 embedding 配置不一致，请重建索引"
            )
    effective_kinds = [kind for kind in (kinds or []) if kind] or None

    semantic_rows: list[dict[str, Any]] = []
    if mode in ("semantic", "hybrid") and state is not None and state["embedder"] == runtime.name:
        semantic_rows, engine, vector_notice = _semantic_leg(
            needle,
            embedder_name=state["embedder"],
            dim=int(runtime.dim),
            top_k=size * _LEG_WIDEN,
            kinds=effective_kinds,
        )
        if vector_notice:
            notices.append(vector_notice)

    lexical_rows: list[dict[str, Any]] = []
    if mode in ("keyword", "hybrid"):
        lexical_rows = repository.rag_lexical_search(
            needle, top_k=size * _LEG_WIDEN, kinds=effective_kinds
        )

    if mode == "keyword":
        items = [_item(row, 1.0) for row in lexical_rows[:size]]
    elif mode == "semantic":
        items = [_item(row, row.get("score", 0.0)) for row in semantic_rows[:pool_k]]
    else:
        pool: dict[str, dict[str, Any]] = {}
        for row in [*semantic_rows, *lexical_rows]:
            pool.setdefault(str(row["id"]), row)
        fused = rrf_fuse(
            [
                [str(row["id"]) for row in semantic_rows],
                [str(row["id"]) for row in lexical_rows],
            ],
            top_k=pool_k,
        )
        items = [_item(pool[chunk_id], score) for chunk_id, score in fused if chunk_id in pool]

    # r119 精排：交叉编码器重排融合池后截回 size；失败 fail-open（原序 + notice）。
    # keyword 模式不精排：它是纯 ILIKE 对照面，保持与既有引擎同一口径。
    reranked = False
    if stage is not None and mode in ("semantic", "hybrid") and items:
        ranked, rerank_notice = rerank_order(
            needle, [str(item["content"]) for item in items], stage
        )
        if rerank_notice:
            notices.append(rerank_notice)
        else:
            # r121：score 换成精排分（已归一到 0~1）。排序依据变了，展示分必须跟着变，
            # 否则会出现「第一名分数低于第四名」的自相矛盾（r119 遗留）。
            items = [{**items[index], "score": score} for index, score in ranked][:size]
            reranked = True

    if not notices and mode == "hybrid" and not items:
        notices.append("两条检索腿都没有命中，可尝试更短的关键词或换用关键词模式")
    if not reranked:
        # 反馈加权按 score 重排，会毁掉精排序——精排启用时让位（见模块 docstring 取舍）。
        items = items[:size]
        items, touched = _apply_feedback(items, needle)
        if touched > 0:
            notices.append("已按你的反馈调整 " + str(touched) + " 条结果的排序")
    return {
        "items": items,
        "total": len(items),
        "mode": mode,
        "engine": engine,
        "reranked": reranked,
        "notice": "；".join(notices),
    }
