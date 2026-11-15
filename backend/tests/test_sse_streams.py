"""r102 SSE 流测试：任务进度流（status / done / error / 隔离）与面试回合流（phase / turn / done）。

零网络：面试的模型调用经 `patch_ai` 走预置 responder；任务流直接写 `profile_jobs` 行。
"""

import asyncio
import json

import pytest

from app.core import repository
from app.core.config import get_settings
from app.services.interview import interview as interview_service


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _seed_job(status: str, *, user_id: str = "default", job_id: str = "pj-1") -> str:
    """造一行任务：时间取「现在」——固定旧时间会让 running 行被 30 分钟惰性清扫判死（正确行为）。"""
    stamp = _now_iso()
    with repository.connection() as conn:
        conn.execute(
            "INSERT INTO profile_jobs (id, user_id, document_id, file_name, chars, sections,"
            " status, error, result, created_at, updated_at) "
            "VALUES (?, ?, 'doc-1', '简历.txt', 100, 3, ?, ?, '', ?, ?)",
            (job_id, user_id, status, "失败原因" if status == "failed" else "", stamp, stamp),
        )
    return job_id


def _set_status(job_id: str, status: str) -> None:
    with repository.connection() as conn:
        conn.execute(
            "UPDATE profile_jobs SET status = ?, updated_at = ? WHERE id = ?",
            (status, _now_iso(), job_id),
        )


def _fast_poll(monkeypatch: pytest.MonkeyPatch) -> None:
    """把流内轮询压到 10ms，用例不必真的等 0.8s 一帧。"""
    monkeypatch.setenv("JOBS_STREAM_POLL_S", "0.01")
    monkeypatch.setenv("JOBS_STREAM_HEARTBEAT_S", "1")
    get_settings.cache_clear()


def test_job_stream_terminal_pushes_status_and_done(client, monkeypatch):
    """已完成任务：立刻推 status + done 并关闭（前端据此只补一次单查拿结果）。"""
    job_id = _seed_job("completed")
    _fast_poll(monkeypatch)
    with client.stream("GET", f"/api/jobs/profile/{job_id}/stream") as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        body = "".join(response.iter_text())
    assert "event: status" in body
    assert '"status":"completed"' in body
    assert "event: done" in body


def test_job_stream_pushes_transition(client, monkeypatch):
    """运行中 → 完成：同一条流里依次看到 running 与 completed（推送而非轮询）。"""
    job_id = _seed_job("running")
    _fast_poll(monkeypatch)
    statuses: list[str] = []
    with client.stream("GET", f"/api/jobs/profile/{job_id}/stream") as response:
        for line in response.iter_lines():
            if line.startswith("data:"):
                payload = json.loads(line[5:].strip())
                if "status" in payload:
                    statuses.append(payload["status"])
                    if payload["status"] == "running":
                        _set_status(job_id, "completed")
            if line.startswith("event: done"):
                break
    assert statuses == ["running", "completed"]


def test_job_stream_reports_failure(client, monkeypatch):
    """失败任务：status 帧带中文原因，done 关流。"""
    job_id = _seed_job("failed")
    _fast_poll(monkeypatch)
    with client.stream("GET", f"/api/jobs/profile/{job_id}/stream") as response:
        body = "".join(response.iter_text())
    assert '"status":"failed"' in body
    assert "失败原因" in body


def test_job_stream_404_for_missing(client, assert_chinese):
    """不存在的任务：HTTP 层 404 + 中文 envelope（流未开始就拒绝，符合既有错误口径）。"""
    response = client.get("/api/jobs/profile/pj-nope/stream")
    assert response.status_code == 404
    assert_chinese(response.json()["error"]["message"])


def test_job_stream_unknown_kind(client, assert_chinese):
    """未知任务类型：400 + 中文说明（闭集外不猜）。"""
    response = client.get("/api/jobs/unknown/pj-1/stream")
    assert response.status_code == 400
    assert_chinese(response.json()["error"]["message"])


def test_job_stream_isolated_by_user(client):
    """跨用户 job_id：按「不存在」处理（不暴露他人任务的存在性）。"""
    job_id = _seed_job("running", user_id="someone-else", job_id="pj-other")
    response = client.get(f"/api/jobs/profile/{job_id}/stream")
    assert response.status_code == 404


# --- 面试回合流 ---------------------------------------------------------------


def _interview_responder():
    plan = [
        {"kind": "technical", "prompt": f"第 {i} 题：结合简历说明做法与取舍", "hint": "结合经历"}
        for i in range(1, 6)
    ] + [
        {"kind": "project", "prompt": f"第 {i} 题：讲一个项目的细节", "hint": ""}
        for i in range(6, 9)
    ]

    def _respond(model_cls, _user):
        fields = getattr(model_cls, "model_fields", {})
        if "questions" in fields:
            return {"questions": plan}
        if "shortfalls" in fields:
            return {"shortfalls": []}
        return {"score": 6.0, "comment": "思路清楚，缺量化结果", "next": {"mode": "advance"}}

    return _respond


def test_interview_stream_emits_phase_turn_done(client, patch_ai, profile_factory):
    """回合流：phase → turn → done，turn 帧即同步端点的完整契约。"""
    repository.insert_profile(profile_factory())
    patch_ai(_interview_responder())
    run = asyncio.run(
        interview_service.create_run("prof-1", None, client=None)
    )
    with client.stream(
        "POST",
        f"/api/interviews/{run.run_id}/answers/stream",
        json={"question_id": run.question.id, "answer": "先讲背景，再讲做法与结果"},
    ) as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())
    assert "event: phase" in body
    assert '"phase":"scoring"' in body
    assert "event: turn" in body
    assert '"score"' in body
    assert "event: done" in body


def test_interview_stream_error_frame(client, patch_ai, profile_factory):
    """错误（答已过期的题）：流内 error 帧 + 中文 message，不出现 turn。"""
    repository.insert_profile(profile_factory())
    patch_ai(_interview_responder())
    run = asyncio.run(
        interview_service.create_run("prof-1", None, client=None)
    )
    with client.stream(
        "POST",
        f"/api/interviews/{run.run_id}/answers/stream",
        json={"question_id": "iq-999", "answer": "答一道不存在的题"},
    ) as response:
        body = "".join(response.iter_text())
    assert "event: error" in body
    assert "没有这道题" in body
    assert "event: turn" not in body
