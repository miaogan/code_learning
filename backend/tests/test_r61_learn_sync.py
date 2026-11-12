"""学习进度与计划打卡上云（r61）：净化规则 + 两对端点的整份读写。

口径：
- 净化一律**静默夹取**（脏 id 丢弃、去重、限长），不返回 400 —— 这两个接口是后台自动同步，
  用户没有重试入口；
- 计划打卡只允许挂在自己真实生成的报告上（未知 report_id → 404 中文 envelope）。
"""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core import repository
from app.schemas import LearnChapterProgress, LearnProgress, Report
from app.services import learn


def _report(report_id: str = "rep-r61") -> Report:
    return Report(
        id=report_id,
        run_ids=[],
        shortfalls=[],
        generated_at="2026-11-10T00:00:00+00:00",
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("ai-model-basics", "ai-model-basics"),
        ("  ai-glossary  ", "ai-glossary"),
        ("d1-int-1", "d1-int-1"),
        ("../etc/passwd", ""),
        ("", ""),
        ("x" * 65, ""),
        (None, ""),
        (123, ""),
    ],
)
def test_clean_id_keeps_only_short_safe_ids(value: Any, expected: str) -> None:
    assert learn.clean_id(value) == expected


def test_normalize_drops_bad_ids_and_dedups_seen() -> None:
    payload = LearnProgress(
        last_chapter_id="../bad",
        chapters={
            "ai-glossary": LearnChapterProgress(
                seen=["s1", "s1", "../bad", "", "s2"],
                last_section_id="../bad",
                updated_at=-3,
            ),
            "../bad": LearnChapterProgress(seen=["s1"]),
        },
    )

    cleaned = learn.normalize_progress(payload)

    assert list(cleaned.chapters) == ["ai-glossary"]
    assert cleaned.chapters["ai-glossary"].seen == ["s1", "s2"]
    assert cleaned.chapters["ai-glossary"].last_section_id is None
    assert cleaned.chapters["ai-glossary"].updated_at == 0
    # last_chapter_id 指向被丢弃的章节 → 一并置空，避免「继续学习」跳到空章
    assert cleaned.last_chapter_id is None


def test_normalize_caps_chapter_and_section_counts() -> None:
    payload = LearnProgress(
        last_chapter_id="c-0",
        chapters={
            f"c-{index}": LearnChapterProgress(seen=[f"s-{n}" for n in range(learn.MAX_SEEN + 5)])
            for index in range(learn.MAX_CHAPTERS + 5)
        },
    )

    cleaned = learn.normalize_progress(payload)

    assert len(cleaned.chapters) == learn.MAX_CHAPTERS
    assert len(cleaned.chapters["c-0"].seen) == learn.MAX_SEEN
    assert cleaned.last_chapter_id == "c-0"


def test_progress_empty_state_then_roundtrip(client: TestClient) -> None:
    assert client.get("/api/learn/progress").json() == {"last_chapter_id": None, "chapters": {}}

    body = {
        "last_chapter_id": "ai-glossary",
        "chapters": {
            "ai-glossary": {"seen": ["s1", "s2"], "last_section_id": "s2", "updated_at": 1762300000000},
        },
    }
    saved = client.put("/api/learn/progress", json=body)
    assert saved.status_code == 200
    assert saved.json() == body

    assert client.get("/api/learn/progress").json() == body


def test_progress_put_overwrites_instead_of_appending(client: TestClient) -> None:
    """整份覆盖语义：第二次同步少了某章，该章必须消失（否则取消的阅读记录会幽灵留存）。"""
    client.put(
        "/api/learn/progress",
        json={
            "last_chapter_id": "c-1",
            "chapters": {
                "c-1": {"seen": ["s1"], "last_section_id": "s1", "updated_at": 1},
                "c-2": {"seen": ["s1"], "last_section_id": "s1", "updated_at": 2},
            },
        },
    )

    client.put(
        "/api/learn/progress",
        json={"last_chapter_id": "c-1", "chapters": {"c-1": {"seen": [], "last_section_id": None, "updated_at": 3}}},
    )

    stored = client.get("/api/learn/progress").json()
    assert list(stored["chapters"]) == ["c-1"]
    assert stored["chapters"]["c-1"]["seen"] == []


def test_plan_unknown_report_is_404_with_chinese_message(client: TestClient, assert_chinese: Any) -> None:
    response = client.get("/api/plans/rep-not-exist")

    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "NOT_FOUND"
    assert error["retryable"] is False
    assert_chinese(error["message"])


def test_plan_empty_state_then_roundtrip(client: TestClient) -> None:
    repository.insert_report(_report())
    report_id = "rep-r61"

    empty = client.get(f"/api/plans/{report_id}").json()
    assert empty == {
        "report_id": report_id,
        "daily_minutes": 30,
        "done": {},
        "started_on": "",
        "updated_at": "",
    }

    saved = client.put(f"/api/plans/{report_id}", json={"daily_minutes": 60, "done": {"t-1": True, "t-2": False}})
    assert saved.status_code == 200
    body = saved.json()
    assert body["daily_minutes"] == 60
    # 取消打卡等价于不在 map 里：False 条目不入库
    assert body["done"] == {"t-1": True}
    assert body["updated_at"]

    assert client.get(f"/api/plans/{report_id}").json() == body


def test_plan_rejects_minutes_outside_closed_set(client: TestClient) -> None:
    repository.insert_report(_report())
    response = client.put("/api/plans/rep-r61", json={"daily_minutes": 45, "done": {}})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_plan_is_scoped_per_report(client: TestClient) -> None:
    repository.insert_report(_report("rep-a"))
    repository.insert_report(_report("rep-b"))

    client.put("/api/plans/rep-a", json={"daily_minutes": 15, "done": {"t-1": True}})

    other = client.get("/api/plans/rep-b").json()
    assert other["daily_minutes"] == 30
    assert other["done"] == {}
    assert other["updated_at"] == ""


# --- r95 计划按日历推进：起始日净化与整份读写 ---------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-11-12", "2026-11-12"),
        ("  2026-11-12 ", "2026-11-12"),
        ("2026-02-31", ""),
        ("2026-13-01", ""),
        ("2026/11/12", ""),
        ("20261112", ""),
        ("", ""),
        (None, ""),
        (20261112, ""),
    ],
)
def test_clean_date_accepts_only_real_calendar_days(value: Any, expected: str) -> None:
    assert learn.clean_date(value) == expected


def test_plan_started_on_roundtrip(client: TestClient) -> None:
    repository.insert_report(_report("rep-r95"))

    saved = client.put(
        "/api/plans/rep-r95",
        json={"daily_minutes": 30, "done": {"t-1": True}, "started_on": "2026-11-12"},
    )

    assert saved.status_code == 200
    assert saved.json()["started_on"] == "2026-11-12"
    assert client.get("/api/plans/rep-r95").json()["started_on"] == "2026-11-12"


def test_plan_bad_started_on_is_silently_dropped(client: TestClient) -> None:
    """起始日是后台同步字段：脏值静默落空串（＝未开始），不能把整次同步打成 422。"""
    repository.insert_report(_report("rep-r95-bad"))

    response = client.put(
        "/api/plans/rep-r95-bad",
        json={"daily_minutes": 30, "done": {}, "started_on": "2026-02-31"},
    )

    assert response.status_code == 200
    assert response.json()["started_on"] == ""
    # 打卡照常写入：起始日不合法不影响其它字段
    assert client.get("/api/plans/rep-r95-bad").json()["started_on"] == ""


def test_plan_started_on_survives_unrelated_writes(client: TestClient) -> None:
    """整份覆盖写下，勾选打卡 / 改时长不会把起始日抹掉（前端每次都带整份状态）。"""
    repository.insert_report(_report("rep-r95-keep"))
    client.put(
        "/api/plans/rep-r95-keep",
        json={"daily_minutes": 30, "done": {}, "started_on": "2026-11-10"},
    )

    client.put(
        "/api/plans/rep-r95-keep",
        json={"daily_minutes": 60, "done": {"t-9": True}, "started_on": "2026-11-10"},
    )

    stored = client.get("/api/plans/rep-r95-keep").json()
    assert stored["daily_minutes"] == 60
    assert stored["done"] == {"t-9": True}
    assert stored["started_on"] == "2026-11-10"
