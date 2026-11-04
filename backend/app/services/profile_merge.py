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

# 显式再导出：`services/profile.py` 从这里取 `ProfileWithMerge`（契约真源在 schemas）。
from ..schemas import (
    Evidence,
    Profile,
    ProfileDraft,
    ProfileMergeSummary,
    ProfileProject,
    ProfileSkill,
    ProfileWithMerge as ProfileWithMerge,
)

#: 历史项的状态值。active 表示「当前简历仍然写了」，historical 表示「只在旧简历里出现」。
STATUS_ACTIVE = "active"
STATUS_HISTORICAL = "historical"

#: 出题素材的下限：active 能力项少于这个数时，出题侧以 `tech_stack` 兜底（AC-7）。
MIN_ACTIVE_SKILLS = 3


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


def _prefer_text(new: object, old: object) -> str | None:
    """空值不覆盖已知值：新草稿有内容取新，否则沿用旧；两侧皆空 ⇒ `None`（不写 `""`）。

    r8 的单一出口：新简历没写角色/时间不等于「写过又删掉」，与 r3 `target_role` 的
    「空不覆盖」同源。`None` 表示「简历没写」，绝不用空串伪装。
    """
    if isinstance(new, str) and new.strip():
        return new
    if old is None:
        return None
    if isinstance(old, str) and not old.strip():
        return None
    return str(old)


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
            # r8：role / period / bullets 都走「空值不覆盖旧值」；bullets 空不得抹掉旧要点。
            "role": _prefer_text(getattr(source, "role", None), getattr(base, "role", None)),
            "period": _prefer_text(getattr(source, "period", None), getattr(base, "period", None)),
            "bullets": list(getattr(source, "bullets", None) or getattr(base, "bullets", None) or []),
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
) -> tuple[Profile, ProfileMergeSummary]:
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
    profile = Profile.model_validate(payload)
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


def backfill_evidence(profile: Profile) -> Profile:
    """兼容读取的读侧实现（`source_quotes` 为空则用兼容字段 `source_quote` 回填）。

    为什么读侧也需要它：存量画像行只写了 `source_quote`，而 `repository` 的读路径
    （`_profile_of → Profile.model_validate_json`）要求条目带 `source_quotes`，
    于是 GET/PATCH 的条目形状会与 POST 合并结果不一致。本函数让两侧形状一致
    （`source_quotes[0].quote == source_quote`，`status` 缺省 active）。
    条目本就带证据链时**原样返回**（多证据不被截断），所以对 r3 之后的写路径是空操作。
    """
    payload = profile.model_dump()
    payload["skills"] = [
        _backfill_entry(entry, profile.resume_id) for entry in payload.get("skills", [])
    ]
    payload["projects"] = [
        _backfill_entry(entry, profile.resume_id) for entry in payload.get("projects", [])
    ]
    return Profile.model_validate(payload)


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
