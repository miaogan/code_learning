"""r62 历史面试列表：`GET /api/interviews` 的在途 / 已完成场次投影。

口径与 `GET /api/interviews/{run_id}` 共用同一批纯函数（`_entries` / `_total_of` /
`_settings_or_none` / `history.score_of`），因此这里只验证「列出来的是同一套读数」，
不重复实现换算。
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from app.core import repository

SETTINGS: dict[str, Any] = {
    "target_role": "后端开发工程师",
    "years_experience": "3-5年",
    "market": "国内",
    "company_size": "大厂",
}


def _payload(*, scored: list[float | None]) -> dict[str, Any]:
    """造一份面试 payload：`scored` 的长度即题目数，`None` 表示还没答。"""
    questions = [
        {
            "id": f"q-{index}",
            "kind": "technical",
            "prompt": f"第 {index} 题",
            "hint": "提示",
            "parent_id": None,
            "answer": None if score is None else "我的回答",
            "score": score,
            "comment": None if score is None else "点评",
        }
        for index, score in enumerate(scored, start=1)
    ]
    return {
        "settings": SETTINGS,
        "plan": questions,
        "questions": questions,
        "total": len(questions),
        "current_id": None,
    }


def _insert(run_id: str, *, scored: list[float | None], completed: bool) -> None:
    payload = _payload(scored=scored)
    repository.insert_run(run_id, "interview", "prof-1", payload)
    if completed:
        repository.save_run(run_id, payload, repository.RUN_COMPLETED)


def test_empty_list(client: TestClient) -> None:
    response = client.get("/api/interviews")
    assert response.status_code == 200
    assert response.json() == []


def test_lists_interview_sessions_with_shared_readings(client: TestClient) -> None:
    _insert("run-old", scored=[6.0, 6.0], completed=True)
    _insert("run-running", scored=[8.0, None], completed=False)
    # 笔试不进面试列表
    repository.insert_run("exam-1", "exam", "prof-1", {"total": 80})
    repository.save_run("exam-1", {"total": 80}, repository.RUN_COMPLETED)

    response = client.get("/api/interviews")
    assert response.status_code == 200
    rows = response.json()
    assert [row["run_id"] for row in rows] == ["run-running", "run-old"]

    running, done = rows
    assert running["status"] == "running"
    assert running["answered_count"] == 1
    assert running["total"] == 2
    assert running["interview_avg"] == 8.0
    assert running["settings"]["target_role"] == "后端开发工程师"

    assert done["status"] == "completed"
    assert done["answered_count"] == 2
    assert done["interview_avg"] == 6.0


def test_limit_is_clamped_not_rejected(client: TestClient) -> None:
    for index in range(3):
        _insert(f"run-{index}", scored=[7.0], completed=True)

    assert len(client.get("/api/interviews?limit=1").json()) == 1
    # 越界上限静默夹到 50（与历史页同一口径：不做 422）
    assert client.get("/api/interviews?limit=100").status_code == 200
    assert client.get("/api/interviews?limit=0").status_code == 200


def test_dirty_payload_does_not_break_list(client: TestClient) -> None:
    """脏 payload（缺 settings / 分数越界 / 计划为空）只降级读数，不让列表接口 500。"""
    bad: dict[str, Any] = {
        "settings": {"target_role": "后端开发工程师"},
        "questions": [
            {"id": "q-1", "kind": "technical", "prompt": "题", "score": 30},
            {"id": "q-2", "kind": "technical", "prompt": "题", "score": "高"},
        ],
    }
    repository.insert_run("run-dirty", "interview", "prof-1", bad)
    repository.save_run("run-dirty", bad, repository.RUN_COMPLETED)

    rows = client.get("/api/interviews").json()
    assert len(rows) == 1
    row = rows[0]
    # settings 缺必填键 → null（不伪造默认值），与 /interviews/{run_id} 的读侧口径一致
    assert row["settings"] is None
    assert row["total"] == 2
    # 只有数字分算「答过」；字符串分数忽略，读数与历史页同一份 `score_of`
    assert row["answered_count"] == 1
    assert row["interview_avg"] == 30.0


def test_requires_login(client: TestClient) -> None:
    client.cookies.clear()
    response = client.get("/api/interviews")
    assert response.status_code in {401, 403}
