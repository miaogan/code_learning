"""r138 回归：连续学习活跃日口径（测评 + 演武 + 学堂，按用户时区去重）。

硬断言：
1. 三类来源合并、同一本地日只算一次；
2. 时区偏移真的影响日键（UTC+8 与 UTC 可见不同日期）；
3. 只统计当前账号，未完成 run / exam 作答 / 脏时间不混入；
4. `total` 是截断前总天数，`days` 受 `limit` 约束。
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from app.core import repository
from app.core.context import set_current_user_id
from app.core.db import connection
from conftest import TEST_USER_ID


def _seed_run(run_id: str, created_at: str, *, status: str = "completed") -> None:
    repository.insert_run(run_id, "interview", "p-test", {})
    with connection() as conn:
        conn.execute(
            "UPDATE runs SET status = ?, created_at = ? WHERE id = ?",
            (status, created_at, run_id),
        )


def _seed_attempt(attempt_id: str, answered_at: str, *, source: str = "practice") -> None:
    rows: list[dict[str, Any]] = [
        {
            "id": attempt_id,
            "question_id": "q-" + attempt_id,
            "run_id": "run-" + attempt_id,
            "correct": 1,
            "answered_at": answered_at,
            "created_at": answered_at,
            "source": source,
        }
    ]
    repository.insert_attempts(rows)


def test_merges_three_sources_and_dedupes_local_day(client: TestClient) -> None:
    set_current_user_id(TEST_USER_ID)
    # UTC+8 下这三条都落在 11-19；另加一条落在 11-18。
    _seed_run("run-assessment", "2026-11-18T20:00:00+00:00")
    _seed_attempt("att-practice", "2026-11-18T22:00:00+00:00")
    millis_1119 = 1795104000000  # 2026-11-19T16:00:00Z → UTC+8 的 11-20 00:00
    repository.save_learn_progress(
        "chap-1",
        {
            "chap-1": {
                "seen": ["s1"],
                "last_section_id": "s1",
                "updated_at": millis_1119,
            }
        },
    )
    _seed_run("run-older", "2026-11-17T20:00:00+00:00")

    body = client.get("/api/activity/days?tz_offset=-480").json()
    assert "2026-11-19" in body["days"]
    assert "2026-11-18" in body["days"]
    assert body["days"].count("2026-11-19") == 1
    assert body["tz_offset"] == -480
    assert body["total"] == 3  # 11-19 / 11-20（学堂）/ 11-18，三条独立日键


def test_offset_changes_day_key(client: TestClient) -> None:
    set_current_user_id(TEST_USER_ID)
    _seed_run("run-boundary", "2026-11-18T20:30:00+00:00")

    as_utc = client.get("/api/activity/days?tz_offset=0").json()
    as_shanghai = client.get("/api/activity/days?tz_offset=-480").json()
    assert as_utc["days"] == ["2026-11-18"]
    assert as_shanghai["days"] == ["2026-11-19"]


def test_ignores_other_users_incomplete_exam_and_dirty_values(client: TestClient) -> None:
    set_current_user_id(TEST_USER_ID)
    _seed_run("run-good", "2026-11-17T10:00:00+00:00")
    _seed_run("run-running", "2026-11-16T10:00:00+00:00", status="running")
    _seed_run("run-dirty", "not-a-date")
    _seed_attempt("att-exam", "2026-11-15T10:00:00+00:00", source="exam")
    repository.save_learn_progress(
        "chap-zero",
        {"chap-zero": {"seen": [], "last_section_id": None, "updated_at": 0}},
    )

    set_current_user_id("somebody-else")
    _seed_run("run-other", "2026-11-14T10:00:00+00:00")

    set_current_user_id(TEST_USER_ID)
    body = client.get("/api/activity/days?tz_offset=0").json()
    assert body["days"] == ["2026-11-17"]


def test_total_is_before_truncation(client: TestClient) -> None:
    set_current_user_id(TEST_USER_ID)
    for day in range(1, 6):
        _seed_run(f"run-limit-{day}", f"2026-10-{day:02d}T10:00:00+00:00")

    body = client.get("/api/activity/days?tz_offset=0&limit=2").json()
    assert body["days"] == ["2026-10-05", "2026-10-04"]
    assert body["total"] == 5
