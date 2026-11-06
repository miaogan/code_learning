"""简历改进要点投影（r7 AC-4 / AC-5 / AC-6 / AC-11 的 service 侧）。

本模块只做一件事：把 `resume_polish` 已经产出、已经过反幻觉校验的建议，投影成
「可逐字定位」的 3–5 条要点。它是 `resume_polish` 的**唯一**下游消费者，因此：

1. **零新入口**：`build_suggestions` + `validate_suggestions` 都从 `resume_polish`
   直接复用 —— 未在正文里逐字出现的建议在那一层已被整条丢弃（AC-4 ③），
   这里绝不再自写一遍校验，否则就会出现第二份口径；
2. **零猜测**：`anchor_text` 是简历正文的**逐字切片**（≤ `ANCHOR_MAX`），
   `focus_key` 与它逐字相等 —— 前端 `/polish?focus=` 的命中语义就是「逐字相等」（AC-5），
   因此不需要任何新 id、不需要落库；
3. **零抛错**：无正文 → `RESUME_NO_TEXT`（一次模型都不调），模型异常 → `RESUME_AI_FALLBACK`，
   两种降级都返回「空列表 + 中文原因」，报告页永远能渲染（AC-11 / anti-goal 5）。

文案一律取自 `services/coach_copy.py`（中文单源），本模块不写任何面向用户的字面量。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.schemas import PolishSuggestion, Profile, ResumePointer
from app.services.ai.ai import AIClient
from app.services.resume import resume_polish
from app.services.resume.coach_copy import RESUME_AI_FALLBACK, RESUME_NO_TEXT, SECTION_LABEL

#: 要点条数区间：少于 3 条如实给（不编造补足），多于 5 条按正文顺序截断。
MIN_POINTERS = 3
MAX_POINTERS = 5

#: 锚点上限：`anchor_text` / `focus_key` 都是 ≤40 字的逐字切片。
ANCHOR_MAX = 40

#: `issue` 上限（一句话问题），超长时按字截断，不加省略号（DESIGN §0.7 反模式）。
ISSUE_MAX = 60

#: 中文句末标点：`reason` 取第一句用。
_SENTENCE_ENDS = "。！？；"

#: `reason` 为空时的兜底问题句（保证 `issue` 永不为空，AC-4 的展示前提）。
_ISSUE_FALLBACK = "这条表述还可以更具体些"


@dataclass(frozen=True)
class ResumeHints:
    """`build_resume_pointers` 的返回值：要点列表 + 空态/降级原因（服务端定，前端只渲染）。"""

    pointers: list[ResumePointer]
    notice: str | None


def anchor_of(suggestion: PolishSuggestion, resume_text: str) -> str:
    """纯函数：`original_text` 的逐字锚点（≤40 字，不做 trim / 归一化）。

    - 原文不超过 `ANCHOR_MAX` 时原样使用（`validate_suggestions` 已保证它逐字出现在正文里）；
    - 否则取正文 `resume_text[found:found+ANCHOR_MAX]` —— 依然是正文切片，而不是对
      `original_text` 做任何改写（保证前端逐字匹配仍然命中）。
    """
    original = suggestion.original_text or ""
    if not original:
        return ""
    if len(original) <= ANCHOR_MAX:
        return original
    found = resume_text.find(original)
    if found < 0:  # 未经校验的调用方：退化成原文前缀，仍然来自正文的同一段文字
        return original[:ANCHOR_MAX]
    return resume_text[found : found + ANCHOR_MAX]


def _first_sentence(text: str) -> str:
    """取第一句（按中文句末标点切），并压掉首尾空白。"""
    body = (text or "").strip()
    for index, char in enumerate(body):
        if char in _SENTENCE_ENDS:
            return body[:index].strip()
    return body


def issue_of(suggestion: PolishSuggestion) -> str:
    """`issue` = `reason` 首句，≤60 字（超长直接按字截断，不加省略号）。"""
    sentence = _first_sentence(suggestion.reason)
    return sentence[:ISSUE_MAX] if sentence else _ISSUE_FALLBACK


def _location_of(suggestion: PolishSuggestion, resume_text: str) -> str:
    """「项目经历 · 第 12 行」：行号由服务端算出的 `start` 推出，零猜测。"""
    start = max(int(suggestion.start or 0), 0)
    line = resume_text[:start].count("\n") + 1
    label = SECTION_LABEL.get(suggestion.section) or suggestion.section
    return f"{label} · 第 {line} 行"


def to_pointers(suggestions: list[PolishSuggestion], resume_text: str) -> list[ResumePointer]:
    """纯函数：校验过的建议 → 要点列表（`start` 升序、锚点去重、最多 `MAX_POINTERS` 条）。

    锚点即定位键，两个建议落到同一段原文时展示会重复且跳转无区分度，因此保留
    `start` 更靠前的那条（`sorted` 稳定，同 `start` 时保持上游顺序）。
    """
    ordered = sorted(suggestions, key=lambda item: int(item.start or 0))
    pointers: list[ResumePointer] = []
    seen: set[str] = set()
    for suggestion in ordered:
        anchor = anchor_of(suggestion, resume_text)
        if not anchor or anchor in seen:
            continue
        seen.add(anchor)
        pointers.append(
            ResumePointer(
                section=suggestion.section,
                location=_location_of(suggestion, resume_text),
                anchor_text=anchor,
                issue=issue_of(suggestion),
                focus_key=anchor,
            )
        )
        if len(pointers) >= MAX_POINTERS:
            break
    return pointers


async def build_resume_pointers(
    resume_text: str | None,
    profile: Profile | None,
    target_role: str | None,
    *,
    client: AIClient | None = None,
) -> ResumeHints:
    """报告页「简历改进要点」的唯一入口：复用润色引擎，任何异常都降级为空列表 + 中文原因。

    `client` 走注入（单测零网络）；未注入时才由 `resume_polish` 构造 `AIClient`。
    """
    if not resume_text or not resume_text.strip():
        # AC-6：没有正文就没有可定位的句子，连模型都不调（省钱也省延迟）。
        return ResumeHints([], RESUME_NO_TEXT)

    try:
        drafts = await resume_polish.build_suggestions(
            resume_text, profile, target_role, client=client
        )
        kept, _dropped = resume_polish.validate_suggestions(
            drafts, resume_text, profile, target_role=target_role
        )
    except Exception:  # noqa: BLE001 - 降级是设计行为（AC-11），不是异常路径
        return ResumeHints([], RESUME_AI_FALLBACK)

    pointers = to_pointers(kept, resume_text)
    if not pointers:
        # 模型给了东西但全被反幻觉层丢掉（或无 Key / 空响应）：按降级文案提示去润色页。
        return ResumeHints([], RESUME_AI_FALLBACK)
    return ResumeHints(pointers, None)
