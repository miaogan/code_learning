"""报告链（AC-5 / AC-6）：短板条数、排序、证据可溯源、课程兜底、AI 降级。"""

from __future__ import annotations

import asyncio
import re
from typing import Any

import pytest

from app.core import repository
from app.core.errors import AI_UNAVAILABLE, AppError
from app.schemas import Report, Shortfall
from app.services.assessment import exam as exam_service
from app.services.interview import interview as interview_service
from app.services.report import diagnosis, rules
from conftest import drive_session

VALID_KINDS = ["technical"] * rules.MIN_TECHNICAL_QUESTIONS + ["project"] * (
    rules.MIN_INTERVIEW_QUESTIONS - rules.MIN_TECHNICAL_QUESTIONS
)
EVIDENCE_PATTERN = re.compile(r"Q\d+\s*·\s*\d+(?:\.\d+)?/10")


def test_severity_thresholds_match_design() -> None:
    """分档口径唯一出处（`rules.py`）：<4 high、<7 medium、其余 low。"""
    assert rules.severity_of(0.0) == "high"
    assert rules.severity_of(3.9) == "high"
    assert rules.severity_of(4.0) == "medium"
    assert rules.severity_of(6.9) == "medium"
    assert rules.severity_of(7.0) == "low"
    assert rules.severity_of(10.0) == "low"


def test_shortfall_and_challenge_bounds() -> None:
    """跨面试 / 笔试 / 报告共用的阈值常量：任何一处就地写魔数都会让这里失真。"""
    assert (rules.MIN_INTERVIEW_QUESTIONS, rules.MIN_TECHNICAL_QUESTIONS) == (8, 5)
    assert rules.MIN_PROJECT_QUESTIONS == 3
    assert rules.MAX_CHALLENGE_RATIO == 0.2
    assert rules.max_challenge_count(8) == 2
    assert rules.max_challenge_count(10) == 2
    assert (rules.MIN_EXAM_QUESTIONS, rules.MIN_OBJECTIVE_QUESTIONS) == (10, 8)
    assert (rules.MIN_SHORTFALLS, rules.MAX_SHORTFALLS) == (3, 5)
    assert rules.SEVERITY_ORDER == {"high": 0, "medium": 1, "low": 2}


def _bad_score_responder(model_cls: type[Any], _user: str) -> dict[str, Any]:
    if "questions" in getattr(model_cls, "model_fields", {}):
        return {
            "questions": [
                {
                    "id": f"iq-{index}",
                    "kind": kind,
                    "prompt": f"第 {index} 题（{kind}）：请结合简历里的经历说明做法与结果",
                    "hint": "结合具体经历",
                }
                for index, kind in enumerate(VALID_KINDS)
            ]
        }
    return {"score": 2.0, "comment": "答不出关键点"}


def _prepare_runs(
    tmp_db: Any, profile_factory: Any, fake_ai: Any, seed_questions: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """产出生产口径的两条 run：一次面试（全是低分）+ 一次笔试（客观题全错）。"""
    profile = profile_factory()
    repository.insert_profile(profile)

    fake_ai.responder = _bad_score_responder
    interview = asyncio.run(interview_service.create_run(profile.id, client=fake_ai))
    turns = drive_session(interview, fake_ai, answer="答不上来")
    assert turns and turns[-1].next_question is None, "面试必须被推进到终态（r5：一次一问）"

    paper = exam_service.create_run(profile.id)
    exam_service.submit_run(paper.run_id, {question.id: ["Z"] for question in paper.questions})

    return repository.list_runs(limit=10)


def _shortfalls_of(runs: list[dict[str, Any]]) -> list[Shortfall]:
    shortfalls = diagnosis.build_shortfalls(runs)
    return diagnosis.attach_courses(shortfalls)


def test_shortfall_count_within_bounds(
    tmp_db: Any, profile_factory: Any, fake_ai: Any, seed_questions: list[dict[str, Any]]
) -> None:
    shortfalls = _shortfalls_of(_prepare_runs(tmp_db, profile_factory, fake_ai, seed_questions))
    assert rules.MIN_SHORTFALLS <= len(shortfalls) <= rules.MAX_SHORTFALLS


def test_shortfalls_sorted_by_severity(
    tmp_db: Any, profile_factory: Any, fake_ai: Any, seed_questions: list[dict[str, Any]]
) -> None:
    shortfalls = _shortfalls_of(_prepare_runs(tmp_db, profile_factory, fake_ai, seed_questions))
    order = [rules.SEVERITY_ORDER[item.severity] for item in shortfalls]
    assert order == sorted(order), f"严重度必须升序：{[i.severity for i in shortfalls]}"
    assert shortfalls[0].severity == "high", "全低分的测评至少产出一条 high 短板"


def test_every_shortfall_cites_a_real_question(
    tmp_db: Any, profile_factory: Any, fake_ai: Any, seed_questions: list[dict[str, Any]]
) -> None:
    runs = _prepare_runs(tmp_db, profile_factory, fake_ai, seed_questions)
    shortfalls = _shortfalls_of(runs)
    known_ids = {
        str(question.get("id"))
        for run in runs
        for question in run["payload"].get("questions", [])
    }
    assert known_ids, "run payload 里必须能取到题目 id"
    for item in shortfalls:
        assert EVIDENCE_PATTERN.match(item.evidence), f"证据展示形不符：{item.evidence}"
        ref = getattr(item, "question_ref", None)
        if "question_ref" in Shortfall.model_fields:
            assert ref in known_ids, f"question_ref={ref} 不是真实题目"


def test_every_shortfall_has_course(
    tmp_db: Any, profile_factory: Any, fake_ai: Any, seed_questions: list[dict[str, Any]]
) -> None:
    runs = _prepare_runs(tmp_db, profile_factory, fake_ai, seed_questions)
    for item in _shortfalls_of(runs):
        assert item.courses, f"短板「{item.name}」缺课程"
        for course in item.courses:
            assert course.title and course.why


def test_fallback_course_for_unknown_direction() -> None:
    """anti-goal 4：冷门短板也必须落到兜底入门课，不允许空列表。"""
    payload: dict[str, Any] = {
        "name": "量子计算与芯片验证",
        "severity": "high",
        "evidence": "Q1 · 3/10",
        "diagnosis": "该方向完全没有作答记录",
        "actions": ["先补齐基础概念"],
        "courses": [],
    }
    if "question_ref" in Shortfall.model_fields:
        payload["question_ref"] = "fe-q1"
    shortfall = Shortfall.model_validate(payload)

    attached = diagnosis.attach_courses([shortfall])

    assert attached and attached[0].courses
    assert all(course.level in {"入门", "进阶"} for course in attached[0].courses)


def test_build_report_degrades_when_ai_fails(
    tmp_db: Any, profile_factory: Any, fake_ai: Any, seed_questions: list[dict[str, Any]]
) -> None:
    runs = _prepare_runs(tmp_db, profile_factory, fake_ai, seed_questions)
    run_ids = [run["id"] for run in runs]

    def _explode(_model_cls: type[Any], _user: str) -> dict[str, Any]:
        raise AppError(AI_UNAVAILABLE, "AI 服务暂时不可用，请稍后重试", status=503, retryable=True)

    fake_ai.responder = _explode

    report = asyncio.run(diagnosis.build_report(run_ids, client=fake_ai))

    assert isinstance(report, Report)
    assert report.id and report.generated_at
    assert rules.MIN_SHORTFALLS <= len(report.shortfalls) <= rules.MAX_SHORTFALLS
    for item in report.shortfalls:
        assert item.diagnosis and item.actions
        assert item.courses
    if "run_ids" in Report.model_fields:
        assert report.run_ids == run_ids


def test_build_report_unknown_runs_rejected(tmp_db: Any, fake_ai: Any) -> None:
    with pytest.raises(AppError) as excinfo:
        asyncio.run(diagnosis.build_report(["no-such-run"], client=fake_ai))
    assert excinfo.value.status in {400, 404}


def test_build_report_without_any_run_rejected(tmp_db: Any, fake_ai: Any) -> None:
    with pytest.raises(AppError) as excinfo:
        asyncio.run(diagnosis.build_report(None, client=fake_ai))
    assert excinfo.value.status in {400, 404}


def test_auto_resolution_skips_finished_but_unanswered_run(
    tmp_db: Any, profile_factory: Any, fake_ai: Any
) -> None:
    """提前结束（0 答）的会话也是 completed，但不得挤掉最近一次有成绩的同类测评。"""
    profile = profile_factory()
    repository.insert_profile(profile)

    fake_ai.responder = _bad_score_responder
    answered = asyncio.run(interview_service.create_run(profile.id, client=fake_ai))
    turns = drive_session(answered, fake_ai, answer="答不上来")
    assert turns[-1].next_question is None

    empty = asyncio.run(interview_service.create_run(profile.id, client=fake_ai))
    interview_service.finish_run(empty.run_id)

    resolved = [run["id"] for run in diagnosis._resolve_runs(None)]
    assert answered.run_id in resolved, "有成绩的那场必须被选中"
    assert empty.run_id not in resolved, "0 答的完成态不可诊断，不得挤掉上一场"


def test_report_aggregates_both_run_kinds(
    tmp_db: Any, profile_factory: Any, fake_ai: Any, seed_questions: list[dict[str, Any]]
) -> None:
    """一次面试 + 一次笔试都要进汇总：报告是两条链路的合并视图。"""
    runs = _prepare_runs(tmp_db, profile_factory, fake_ai, seed_questions)
    report = asyncio.run(diagnosis.build_report([run["id"] for run in runs], client=fake_ai))
    assert report.interview_avg is not None
    assert report.exam_total is not None
    assert report.interview_avg <= 10.0
    assert report.exam_total <= 100.0
