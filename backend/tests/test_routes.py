"""端点级契约（AC-7 / AC-9 / AC-10）：错误码、错误 envelope、markdown 同源、历史排序。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi.testclient import TestClient

from app import repository
from app.errors import AI_SCHEMA_INVALID, AI_UNAVAILABLE, AppError
from app.schemas import Course, Report, ResumeMeta, Shortfall
from app.services import exam as exam_service, rules

OBJECTIVE_KINDS = frozenset(rules.OBJECTIVE_KINDS)  # 闭集只在 rules.py（r11：含 judge）
VALID_KINDS = ["technical"] * rules.MIN_TECHNICAL_QUESTIONS + ["project"] * (
    rules.MIN_INTERVIEW_QUESTIONS - rules.MIN_TECHNICAL_QUESTIONS
)


def _questions(kinds: list[str] = VALID_KINDS, prefix: str = "iq") -> list[dict[str, str]]:
    return [
        {
            "id": f"{prefix}-{index}",
            "kind": kind,
            "prompt": f"第 {index} 题（{kind}）：请结合简历说明做法与结果",
            "hint": "结合具体经历",
        }
        for index, kind in enumerate(kinds)
    ]


def _responder(model_cls: type[Any], _user: str) -> dict[str, Any]:
    """一个 responder 覆盖画像 / 出题 / 评分；其余模型按「AI 不可用」处理（驱动报告降级）。"""
    fields = getattr(model_cls, "model_fields", {})
    if "skills" in fields:
        return {
            "skills": [{"name": "React", "source_quote": "React TypeScript Python SQLite"}],
            "tech_stack": ["React", "TypeScript", "Python", "SQLite"],
            "years_experience": 3.0,
            "projects": [
                {
                    "name": "数据看板",
                    "role": "前端主力",
                    "period": "2025-2026",
                    "bullets": ["虚拟滚动"],
                    "source_quote": "数据看板项目：主导表格虚拟滚动与缓存策略",
                }
            ],
            "target_role": "前端开发工程师",
        }
    if "questions" in fields:
        return {"run_id": "run-temp", "questions": _questions()}
    if "score" in fields:
        return {"score": 6.5, "comment": "结构清楚，但缺少量化结果"}
    raise AppError(AI_UNAVAILABLE, "AI 服务暂时不可用，请稍后重试", status=503, retryable=True)


def _assert_error(body: dict[str, Any], code: str, assert_chinese: Callable[[str], None]) -> None:
    error = body["error"]
    assert error["code"] == code
    assert error["retryable"] in {True, False}
    assert_chinese(error["message"])


# --- 画像端点 -------------------------------------------------------------


def test_latest_profile_404_when_empty(
    client: TestClient, assert_chinese: Callable[[str], None]
) -> None:
    response = client.get("/api/profiles/latest")
    assert response.status_code == 404
    _assert_error(response.json(), "NOT_FOUND", assert_chinese)


def test_method_not_allowed_is_localized(
    client: TestClient, assert_chinese: Callable[[str], None]
) -> None:
    """框架级 405 不再直出英文 detail，统一成中文 envelope。"""
    response = client.put("/health")
    assert response.status_code == 405
    _assert_error(response.json(), "METHOD_NOT_ALLOWED", assert_chinese)


def test_generate_profile_unknown_resume_404(
    client: TestClient, assert_chinese: Callable[[str], None]
) -> None:
    response = client.post("/api/resumes/res-missing/profile")
    assert response.status_code == 404
    _assert_error(response.json(), "NOT_FOUND", assert_chinese)


def test_profile_generate_then_patch_roundtrip(
    client: TestClient,
    patch_ai: Callable[[Any], None],
    resume_text: str,
    assert_chinese: Callable[[str], None],
) -> None:
    repository.insert_document(
        ResumeMeta(resume_id="res-1", file_name="resume.txt", chars=len(resume_text), sections=3),
        resume_text,
    )
    assert client.get("/api/profiles/latest").status_code == 404
    patch_ai(_responder)

    created = client.post("/api/resumes/res-1/profile")
    assert created.status_code == 200
    profile = created.json()
    assert profile["id"]
    assert profile["skills"] and profile["tech_stack"] and profile["projects"]
    assert profile["skills"][0]["source_quote"]

    latest = client.get("/api/profiles/latest")
    assert latest.status_code == 200
    assert latest.json()["id"] == profile["id"]

    patched = client.patch(
        f"/api/profiles/{profile['id']}",
        json={"target_role": "后端工程师", "tech_stack": ["Go", "PostgreSQL"]},
    )
    assert patched.status_code == 200
    body = patched.json()
    assert body["target_role"] == "后端工程师"
    assert body["tech_stack"] == ["Go", "PostgreSQL"]
    assert body["skills"] == profile["skills"]

    missing = client.patch("/api/profiles/no-such-id", json={"target_role": "后端工程师"})
    assert missing.status_code == 404
    _assert_error(missing.json(), "NOT_FOUND", assert_chinese)


def test_patch_rejects_empty_quote(
    client: TestClient,
    profile_factory: Callable[..., Any],
    assert_chinese: Callable[[str], None],
) -> None:
    profile = profile_factory()
    repository.insert_profile(profile)

    response = client.patch(
        f"/api/profiles/{profile.id}",
        json={"skills": [{"name": "React", "source_quote": ""}]},
    )

    assert response.status_code in {400, 422}
    _assert_error(response.json(), "VALIDATION_ERROR", assert_chinese)


def test_ai_outage_maps_to_503(
    client: TestClient,
    ai_outage: None,
    resume_text: str,
    assert_chinese: Callable[[str], None],
) -> None:
    repository.insert_document(
        ResumeMeta(resume_id="res-1", file_name="resume.txt", chars=len(resume_text), sections=3),
        resume_text,
    )

    response = client.post("/api/resumes/res-1/profile")

    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == AI_UNAVAILABLE
    assert error["retryable"] is True
    assert_chinese(error["message"])


# --- 面试端点 -------------------------------------------------------------


def test_interview_create_and_answer(
    client: TestClient,
    patch_ai: Callable[[Any], None],
    profile_factory: Callable[..., Any],
    assert_chinese: Callable[[str], None],
) -> None:
    profile = profile_factory()
    repository.insert_profile(profile)
    patch_ai(_responder)

    created = client.post("/api/interviews", json={"profile_id": profile.id})
    assert created.status_code == 200
    run = created.json()
    # r5 契约：开局只投放第 1 条发言（计划留在 payload.plan，不随响应铺开）
    assert set(run) == {"run_id", "settings", "question", "total"}
    assert set(run["question"]) == {"id", "kind", "prompt", "hint", "parent_id"}
    assert run["question"]["id"] == "iq-1"
    assert run["total"] >= rules.MIN_INTERVIEW_QUESTIONS

    answered = client.post(
        f"/api/interviews/{run['run_id']}/answers",
        json={"question_id": run["question"]["id"], "answer": "我负责组件库重构"},
    )
    assert answered.status_code == 200
    turn = answered.json()
    assert 0 <= turn["score"] <= 10
    assert turn["comment"]
    assert turn["answered_count"] == 1
    assert turn["next_question"]["id"] == "iq-2", "同轮返回下一条发言"

    missing_run = client.post(
        "/api/interviews/no-such-run/answers",
        json={"question_id": "iq-0", "answer": "随便答"},
    )
    assert missing_run.status_code == 404
    _assert_error(missing_run.json(), "NOT_FOUND", assert_chinese)


def test_interview_create_unknown_profile_404(
    client: TestClient, assert_chinese: Callable[[str], None]
) -> None:
    response = client.post("/api/interviews", json={"profile_id": "no-such-profile"})
    assert response.status_code == 404
    _assert_error(response.json(), "NOT_FOUND", assert_chinese)


def test_interview_bad_paper_maps_to_502(
    client: TestClient,
    patch_ai: Callable[[Any], None],
    profile_factory: Callable[..., Any],
    assert_chinese: Callable[[str], None],
) -> None:
    profile = profile_factory()
    repository.insert_profile(profile)
    patch_ai(lambda _cls, _user: {"questions": _questions(["technical"] * 4 + ["project"] * 3)})

    response = client.post("/api/interviews", json={"profile_id": profile.id})

    assert response.status_code == 502
    error = response.json()["error"]
    assert error["code"] in {AI_SCHEMA_INVALID, AI_UNAVAILABLE}
    assert_chinese(error["message"])


def test_interview_finish_early_is_idempotent(
    client: TestClient,
    patch_ai: Callable[[Any], None],
    profile_factory: Callable[..., Any],
    assert_chinese: Callable[[str], None],
) -> None:
    """提前结束：不调 AI、未答满也可结束；重复结束幂等，已答分数保留。"""
    profile = profile_factory()
    repository.insert_profile(profile)
    patch_ai(_responder)

    run = client.post("/api/interviews", json={"profile_id": profile.id}).json()
    answered = client.post(
        f"/api/interviews/{run['run_id']}/answers",
        json={"question_id": run["question"]["id"], "answer": "我负责组件库重构"},
    ).json()
    assert answered["answered_count"] == 1

    finished = client.post(f"/api/interviews/{run['run_id']}/finish")
    assert finished.status_code == 200
    session = finished.json()
    assert session["status"] == "completed"
    assert session["current_id"] is None
    assert session["answered_count"] == 1, "已答分数保留，未答题目不计分"
    assert session["total"] == run["total"]
    assert session["questions"][0]["score"] == answered["score"]

    again = client.post(f"/api/interviews/{run['run_id']}/finish")
    assert again.status_code == 200
    assert again.json() == session, "重复结束幂等，不重复写时间线"

    restored = client.get(f"/api/interviews/{run['run_id']}")
    assert restored.status_code == 200
    assert restored.json()["status"] == "completed"

    missing = client.post("/api/interviews/no-such-run/finish")
    assert missing.status_code == 404
    _assert_error(missing.json(), "NOT_FOUND", assert_chinese)


# --- 笔试端点 -------------------------------------------------------------


def test_exam_create_submit_and_resubmit_400(
    client: TestClient,
    profile_factory: Callable[..., Any],
    seed_questions: list[dict[str, Any]],
    assert_chinese: Callable[[str], None],
) -> None:
    profile = profile_factory()
    repository.insert_profile(profile)
    seeds = {item["id"]: item for item in seed_questions}

    created = client.post("/api/exams", json={"profile_id": profile.id})
    assert created.status_code == 200
    paper = created.json()
    assert len(paper["questions"]) >= rules.MIN_EXAM_QUESTIONS
    for question in paper["questions"]:
        assert set(question) == {"id", "kind", "direction", "prompt", "options"}

    answers = {
        question["id"]: (
            seeds[question["id"]]["answer"]
            if question["kind"] in OBJECTIVE_KINDS
            else "简答：先建索引再看执行计划"
        )
        for question in paper["questions"]
    }
    submitted = client.post(f"/api/exams/{paper['run_id']}/submit", json={"answers": answers})
    assert submitted.status_code == 200
    result = submitted.json()
    assert result["correct_count"] == result["objective_total"]
    assert result["total"] == 100.0
    assert result["elapsed_s"] >= 0

    again = client.post(f"/api/exams/{paper['run_id']}/submit", json={"answers": answers})
    assert again.status_code == 400
    retry_error = again.json()["error"]
    assert "已提交" in retry_error["message"]
    assert_chinese(retry_error["message"])

    missing = client.post("/api/exams", json={"profile_id": "no-such-profile"})
    assert missing.status_code == 404
    _assert_error(missing.json(), "NOT_FOUND", assert_chinese)


# --- 报告端点 + markdown 同源（AC-9） --------------------------------------


def _completed_runs(
    profile_factory: Callable[..., Any], seed_questions: list[dict[str, Any]]
) -> list[str]:
    """造两条已完成的 run（面试全低分 + 笔试客观题全错），供报告端点使用。"""
    profile = profile_factory()
    repository.insert_profile(profile)

    interview_payload = {
        "questions": [
            {
                "id": question["id"],
                "kind": question["kind"],
                "prompt": question["prompt"],
                "hint": question["hint"],
                "answer": "答不上来",
                "score": 2.0,
                "comment": "答不出关键点",
                "answered_at": "2026-10-31T05:00:00+00:00",
                "elapsed_s": 1.5,
            }
            for question in _questions()
        ],
        "answered_count": rules.MIN_INTERVIEW_QUESTIONS,
        "total": rules.MIN_INTERVIEW_QUESTIONS,
    }
    repository.insert_run("run-interview", "interview", profile.id, interview_payload)
    repository.save_run("run-interview", interview_payload, repository.RUN_COMPLETED)

    paper = exam_service.create_run(profile.id)
    exam_service.submit_run(paper.run_id, {q.id: ["Z"] for q in paper.questions})
    return ["run-interview", paper.run_id]


def test_report_generate_latest_and_markdown(
    client: TestClient,
    profile_factory: Callable[..., Any],
    seed_questions: list[dict[str, Any]],
    assert_chinese: Callable[[str], None],
) -> None:
    run_ids = _completed_runs(profile_factory, seed_questions)

    generated = client.post("/api/reports/generate", json={"run_ids": run_ids})
    assert generated.status_code == 200
    report = generated.json()
    assert rules.MIN_SHORTFALLS <= len(report["shortfalls"]) <= rules.MAX_SHORTFALLS

    latest = client.get("/api/reports/latest")
    assert latest.status_code == 200
    assert latest.json()["id"] == report["id"]

    markdown = client.get(f"/api/reports/{report['id']}/markdown")
    assert markdown.status_code == 200
    assert markdown.headers["content-type"].startswith("text/markdown")
    text = markdown.text
    for shortfall in report["shortfalls"]:
        assert shortfall["name"] in text
        assert shortfall["evidence"] in text
        for course in shortfall["courses"]:
            assert course["title"] in text

    missing = client.get("/api/reports/no-such-report/markdown")
    assert missing.status_code == 404
    _assert_error(missing.json(), "NOT_FOUND", assert_chinese)


def test_report_generate_without_runs_rejected(
    client: TestClient, assert_chinese: Callable[[str], None]
) -> None:
    response = client.post("/api/reports/generate", json={})
    assert response.status_code in {400, 404}
    _assert_error(response.json(), response.json()["error"]["code"], assert_chinese)
    assert client.get("/api/reports/latest").status_code == 404


# --- 历史端点（AC-10） ----------------------------------------------------


def test_history_sorted_desc_and_limited(
    client: TestClient,
    profile_factory: Callable[..., Any],
    seed_questions: list[dict[str, Any]],
    assert_chinese: Callable[[str], None],
) -> None:
    run_ids = _completed_runs(profile_factory, seed_questions)
    assert len(run_ids) >= 2

    rows = client.get("/api/history", params={"limit": 10}).json()
    assert len(rows) >= 2
    stamps = [row["created_at"] for row in rows]
    assert stamps == sorted(stamps, reverse=True), "history 必须按 created_at 倒序"
    for row in rows:
        assert row["kind"] in {"interview", "exam"}
        assert set(row) >= {"id", "kind", "score", "shortfall_count", "created_at"}

    only_one = client.get("/api/history", params={"limit": 1}).json()
    assert len(only_one) == 1

    out_of_range = client.get("/api/history", params={"limit": 0})
    assert out_of_range.status_code == 422
    _assert_error(out_of_range.json(), "VALIDATION_ERROR", assert_chinese)


# --- 存储基座（T0）：唯一的 SQL 出口查不到就返回 None ----------------------


def test_repository_roundtrip_and_missing_returns_none(
    tmp_db: Any, profile_factory: Callable[..., Any]
) -> None:
    profile = profile_factory()
    repository.insert_profile(profile)
    assert repository.get_profile(profile.id) is not None
    assert repository.latest_profile() is not None
    assert repository.get_profile("no-such-profile") is None
    assert repository.get_document_text("no-such-document") is None

    repository.insert_run(
        "run-x", "interview", profile.id, {"questions": [], "answered_count": 0, "total": 0}
    )
    stored = repository.get_run("run-x")
    assert stored is not None
    assert stored["kind"] == "interview"
    assert stored["payload"]["answered_count"] == 0
    assert repository.get_run("no-such-run") is None
    assert repository.list_runs(limit=10)

    shortfall = Shortfall.model_validate(
        {
            "name": "缓存与索引",
            "severity": "high",
            "evidence": "Q1 · 3/10",
            "diagnosis": "对索引选择性理解不足",
            "actions": ["重做索引练习"],
            "courses": [
                Course.model_validate(
                    {
                        "id": "c-sql",
                        "title": "数据库索引基础",
                        "direction": "计算机基础",
                        "level": "入门",
                        "url": None,
                        "why": "补齐索引原理",
                    }
                ).model_dump()
            ],
            "question_ref": "iq-1",
        }
    )
    report = Report.model_validate(
        {
            "id": "rep-x",
            "interview_avg": 4.0,
            "exam_total": 60.0,
            "shortfalls": [shortfall.model_dump()],
            "generated_at": "2026-10-31T05:00:00+00:00",
            "run_ids": ["run-x"],
        }
    )
    repository.insert_report(report)
    assert repository.get_report("rep-x") is not None
    assert repository.latest_report() is not None
    assert repository.get_report("no-such-report") is None


# --- 端到端（7c）：五步闭环跑到终态 ----------------------------------------


def test_full_flow_reaches_terminal_report(
    client: TestClient,
    patch_ai: Callable[[Any], None],
    resume_text: str,
    seed_questions: list[dict[str, Any]],
) -> None:
    upload = client.post(
        "/api/resumes",
        files={"file": ("resume.txt", resume_text.encode("utf-8"), "text/plain")},
    )
    assert upload.status_code == 200
    resume_id = upload.json()["resume_id"]

    patch_ai(_responder)
    generated = client.post(f"/api/resumes/{resume_id}/profile")
    assert generated.status_code == 200
    profile_id = generated.json()["id"]

    interview = client.post("/api/interviews", json={"profile_id": profile_id})
    assert interview.status_code == 200
    run = interview.json()
    # r5：一次一问，逐轮按 next_question 推进到终态（不再预铺 8 题）
    question_id: str | None = run["question"]["id"]
    rounds = 0
    while question_id is not None:
        answer = client.post(
            f"/api/interviews/{run['run_id']}/answers",
            json={"question_id": question_id, "answer": "结合项目讲了做法与结果"},
        )
        assert answer.status_code == 200
        turn = answer.json()
        rounds += 1
        question_id = turn["next_question"]["id"] if turn["next_question"] else None
    assert rounds >= rules.MIN_INTERVIEW_QUESTIONS

    paper = client.post("/api/exams", json={"profile_id": profile_id})
    assert paper.status_code == 200
    exam = paper.json()
    seeds = {item["id"]: item for item in seed_questions}
    answers = {
        question["id"]: (
            seeds[question["id"]]["answer"]
            if question["kind"] in OBJECTIVE_KINDS
            else "简答：先建索引再看执行计划"
        )
        for question in exam["questions"]
    }
    submitted = client.post(f"/api/exams/{exam['run_id']}/submit", json={"answers": answers})
    assert submitted.status_code == 200
    assert submitted.json()["total"] == 100.0

    report = client.post("/api/reports/generate", json={})
    assert report.status_code == 200
    body = report.json()
    assert rules.MIN_SHORTFALLS <= len(body["shortfalls"]) <= rules.MAX_SHORTFALLS
    assert body["interview_avg"] is not None
    assert body["exam_total"] is not None

    markdown = client.get(f"/api/reports/{body['id']}/markdown")
    assert markdown.status_code == 200 and markdown.text

    history = client.get("/api/history", params={"limit": 10})
    assert history.status_code == 200
    kinds = {row["kind"] for row in history.json()}
    assert kinds == {"interview", "exam"}
