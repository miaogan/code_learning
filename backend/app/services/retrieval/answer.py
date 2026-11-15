"""r100 检索增强生成（RAG answer）+ LLM-as-judge（自动评审）。

管线与「能力边界」口径：
- **生成必须可溯源**：`generate_answer` 只把检索命中的 chunk 喂进提示词，模型引用
  的 chunk_id 必须落在白名单内，越界引用一律丢弃并计数（`dropped_citations`）——
  与画像 `source_quote` 原文命中、教练 href 白名单同一套反幻觉纪律。
- **评的是管线不是模型**：`judge_answer` 是给 `scripts/eval_rag_judge.py` 复用的
  评分器（faithfulness 引用忠实度 / relevance 相关性，0-10 分制）。默认
  `AI_EMBED_MODEL` 为空时整个 RAG 链路零网络可复跑；`--live` 真跑才消耗配额，
  报告必须如实标注 DRY-RUN / LIVE（与 eval_live.py 同一口径）。
"""

from __future__ import annotations

from app.schemas import RagAnswerDraft, RagJudgeDraft
from app.services.retrieval.hybrid import search_chunks

#: 每条 chunk 进提示词的正文上限：题目 prompt+explanation 实测 ≈2k 字符，
#: 截到 600 兼顾「答案有足够上下文」与「单次调用的 token 上界」。
_CITE_CONTEXT_CHARS = 600

#: 单次生成最多喂几条 chunk：top_k 与它取小。
_MAX_CONTEXT_CHUNKS = 5

_ANSWER_SYSTEM = (
    "你是站内题库与教程的答疑助手。你只能依据【材料】回答问题："
    "材料里没有的内容不要编造，可以直说材料未覆盖。"
    "回答末尾给出 citations 数组，逐项填写你实际引用的材料编号（如 m1、m2），"
    "不要引用没用到的材料。只输出一个 JSON 对象。"
)


def _material_block(chunks: list[dict]) -> str:
    lines = []
    for index, chunk in enumerate(chunks, start=1):
        content = str(chunk.get("content") or "")[:_CITE_CONTEXT_CHARS]
        title = str(chunk.get("title") or "")
        head = "m{}（{}）：{}".format(index, chunk.get("kind", ""), title)
        lines.append(head + "\n" + content)
    return "\n\n".join(lines)


async def generate_answer(
    query: str,
    chunks: list[dict],
    client: object,
) -> RagAnswerDraft:
    """检索增强生成：材料编号 → 答案 + 引用白名单过滤。

    `client` 是 `AIClient`（或测试里的 FakeAI），路由层经 `user_ai.client_for`
    取得，本模块不读任何裸配置（与 coach / 画像同一注入口径）。
    """
    if not chunks:
        return RagAnswerDraft(answer="没有检索到相关材料，暂时无法回答这个问题。", citations=[])
    user = "【问题】\n" + query + "\n\n【材料】\n" + _material_block(chunks)
    draft: RagAnswerDraft = await client.complete_model(  # type: ignore[attr-defined]
        _ANSWER_SYSTEM, user, RagAnswerDraft
    )
    # 白名单：m<n> 映射回第 n 条 chunk 的 chunk_id；模型若直接引用 chunk_id 也可通过
    # （两种形态都认），越界 / 不存在的引用一律丢弃并计入 dropped_citations。
    valid: list[str] = []
    for citation in draft.citations:
        text = str(citation).strip()
        if text.startswith("m") and text[1:].isdigit():
            num = int(text[1:])
            if 1 <= num <= len(chunks):
                valid.append(str(chunks[num - 1]["chunk_id"]))
                continue
        if text in {str(chunk["chunk_id"]) for chunk in chunks}:
            valid.append(text)
    deduped = list(dict.fromkeys(valid))
    draft.dropped_citations = max(0, len(draft.citations) - len(deduped))
    draft.citations = deduped
    return draft


_JUDGE_SYSTEM = (
    "你是 RAG 质量评审员。依据【问题】与【材料】对【回答】打分（0-10 整数）："
    "faithfulness = 回答是否只由材料支撑（编造、与材料矛盾即低分）；"
    "relevance = 回答是否切题且有信息量。发现的问题用中文短句列入 issues。"
    "只输出一个 JSON 对象。"
)


async def judge_answer(
    query: str, answer: str, chunks: list[dict], client: object
) -> RagJudgeDraft:
    """LLM-as-judge：对「检索增强生成」的输出做忠实度 / 相关性自动评审。"""
    user = (
        "【问题】\n"
        + query
        + "\n\n【材料】\n"
        + _material_block(chunks)
        + "\n\n【回答】\n"
        + answer
    )
    draft: RagJudgeDraft = await client.complete_model(  # type: ignore[attr-defined]
        _JUDGE_SYSTEM, user, RagJudgeDraft
    )
    return draft


def retrieve_for_answer(
    query: str, *, mode: str = "hybrid", top_k: int = _MAX_CONTEXT_CHUNKS
) -> dict:
    """生成前的检索步（包一层方便路由与评测脚本共用同一口径）。"""
    return search_chunks(query, mode=mode, top_k=max(1, min(int(top_k), _MAX_CONTEXT_CHUNKS)))
