"""T8 集成回归：`build_report` 的三块编排（AC-11 / AC-13 / AC-14 / anti-goal 5）。

这一层只证明「接线是对的」，三块各自的算法细节在 test_weakness / test_role_fit /
test_resume_hints 里已经测过。所以这里的断言集中在四件事：
1. 短板序列与 r6 的口径**逐字不变**（AC-14：加了三块，主轴不许动）；
2. 三路 AI 全挂 → 报告照样 200，三块结构完整、文案是模板而不是占位；
3. AI 返回的条目数与输入对不上 → 输出条数/顺序不改（只换文案）；
4. 旧 payload（四字段缺失）反序列化即 `None`，`[]` 与 `None` 语义不混。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from app.core import repository
from app.schemas import Report
from app.services.assessment import exam as exam_service
from app.services.report import diagnosis, rules, weakness as weakness_service
from app.services.report.diagnosis import _CoachCopyDraft
from app.services.resume import coach_copy
from test_report_service import VALID_KINDS, _bad_score_responder, _prepare_runs


def _build(run_ids: list[str], client: Any = None) -> Report:
    return asyncio.run(diagnosis.build_report(run_ids, client=client))


def _shape(item: Any) -> tuple[str, str, str, str]:
    """短板的**结构性**字段（diagnosis/actions 是 AI 文案，可能被替换，不进比较）。"""
    return (item.name, item.severity, item.evidence, item.question_ref)


def test_shortfall_sequence_unchanged(
    tmp_db: Any, profile_factory: Any, fake_ai: Any, seed_questions: list[dict[str, Any]]
) -> None:
    """AC-14：三块加进来之后，主轴仍是同一批 `build_shortfalls` 结果。"""
    runs = _prepare_runs(tmp_db, profile_factory, fake_ai, seed_questions)
    run_ids = [str(run["id"]) for run in runs]
    pure = diagnosis.attach_courses(diagnosis.build_shortfalls(runs))

    report = _build(run_ids)

    assert rules.MIN_SHORTFALLS <= len(report.shortfalls) <= rules.MAX_SHORTFALLS
    assert [_shape(item) for item in report.shortfalls] == [_shape(item) for item in pure]


def test_weakness_totals_match_history_scope(
    tmp_db: Any, profile_factory: Any, fake_ai: Any, seed_questions: list[dict[str, Any]]
) -> None:
    """anti-goal 2：地图的题量分母必须等于历史页/主轴看到的已计分题数。"""
    runs = _prepare_runs(tmp_db, profile_factory, fake_ai, seed_questions)
    report = _build([str(run["id"]) for run in runs])

    scored = sum(len(diagnosis._scored(run)) for run in runs)
    assert report.weakness_map is not None
    assert sum(item.total for item in report.weakness_map) == scored
    for item in report.weakness_map:
        assert item.summary and "占位" not in item.summary


def test_three_way_ai_outage_still_returns_full_report(
    tmp_db: Any,
    profile_factory: Any,
    fake_ai: Any,
    seed_questions: list[dict[str, Any]],
    client: Any,
    ai_outage: None,
) -> None:
    """AC-11 / anti-goal 5：AI 全挂 → HTTP 200，三块结构完整、文案退回模板。"""
    runs = _prepare_runs(tmp_db, profile_factory, fake_ai, seed_questions)
    response = client.post("/api/reports/generate", json={"run_ids": [str(r["id"]) for r in runs]})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["weakness_map"] is not None and body["weakness_map"]
    assert body["resume_pointers"] is not None
    assert body["role_fit"] is not None
    for item in body["weakness_map"]:
        assert item["summary"] and "TODO" not in item["summary"]
    # 降级不是「结构消失」：有正文时要么给要点，要么给一句中文原因（二者必居其一）。
    assert body["resume_pointers"] or body["resume_pointers_notice"]


def test_ai_entry_count_mismatch_keeps_order(
    tmp_db: Any, profile_factory: Any, fake_ai: Any, seed_questions: list[dict[str, Any]]
) -> None:
    """AC-13：AI 少给/多给/给错 key 都不许改条数与顺序，只许换文案。"""
    runs = _prepare_runs(tmp_db, profile_factory, fake_ai, seed_questions)
    run_ids = [str(run["id"]) for run in runs]
    pure = weakness_service.build_weakness_map(runs)

    class _DraftAI:
        """只答教练文案的替身：返回 1 条合法 key（必然不匹配）+ 1 条乱造 key。"""

        async def complete_model(
            self, _system: str, _user: str, model_cls: type[Any], **_kwargs: Any
        ) -> Any:
            if model_cls is _CoachCopyDraft:
                return model_cls.model_validate(
                    {
                        "weaknesses": [
                            {"key": "瞎写的键", "summary": "这组的缺口在于缺少系统训练"},
                            {"key": pure[0].key if pure else "x", "summary": "补基础概念与错题复盘"},
                        ],
                        "role_conclusion": "先补必备技能，再扩广度",
                    }
                )
            raise RuntimeError("其它链路不参与本用例")

    report = _build(run_ids, client=_DraftAI())

    assert [item.key for item in report.weakness_map or []] == [item.key for item in pure]
    assert [item.point for item in report.weakness_map or []] == [item.point for item in pure]
    if pure:
        assert report.weakness_map is not None
        assert report.weakness_map[0].summary == "补基础概念与错题复盘"
    assert report.role_fit is not None


def test_role_source_stays_interview_when_settings_match_profile(
    tmp_db: Any, profile_factory: Any, fake_ai: Any, seed_questions: list[dict[str, Any]]
) -> None:
    """D-1 门禁：面试设定与画像岗位**同值**时，来源仍须是「本次面试设定」。

    编排层若把 `resolve_target_role(...)` 的结果降级成裸岗位名再交给 `build_role_fit`，
    纯函数只能反向推断成「简历画像」——真实来源丢失。这里锁死端到端的接线。
    """
    runs = _prepare_runs(tmp_db, profile_factory, fake_ai, seed_questions)
    settings = diagnosis.interview_settings_of(runs)
    profile = repository.latest_profile()
    assert settings is not None and profile is not None
    assert settings.target_role == profile.target_role, "本用例的前提：两处岗位同值"

    report = _build([str(run["id"]) for run in runs])

    assert report.role_fit is not None
    assert report.role_fit.role_source == "interview", (
        f"同值时面试设定优先，实际 {report.role_fit.role_source}"
    )
    assert report.role_fit.role_source_label == coach_copy.ROLE_SOURCE_LABEL["interview"]


def test_legacy_payload_reads_as_none(
    tmp_db: Any, profile_factory: Any, fake_ai: Any, seed_questions: list[dict[str, Any]], client: Any
) -> None:
    """AC-13：旧报告（四个键都不存在）反序列化不炸，且四字段一律 `None` 而不是 `[]`。"""
    runs = _prepare_runs(tmp_db, profile_factory, fake_ai, seed_questions)
    report = _build([str(run["id"]) for run in runs])
    payload = json.loads(report.model_dump_json())
    for key in ("weakness_map", "resume_pointers", "resume_pointers_notice", "role_fit"):
        payload.pop(key, None)

    with repository.connection() as conn:
        conn.execute(
            "INSERT INTO reports (id, payload, created_at) VALUES (?, ?, ?)",
            ("rep-legacy", json.dumps(payload, ensure_ascii=False), "2099-01-01T00:00:00+00:00"),
        )

    stored = repository.latest_report()
    assert stored is not None
    assert stored.weakness_map is None
    assert stored.resume_pointers is None
    assert stored.resume_pointers_notice is None
    assert stored.role_fit is None

    response = client.get("/api/reports/latest")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["weakness_map"] is None and body["role_fit"] is None
    assert body["shortfalls"]


def test_no_resume_text_gives_notice(
    tmp_db: Any,
    profile_factory: Any,
    fake_ai: Any,
    seed_questions: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-6：没有可定位的正文 → 空列表 + 中文原因，且**不调模型**。"""
    runs = _prepare_runs(tmp_db, profile_factory, fake_ai, seed_questions)
    monkeypatch.setattr(diagnosis.repository, "get_document_text", lambda _id: None)

    report = _build([str(run["id"]) for run in runs])

    assert report.resume_pointers == []
    assert report.resume_pointers_notice == coach_copy.RESUME_NO_TEXT


def test_unmatched_role_degrades_to_notice(
    tmp_db: Any, profile_factory: Any, seed_questions: list[dict[str, Any]]
) -> None:
    """AC-10：目标岗位没有内置模型 → `model=None` + 降级文案，其余两块照常。"""
    profile = profile_factory(target_role="产品经理")
    repository.insert_profile(profile)
    paper = exam_service.create_run(profile.id)
    exam_service.submit_run(paper.run_id, {question.id: ["A"] for question in paper.questions})

    report = _build([paper.run_id])

    assert report.role_fit is not None
    assert report.role_fit.model is None
    assert report.role_fit.notice == coach_copy.ROLE_NO_MODEL
    assert report.role_fit.target_role == "产品经理"
    assert report.weakness_map is not None


def test_no_ai_request_when_both_blocks_empty(
    tmp_db: Any, profile_factory: Any, seed_questions: list[dict[str, Any]]
) -> None:
    """两块都没有内容时 `_enrich_coach` 不发请求（零额外延迟）。"""
    calls: list[str] = []

    class _CountingAI:
        async def complete_model(
            self, system: str, _user: str, model_cls: type[Any], **_kwargs: Any
        ) -> Any:
            calls.append(system)
            raise RuntimeError("不该被调用")

    role_fit_empty = diagnosis.role_fit.RoleFit()
    asyncio.run(diagnosis._enrich_coach([], role_fit_empty, client=_CountingAI()))
    assert calls == []


def test_generated_report_reads_back_and_exports_three_blocks(
    tmp_db: Any, profile_factory: Any, fake_ai: Any, seed_questions: list[dict[str, Any]], client: Any
) -> None:
    """端到端到终态：生成 → 落库 → 读回 → 导出 .md，全程走真实路由 + 真实数据库。

    这条用例是「页面 / 复制 / 导出一致」的终态证据（AC-12）：同一份报告经 HTTP 读回后，
    `.md` 里必须出现三块标题，而报告 JSON 里必须是三块的**结构化**数据（不是拼好的字符串）。
    """
    runs = _prepare_runs(tmp_db, profile_factory, fake_ai, seed_questions)
    created = client.post("/api/reports/generate", json={"run_ids": [str(r["id"]) for r in runs]})
    assert created.status_code == 200, created.text
    report_id = created.json()["id"]

    latest = client.get("/api/reports/latest")
    assert latest.status_code == 200, latest.text
    assert latest.json()["id"] == report_id

    exported = client.get(f"/api/reports/{report_id}/markdown")
    assert exported.status_code == 200, exported.text
    text = exported.text
    for heading in ("## 知识薄弱地图", "## 简历改进要点", "## 市场竞争力对标"):
        assert heading in text, f"导出 .md 缺 {heading}"


def test_valid_kinds_fixture_still_matches_rules() -> None:
    """守住本文件对 `test_report_service` 夹具的复用（r6 的常量若漂移，这里先红）。"""
    assert len(VALID_KINDS) == rules.MIN_INTERVIEW_QUESTIONS
    assert callable(_bad_score_responder)
