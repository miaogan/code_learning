"""镜试服务（r125）：反向面试的评题与复盘编排。

与 `services.interview` 的分工：那边是「AI 面我」的计分状态机（runs / 评分 / 追问推进）；
这边是「我面我」的一次性复盘——没有场次、没有分数、没有成长时间线，一题一条完整复盘卡。

防编造的两层闸门（对齐 r116 画像溯源口径）：

1. **证据闸门**：AI 给出的每条 `evidence.quote` 必须能在所选简历正文中归一化后连续命中；
   命不中的整条剔除并计数（`dropped_evidence_count`），不让「宁缺毋滥」变成「整份报废」。
2. **数字闸门**：参考答案里新出现的多位数（指标、百分比、年限等）若简历正文找不到，
   一律降级为 `〈待补充〉` 并置 `answer_sanitized=True` —— 不能为了凑「满分」虚构量化成果。

缺失信息永远以「待补充」呈现：AI 只能说缺什么、为什么影响说服力，不能代填项目、指标或职责。
生成失败在入库前抛错，不会留下半条复盘记录。
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from typing import Any

from pydantic import BaseModel, Field

from app.core import repository
from app.core.errors import NOT_FOUND, AppError
from app.schemas import (
    MirrorAssessment,
    MirrorCard,
    MirrorEvidence,
    MirrorSuggestion,
    MirrorSuggestions,
)

#: 引用归一化口径与画像溯源一致：NFKC 抹平全半角 + 去 Unicode Cf 不可见字符 + 去空白。
_IGNORABLE_CATEGORY = "Cf"

#: 模型抄到一半用省略号收尾很常见，是截断不是编造——只放宽末尾。
_TRAILING_ELLIPSES = ("……", "...", "…", "。。", "~", "～")

#: 数字闸门只拦「多位数或百分比」：单个数字常是序号（"第1"），误杀率高于收益。
_NUMBER_PATTERN = re.compile(r"\d[\d,]*\.?\d*\s*%?")

#: 归一化后的简历正文超过这个长度就截断进提示词（与画像链路同量级），防止撑爆上下文。
_MAX_RESUME_CHARS = 18000


# --- 溯源工具（与 profile._squash / _quote_hits 同口径，独立实现避免反向依赖画像模块）


def _squash(text: str) -> str:
    """NFKC + 去 Cf + 去空白：模型丢换行、全半角互换、PDF 隐形字符都不算编造。"""
    return "".join(
        char
        for char in unicodedata.normalize("NFKC", text)
        if not char.isspace() and unicodedata.category(char) != _IGNORABLE_CATEGORY
    )


def _without_trailing_ellipsis(text: str) -> str:
    cleaned = text.rstrip()
    for mark in _TRAILING_ELLIPSES:
        while cleaned.endswith(mark):
            cleaned = cleaned[: -len(mark)].rstrip()
    return cleaned


def _quote_hits(quote: str, haystack: str) -> bool:
    normalized = _squash(_without_trailing_ellipsis(quote))
    return bool(normalized) and normalized in haystack


def _clip_quote(quote: str, limit: int = 360) -> str:
    """过长引用从起点截断——截断后仍是连续逐字片段，命中口径不变。"""
    return quote[:limit].rstrip()


# --- AI 输出草稿模型（HTTP 契约在 schemas.py，这里的草稿模型只服务于解析与校验）


class _SuggestionDraft(BaseModel):
    """AI 推荐题草稿：quote 会在服务端过原文闸门，命不中的整条剔除。"""

    items: list[MirrorSuggestion] = Field(default_factory=list)


class _CardDraft(BaseModel):
    """一次完整复盘的 AI 草稿；answer / rationale / evidence 都会在服务端二次校验。

    `question` 只在用户没有自拟问题时生效（AI 先推荐题目再复盘）；自拟路径下服务端
    直接使用用户的原文，AI 返回什么都会被丢弃。
    """

    question: str = Field(default="", max_length=300)
    answer: str = Field(min_length=1, max_length=4000)
    rationale: list[str] = Field(default_factory=list, max_length=6)
    assessment: MirrorAssessment
    follow_ups: list[str] = Field(default_factory=list, max_length=4)
    evidence: list[MirrorEvidence] = Field(default_factory=list, max_length=6)
    missing_info: list[str] = Field(default_factory=list, max_length=4)


# --- 提示词 ------------------------------------------------------------------------

_SUGGEST_SYSTEM = (
    "你是资深技术面试官教练。用户会提供自己的一份简历，你的任务是站在面试官视角，"
    "为这份简历设计面试官最可能追问的问题，帮用户自查简历盲点。"
    "每个问题必须锚定简历原文的一个真实片段（quote 字段逐字摘录原文，不要改写），"
    "并说明为什么值得问（rationale）。不要编造简历里没有的经历、项目或指标。"
    "全部用简体中文。"
)

_ASK_SYSTEM = (
    "你是资深技术面试官教练，帮助用户以面试官视角复盘自己的简历。"
    "用户会提供一份简历和一个问题（问题可能是用户自拟的，也可能是你推荐的）。"
    "你需要产出一份完整复盘：参考满分答案、为什么这么答（答案结构与表达思路，"
    "并标注它依据简历哪些原文）、这道题本身的出题水准评价、面试官可能的追问方向。"
    "严格约束：满分答案只能使用简历正文里真实存在的信息；"
    "答案需要的量化指标或细节如果简历里没有，写成〈待补充〉并说明应补什么，"
    "绝不编造项目、数字、经历或职责。evidence 的 quote 字段必须逐字摘录简历原文。"
    "全部用简体中文。"
)


def _resume_snippet(text: str) -> str:
    """简历正文进提示词前的统一截断（保留开头——简历天然是头重脚轻的）。"""
    flat = text.strip()
    if len(flat) > _MAX_RESUME_CHARS:
        return flat[:_MAX_RESUME_CHARS].rstrip() + "\n（后文已截断）"
    return flat


def _load_resume(resume_id: str) -> tuple[str, str]:
    """读简历正文与文件名；查不到或正文为空一律按「简历不存在」处理（跨用户同口径 404）。"""
    document = repository.get_document(resume_id)
    if document is None or not str(document["text"]).strip():
        raise AppError(
            NOT_FOUND, "简历不存在或内容为空，请先上传简历", status=404
        )
    return str(document["text"]), str(document["file_name"] or "")


def _sanitize_numbers(answer: str, haystack: str) -> tuple[str, bool]:
    """数字闸门：答案里简历找不到的多位数/百分比替换为〈待补充〉。

    只拦 2 位以上或带百分号的数字——单个数字多为序号与年份片段，误杀率高。
    逗号在归一化后不参与比对（`3,000` 与 `3000` 算同一数字）。
    """
    sanitized = False

    def _replace(match: re.Match[str]) -> str:
        nonlocal sanitized
        token = match.group(0)
        digits = token.replace(",", "").replace(" ", "").rstrip("%").rstrip(".")
        if len(digits) < 2 and "%" not in token:
            return token
        if digits in haystack:
            return token
        placeholder = "〈待补充〉"
        if "%" in token:
            placeholder += "（占比）"
        sanitized = True
        return placeholder

    return _NUMBER_PATTERN.sub(_replace, answer), sanitized


def _filter_evidence(
    evidence: list[MirrorEvidence], haystack: str
) -> tuple[list[MirrorEvidence], int]:
    """证据闸门：quote 命不中的整条剔除，返回（保留条目, 剔除数）。"""
    kept: list[MirrorEvidence] = []
    dropped = 0
    for item in evidence:
        item.quote = _clip_quote(item.quote)
        if item.quote and _quote_hits(item.quote, haystack):
            kept.append(item)
        else:
            dropped += 1
    return kept, dropped


# --- 对外入口 ----------------------------------------------------------------------


async def suggest_questions(
    resume_id: str, count: int, *, client: Any
) -> MirrorSuggestions:
    """AI 依据简历推荐自问题目；quote 过不了原文闸门的整条不推荐。"""
    resume_text, _ = _load_resume(resume_id)
    haystack = _squash(resume_text)
    prompt = (
        f"以下是用户的简历正文。请推荐 {count} 个面试官视角的自查问题。\n\n"
        f"{_resume_snippet(resume_text)}"
    )
    draft = await client.complete_model(_SUGGEST_SYSTEM, prompt, _SuggestionDraft)
    kept: list[MirrorSuggestion] = []
    dropped = 0
    for item in draft.items:
        item.quote = _clip_quote(item.quote)
        if item.quote and _quote_hits(item.quote, haystack):
            if len(kept) < count:
                kept.append(item)
            # 超出请求数的合格条目直接不返回，也不计入 dropped（那是编造的口径）。
        else:
            dropped += 1
    return MirrorSuggestions(resume_id=resume_id, items=kept, dropped_count=dropped)


async def ask(
    resume_id: str,
    question: str | None,
    source: str,
    *,
    client: Any,
) -> MirrorCard:
    """一次自问复盘：生成完整复盘卡并入库；失败在入库前抛错，不留半条记录。"""
    resume_text, file_name = _load_resume(resume_id)
    haystack = _squash(resume_text)
    asked = (question or "").strip()
    question_block = (
        f"用户自拟的问题：「{asked}」\n请围绕这个问题产出复盘，不要另拟问题。"
        if asked
        else "用户没有自拟问题。请先依据简历推荐一个值得自查的问题（作为 question 返回），"
        "再产出完整复盘。"
    )
    prompt = (
        f"{question_block}\n\n以下是用户的简历正文：\n\n{_resume_snippet(resume_text)}"
    )
    draft = await client.complete_model(_ASK_SYSTEM, prompt, _CardDraft)

    # 输出护栏：答案正文与列表项都是模型写的，可能复述用户输入里的联系方式。
    from app.services.ai import guardrails

    answer = draft.answer
    guarded = guardrails.guard_output(answer, surface="mirror.answer")
    if guarded.blocked:
        answer = guarded.notice
    elif guarded.changed:
        answer = guarded.text
    rationale = _guard_list(draft.rationale)
    follow_ups = _guard_list(draft.follow_ups)

    evidence, dropped_evidence = _filter_evidence(draft.evidence, haystack)
    answer, answer_sanitized = _sanitize_numbers(answer, haystack)

    card_id = uuid.uuid4().hex
    payload: dict[str, Any] = {
        "answer": answer,
        "rationale": rationale,
        "assessment": draft.assessment.model_dump(),
        "follow_ups": follow_ups,
        "evidence": [item.model_dump() for item in evidence],
        "missing_info": draft.missing_info,
        "dropped_evidence_count": dropped_evidence,
        "answer_sanitized": answer_sanitized,
    }
    repository.save_mirror_card(
        card_id,
        resume_id=resume_id,
        file_name=file_name,
        question=asked or draft.question.strip() or "（AI 推荐题）",
        payload=payload,
        source=source,
    )
    row = repository.mirror_card_row(card_id)
    assert row is not None, "复盘卡写入后必须立即可读"
    return card_from_row(row)


def _guard_list(items: list[str]) -> list[str]:
    """列表型输出逐条过输出护栏：命中整条丢弃，被改动则用净化文本。"""
    from app.services.ai import guardrails

    kept: list[str] = []
    for item in items:
        guarded = guardrails.guard_output(item, surface="mirror.answer")
        if guarded.blocked:
            continue
        kept.append(guarded.text if guarded.changed else item)
    return kept


def list_cards(limit: int = 50) -> list[dict[str, Any]]:
    """当前账号最近的复盘列表（repository 透传；行 → 契约在路由层用 `card_from_row`）。"""
    return repository.list_mirror_cards(limit)


def card_from_row(row: dict[str, Any]) -> MirrorCard:
    """repository 行 → 契约模型。AI 草稿里若带了多余的 question 字段在这里被丢弃。"""
    payload = dict(row["payload"])
    question = str(row["question"])
    assessment_raw = payload.get("assessment")
    assessment = (
        MirrorAssessment.model_validate(assessment_raw)
        if isinstance(assessment_raw, dict)
        else MirrorAssessment(level="合格", strengths=[], improvements=[])
    )
    evidence = [
        MirrorEvidence.model_validate(item)
        for item in payload.get("evidence", [])
        if isinstance(item, dict)
    ]
    return MirrorCard(
        id=str(row["id"]),
        resume_id=str(row["resume_id"]),
        file_name=str(row["file_name"]),
        question=question,
        answer=str(payload.get("answer", "")),
        rationale=[str(item) for item in payload.get("rationale", [])],
        assessment=assessment,
        follow_ups=[str(item) for item in payload.get("follow_ups", [])],
        evidence=evidence,
        missing_info=[str(item) for item in payload.get("missing_info", [])],
        origin="recommended" if row["source"] == "recommended" else "custom",
        dropped_evidence_count=max(int(payload.get("dropped_evidence_count", 0)), 0),
        answer_sanitized=bool(payload.get("answer_sanitized", False)),
        created_at=str(row["created_at"]),
    )
