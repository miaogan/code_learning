"""画像增量合并与「记忆视图」（AC-6 / AC-7 的唯一语义出口）。

契约：
- `merge_profile` 是**纯函数**：不碰 AI、不碰 DB，输入旧画像 + 新草稿，输出合并后的
  画像与新事件摘要 —— 这样合并规则可以表驱动单测（TECHNICAL §4.4）。
- 归一口径（`normalize_name`）只此一处：出题、诊断要取能力项一律走
  `active_skills` / `active_projects`，历史项（`status="historical"`）永不出现在
  出题素材里（AC-7「历史项不进画出题与诊断的能力输入」）。
- 证据累积方向固定**旧→新**：旧证据在前、本次简历证据追加在后，且同
  `resume_id` + 同 quote 的证据不重复追加（同一份简历连传两次不涨证据）。
- `source_quote` 是兼容字段，恒等于 `source_quotes[0].quote`（首条证据即「最早的出处」）。
"""

from __future__ import annotations

import unicodedata
import uuid
from datetime import UTC, datetime
from typing import NamedTuple

from pydantic import BaseModel, Field

from ..schemas import Profile, ProfileDraft, ProfileProject, ProfileSkill

#: 历史项的状态值。active 表示「当前简历仍然写了」，historical 表示「只在旧简历里出现」。
STATUS_ACTIVE = "active"
STATUS_HISTORICAL = "historical"

#: 出题素材的下限：active 能力项少于这个数时，出题侧以 `tech_stack` 兜底（AC-7）。
MIN_ACTIVE_SKILLS = 3

# --- 契约兼容层（TECHNICAL §3）------------------------------------------------
# `Evidence` / `ProfileSkill(source_quotes, status)` / `ProfileMergeSummary` /
# `ProfileWithMerge` 的契约归属是 `schemas.py`（T1）。并行开发窗口内该契约可能尚未
# 落地：此时在**本模块**声明字段等价的超集模型，POST 照样返回 r3 形状（前端 T7/T8
# 直接消费，不空等契约），而 `schemas.py` 一旦声明了同名字段，下面每个名字都会自动
# 切回契约真源 —— 本层随即退化为空操作，不产生第二份契约定义。

try:  # pragma: no cover - 走哪个分支由 `schemas.py` 是否已含 r3 契约决定
    from ..schemas import Evidence as _SchemaEvidence
    from ..schemas import ProfileMergeSummary as _SchemaMergeSummary
    from ..schemas import ProfileWithMerge as _SchemaWithMerge
except ImportError:  # pragma: no cover - 契约未落地
    _SchemaEvidence = None  # type: ignore[assignment,misc]
    _SchemaMergeSummary = None  # type: ignore[assignment,misc]
    _SchemaWithMerge = None  # type: ignore[assignment,misc]

#: `schemas.py` 是否已声明证据链字段（`ProfileSkill` 的两个 r3 新字段）。
SKILL_HAS_EVIDENCE_FIELDS = all(
    name in getattr(ProfileSkill, "model_fields", {}) for name in ("source_quotes", "status")
)

#: 契约真源是否就绪（证据字段 + 摘要 + 响应模型三件齐备）。
CONTRACT_READY = (
    SKILL_HAS_EVIDENCE_FIELDS
    and _SchemaEvidence is not None
    and _SchemaMergeSummary is not None
    and _SchemaWithMerge is not None
)


class _FallbackEvidence(BaseModel):  # pragma: no cover - 契约未落地时才实例化
    """一条可溯源证据（字段与 `schemas.Evidence` 等价）。"""

    quote: str
    resume_id: str = ""
    file_name: str = ""
    captured_at: str = ""


class _FallbackMergeSummary(BaseModel):  # pragma: no cover - 契约未落地时才实例化
    """合并摘要（字段与 `schemas.ProfileMergeSummary` 等价）。"""

    added: int = 0
    historical: int = 0
    evidence_added: int = 0
    duplicate: bool = False


Evidence = _SchemaEvidence if _SchemaEvidence is not None else _FallbackEvidence
ProfileMergeSummary = (
    _SchemaMergeSummary if _SchemaMergeSummary is not None else _FallbackMergeSummary
)


if CONTRACT_READY:  # pragma: no cover - 契约真源就绪：本模块零模型定义
    MergedSkill = ProfileSkill
    MergedProject = ProfileProject
    MergedProfile = Profile
    ProfileWithMerge = _SchemaWithMerge
else:  # pragma: no cover - 并行开发窗口：字段等价超集，契约落地后整段失效

    class MergedSkill(ProfileSkill):
        """带证据链与历史标记的能力项（`source_quotes` 旧→新累积）。"""

        source_quotes: list[Evidence] = Field(default_factory=list)  # type: ignore[valid-type]
        status: str = STATUS_ACTIVE

    class MergedProject(ProfileProject):
        """带证据链与历史标记的项目经历（字段口径与技能一致）。"""

        source_quotes: list[Evidence] = Field(default_factory=list)  # type: ignore[valid-type]
        status: str = STATUS_ACTIVE

    class MergedProfile(Profile):
        """合并结果：技能/项目换成带证据链的条目，其余维度沿用契约本体。"""

        skills: list[MergedSkill] = Field(default_factory=list)
        projects: list[MergedProject] = Field(default_factory=list)

    class ProfileWithMerge(MergedProfile):  # type: ignore[no-redef]
        """POST 的一次性响应：`merge_summary` 只挂这里，不进 GET 的持久契约。"""

        merge_summary: ProfileMergeSummary | None = None  # type: ignore[valid-type]


def normalize_name(name: str) -> str:
    """能力项判同口径：NFKC（全角→半角）→ 去首尾空白 → casefold → 折叠内部空白。

    `"Python"` / `"python "` / `"Ｐｙｔｈｏｎ"` 归一后都是 `"python"`（AC-7）。
    """
    text = unicodedata.normalize("NFKC", name).strip().casefold()
    return " ".join(text.split())


class _EvidenceSource(NamedTuple):
    """本次简历的出处信息：三条证据都指向同一份简历，只有片段不同。"""

    resume_id: str
    file_name: str
    captured_at: str

    def of(self, quote: str) -> Evidence:
        return Evidence(
            quote=quote,
            resume_id=self.resume_id,
            file_name=self.file_name,
            captured_at=self.captured_at,
        )


def _quotes_of(entry: ProfileSkill | ProfileProject) -> list[Evidence]:
    """读出一条条目的证据链（旧→新）；存量 payload 没有 `source_quotes` 时由 `source_quote` 回填。"""
    quotes = list(getattr(entry, "source_quotes", []) or [])
    if not quotes:
        quote = getattr(entry, "source_quote", "")
        if quote:
            quotes = [Evidence(quote=quote)]
    return quotes


def _status_of(entry: ProfileSkill | ProfileProject) -> str:
    return getattr(entry, "status", STATUS_ACTIVE) or STATUS_ACTIVE


def _same_evidence(left: Evidence, right: Evidence) -> bool:
    """同来源简历 + 同原文片段 = 同一条证据（空白差异不算新证据）。"""
    return left.resume_id == right.resume_id and "".join(left.quote.split()) == "".join(
        right.quote.split()
    )


def _append_evidence(
    quotes: list[Evidence], incoming: Evidence, *, counters: dict[str, int]
) -> list[Evidence]:
    """把本次简历的证据追加到旧证据链末尾（旧→新），已存在则不重复追加。"""
    if any(_same_evidence(existing, incoming) for existing in quotes):
        return quotes
    counters["evidence_added"] += 1
    return [*quotes, incoming]


def _merge_entries(
    old_entries: list[ProfileSkill] | list[ProfileProject],
    draft_entries: list[ProfileSkill] | list[ProfileProject],
    *,
    source: _EvidenceSource,
    is_skill: bool,
    counters: dict[str, int],
) -> list[dict[str, object]]:
    """按 `normalize_name` 判同合并技能 / 项目，返回可直接喂给 pydantic 的 payload 列表。

    顺序口径：旧条目原位保留（`name` 用首次出现的写法，避免展示抖动），只在本次简历
    出现的新条目追加在末尾 —— 画像页的条目顺序因此不会随每次上传重排。
    """
    drafts_by_key = {normalize_name(entry.name): entry for entry in draft_entries}
    merged: list[dict[str, object]] = []
    seen: set[str] = set()

    for entry in old_entries:
        key = normalize_name(entry.name)
        if key in seen:  # 存量里已有同义重复项：只保留第一条，其余并入
            continue
        seen.add(key)
        quotes = _quotes_of(entry)
        draft_entry = drafts_by_key.get(key)
        if draft_entry is None:
            status = _status_of(entry)
            if status == STATUS_ACTIVE and is_skill:
                counters["historical"] += 1
            status = STATUS_HISTORICAL
        else:
            status = STATUS_ACTIVE
            quotes = _append_evidence(
                quotes, source.of(draft_entry.source_quote), counters=counters
            )
        merged.append(_entry_payload(entry, quotes, status, draft_entry, is_skill=is_skill))

    for entry in draft_entries:
        key = normalize_name(entry.name)
        if key in seen:
            continue
        seen.add(key)
        if is_skill:  # 摘要只统计技能口径（`added` / `historical` 都是「能力项」数）
            counters["added"] += 1
        merged.append(
            _entry_payload(entry, [source.of(entry.source_quote)], STATUS_ACTIVE, entry, is_skill=is_skill)
        )

    return merged


def _entry_payload(
    base: ProfileSkill | ProfileProject,
    quotes: list[Evidence],
    status: str,
    draft_entry: ProfileSkill | ProfileProject | None,
    *,
    is_skill: bool,
) -> dict[str, object]:
    """组装单条目 payload：`name` 取旧写法，其余维度优先本次简历（同一条目也可能补全）。"""
    payload: dict[str, object] = {
        "name": base.name,
        "source_quote": quotes[0].quote if quotes else getattr(base, "source_quote", ""),
        "source_quotes": quotes,
        "status": status,
    }
    if is_skill:
        return payload
    source = draft_entry or base
    payload.update(
        {
            "role": getattr(source, "role", ""),
            "period": getattr(source, "period", ""),
            "bullets": list(getattr(source, "bullets", []) or []),
        }
    )
    return payload


def merge_profile(
    old: Profile | None,
    draft: ProfileDraft,
    *,
    resume_id: str,
    file_name: str = "",
    captured_at: str = "",
    duplicate: bool = False,
) -> tuple[MergedProfile, ProfileMergeSummary]:
    """把新简历草稿合并进当前画像：同 `profile_id`、证据旧→新累积、消失项转 historical。"""
    now = datetime.now(UTC).isoformat()
    source = _EvidenceSource(
        resume_id=resume_id, file_name=file_name, captured_at=captured_at
    )
    counters = {"added": 0, "historical": 0, "evidence_added": 0}

    skills = _merge_skills(old.skills if old else [], draft.skills, source, counters)
    projects = _merge_projects(old.projects if old else [], draft.projects, source, counters)

    tech_stack = list(draft.tech_stack) or (list(old.tech_stack) if old else [])
    payload = {
        "id": old.id if old else uuid.uuid4().hex,
        "resume_id": resume_id,
        "updated_at": now,
        "skills": skills,
        "projects": projects,
        "tech_stack": tech_stack,
        "years_experience": (
            draft.years_experience if draft.years_experience is not None else (old.years_experience if old else None)
        ),
        "target_role": draft.target_role if draft.target_role is not None else (old.target_role if old else None),
    }
    # 用兼容层模型校验：契约落地时它等价于 `Profile`，未落地时它保留证据链/历史标记。
    profile = MergedProfile.model_validate(payload)
    summary = ProfileMergeSummary(
        added=counters["added"],
        historical=counters["historical"],
        evidence_added=counters["evidence_added"],
        duplicate=duplicate,
    )
    return profile, summary


def _backfill_entry(entry: dict[str, object], resume_id: str) -> dict[str, object]:
    """给「只有兼容字段」的条目补首条证据（`source_quotes` 已存在则原样返回）。"""
    if entry.get("source_quotes"):
        return entry
    quote = str(entry.get("source_quote") or "")
    return {
        **entry,
        "source_quotes": [Evidence(quote=quote, resume_id=resume_id)] if quote else [],
        "status": entry.get("status") or STATUS_ACTIVE,
    }


def backfill_evidence(profile: Profile) -> MergedProfile:
    """兼容读取（TECHNICAL §3「`source_quotes` 为空则用 `source_quote` 回填」）的读侧实现。

    为什么读侧也需要它：契约（`schemas.py`）未声明 `source_quotes`/`status` 时，
    `repository` 的读路径（`_profile_of → Profile.model_validate_json`）会把证据链丢掉，
    于是 GET/PATCH 的条目形状与 POST 合并结果不一致。本函数让两侧形状一致
    （`source_quotes[0].quote == source_quote`，`status` 缺省 active）。
    契约落地后**自动退化为空操作**：条目本就带证据链时原样返回（多证据不被截断）。
    """
    payload = profile.model_dump()
    payload["skills"] = [
        _backfill_entry(entry, profile.resume_id) for entry in payload.get("skills", [])
    ]
    payload["projects"] = [
        _backfill_entry(entry, profile.resume_id) for entry in payload.get("projects", [])
    ]
    return MergedProfile.model_validate(payload)


def _merge_skills(
    old_entries: list[ProfileSkill],
    draft_entries: list[ProfileSkill],
    source: _EvidenceSource,
    counters: dict[str, int],
) -> list[dict[str, object]]:
    return _merge_entries(
        old_entries,
        draft_entries,
        source=source,
        is_skill=True,
        counters=counters,
    )


def _merge_projects(
    old_entries: list[ProfileProject],
    draft_entries: list[ProfileProject],
    source: _EvidenceSource,
    counters: dict[str, int],
) -> list[dict[str, object]]:
    return _merge_entries(
        old_entries,
        draft_entries,
        source=source,
        is_skill=False,
        counters=counters,
    )


def active_skills(profile: Profile) -> list[ProfileSkill]:
    """当前能力项（出题 / 诊断只许取这一份，历史项永不回流）。"""
    return [skill for skill in profile.skills if _status_of(skill) == STATUS_ACTIVE]


def active_projects(profile: Profile) -> list[ProfileProject]:
    return [project for project in profile.projects if _status_of(project) == STATUS_ACTIVE]


def needs_tech_fallback(profile: Profile) -> bool:
    """active 能力项不足 `MIN_ACTIVE_SKILLS` 时，出题需以 `tech_stack` 补齐（AC-7）。"""
    return len(active_skills(profile)) < MIN_ACTIVE_SKILLS
