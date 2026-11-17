"""画像链（AC-2 / anti-goal 1）：溯源校验与 FakeAI 生成，全程零网络。"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from pydantic import ValidationError

from app.core.errors import AI_SCHEMA_INVALID, AppError
from app.schemas import Profile, ProfileDraft, ProfileSkill
from app.services.profile import profile as profile_service

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


def test_generate_profile_drops_hallucinated_quote(
    tmp_db: Any, resume_text: str, fake_ai: Any, draft_payload: dict[str, Any]
) -> None:
    """anti-goal 1（r116 口径）：编造的那一条**不入库**，其余合规条目照常落库。

    r3 的实现是「任一条不合格就整份 502」，实测会让失败率随条目数指数放大
    （`(1-p)^N`），表现为「同一份简历有时成功有时失败」。改为逐条剔除后，
    anti-goal 1 的字面要求（画像里不出现无源之词）仍然满足，但不再牵连整份。
    """
    draft_payload["skills"] = [
        {"name": "K8s", "source_quote": INVENTED_QUOTE},
        {"name": "React", "source_quote": "React TypeScript Python SQLite"},
    ]
    fake_ai.responder = lambda _model_cls, _user: draft_payload

    profile = asyncio.run(
        profile_service.generate_profile("res-1", resume_text, client=fake_ai)
    )

    names = [skill.name for skill in profile.skills]
    assert names == ["React"], f"编造条目必须被剔除、合规条目必须保留，实际 {names}"
    assert all(_squash(skill.source_quote) in _squash(resume_text) for skill in profile.skills)


def test_generate_profile_blocks_when_nothing_is_sourced(
    tmp_db: Any, resume_text: str, fake_ai: Any, draft_payload: dict[str, Any]
) -> None:
    """整体编造（一条都站不住）仍必须 502 —— 那不是抄写偏差，重试才有意义。"""
    draft_payload["skills"] = [{"name": "K8s", "source_quote": INVENTED_QUOTE}]
    draft_payload["projects"] = [
        {
            "name": "推荐系统",
            "role": None,
            "period": None,
            "bullets": [],
            "source_quote": INVENTED_QUOTE,
        }
    ]
    fake_ai.responder = lambda _model_cls, _user: draft_payload

    with pytest.raises(AppError) as excinfo:
        asyncio.run(profile_service.generate_profile("res-1", resume_text, client=fake_ai))
    assert excinfo.value.code == AI_SCHEMA_INVALID
    assert excinfo.value.status == 502
    assert excinfo.value.retryable is True


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
