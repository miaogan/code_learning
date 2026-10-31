"""面试链（AC-3）：出题配比校验、逐题评分回写、评分口径越界被拒。"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from pydantic import ValidationError

from app import repository
from app.errors import AI_SCHEMA_INVALID, NOT_FOUND, AppError
from app.schemas import InterviewQuestion, ScoreResult
from app.services import interview as interview_service
from app.services import rules

VALID_KINDS = ["technical"] * rules.MIN_TECHNICAL_QUESTIONS + ["project"] * (
    rules.MIN_INTERVIEW_QUESTIONS - rules.MIN_TECHNICAL_QUESTIONS
)


def _payload(kinds: list[str], *, repeat_prompt: bool = False) -> list[dict[str, str]]:
    return [
        {
            "id": f"iq-{index}",
            "kind": kind,
            "prompt": (
                "同一道题：请谈谈你在项目里的贡献"
                if repeat_prompt and index < 2
                else f"第 {index} 题（{kind}）：请结合简历里的经历说明做法与结果"
            ),
            "hint": "结合具体经历，说明取舍与结果",
        }
        for index, kind in enumerate(kinds)
    ]


def _questions(kinds: list[str], *, repeat_prompt: bool = False) -> list[InterviewQuestion]:
    return [
        InterviewQuestion.model_validate(item)
        for item in _payload(kinds, repeat_prompt=repeat_prompt)
    ]


def _responder_for_paper(kinds: list[str]) -> Any:
    """按目标模型分流：出题模型给题目，评分模型给分数。"""

    def _respond(model_cls: type[Any], _user: str) -> dict[str, Any]:
        if "questions" in getattr(model_cls, "model_fields", {}):
            return {"questions": _payload(kinds)}
        return {"score": 6.0, "comment": "结构清楚，但缺少量化结果"}

    return _respond


def _seed_profile(profile_factory: Any) -> Any:
    profile = profile_factory()
    repository.insert_profile(profile)
    return profile


# --- 出题配比（AI 出题不合格即报错，不做静默补题） -------------------------


def test_valid_paper_passes_ratio_check() -> None:
    assert interview_service.validate_questions(_questions(VALID_KINDS)) is None


def test_question_count_below_floor_rejected() -> None:
    kinds = ["technical"] * 4 + ["project"] * 3
    with pytest.raises(AppError) as excinfo:
        interview_service.validate_questions(_questions(kinds))
    assert excinfo.value.status == 502
    assert excinfo.value.code == AI_SCHEMA_INVALID


def test_technical_ratio_enforced() -> None:
    kinds = ["technical"] * 4 + ["project"] * 3 + ["challenge"] * 1
    with pytest.raises(AppError) as excinfo:
        interview_service.validate_questions(_questions(kinds))
    assert excinfo.value.status == 502


def test_challenge_ratio_capped() -> None:
    kinds = VALID_KINDS + ["challenge"] * 4  # 12 题里挑战 4 道，超过 ceil(12×20%)=3
    assert len(kinds) > rules.max_challenge_count(len(kinds))
    with pytest.raises(AppError) as excinfo:
        interview_service.validate_questions(_questions(kinds))
    assert excinfo.value.code == AI_SCHEMA_INVALID


def test_duplicate_prompt_rejected() -> None:
    with pytest.raises(AppError) as excinfo:
        interview_service.validate_questions(_questions(VALID_KINDS, repeat_prompt=True))
    assert excinfo.value.status == 502


# --- 出题 run 与落库 -------------------------------------------------------


def test_create_run_returns_questions_without_answers(
    tmp_db: Any, profile_factory: Any, fake_ai: Any
) -> None:
    profile = _seed_profile(profile_factory)
    fake_ai.responder = _responder_for_paper(VALID_KINDS)

    run = asyncio.run(interview_service.create_run(profile.id, client=fake_ai))

    assert len(run.questions) >= rules.MIN_INTERVIEW_QUESTIONS
    for question in run.questions:
        assert set(question.model_dump()) == {"id", "kind", "prompt", "hint"}
    stored = repository.get_run(run.run_id)
    assert stored is not None
    assert stored["kind"] == "interview"
    assert stored["profile_id"] == profile.id
    assert stored["payload"]["total"] == len(run.questions)
    assert stored["payload"]["answered_count"] == 0


def test_create_run_unknown_profile_404(tmp_db: Any, fake_ai: Any) -> None:
    with pytest.raises(AppError) as excinfo:
        asyncio.run(interview_service.create_run("no-such-profile", client=fake_ai))
    assert excinfo.value.code == NOT_FOUND
    assert excinfo.value.status == 404


def test_create_run_rejects_bad_paper_502(
    tmp_db: Any, profile_factory: Any, fake_ai: Any
) -> None:
    profile = _seed_profile(profile_factory)
    fake_ai.responder = _responder_for_paper(["technical"] * 4 + ["project"] * 3)

    with pytest.raises(AppError) as excinfo:
        asyncio.run(interview_service.create_run(profile.id, client=fake_ai))
    assert excinfo.value.status == 502


# --- 逐题评分回写 ---------------------------------------------------------


def test_score_answer_persists_then_completes_run(
    tmp_db: Any, profile_factory: Any, fake_ai: Any
) -> None:
    profile = _seed_profile(profile_factory)
    fake_ai.responder = _responder_for_paper(VALID_KINDS)
    assert interview_service.SCORING_TIMEOUT_S <= 15.0, "AC-3 要求单题评分 15s 内"

    run = asyncio.run(interview_service.create_run(profile.id, client=fake_ai))
    first = run.questions[0]

    result = asyncio.run(
        interview_service.score_answer(run.run_id, first.id, "我负责组件库重构", client=fake_ai)
    )
    assert isinstance(result, ScoreResult)
    assert 0.0 <= result.score <= 10.0
    assert result.comment
    assert fake_ai.calls[-1][2] is None or fake_ai.calls[-1][2] <= 15.0

    stored = repository.get_run(run.run_id)
    assert stored is not None
    assert stored["payload"]["answered_count"] == 1
    assert stored["status"] != repository.RUN_COMPLETED, "未答完不能提前标 completed"

    for question in run.questions[1:]:
        asyncio.run(
            interview_service.score_answer(run.run_id, question.id, "补充说明", client=fake_ai)
        )

    stored = repository.get_run(run.run_id)
    assert stored["payload"]["answered_count"] == len(run.questions)
    assert stored["status"] == repository.RUN_COMPLETED


def test_reanswer_same_question_is_idempotent(
    tmp_db: Any, profile_factory: Any, fake_ai: Any
) -> None:
    profile = _seed_profile(profile_factory)
    fake_ai.responder = _responder_for_paper(VALID_KINDS)
    run = asyncio.run(interview_service.create_run(profile.id, client=fake_ai))
    first = run.questions[0]

    for _ in range(2):
        asyncio.run(interview_service.score_answer(run.run_id, first.id, "再答一次", client=fake_ai))

    stored = repository.get_run(run.run_id)
    assert stored["payload"]["answered_count"] == 1


def test_score_answer_unknown_run_404(tmp_db: Any, fake_ai: Any) -> None:
    with pytest.raises(AppError) as excinfo:
        asyncio.run(interview_service.score_answer("no-such-run", "iq-0", "回答", client=fake_ai))
    assert excinfo.value.code == NOT_FOUND


def test_score_out_of_range_rejected_by_schema() -> None:
    with pytest.raises(ValidationError):
        ScoreResult.model_validate({"score": 11.0, "comment": "越界"})
    with pytest.raises(ValidationError):
        ScoreResult.model_validate({"score": -1.0, "comment": "越界"})
