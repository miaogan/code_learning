"""成长时间线（r3 AC-1 / AC-2 / AC-3 / AC-5）：写入钩子、数值单一来源、幂等、对比与读取端点。

口径纪律是本轮的验收核心，因此这里全部用**既有出口**做对照，而不是复制算式：
- 分数对照 `services.history.score_of` / `GET /api/history`（差 ≤0.05）；
- 短板对照 `diagnosis.build_shortfalls([run])` 的条数与名称；
- 对比只断言服务端算出的 `delta` / 复现 / 消失，前端无需任何减法。

端到端（AC-1「必新增恰好 1 条」）用真实主路径驱动到底：
面试逐题作答至 `completed`、笔试真实提交判分、简历事件由 service 直接写 —— 每条都读回
`GET /api/timeline` 验证终态，而不是只断言单个函数。
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from conftest import drive_session
from fastapi.testclient import TestClient

from app import repository
from app.errors import AI_UNAVAILABLE, VALIDATION_ERROR, AppError
from app.schemas import TimelineComparison, TimelineEvent, TimelineMetrics
from app.services import diagnosis
from app.services import exam as exam_service
from app.services import interview as interview_service
from app.services import rules, timeline

#: 与 `test_interview_service` 同一套合法配比（8 题：5 技术 + 3 项目）。
INTERVIEW_KINDS = ["technical"] * rules.MIN_TECHNICAL_QUESTIONS + ["project"] * (
    rules.MIN_INTERVIEW_QUESTIONS - rules.MIN_TECHNICAL_QUESTIONS
)

EVENT_FIELDS = {
    "id",
    "type",
    "ref_id",
    "occurred_at",
    "key_metrics",
    "shortfall_names",
    "added_shortfalls",
    "removed_shortfalls",
    "summary",
    "duplicate",
    "comparison",
}
METRIC_FIELDS = {
    "interview_avg",
    "exam_total",
    "shortfall_count",
    "skill_added",
    "skill_removed",
}


# --- 测试基座 --------------------------------------------------------------


class _DownAI:
    """AI 整体不可用（出网口 500 → `AI_UNAVAILABLE`）：用于「失败不写事件」的反面用例。"""

    async def complete_model(self, *_args: Any, **_kwargs: Any) -> Any:
        raise AppError(AI_UNAVAILABLE, "AI 暂时不可用，请稍后重试", status=503, retryable=True)


def _responder_for_paper(kinds: list[str]) -> Any:
    """按目标模型分流：出题模型给题目，评分模型给分数（与既有面试用例同一替身逻辑）。"""

    def _respond(payload_model: type[Any], _user: str) -> dict[str, Any]:
        if "questions" in getattr(payload_model, "model_fields", {}):
            return {
                "questions": [
                    {
                        "id": f"iq-{index}",
                        "kind": kind,
                        "prompt": f"第 {index} 题（{kind}）：请结合简历里的经历说明做法与结果",
                        "hint": "结合具体经历，说明取舍与结果",
                    }
                    for index, kind in enumerate(kinds)
                ]
            }
        return {"score": 6.0, "comment": "结构清楚，但缺少量化结果"}

    return _respond


def _seed_profile(profile_factory: Any) -> Any:
    profile = profile_factory()
    repository.insert_profile(profile)
    return profile


def _interview_payload(seed_questions: list[dict[str, Any]], scores: list[float]) -> dict[str, Any]:
    """离线造一份「已完成」的面试 payload（形状与 `score_answer` 回写的一致）。"""
    questions = [
        {
            "id": seed["id"],
            "kind": seed["kind"],
            "prompt": seed["prompt"],
            "hint": seed.get("hint") or "",
            "answer": f"第 {index} 题的回答",
            "score": score,
            "comment": "结构清楚",
            "answered_at": "2026-10-30T00:00:00+00:00",
            "elapsed_s": 1.5,
        }
        for index, (seed, score) in enumerate(
            zip(seed_questions[: len(scores)], scores, strict=True)
        )
    ]
    return {"questions": questions, "answered_count": len(questions), "total": len(questions)}


def _store_run(run_id: str, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    """落一条已完成 run 并读回（`run` 的形状就是写入钩子拿到的形状）。"""
    repository.insert_run(run_id, kind, "prof-1", payload)
    repository.save_run(run_id, payload, repository.RUN_COMPLETED)
    stored = repository.get_run(run_id)
    assert stored is not None
    return stored


def _unique(names: list[str]) -> set[str]:
    return {str(name).strip() for name in names if str(name).strip()}


# --- AC-1：完成即写 1 条，读取端点可用 --------------------------------------


def test_interview_completion_writes_exactly_one_event(
    tmp_db: Any, profile_factory: Any, fake_ai: Any
) -> None:
    """答满最后一题 → `completed` → 恰好 1 条 interview 事件（不是每答一题写一条）。"""
    profile = _seed_profile(profile_factory)
    fake_ai.responder = _responder_for_paper(INTERVIEW_KINDS)
    run = asyncio.run(interview_service.create_run(profile.id, client=fake_ai))

    def _no_event_before_completion(turn: Any) -> None:
        if turn.next_question is not None:
            assert len(timeline.list_timeline()) == 0, "未答完不得提前写事件"

    drive_session(run, fake_ai, answer="我负责组件库重构", on_turn=_no_event_before_completion)
    assert len(timeline.list_timeline()) == 1, "答满整场只写 1 条事件"

    stored = repository.get_run(run.run_id)
    assert stored["status"] == repository.RUN_COMPLETED

    events = timeline.list_timeline()
    assert len(events) == 1
    event = events[0]
    assert event.type == "interview"
    assert event.ref_id == run.run_id
    assert event.occurred_at
    assert event.key_metrics.interview_avg is not None
    assert event.key_metrics.exam_total is None
    assert event.summary.startswith("面试均分")
    assert event.comparison is None, "首次面试没有上一条对比"


def test_exam_submit_writes_event_matching_result(tmp_db: Any, profile_factory: Any) -> None:
    """笔试真实提交 → 1 条 exam 事件，`exam_total` 与响应 `total` 完全一致。"""
    profile = _seed_profile(profile_factory)
    paper = exam_service.create_run(profile.id)
    result = exam_service.submit_run(paper.run_id, {q.id: ["Z"] for q in paper.questions})

    events = timeline.list_timeline()
    assert len(events) == 1
    event = events[0]
    assert event.type == "exam"
    assert event.ref_id == paper.run_id
    assert event.key_metrics.exam_total == result.total
    assert event.key_metrics.interview_avg is None
    assert event.summary.startswith("笔试总分")

    stored = repository.get_run(paper.run_id)
    shortfalls = diagnosis.build_shortfalls([stored])
    assert event.key_metrics.shortfall_count == len(shortfalls)
    assert _unique(event.shortfall_names) == _unique([item.name for item in shortfalls])


# --- AC-2：数值单一来源，写入即定格 ----------------------------------------


def test_interview_event_matches_history_and_diagnosis(
    client: TestClient, tmp_db: Any, profile_factory: Any, fake_ai: Any
) -> None:
    """时间线的分数与 `GET /api/history` 对同一 run 的 `score` 差 ≤0.05（无第二套算式）。"""
    profile = _seed_profile(profile_factory)
    fake_ai.responder = _responder_for_paper(INTERVIEW_KINDS)
    run = asyncio.run(interview_service.create_run(profile.id, client=fake_ai))
    drive_session(run, fake_ai, answer="补充说明")

    event = timeline.list_timeline()[0]
    rows = client.get("/api/history?limit=10").json()
    row = next(item for item in rows if item["id"] == run.run_id)
    assert row["score"] is not None
    assert abs(float(event.key_metrics.interview_avg) - float(row["score"])) <= 0.05

    stored = repository.get_run(run.run_id)
    assert event.key_metrics.shortfall_count == len(diagnosis.build_shortfalls([stored]))


def test_event_metrics_do_not_drift_after_payload_changes(
    tmp_db: Any, profile_factory: Any, fake_ai: Any
) -> None:
    """事件写入后重算 / 改分，`ref_id` 重读的数值不变（快照语义，AC-2 后半条）。"""
    profile = _seed_profile(profile_factory)
    fake_ai.responder = _responder_for_paper(INTERVIEW_KINDS)
    run = asyncio.run(interview_service.create_run(profile.id, client=fake_ai))
    drive_session(run, fake_ai, answer="补充说明")

    first = timeline.list_timeline()[0]
    stored = repository.get_run(run.run_id)
    payload = dict(stored["payload"])
    payload["questions"][0]["score"] = 1.0  # 模拟事后重算 / 改分
    repository.save_run(run.run_id, payload, repository.RUN_COMPLETED)

    again = timeline.list_timeline()[0]
    assert again.id == first.id
    assert again.key_metrics.interview_avg == first.key_metrics.interview_avg
    assert again.shortfall_names == first.shortfall_names


# --- AC-3：幂等 + 失败不写 -------------------------------------------------


def test_repeated_completion_keeps_single_event(
    tmp_db: Any, profile_factory: Any, fake_ai: Any
) -> None:
    """同一 `(type, ref_id)` 反复写只有 1 条：重复完成 / 重放 / 前端重复提交（AC-3）。"""
    profile = _seed_profile(profile_factory)
    fake_ai.responder = _responder_for_paper(INTERVIEW_KINDS)
    run = asyncio.run(interview_service.create_run(profile.id, client=fake_ai))
    drive_session(run, fake_ai, answer="补充说明")

    first = timeline.list_timeline()[0]
    stored = repository.get_run(run.run_id)
    assert timeline.record_run_event({**stored, "kind": "interview"}) is None
    assert timeline.record_run_event({**stored, "kind": "interview"}) is None

    events = timeline.list_timeline()
    assert len(events) == 1
    assert events[0].id == first.id
    assert repository.get_timeline_event("interview", run.run_id) is not None


def test_ai_failure_writes_no_event(tmp_db: Any, profile_factory: Any, fake_ai: Any) -> None:
    """评分失败 → 抛出 `AI_UNAVAILABLE`，run 保持未完成，时间线**一条都不写**（AC-3）。"""
    profile = _seed_profile(profile_factory)
    fake_ai.responder = _responder_for_paper(INTERVIEW_KINDS)
    run = asyncio.run(interview_service.create_run(profile.id, client=fake_ai))

    with pytest.raises(AppError) as excinfo:
        asyncio.run(
            interview_service.score_answer(
                run.run_id, run.question.id, "回答", client=_DownAI()
            )
        )
    assert excinfo.value.code == AI_UNAVAILABLE

    assert timeline.list_timeline() == []
    assert repository.list_timeline_events() == []
    stored = repository.get_run(run.run_id)
    assert stored["status"] != repository.RUN_COMPLETED


def test_record_run_event_swallows_write_failure(
    tmp_db: Any, seed_questions: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """写入失败一律不外抛（旁路不得阻断「进报告」的主流程）。"""
    run = _store_run("run-a", "interview", _interview_payload(seed_questions, [4.0] * 5))

    def _boom(_event: TimelineEvent) -> bool:
        raise RuntimeError("数据库暂时不可用")

    monkeypatch.setattr(repository, "insert_timeline_event", _boom)
    assert timeline.record_run_event(run, occurred_at="2026-10-01T00:00:00+00:00") is None
    assert timeline.list_timeline() == []


def test_record_run_event_ignores_non_run_kind(tmp_db: Any) -> None:
    """简历事件走 `record_resume_event`；`record_run_event` 对非测评 kind 返回 `None` 且不抛。"""
    assert timeline.record_run_event({"id": "res-1", "kind": "resume", "payload": {}}) is None
    assert timeline.record_run_event({"kind": "interview", "payload": {}}) is None
    assert timeline.list_timeline() == []


# --- AC-5：本次 vs 上次（服务端算好 delta / 复现 / 消失） -------------------


def _event(
    *,
    event_id: str,
    kind: str = "exam",
    score: float | None = 60.0,
    shortfall_names: list[str] | None = None,
    occurred_at: str = "2026-10-01T00:00:00+00:00",
) -> TimelineEvent:
    metric = "exam_total" if kind == "exam" else "interview_avg"
    return TimelineEvent(
        id=event_id,
        type=kind,  # type: ignore[arg-type]
        ref_id=f"ref-{event_id}",
        occurred_at=occurred_at,
        key_metrics=TimelineMetrics(**{metric: score}),
        shortfall_names=list(shortfall_names or []),
        summary="",
    )


def test_build_comparison_delta_and_shortfall_changes() -> None:
    """delta 保留 1 位小数，复现 = 两次都在，消失 = 上次有本次无（AC-5 的数值契约）。"""
    previous = _event(
        event_id="prev",
        score=60.0,
        shortfall_names=["索引失效", "并发模型", "缓存策略"],
        occurred_at="2026-10-01T00:00:00+00:00",
    )
    current = _event(
        event_id="cur",
        score=74.5,
        shortfall_names=["索引失效", "缓存策略", "边界用例"],
        occurred_at="2026-10-02T00:00:00+00:00",
    )

    comparison = timeline.build_comparison(current, previous)
    assert comparison is not None
    assert comparison.metric == "exam_total"
    assert comparison.prev_event_id == "prev"
    assert comparison.prev_occurred_at == "2026-10-01T00:00:00+00:00"
    assert comparison.prev_value == 60.0
    assert comparison.current_value == 74.5
    assert comparison.delta == 14.5
    assert comparison.repeated_shortfalls == ["索引失效", "缓存策略"]
    assert comparison.disappeared_shortfalls == ["并发模型"]


def test_build_comparison_none_without_previous_or_on_other_type() -> None:
    """三例：无上一条 / 上一条是另一类型 / 任一侧指标缺失 → `None`（前端渲染「暂无对比」）。"""
    current = _event(event_id="cur", kind="interview", score=7.5)
    assert timeline.build_comparison(current, None) is None
    assert timeline.build_comparison(current, _event(event_id="exam-prev", kind="exam")) is None
    assert timeline.build_comparison(current, _event(event_id="prev", kind="interview", score=None)) is None
    assert timeline.build_comparison(_event(event_id="resume", kind="resume", score=None), current) is None


def test_comparison_uses_previous_same_kind_event(
    tmp_db: Any, seed_questions: list[dict[str, Any]]
) -> None:
    """写入链路真的会找「同类型上一条」：第二次面试带上 delta 与摘要尾句。"""
    low = _store_run("run-low", "interview", _interview_payload(seed_questions, [4.0] * 5))
    high = _store_run("run-high", "interview", _interview_payload(seed_questions, [9.0] * 5))

    first = timeline.record_run_event(low, occurred_at="2026-10-01T00:00:00+00:00")
    second = timeline.record_run_event(high, occurred_at="2026-10-02T00:00:00+00:00")
    assert first is not None and first.comparison is None
    assert second is not None and second.comparison is not None

    comparison = second.comparison
    assert comparison.metric == "interview_avg"
    assert comparison.prev_event_id == first.id
    assert comparison.prev_value == 4.0
    assert comparison.current_value == 9.0
    assert comparison.delta == 5.0
    assert set(comparison.repeated_shortfalls) == _unique(
        first.shortfall_names
    ) & _unique(second.shortfall_names)
    assert set(comparison.disappeared_shortfalls) == _unique(
        first.shortfall_names
    ) - _unique(second.shortfall_names)
    assert "较上次" in second.summary


def test_exam_event_has_no_comparison_when_previous_is_interview(
    client: TestClient, tmp_db: Any, profile_factory: Any, fake_ai: Any
) -> None:
    """上一条是另一类型时 `comparison` 为 `null`（不得跨量纲比较，AC-5 第三例）。"""
    profile = _seed_profile(profile_factory)
    fake_ai.responder = _responder_for_paper(INTERVIEW_KINDS)
    run = asyncio.run(interview_service.create_run(profile.id, client=fake_ai))
    drive_session(run, fake_ai, answer="补充说明")
    paper = exam_service.create_run(profile.id)
    exam_service.submit_run(paper.run_id, {q.id: ["Z"] for q in paper.questions})

    rows = client.get("/api/timeline").json()
    exam_row = next(item for item in rows if item["type"] == "exam")
    assert exam_row["comparison"] is None
    assert exam_row["key_metrics"]["exam_total"] is not None


# --- 读取端点：倒序 + limit 校验 + 字段集 ------------------------------------


def test_timeline_endpoint_orders_desc_and_validates_limit(
    client: TestClient, tmp_db: Any, seed_questions: list[dict[str, Any]]
) -> None:
    """`GET /api/timeline` 按 `occurred_at` 倒序（服务端唯一排序），越界 limit 422 envelope。"""
    schedule = [
        ("run-a", "2026-10-01T00:00:00+00:00"),
        ("run-b", "2026-10-03T00:00:00+00:00"),
        ("run-c", "2026-10-02T00:00:00+00:00"),
    ]
    for run_id, when in schedule:
        run = _store_run(run_id, "interview", _interview_payload(seed_questions, [6.0] * 5))
        assert timeline.record_run_event(run, occurred_at=when) is not None

    rows = client.get("/api/timeline").json()
    assert [row["ref_id"] for row in rows] == ["run-b", "run-c", "run-a"]
    assert set(rows[0]) == EVENT_FIELDS
    assert set(rows[0]["key_metrics"]) == METRIC_FIELDS
    assert timeline.DEFAULT_LIMIT == 20

    limited = client.get("/api/timeline?limit=2").json()
    assert [row["ref_id"] for row in limited] == ["run-b", "run-c"]

    for bad in (0, 51):
        response = client.get(f"/api/timeline?limit={bad}")
        assert response.status_code == 422
        assert response.json()["error"]["code"] == VALIDATION_ERROR


# --- 简历事件 --------------------------------------------------------------


def test_resume_event_records_skill_counts_and_is_idempotent(tmp_db: Any) -> None:
    """简历事件带 `skill_added` / `skill_removed` / `duplicate`，同一份简历只记 1 条。"""
    event = timeline.record_resume_event(
        resume_id="res-1",
        skill_added=["Go", "Kubernetes", "react", "Go"],
        skill_removed=["SQLite"],
        duplicate=True,
    )
    assert event is not None
    assert event.type == "resume"
    assert event.ref_id == "res-1"
    assert event.key_metrics.skill_added == 3, "重名能力项只算一条"
    assert event.key_metrics.skill_removed == 1
    assert event.key_metrics.interview_avg is None
    assert event.duplicate is True
    assert event.comparison is None
    assert "新增 3 项能力" in event.summary
    assert "1 项转为历史" in event.summary

    assert (
        timeline.record_resume_event(
            resume_id="res-1", skill_added=["Kotlin"], skill_removed=[], duplicate=True
        )
        is None
    )
    assert len(timeline.list_timeline()) == 1
    assert timeline.record_resume_event(
        resume_id="", skill_added=[], skill_removed=[]
    ) is None


# --- 端到端：一次完整的成长旅程跑到终态 -------------------------------------


def test_growth_journey_end_to_end(
    client: TestClient, tmp_db: Any, profile_factory: Any, fake_ai: Any
) -> None:
    """真实主路径跑到终态：面试答满 → 笔试提交 → 简历上传事件，时间线终态 3 条且不重复。

    单函数断言无法覆盖「完成钩子只在该完成点触发一次」这条状态机语义，因此这里串起来跑：
    先面试逐题作答至 `completed`，再提交一次笔试，最后写 1 条简历事件，读 `GET /api/timeline`
    验证终态条数、类型集合、`duplicate` 全为 false，以及重复完成不会多写。
    """
    profile = _seed_profile(profile_factory)
    fake_ai.responder = _responder_for_paper(INTERVIEW_KINDS)

    run = asyncio.run(interview_service.create_run(profile.id, client=fake_ai))
    drive_session(run, fake_ai, answer="补充说明")
    stored = repository.get_run(run.run_id)
    assert stored["status"] == repository.RUN_COMPLETED

    paper = exam_service.create_run(profile.id)
    result = exam_service.submit_run(paper.run_id, {q.id: ["Z"] for q in paper.questions})
    assert result.objective_total > 0

    resume_event = timeline.record_resume_event(
        resume_id="res-1", skill_added=["Go"], skill_removed=[], duplicate=False
    )
    assert resume_event is not None

    rows = client.get("/api/timeline?limit=20").json()
    assert len(rows) == 3, "三种完成点各写恰好 1 条"
    assert {row["type"] for row in rows} == {"interview", "exam", "resume"}
    assert all(row["duplicate"] is False for row in rows)
    assert rows[0]["type"] == "resume", "occurred_at 倒序：最后写入的简历事件在最前"
    exam_row = next(row for row in rows if row["type"] == "exam")
    assert exam_row["key_metrics"]["exam_total"] == result.total

    # 重复完成（重放）：r5 起已完成会话只读 ⇒ 400 拒绝，时间线不新增（与 QA D-2 同源语义）
    with pytest.raises(AppError):
        asyncio.run(
            interview_service.score_answer(run.run_id, run.question.id, "再答一次", client=fake_ai)
        )
    assert len(client.get("/api/timeline?limit=20").json()) == 3


def test_list_timeline_returns_validated_events(tmp_db: Any) -> None:
    """读取回来的是 `TimelineEvent` 实例（契约模型没被 payload 漂移），且 `comparison` 类型正确。"""
    timeline.record_resume_event(resume_id="res-1", skill_added=["Go"], skill_removed=[])
    stored = timeline.list_timeline()
    assert len(stored) == 1
    assert isinstance(stored[0], TimelineEvent)
    assert stored[0].comparison is None
    assert isinstance(timeline.build_comparison(stored[0], None), type(None))
    comparison: TimelineComparison | None = stored[0].comparison
    assert comparison is None
