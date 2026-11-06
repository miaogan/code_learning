"""r30 异步画像任务：受理 → 后台执行 → 轮询终态（TECHNICAL §6.1 零网络口径不变）。

要点：
- `POST /api/resumes/{id}/profile/async` 只受理，立即返回 `job_id`；真正的 AI 调用
  在 `asyncio.create_task` 里跑，测试里轮询 `GET /api/profile-jobs/{id}` 等终态。
- 后台任务两种终态都必须落库可见（completed 带 `ProfileWithMerge`，failed 带中文原因），
  不允许「无声消失」。
- 任务行按 `user_id` 隔离：别人的任务读不到（404）。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core import repository
from app.core.auth import COOKIE_NAME, hash_password, new_session_token, session_expiry
from app.core.db import connection
from app.core.errors import VALIDATION_ERROR, AppError
from app.schemas import ResumeMeta

TEST_USER_ID = "default"
OTHER_USER_ID = "other-user"

#: 轮询上限：FakeAI 即时返回，5 秒足够；超时视为「任务无声消失」直接失败。
WAIT_TIMEOUT_S = 5.0


def _insert_resume(resume_text: str, resume_id: str = "res-1") -> None:
    repository.insert_document(
        ResumeMeta(resume_id=resume_id, file_name="resume.txt", chars=len(resume_text), sections=3),
        resume_text,
    )


def _wait_terminal(
    client: TestClient,
    job_id: str,
    *,
    statuses: set[str],
) -> dict[str, Any]:
    deadline = time.monotonic() + WAIT_TIMEOUT_S
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        response = client.get(f"/api/profile-jobs/{job_id}")
        assert response.status_code == 200
        last = response.json()
        if last["status"] in statuses:
            return last
        time.sleep(0.05)
    pytest.fail(f"任务在 {WAIT_TIMEOUT_S}s 内未到达终态，最后状态：{last}")


def _start_job(client: TestClient, resume_id: str = "res-1") -> str:
    response = client.post(f"/api/resumes/{resume_id}/profile/async")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "running"
    return str(body["job_id"])


def test_async_job_completes_with_merge_result(
    client: TestClient,
    patch_ai: Callable[[Any], None],
    resume_text: str,
) -> None:
    _insert_resume(resume_text)
    patch_ai(lambda *_: {
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
    })

    job_id = _start_job(client)
    job = _wait_terminal(client, job_id, statuses={"completed", "failed"})

    assert job["status"] == "completed", job
    assert job["file_name"] == "resume.txt"
    assert job["chars"] == len(resume_text)
    assert job["sections"] == 3
    result = job["result"]
    assert result is not None and result["id"]
    assert result["skills"][0]["name"] == "React"
    # 后台完成也要带一次性 merge_summary（r3 的「本次合并」摘要不因异步而丢）。
    assert "merge_summary" in result
    # 画像本身已入库：同步读路径照常能读到。
    latest = client.get("/api/profiles/latest")
    assert latest.status_code == 200
    assert latest.json()["id"] == result["id"]


def test_async_job_unknown_resume_404(
    client: TestClient, assert_chinese: Callable[[str], None]
) -> None:
    response = client.post("/api/resumes/res-missing/profile/async")
    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "NOT_FOUND"
    assert_chinese(error["message"])


def test_async_job_failure_is_visible(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    resume_text: str,
    assert_chinese: Callable[[str], None],
) -> None:
    _insert_resume(resume_text)

    async def _boom(*_args: Any, **_kwargs: Any) -> None:
        raise AppError(VALIDATION_ERROR, "简历正文无法用于生成画像", status=400)

    monkeypatch.setattr("app.routers.profile.generate_profile", _boom)

    job_id = _start_job(client)
    job = _wait_terminal(client, job_id, statuses={"completed", "failed"})

    assert job["status"] == "failed", job
    assert job["result"] is None
    assert job["error"] == "简历正文无法用于生成画像"
    assert_chinese(job["error"])


def test_latest_profile_job_and_empty_404(client: TestClient) -> None:
    assert client.get("/api/profile-jobs/latest").status_code == 404

    repository.insert_profile_job("job-1", "res-1", "resume.txt", 100, 3)
    response = client.get("/api/profile-jobs/latest")
    assert response.status_code == 200
    body = response.json()
    assert body["job_id"] == "job-1"
    assert body["status"] == "running"
    assert body["result"] is None


def test_stale_running_job_marked_failed_on_read(client: TestClient) -> None:
    """r32 僵尸任务：服务重启后无人推进的 running 行，读一次就拿到 failed 终态。"""
    repository.insert_profile_job("job-zombie", "res-1", "resume.txt", 100, 3)
    stale_at = (datetime.now(UTC) - timedelta(seconds=11 * 60)).isoformat()
    with connection() as conn:
        conn.execute(
            "UPDATE profile_jobs SET updated_at = ? WHERE id = 'job-zombie'", (stale_at,)
        )

    body = client.get("/api/profile-jobs/job-zombie").json()
    assert body["status"] == "failed"
    assert body["result"] is None
    assert "重新生成画像" in body["error"]

    # latest 读路径同样先清扫：前端重接入拿到的是确定终态，不会无限等。
    latest = client.get("/api/profile-jobs/latest").json()
    assert latest["job_id"] == "job-zombie"
    assert latest["status"] == "failed"


def test_fresh_running_job_not_expired(client: TestClient) -> None:
    """正常的在途任务（updated_at 新鲜）不受清扫影响，轮询照常拿到 running。"""
    repository.insert_profile_job("job-fresh", "res-1", "resume.txt", 100, 3)
    body = client.get("/api/profile-jobs/job-fresh").json()
    assert body["status"] == "running"
    assert body["error"] == ""


def test_profile_job_isolated_between_users(
    client: TestClient,
    resume_text: str,
) -> None:
    repository.insert_profile_job("job-1", "res-1", "resume.txt", 100, 3)

    # 第二个登录用户：自己的库里没有这个任务，读别人的任务必须 404。
    repository.create_user(
        user_id=OTHER_USER_ID,
        email="other@example.com",
        password_hash=hash_password("other-password-123"),
        display_name="其他用户",
        role="member",
        key_mode="own",
    )
    raw, digest = new_session_token()
    repository.create_session(
        token_hash=digest, user_id=OTHER_USER_ID, expires_at=session_expiry()
    )
    other = TestClient(client.app)
    other.cookies.set(COOKIE_NAME, raw)

    assert other.get("/api/profile-jobs/job-1").status_code == 404
    # 自己仍然读得到。
    assert client.get("/api/profile-jobs/job-1").status_code == 200
