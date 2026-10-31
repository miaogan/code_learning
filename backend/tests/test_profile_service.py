"""画像链（AC-2 / anti-goal 1）：溯源校验与 FakeAI 生成，全程零网络。"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from pydantic import ValidationError

from app.errors import AI_SCHEMA_INVALID, AppError
from app.schemas import Profile, ProfileDraft, ProfileSkill
from app.services import profile as profile_service

INVENTED_QUOTE = "精通 Kubernetes 多集群运维与 Istio 服务网格治理"


def _draft(*skills: str, projects: list[dict[str, Any]] | None = None) -> ProfileDraft:
    return ProfileDraft.model_validate(
        {
            "skills": [{"name": quote[:12], "source_quote": quote} for quote in skills],
            "tech_stack": ["React"],
            "years_experience": 3.0,
            "projects": projects or [],
            "target_role": "前端开发工程师",
        }
    )


def test_verify_quotes_exact_hit(resume_text: str) -> None:
    draft = _draft("React TypeScript Python SQLite")
    assert profile_service.verify_quotes(draft, resume_text) is None


def test_verify_quotes_whitespace_tolerant(resume_text: str) -> None:
    draft = _draft("工作经历\n2023-2026\n前端开发工程师")
    assert profile_service.verify_quotes(draft, resume_text) is None


def test_verify_quotes_covers_projects(resume_text: str) -> None:
    draft = _draft(
        "React TypeScript Python SQLite",
        projects=[
            {
                "name": "数据看板",
                "role": "前端主力",
                "period": "2025-2026",
                "bullets": ["虚拟滚动"],
                "source_quote": "数据看板项目：主导表格虚拟滚动与缓存策略",
            }
        ],
    )
    assert profile_service.verify_quotes(draft, resume_text) is None


def test_verify_quotes_rejects_invented_skill(resume_text: str) -> None:
    """anti-goal 1：简历里没有的技能必须在入库前被拦下。"""
    draft = _draft(INVENTED_QUOTE)
    with pytest.raises(AppError) as excinfo:
        profile_service.verify_quotes(draft, resume_text)
    assert excinfo.value.code == AI_SCHEMA_INVALID
    assert excinfo.value.status == 502


def test_empty_quote_is_blocked_by_contract() -> None:
    """`source_quote` 在契约层就不可为空（双保险的第二道）。"""
    with pytest.raises(ValidationError):
        ProfileSkill(name="React", source_quote="")


def test_generate_profile_returns_five_dimensions(
    tmp_db: Any, resume_text: str, fake_ai: Any, draft_payload: dict[str, Any]
) -> None:
    fake_ai.responder = lambda _model_cls, _user: draft_payload

    profile = asyncio.run(
        profile_service.generate_profile("res-1", resume_text, client=fake_ai)
    )

    assert isinstance(profile, Profile)
    assert profile.resume_id == "res-1"
    assert profile.id and profile.updated_at
    assert profile.skills and profile.tech_stack and profile.projects
    assert profile.target_role == "前端开发工程师"
    for skill in profile.skills:
        assert _squash(skill.source_quote) in _squash(resume_text)
    for project in profile.projects:
        assert _squash(project.source_quote) in _squash(resume_text)
    assert len(fake_ai.calls) == 1
    assert profile_service.PROFILE_SYSTEM in fake_ai.calls[0][0]


def test_generate_profile_blocks_hallucinated_quote(
    tmp_db: Any, resume_text: str, fake_ai: Any, draft_payload: dict[str, Any]
) -> None:
    draft_payload["skills"] = [{"name": "K8s", "source_quote": INVENTED_QUOTE}]
    fake_ai.responder = lambda _model_cls, _user: draft_payload

    with pytest.raises(AppError) as excinfo:
        asyncio.run(profile_service.generate_profile("res-1", resume_text, client=fake_ai))
    assert excinfo.value.code == AI_SCHEMA_INVALID


def test_generate_profile_truncates_long_text(
    tmp_db: Any, resume_text: str, fake_ai: Any, draft_payload: dict[str, Any]
) -> None:
    long_text = resume_text + "\n" + ("填充内容 " * 5000)
    fake_ai.responder = lambda _model_cls, _user: draft_payload

    asyncio.run(profile_service.generate_profile("res-1", long_text, client=fake_ai))

    sent = fake_ai.calls[0][1]
    assert len(sent) <= profile_service.MAX_PROFILE_CHARS + 40


def _squash(text: str) -> str:
    return "".join(text.split())
