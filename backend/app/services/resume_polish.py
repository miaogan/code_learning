"""简历 AI 润色单一入口（r3 AC-8 ~ AC-13）。

四条硬约束，都靠「只有这一个入口」来保证：

1. **提示词只在这里**：`backend/app/routers/` / 前端 `pages/`、`components/` 零提示词、
   零模型名（AC-13 由检查器 grep 断言）；
2. **不落库**：采纳状态、临时目标岗位、成稿一律只活在 `_POLISH_CACHE`（进程内，
   `polish_id` 一次性句柄），`documents.text` 字节不变（AC-10 / AC-12）；
3. **反幻觉分两档**：新增**数字**就地降级为 `〈待补充〉`（建议保留），新增**专名**
   整条丢弃（宁可少一条，也不让「某大厂 / GMV 8000 万」进成稿）（AC-9）；
4. **成稿单源**：`compose_full` 按 `start/end` **区间拼装**（零 `str.replace`，杜绝级联替换），
   导出 / 复制只取 `/full` 响应的 `markdown`（AC-11）。
"""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from ..schemas import PolishSection, PolishSuggestion, Profile
from .ai import AIClient

#: 缺数值处的占位（唯一一处，前端只认这个串，不做本地改写）。
UNFILLED = "〈待补充〉"

#: 通过校验的最低口径（AC-8）：少于这个数就带 `insufficient_reason` 说明。
MIN_SUGGESTIONS = 3
MIN_SECTIONS = 2

POLISH_SECTIONS: tuple[str, ...] = ("project", "experience", "education", "summary")

POLISH_SYSTEM = """你是中文简历润色顾问。读候选人简历与画像，给出逐条、可逐字定位的润色建议，只输出 JSON。

硬性要求：
1. 至少 5 条建议，覆盖「项目经历 / 工作经历 / 教育经历 / 技能概述」中至少 2 个部分；
2. 每条 `original_text` 必须从简历正文**逐字抄录**（含标点与空格，不要缩写、不要拼接多段）；
3. `suggested_text` 只改措辞、句式与结构，**不得新增事实**：不新增公司名、项目名、
   技术专名、奖项、数字与年份；原句缺数值时写「〈待补充〉」占位，由候选人自己补；
4. `reason` 用中文说明改动带来的表达收益（20–60 字），不要空话；
5. `section` 只能取 project / experience / education / summary。

JSON 形态：{"suggestions":[{"section":…,"original_text":…,"suggested_text":…,"reason":…}]}"""

_SECTION_FALLBACK: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("项目", ("project",)),
    ("工作", ("experience",)),
    ("教育", ("education",)),
    ("技能", ("summary",)),
)

_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
_ASCII_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{1,}")
_BRACKET_RE = re.compile(r"「([^」]+)」|《([^》]+)》")


class _SuggestCase(BaseModel):
    """模型单条输出。`extra="ignore"`：预置响应里多出来的键不与契约绑定。"""

    model_config = {"extra": "ignore"}

    section: str = "summary"
    original_text: str = ""
    suggested_text: str = ""
    reason: str = ""


class _SuggestDraft(BaseModel):
    """模型整套输出（`schemas` 之外的内部草稿：`id` / `start` / `end` 由服务端算）。"""

    model_config = {"extra": "ignore"}

    suggestions: list[_SuggestCase] = Field(default_factory=list)


@dataclass(frozen=True)
class _CachedPolish:
    """`polish_id` 句柄背后的一次建议集（进程内、不落库）。"""

    polish_id: str
    resume_id: str
    target_role: str | None
    suggestions: list[PolishSuggestion] = field(default_factory=list)
    dropped_count: int = 0
    created_at: float = 0.0


#: 进程内缓存：上限 8 条、TTL 1800s、插入序淘汰（单进程 uvicorn 下有效，见 TECHNICAL §5）。
_CACHE_TTL_S = 1800.0
_CACHE_MAX = 8
_POLISH_CACHE: dict[str, _CachedPolish] = {}


# --- 提示词与输入 -------------------------------------------------------------


def _profile_brief(profile: Profile | None) -> str:
    """画像摘要（只给可解释的事实，避免模型拿它编数字）。"""
    if profile is None:
        return "（暂无画像：只按简历正文本身润色，不要引入画像之外的事实）"
    skills = "、".join(skill.name for skill in profile.skills) or "（无）"
    projects = "、".join(project.name for project in profile.projects) or "（无）"
    years = "未标注" if profile.years_experience is None else f"{profile.years_experience:g} 年"
    return (
        f"技能：{skills}\n"
        f"技术栈：{'、'.join(profile.tech_stack) or '（无）'}\n"
        f"项目：{projects}\n"
        f"经验年限：{years}\n"
        f"画像目标岗位：{profile.target_role or '未标注'}"
    )


def _polish_brief(resume_text: str, profile: Profile | None, target_role: str | None) -> str:
    role = target_role or (profile.target_role if profile is not None else None) or "未指定"
    return (
        f"【本次润色的目标岗位】{role}\n\n"
        f"【候选人画像】\n{_profile_brief(profile)}\n\n"
        f"【简历正文（original_text 必须逐字取自这里）】\n{resume_text}\n\n"
        "请输出 JSON：{\"suggestions\": [...]}"
    )


def _normalize_section(section: str, original_text: str, resume_text: str) -> PolishSection:
    """`section` 归一：模型给了合法值就用它，否则按原句所在段落兜底推一个。"""
    raw = (section or "").strip().lower()
    if raw in POLISH_SECTIONS:
        return raw  # type: ignore[return-value]
    index = resume_text.find(original_text) if original_text else -1
    if index >= 0:
        head = resume_text[:index]
        last_line = head.splitlines()[-1] if head.splitlines() else ""
        for keyword, sections in _SECTION_FALLBACK:
            if keyword in last_line:
                return sections[0]  # type: ignore[return-value]
    return "summary"


async def build_suggestions(
    resume_text: str,
    profile: Profile | None,
    target_role: str | None,
    *,
    client: AIClient | None = None,
) -> list[PolishSuggestion]:
    """调一次模型拿建议草案，并补齐服务端独占字段（`id` / `start` / `end` / `target_role`）。

    `client` 走注入（单测零网络）；未注入时才构造 `AIClient`（`ai.py` 是唯一出网口）。
    """
    ai = client or AIClient()
    draft = await ai.complete_model(
        POLISH_SYSTEM, _polish_brief(resume_text, profile, target_role), _SuggestDraft
    )
    suggestions: list[PolishSuggestion] = []
    for index, case in enumerate(draft.suggestions, start=1):
        original = case.original_text
        # `start/end` 只对「首次逐字命中」有意义；未命中留 0/0，交给 validate 丢弃。
        found = resume_text.find(original) if original else -1
        suggestions.append(
            PolishSuggestion(
                id=f"ps-{index}",
                section=_normalize_section(case.section, original, resume_text),
                original_text=original,
                suggested_text=case.suggested_text,
                reason=case.reason,
                target_role=target_role,
                flags=[],
                start=found if found >= 0 else 0,
                end=found + len(original) if found >= 0 else 0,
            )
        )
    return suggestions


# --- 反幻觉校验（纯函数，AC-9）-------------------------------------------------


def _allowed_numbers(profile: Profile | None) -> set[float]:
    """画像可解释的数字集合：经验年限 + 项目周期 / bullet 内数字（逐字对齐正文）。"""
    allowed: set[float] = set()
    if profile is None:
        return allowed
    if profile.years_experience is not None:
        allowed.add(float(profile.years_experience))
    for project in profile.projects:
        for token in _NUMBER_RE.findall(project.period) + _NUMBER_RE.findall(
            " ".join(project.bullets)
        ):
            allowed.add(float(token))
    return allowed


def _vocabulary(resume_text: str, profile: Profile | None, target_role: str | None) -> set[str]:
    """专名白名单（小写）：正文 + 画像技能 / 技术栈 / 项目名 / 目标岗位。"""
    words: set[str] = set()
    if profile is not None:
        for skill in profile.skills:
            words.add(skill.name.strip().lower())
        for token in profile.tech_stack:
            words.add(token.strip().lower())
        for project in profile.projects:
            words.add(project.name.strip().lower())
    if target_role:
        words.add(target_role.strip().lower())
    words.discard("")
    return words


def _downgrade_numbers(
    suggested_text: str,
    resume_text: str,
    allowed_numbers: set[float],
) -> tuple[str, bool]:
    """把「正文里没有、画像也解释不了」的数字就地换成 `〈待补充〉`（不丢建议）。"""
    resume_numbers = {float(token) for token in _NUMBER_RE.findall(resume_text)}
    changed = False

    def _replace(match: re.Match[str]) -> str:
        nonlocal changed
        token = match.group(0)
        value = float(token)
        if value in resume_numbers or value in allowed_numbers:
            return token
        changed = True
        return UNFILLED

    return _NUMBER_RE.sub(_replace, suggested_text), changed


def _first_new_proper_noun(
    suggested_text: str,
    resume_text: str,
    vocabulary: set[str],
) -> str | None:
    """返回第一个「新增专名」；没有则 `None`（该项整条丢弃，但数字降级后仍保留）。"""
    haystack = f"{resume_text}\n" + "\n".join(vocabulary)
    lowered = haystack.lower()
    for match in _ASCII_WORD_RE.finditer(suggested_text):
        word = match.group(0)
        if word.lower() not in lowered:
            return word
    for match in _BRACKET_RE.finditer(suggested_text):
        fragment = (match.group(1) or match.group(2) or "").strip()
        if fragment and fragment not in resume_text and fragment.lower() not in vocabulary:
            return fragment
    return None


def validate_suggestions(
    suggestions: list[PolishSuggestion],
    resume_text: str,
    profile: Profile | None,
    *,
    target_role: str | None = None,
) -> tuple[list[PolishSuggestion], int]:
    """后置事实校验（纯函数）：返回 `(保留列表, 丢弃条数)`。

    1. `original_text` 必须在正文**逐字**出现（不做 squash / trim），否则丢弃；
    2. `start/end` 取首次出现位置（前端切片预览与服务端成稿共用同一份映射）；
    3. 新增数字 → 就地 `〈待补充〉` + `flags=["numeric_added"]`；
    4. 新增专名 → 整条丢弃 + `dropped_count += 1`。
    """
    allowed_numbers = _allowed_numbers(profile)
    vocabulary = _vocabulary(resume_text, profile, target_role)
    kept: list[PolishSuggestion] = []
    dropped = 0

    for suggestion in suggestions:
        original = suggestion.original_text
        index = resume_text.find(original) if original else -1
        if index < 0:
            dropped += 1
            continue

        suggested_text, numeric_added = _downgrade_numbers(
            suggestion.suggested_text, resume_text, allowed_numbers
        )
        if _first_new_proper_noun(suggested_text, resume_text, vocabulary) is not None:
            dropped += 1
            continue

        flags = list(suggestion.flags)
        if numeric_added and "numeric_added" not in flags:
            flags.append("numeric_added")
        kept.append(
            suggestion.model_copy(
                update={
                    "suggested_text": suggested_text,
                    "flags": flags,
                    "start": index,
                    "end": index + len(original),
                }
            )
        )
    return kept, dropped


def insufficient_reason(suggestions: list[PolishSuggestion]) -> str | None:
    """条目不足时的中文说明（AC-8 的可量化口径：≥3 条且覆盖 ≥2 个 section）。"""
    sections = {suggestion.section for suggestion in suggestions}
    if len(suggestions) >= MIN_SUGGESTIONS and len(sections) >= MIN_SECTIONS:
        return None
    return (
        f"本次仅 {len(suggestions)} 条建议通过事实校验（覆盖 {len(sections)} 个部分），"
        f"不足 {MIN_SUGGESTIONS} 条 / {MIN_SECTIONS} 个部分；"
        "可以重试一次，或换一份信息更完整的简历。"
    )


# --- 成稿（纯函数，AC-11）------------------------------------------------------


def _header(target_role: str | None, dropped_count: int) -> str:
    role = (target_role or "").strip() or "未指定"
    return (
        f"# 简历（润色版）\n\n"
        f"> Skill Coach · 目标岗位：{role} · "
        f"{dropped_count} 条建议未通过事实校验已剔除\n\n"
    )


def compose_full(
    resume_text: str,
    suggestions: list[PolishSuggestion],
    adopted_ids: list[str] | None = None,
    *,
    target_role: str | None = None,
    dropped_count: int = 0,
) -> str:
    """按 `start/end` 区间拼装成稿：原文逐字保留，只把采纳区间换成 `suggested_text`。"""
    adopted = None if adopted_ids is None else {item for item in adopted_ids}
    chosen = [
        suggestion
        for suggestion in suggestions
        if adopted is None or suggestion.id in adopted
    ]
    chosen.sort(key=lambda suggestion: (suggestion.start, suggestion.end))

    if target_role is None:
        for suggestion in chosen:
            if suggestion.target_role:
                target_role = suggestion.target_role
                break

    cursor = 0
    parts: list[str] = []
    for suggestion in chosen:
        start, end = suggestion.start, suggestion.end
        # 越界 / 空区间 / 与已用区间重叠 → 跳过（确定性，杜绝重复替换与级联替换）
        if start < cursor or end > len(resume_text) or end <= start:
            continue
        parts.append(resume_text[cursor:start])
        parts.append(suggestion.suggested_text)
        cursor = end
    parts.append(resume_text[cursor:])
    body = "".join(parts)
    if not body.endswith("\n"):
        body += "\n"
    return _header(target_role, dropped_count) + body


# --- 一次性句柄（进程内缓存，不落库）-------------------------------------------


def _prune_cache(now: float) -> None:
    expired = [
        polish_id
        for polish_id, cached in _POLISH_CACHE.items()
        if now - cached.created_at > _CACHE_TTL_S
    ]
    for polish_id in expired:
        _POLISH_CACHE.pop(polish_id, None)


def remember_suggestions(
    resume_id: str,
    target_role: str | None,
    suggestions: list[PolishSuggestion],
    dropped_count: int,
) -> str:
    """把本次建议集挂到一个新的 `polish_id`（沿用插入序淘汰，超上限先丢最旧）。"""
    now = time.monotonic()
    _prune_cache(now)
    while len(_POLISH_CACHE) >= _CACHE_MAX:
        oldest = next(iter(_POLISH_CACHE))
        _POLISH_CACHE.pop(oldest, None)
    polish_id = f"pg-{uuid.uuid4().hex[:16]}"
    _POLISH_CACHE[polish_id] = _CachedPolish(
        polish_id=polish_id,
        resume_id=resume_id,
        target_role=target_role,
        suggestions=list(suggestions),
        dropped_count=dropped_count,
        created_at=now,
    )
    return polish_id


def recall_suggestions(polish_id: str) -> _CachedPolish | None:
    """取回一次建议集；未命中或已过 TTL 一律 `None`（调用方据此重跑并标 `regenerated`）。"""
    cached = _POLISH_CACHE.get(polish_id)
    if cached is None:
        return None
    if time.monotonic() - cached.created_at > _CACHE_TTL_S:
        _POLISH_CACHE.pop(polish_id, None)
        return None
    return cached


def clear_cache() -> None:
    """清空进程内缓存（只在测试与排障里用；生产无调用点）。"""
    _POLISH_CACHE.clear()


__all__ = [
    "MIN_SECTIONS",
    "MIN_SUGGESTIONS",
    "POLISH_SECTIONS",
    "POLISH_SYSTEM",
    "UNFILLED",
    "build_suggestions",
    "clear_cache",
    "compose_full",
    "insufficient_reason",
    "recall_suggestions",
    "remember_suggestions",
    "validate_suggestions",
]
