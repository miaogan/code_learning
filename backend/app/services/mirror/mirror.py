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

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core import repository
from app.core.errors import AI_SCHEMA_INVALID, NOT_FOUND, AppError
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


# --- AI 输出草稿模型（HTTP 契约在 schemas.py，这里的草稿模型只服务于解析）------------
#: 解析口径是「宽松接住、服务端归一」：真实模型的输出会出现 level 写成「非常优秀」、
#: 列表写成单个字符串、字段超长等形态——严格 Literal / max_length 只会把能救的响应
#: 变成 502 AI_SCHEMA_INVALID。所有闭集收敛与裁剪都在这里做，契约模型保持严格。

_WRAPPER_KEYS = ("result", "data", "response", "output")

_LEVEL_WORDS: tuple[tuple[str, str], ...] = (
    ("优秀", "优秀"),
    ("高", "优秀"),
    ("良好", "合格"),
    ("合格", "合格"),
    ("中等", "合格"),
    ("基础", "基础"),
    ("简单", "基础"),
    ("入门", "基础"),
    ("初级", "基础"),
    ("低", "基础"),
)


def _unwrap(value: Any) -> Any:
    """剥掉常见的单键包装（{"result": {...}} / {"data": {...}}），找不到就原样返回。"""
    if isinstance(value, dict) and len(value) == 1 and isinstance(next(iter(value.values())), dict):
        key = next(iter(value))
        if key.lower() in _WRAPPER_KEYS:
            return next(iter(value.values()))
    return value


def _as_str(value: Any) -> str:
    """字段兜底成字符串：None → 空串，dict 包装（{"text": …}）取常见键。"""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("text", "content", "answer", "value"):
            inner = value.get(key)
            if isinstance(inner, str):
                return inner
    if value is None:
        return ""
    return str(value)


def _as_str_list(value: Any) -> list[str]:
    """列表字段兜底：字符串 → 单元素列表；None → []；元素逐个转 str。"""
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, dict):
        # {"items": [...]} / {"points": [...]} 这类键值包装取第一个列表值。
        for inner in value.values():
            if isinstance(inner, list):
                return [str(item) for item in inner]
        return [str(item) for item in value.values()]
    if isinstance(value, list):
        return [str(item) for item in value]
    return []


def _as_obj_list(value: Any, *, str_key: str) -> list[dict[str, Any]]:
    """对象列表字段兜底：dict 包装取首个列表值；裸字符串条目按 `str_key` 收编。"""
    if value is None:
        return []
    if isinstance(value, dict):
        for inner in value.values():
            if isinstance(inner, list):
                value = inner
                break
        else:
            value = [value]
    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            result.append(item)
        elif isinstance(item, str) and item.strip():
            result.append({str_key: item.strip()})
    return result


def _clip_str(value: str, limit: int) -> str:
    return value.strip()[:limit].rstrip()


def _normalize_level(raw: Any) -> str:
    """AI 的档位词收敛进契约闭集；命中不了就保守归「合格」，不让整卡报废。"""
    text = _as_str(raw)
    for token, level in _LEVEL_WORDS:
        if token in text:
            return level
    return "合格"


class _DraftSuggestion(BaseModel):
    """推荐题宽松草稿：三个字段都兜底成 str，超长由服务端裁剪。"""

    question: str = ""
    rationale: str = ""
    quote: str = ""

    model_config = ConfigDict(extra="ignore")

    @field_validator("question", "rationale", "quote", mode="before")
    @classmethod
    def _coerce(cls, value: Any) -> Any:
        return _as_str(value)


class _SuggestionDraft(BaseModel):
    """AI 推荐题草稿：quote 会在服务端过原文闸门，命不中的整条剔除。"""

    items: list[_DraftSuggestion] = Field(default_factory=list)

    model_config = ConfigDict(extra="ignore")

    @field_validator("items", mode="before")
    @classmethod
    def _coerce_items(cls, value: Any) -> Any:
        return _as_obj_list(value, str_key="question")

    @model_validator(mode="before")
    @classmethod
    def _peel(cls, value: Any) -> Any:
        return _unwrap(value)


class _DraftEvidence(BaseModel):
    claim: str = ""
    quote: str = ""

    model_config = ConfigDict(extra="ignore")

    @field_validator("claim", "quote", mode="before")
    @classmethod
    def _coerce(cls, value: Any) -> Any:
        return _as_str(value)


class _DraftAssessment(BaseModel):
    level: str = ""
    strengths: list[str] = Field(default_factory=list)
    improvements: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="ignore")

    @field_validator("level", mode="before")
    @classmethod
    def _coerce_level(cls, value: Any) -> Any:
        return _as_str(value)

    @field_validator("strengths", "improvements", mode="before")
    @classmethod
    def _coerce_lists(cls, value: Any) -> Any:
        return _as_str_list(value)


class _CardDraft(BaseModel):
    """一次完整复盘的宽松草稿；归一成契约模型之前一切字段都可能是不规整的形态。

    `question` 只在用户没有自拟问题时生效（AI 先推荐题目再复盘）；自拟路径下服务端
    直接使用用户的原文，AI 返回什么都会被丢弃。
    """

    question: str = ""
    answer: str = ""
    rationale: list[str] = Field(default_factory=list)
    assessment: _DraftAssessment = Field(default_factory=_DraftAssessment)
    follow_ups: list[str] = Field(default_factory=list)
    evidence: list[_DraftEvidence] = Field(default_factory=list)
    missing_info: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="ignore")

    @field_validator("question", "answer", mode="before")
    @classmethod
    def _coerce_str(cls, value: Any) -> Any:
        return _as_str(value)

    @field_validator("rationale", "follow_ups", "missing_info", mode="before")
    @classmethod
    def _coerce_lists(cls, value: Any) -> Any:
        return _as_str_list(value)

    @field_validator("evidence", mode="before")
    @classmethod
    def _coerce_evidence(cls, value: Any) -> Any:
        return _as_obj_list(value, str_key="quote")

    @field_validator("assessment", mode="before")
    @classmethod
    def _coerce_assessment(cls, value: Any) -> Any:
        if isinstance(value, str):
            # 有些模型把档位压成一个词：「assessment": "优秀"」——按 level 兜住。
            return {"level": value}
        return _unwrap(value)

    @model_validator(mode="before")
    @classmethod
    def _peel(cls, value: Any) -> Any:
        return _unwrap(value)


# --- 提示词（含显式 JSON 骨架：结构错误的最大来源是模型自拟字段名）-------------------

_SUGGEST_SYSTEM = (
    "你是资深技术面试官教练。用户会提供自己的一份简历，你的任务是站在面试官视角，"
    "为这份简历设计面试官最可能追问的问题，帮用户自查简历盲点。"
    "每个问题必须锚定简历原文的一个真实片段（quote 字段逐字摘录原文，不要改写），"
    "并说明为什么值得问（rationale）。不要编造简历里没有的经历、项目或指标。"
    "全部用简体中文。"
    "\n\n只输出一个 JSON 对象，不要输出任何解释文字，结构必须是：\n"
    '{"items": [{"question": "问题", "rationale": "为什么值得问", '
    '"quote": "简历原文的逐字片段"}]}\n'
    "items 给 4 条左右；question 不超过 200 字，rationale 不超过 100 字。"
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
    "\n\n只输出一个 JSON 对象，不要输出任何解释文字，结构必须是：\n"
    '{"question": "复盘的题目", "answer": "参考满分答案", '
    '"rationale": ["答题理由（2-4 条）"], '
    '"assessment": {"level": "只能是 基础 / 合格 / 优秀 三选一", '
    '"strengths": ["出题优点"], "improvements": ["可改进处"]}, '
    '"follow_ups": ["追问方向（2-3 条）"], '
    '"evidence": [{"claim": "这条证据说明什么", "quote": "简历原文的逐字片段"}], '
    '"missing_info": ["简历缺失、需要用户补充的信息"]}\n'
    "answer 不超过 1500 字；各列表不超过 4 条；level 字段只能取 基础、合格、优秀 之一。"
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
    evidence: list[_DraftEvidence], haystack: str
) -> tuple[list[MirrorEvidence], int]:
    """证据闸门：quote 命不中的整条剔除，返回（契约条目, 剔除数）。

    claim 缺失时给中性占位——证据的价值在 quote 能命中原文，claim 只是给人看的摘要。
    """
    kept: list[MirrorEvidence] = []
    dropped = 0
    for item in evidence:
        quote = _clip_quote(item.quote)
        if quote and _quote_hits(quote, haystack):
            claim = _clip_str(item.claim, 240) or "简历原文佐证"
            kept.append(MirrorEvidence(claim=claim, quote=quote))
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
        question = _clip_str(item.question, 300)
        if not question:
            dropped += 1
            continue
        quote = _clip_quote(item.quote)
        if quote and _quote_hits(quote, haystack):
            if len(kept) < count:
                kept.append(
                    MirrorSuggestion(
                        question=question,
                        rationale=_clip_str(item.rationale, 240) or "锚定简历原文的追问点",
                        quote=quote,
                    )
                )
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
    if not draft.answer.strip():
        # 宽松解析后仍然没有答案正文：这卡没法复盘，按既有口径让用户重试。
        raise AppError(
            AI_SCHEMA_INVALID, "AI 返回的结构不符合预期，请重试一次", status=502, retryable=True
        )

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

    assessment = MirrorAssessment(
        level=_normalize_level(draft.assessment.level),
        strengths=[
            _clip_str(item, 120) for item in draft.assessment.strengths if item.strip()
        ][:4],
        improvements=[
            _clip_str(item, 120) for item in draft.assessment.improvements if item.strip()
        ][:4],
    )

    card_id = uuid.uuid4().hex
    payload: dict[str, Any] = {
        "answer": answer[:4000],
        "rationale": rationale[:6],
        "assessment": assessment.model_dump(),
        "follow_ups": follow_ups[:4],
        "evidence": [item.model_dump() for item in evidence],
        "missing_info": [_clip_str(item, 200) for item in draft.missing_info if item.strip()][:4],
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
