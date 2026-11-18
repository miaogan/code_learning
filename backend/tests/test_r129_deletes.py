"""r129 历史记录删除：单条移出 / 清空三条链路的接口级证据。

覆盖：
- 镜试复盘：单条删除后列表不再返回、重复删除 404、清空返回条数；跨账号删不动；
- 测评场次（`DELETE /api/history/{run_id}`）：run + 成长时间线事件 + 该场次作答事件
  同场级联删除；不存在 404；runs 表的 kind 白名单外（旁路数据）删不动；
- 错题本移出：只记移出标记——错题本与 `wrong_total` 同步消失、作答事件仍在
  （统计口径不变）、之后再答错会重新进错题本；清空返回移出条数；
- 简历版本删除：级联清画像 / 画像任务 / 简历时间线事件；历史成绩（快照）保留。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient

from app.core import repository
from app.core.db import connection
from app.schemas import Profile, ResumeMeta


def _stamp(offset_seconds: int = 0) -> str:
    return (datetime.now(UTC) + timedelta(seconds=offset_seconds)).isoformat()


# --- 镜试复盘 -----------------------------------------------------------------


def _save_card(card_id: str, question: str) -> None:
    repository.save_mirror_card(
        card_id,
        resume_id="res-1",
        file_name="简历.txt",
        question=question,
        payload={"question": question},
        source="custom",
    )


def test_mirror_delete_single_then_clear(client: TestClient) -> None:
    _save_card("card-1", "第一题")
    _save_card("card-2", "第二题")

    assert client.delete("/api/mirror/cards/card-1").status_code == 204
    items = client.get("/api/mirror/cards").json()["items"]
    assert [item["id"] for item in items] == ["card-2"]

    # 重复删除（或别人的）→ 404，中文提示
    gone = client.delete("/api/mirror/cards/card-1")
    assert gone.status_code == 404
    assert gone.json()["error"]["code"] == "NOT_FOUND"
    assert any("\u4e00" <= ch <= "\u9fff" for ch in gone.json()["error"]["message"])

    cleared = client.delete("/api/mirror/cards")
    assert cleared.status_code == 200
    assert cleared.json() == {"deleted": 1}
    assert client.get("/api/mirror/cards").json()["items"] == []


def test_mirror_delete_is_account_scoped(client: TestClient) -> None:
    _save_card("card-mine", "我的题")
    with connection() as conn:
        conn.execute(
            "INSERT INTO mirror_cards (id, user_id, resume_id, file_name, question,"
            " payload, source, created_at) VALUES (?, 'someone', 'res-x', '', '别人的题',"
            " '{}', 'custom', ?)",
            ("card-other", _stamp()),
        )

    # 跨账号删除一律 404，且对方的卡完好无损。
    assert client.delete("/api/mirror/cards/card-other").status_code == 404
    with connection() as conn:
        row = conn.execute(
            "SELECT count(*) AS n FROM mirror_cards WHERE id = 'card-other'"
        ).fetchone()
    assert int(row["n"]) == 1  # type: ignore[index]
    client.delete("/api/mirror/cards")  # 清空只影响自己
    with connection() as conn:
        row = conn.execute(
            "SELECT count(*) AS n FROM mirror_cards WHERE id = 'card-other'"
        ).fetchone()
    assert int(row["n"]) == 1  # type: ignore[index]


# --- 测评场次（run）删除 --------------------------------------------------------


def _insert_run(run_id: str, kind: str) -> None:
    repository.insert_run(run_id, kind, "prof-1", {"total": 60})


def _insert_timeline(run_id: str, event_type: str) -> None:
    with connection() as conn:
        conn.execute(
            "INSERT INTO timeline_events (id, user_id, type, ref_id, occurred_at,"
            " payload, created_at) VALUES (?, 'default', ?, ?, ?, '{}', ?)",
            (f"tl-{run_id}", event_type, run_id, _stamp(), _stamp()),
        )


def _insert_attempt(attempt_id: str, run_id: str, question_id: str) -> None:
    repository.insert_attempts(
        [
            {
                "id": attempt_id,
                "question_id": question_id,
                "run_id": run_id,
                "correct": 0,
                "answered_at": _stamp(),
                "created_at": _stamp(),
                "source": "exam",
            }
        ]
    )


def _count(table: str, where: str, value: str) -> int:
    with connection() as conn:
        row = conn.execute(
            f"SELECT count(*) AS n FROM {table} WHERE {where} = ?", (value,)
        ).fetchone()
    return int(row["n"])  # type: ignore[index]


def test_history_delete_cascades_run_timeline_attempts(client: TestClient) -> None:
    _insert_run("run-1", "exam")
    _insert_timeline("run-1", "exam")
    _insert_attempt("att-1", "run-1", "q-1")

    assert client.delete("/api/history/run-1").status_code == 204
    assert repository.get_run("run-1") is None
    assert _count("timeline_events", "ref_id", "run-1") == 0
    assert _count("question_attempts", "run_id", "run-1") == 0

    # 重复删除 → 404
    assert client.delete("/api/history/run-1").status_code == 404


def test_history_delete_interview_kind_and_whitelist(client: TestClient) -> None:
    _insert_run("run-i1", "interview")
    assert client.delete("/api/history/run-i1").status_code == 204

    # runs 表是共享承载：白名单外（旁路数据 / 未来新 kind）删不动，404 且行还在。
    _insert_run("run-x", "some-other-kind")
    assert client.delete("/api/history/run-x").status_code == 404
    assert repository.get_run("run-x") is not None


# --- 错题本移出 -----------------------------------------------------------------


def _question(question_id: str) -> dict[str, Any]:
    return {
        "id": question_id,
        "direction": "后端",
        "sub_direction": "",
        "kind": "single",
        "difficulty": "basic",
        "essentiality": "must_know",
        "prompt": f"题面 {question_id}",
        "options": [
            {"key": "A", "text": "选项 A"},
            {"key": "B", "text": "选项 B"},
            {"key": "C", "text": "选项 C"},
        ],
        "answer": ["A"],
        "source": "test",
        "language": "python",
        "explanation": f"解析 {question_id}",
    }


def _answer_wrong(client: TestClient, question_id: str, session_id: str) -> None:
    response = client.post(
        "/api/practice/answer",
        json={"session_id": session_id, "question_id": question_id, "answer": ["Z"]},
    )
    assert response.status_code == 200, response.text[:300]


def test_wrong_book_dismiss_hides_but_keeps_attempts(client: TestClient) -> None:
    assert repository.insert_question(_question("q-d1")) is True
    _answer_wrong(client, "q-d1", "session-1")

    assert client.get("/api/practice/wrong-book").json()["total"] == 1
    assert client.get("/api/practice/stats").json()["wrong_total"] == 1

    assert client.delete("/api/practice/wrong-book/q-d1").status_code == 204
    # 错题本与统计同步消失（两边口径必须一致），但作答事件还在（统计历史不变）。
    assert client.get("/api/practice/wrong-book").json()["total"] == 0
    assert client.get("/api/practice/stats").json()["wrong_total"] == 0
    assert _count("question_attempts", "question_id", "q-d1") == 1

    # 已移出的题再删一次 → 404（它已经不在错题本里）
    assert client.delete("/api/practice/wrong-book/q-d1").status_code == 404


def test_wrong_book_re_wrong_after_dismiss_returns(client: TestClient) -> None:
    assert repository.insert_question(_question("q-d2")) is True
    _answer_wrong(client, "q-d2", "session-1")
    assert client.delete("/api/practice/wrong-book/q-d2").status_code == 204

    # 移出之后再答错是新事实：重新进错题本（移出不是永久拉黑）。
    _answer_wrong(client, "q-d2", "session-2")
    assert client.get("/api/practice/wrong-book").json()["total"] == 1


def test_wrong_book_clear_returns_dismissed_count(client: TestClient) -> None:
    for index in ("q-c1", "q-c2"):
        assert repository.insert_question(_question(index)) is True
        _answer_wrong(client, index, f"session-{index}")

    cleared = client.delete("/api/practice/wrong-book")
    assert cleared.status_code == 200
    assert cleared.json() == {"deleted": 2}
    assert client.get("/api/practice/wrong-book").json()["total"] == 0
    # 清空只写标记：作答事件全部保留。
    assert _count("question_attempts", "source", "practice") == 2


# --- 简历版本删除 -----------------------------------------------------------------


def _seed_resume_with_profile(resume_id: str, profile: Profile) -> None:
    repository.insert_document(
        ResumeMeta(resume_id=resume_id, file_name="简历.txt", chars=100, sections=3),
        "简历正文",
    )
    repository.save_profile(profile)
    _insert_timeline(resume_id, "resume")


def test_resume_delete_cascades_profile_and_timeline(client: TestClient, profile_factory) -> None:
    profile: Profile = profile_factory(profile_id="prof-del", resume_id="res-del")
    _seed_resume_with_profile("res-del", profile)

    assert client.delete("/api/resumes/res-del").status_code == 204
    assert repository.get_document("res-del") is None
    assert repository.get_profile("prof-del") is None
    assert _count("timeline_events", "ref_id", "res-del") == 0
    assert _count("profile_jobs", "document_id", "res-del") == 0

    # 重复删除 → 404
    assert client.delete("/api/resumes/res-del").status_code == 404


def test_resume_delete_keeps_history_runs(client: TestClient, profile_factory) -> None:
    """删简历版本不清历史成绩：runs 是快照，投影处对画像缺失已容忍。"""
    _insert_run("run-keep", "exam")
    _seed_resume_with_profile("res-k", profile_factory(profile_id="prof-keep", resume_id="res-k"))

    assert client.delete("/api/resumes/res-k").status_code == 204
    assert repository.get_run("run-keep") is not None
