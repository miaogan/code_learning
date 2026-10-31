"""笔试链（AC-4）：组卷配比、本地判分口径、服务端计时。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app import repository
from app.errors import NOT_FOUND, AppError
from app.schemas import ExamAnswers, ExamResult
from app.services import exam as exam_service
from app.services import rules

OBJECTIVE_KINDS = {"single", "multiple"}

SINGLE = {
    "id": "t-single",
    "kind": "single",
    "direction": "前端",
    "prompt": "哪个 Hook 负责副作用？",
    "options": [{"key": "A", "text": "useMemo"}, {"key": "B", "text": "useEffect"}],
    "answer": ["B"],
    "difficulty": "basic",
}

MULTIPLE = {
    "id": "t-multiple",
    "kind": "multiple",
    "direction": "计算机基础",
    "prompt": "下列哪些属于进程间通信方式？",
    "options": [
        {"key": "A", "text": "管道"},
        {"key": "B", "text": "共享内存"},
        {"key": "C", "text": "消息队列"},
        {"key": "D", "text": "闭包"},
    ],
    "answer": ["A", "B", "C"],
    "difficulty": "challenge",
}

TEXT = {
    "id": "t-text",
    "kind": "text",
    "direction": "后端",
    "prompt": "简述索引失效的常见原因",
    "options": [],
    "answer": [],
    "difficulty": "basic",
}


def _paper(tmp_db: Any, profile_factory: Any) -> Any:
    profile = profile_factory()
    repository.insert_profile(profile)
    return exam_service.create_run(profile.id)


def _seed_map(seed_questions: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {item["id"]: item for item in seed_questions}


def _objective_ids(paper: Any) -> list[str]:
    return [q.id for q in paper.questions if q.kind in OBJECTIVE_KINDS]


# --- 组卷 -----------------------------------------------------------------


def test_paper_meets_quantity_floor(
    tmp_db: Any, profile_factory: Any, seed_questions: list[dict[str, Any]]
) -> None:
    paper = _paper(tmp_db, profile_factory)
    kinds = [q.kind for q in paper.questions]
    assert len(paper.questions) >= rules.MIN_EXAM_QUESTIONS
    assert len(paper.questions) <= rules.MAX_EXAM_QUESTIONS
    assert sum(1 for kind in kinds if kind in OBJECTIVE_KINDS) >= rules.MIN_OBJECTIVE_QUESTIONS
    assert len({q.id for q in paper.questions}) == len(paper.questions)


def test_paper_caps_challenge_ratio(
    tmp_db: Any, profile_factory: Any, seed_questions: list[dict[str, Any]]
) -> None:
    paper = _paper(tmp_db, profile_factory)
    seeds = _seed_map(seed_questions)
    challenge = [
        q.id
        for q in paper.questions
        if seeds.get(q.id, {}).get("difficulty") == "challenge"
    ]
    assert len(challenge) <= rules.max_challenge_count(len(paper.questions))


def test_paper_never_leaks_answers(
    tmp_db: Any, profile_factory: Any, seed_questions: list[dict[str, Any]]
) -> None:
    paper = _paper(tmp_db, profile_factory)
    for question in paper.questions:
        assert set(question.model_dump()) == {"id", "kind", "direction", "prompt", "options"}


def test_create_paper_unknown_profile_404(tmp_db: Any) -> None:
    with pytest.raises(AppError) as excinfo:
        exam_service.create_run("no-such-profile")
    assert excinfo.value.code == NOT_FOUND


# --- 判分口径（口径争议用用例钉死） ---------------------------------------


def test_grading_single_choice() -> None:
    assert exam_service.grade_objective(SINGLE, "B") is True
    assert exam_service.grade_objective(SINGLE, ["B"]) is True
    assert exam_service.grade_objective(SINGLE, "A") is False
    assert exam_service.grade_objective(SINGLE, None) is False


def test_grading_multiple_requires_exact_set() -> None:
    assert exam_service.grade_objective(MULTIPLE, ["A", "B", "C"]) is True
    assert exam_service.grade_objective(MULTIPLE, ["C", "A", "B"]) is True  # 顺序无关
    assert exam_service.grade_objective(MULTIPLE, ["A", "B"]) is False  # 少选即错
    assert exam_service.grade_objective(MULTIPLE, ["A", "B", "C", "D"]) is False  # 多选即错


def test_text_question_is_not_graded() -> None:
    assert not exam_service.grade_objective(TEXT, "建立联合索引并避免隐式转换")
    assert not exam_service.grade_objective(TEXT, None)


def test_client_cannot_supply_timing() -> None:
    """`elapsed_s` 必须由服务端算：请求模型里根本没有时间字段。"""
    fields = set(ExamAnswers.model_fields)
    assert fields == {"answers"}
    assert not {"elapsed_s", "started_at", "submitted_at"} & fields


# --- 提交判分 -------------------------------------------------------------


def test_submit_all_objective_correct_scores_full_marks(
    tmp_db: Any, profile_factory: Any, seed_questions: list[dict[str, Any]]
) -> None:
    paper = _paper(tmp_db, profile_factory)
    seeds = _seed_map(seed_questions)
    answers: dict[str, list[str] | str] = {
        q.id: (seeds[q.id]["answer"] if q.kind in OBJECTIVE_KINDS else "简答：先建索引再看执行计划")
        for q in paper.questions
    }
    result = exam_service.submit_run(paper.run_id, answers)

    assert isinstance(result, ExamResult)
    assert result.objective_total >= rules.MIN_OBJECTIVE_QUESTIONS
    assert result.correct_count == result.objective_total
    assert result.total == 100.0
    for item in result.per_question:
        assert item.correct is True


def test_total_scales_with_correct_count(
    tmp_db: Any, profile_factory: Any, seed_questions: list[dict[str, Any]]
) -> None:
    paper = _paper(tmp_db, profile_factory)
    seeds = _seed_map(seed_questions)
    objective = _objective_ids(paper)
    answers: dict[str, list[str] | str] = {qid: ["Z"] for qid in objective}
    answers[objective[0]] = seeds[objective[0]]["answer"]

    result = exam_service.submit_run(paper.run_id, answers)

    assert result.correct_count == 1
    assert result.total == round(1 / result.objective_total * 100, 1)


def test_elapsed_seconds_is_server_side(
    tmp_db: Any, profile_factory: Any
) -> None:
    paper = _paper(tmp_db, profile_factory)
    stored = repository.get_run(paper.run_id)
    assert stored is not None
    payload = dict(stored["payload"])
    payload["started_at"] = (datetime.now(UTC) - timedelta(seconds=30)).isoformat()
    repository.save_run(paper.run_id, payload, repository.RUN_RUNNING)

    result = exam_service.submit_run(paper.run_id, {})

    assert 25.0 <= result.elapsed_s <= 90.0


def test_submit_unknown_run_404(tmp_db: Any) -> None:
    with pytest.raises(AppError) as excinfo:
        exam_service.submit_run("no-such-run", {})
    assert excinfo.value.code == NOT_FOUND
