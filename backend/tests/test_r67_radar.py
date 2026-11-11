"""r67 技术雷达测试：离线采集、只进练习池、自检丢弃、任务幂等、采纳/废弃互斥、排程跨日。"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core import context, db, repository
from app.core.config import get_settings
from app.core.errors import AppError
from app.services import radar
from app.services.ai import user_ai
from app.services.assessment import question_bank
from app.services.radar import jobs, rules, schedule, sources, store

#: 内置样本落点：`backend/seed/radar_samples.json`（`backend/tests/` → 上溯 1 级到 `backend/`）。
SEED_PATH = Path(__file__).resolve().parents[1] / "seed" / "radar_samples.json"

CHAPTER_BODY = "这是正文段落，用于说明这项技术解决什么问题以及最小上手路径。"
EXPLANATION = "该选项与题干描述一致，其余选项与快照给出的信息相矛盾。"


def _question(*, kind: str = "single", answer: list[str] | None = None) -> dict[str, Any]:
    return {
        "kind": kind,
        "difficulty": "basic",
        "essentiality": "advanced",
        "prompt": "以下关于这项技术的描述，哪一项最符合快照给出的信息？",
        "options": [
            {"key": "A", "text": "它解决的是模型推理吞吐问题"},
            {"key": "B", "text": "它只用于前端渲染"},
            {"key": "C", "text": "它要求替换掉操作系统"},
        ],
        "answer": answer if answer is not None else ["A"],
        "explanation": EXPLANATION,
    }


def _judge_question() -> dict[str, Any]:
    """判断题只允许两个选项（`clean_question` 的硬要求），否则会被自检丢弃。"""
    return {
        "kind": "judge",
        "difficulty": "basic",
        "essentiality": "advanced",
        "prompt": "这项技术的主要用途是提升推理吞吐。",
        "options": [
            {"key": "A", "text": "正确"},
            {"key": "B", "text": "错误"},
        ],
        "answer": ["A"],
        "explanation": EXPLANATION,
    }


def _responder(_model_cls: type[Any], _user: str) -> dict[str, Any]:
    """三题里只有一题该被丢弃（答案键 `D` 不在选项里），另两题必须通过自检。"""
    return {
        "chapter": {
            "title": "新技术的入门草稿",
            "summary": "一句话概括",
            "level": "intermediate",
            "sections": [
                {"title": "这是什么", "body": CHAPTER_BODY, "bullets": ["要点一"]},
                {"title": "什么时候用", "body": CHAPTER_BODY, "bullets": ["要点二"]},
            ],
        },
        "questions": [_question(), _question(answer=["D"]), _judge_question()],
    }


@pytest.fixture()
def radar_env(monkeypatch: pytest.MonkeyPatch, tmp_db: Any) -> None:
    """离线 + 关排程 + 不做模型细化：采集用例零网络、零时序依赖。"""
    monkeypatch.setenv("RADAR_OFFLINE", "1")
    monkeypatch.setenv("RADAR_SCHEDULE", "off")
    monkeypatch.setenv("RADAR_MAX_ASSESS_PER_ROUND", "0")
    get_settings.cache_clear()
    db.init_db()


@pytest.fixture()
def fake_radar_ai(monkeypatch: pytest.MonkeyPatch) -> None:
    """所有 `client_for` 一律给零网络替身（模型细化与样例生成共用同一份 responder）。"""

    class _Fake:
        async def complete_model(self, _system: str, _user: str, model_cls: type[Any],
                                 **_kwargs: Any) -> Any:
            return model_cls.model_validate(_responder(model_cls, _user))

    monkeypatch.setattr(user_ai, "client_for", lambda user, tier: _Fake())


def _wait_job(client: TestClient, job_id: str, timeout_s: float = 3.0) -> dict[str, Any]:
    """轮询到终态（后台任务在 TestClient 的事件循环里跑，通常是毫秒级）。"""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        body = client.get(f"/api/radar/jobs/{job_id}").json()
        if body["status"] in ("succeeded", "failed", "adopted", "discarded"):
            return body
        time.sleep(0.05)
    raise AssertionError(f"任务未在 {timeout_s}s 内结束：{body}")


def test_offline_round_lands_techs(radar_env: None) -> None:
    summary = asyncio.run(radar.run_round(trigger="manual", user=None))
    assert summary["techs_seen"] >= 10
    assert "离线模式" in summary["notice"]
    rows = store.list_techs(100)
    assert len(rows) >= 10
    assert all(row["verdict"] in rules.VERDICTS for row in rows)
    assert any(row["star_delta_7d"] == 0 for row in rows)  # 首轮无上一份快照


def test_techs_api_filters_and_paginates(client: TestClient, radar_env: None) -> None:
    """清单接口：结论/方向筛选与列表同口径，`total` 是命中数而不是本页条数。"""
    asyncio.run(radar.run_round(trigger="manual", user=None))
    full = client.get("/api/radar/techs", params={"limit": 100}).json()
    assert full["total"] >= len(full["items"]) >= 10

    verdict = full["items"][0]["verdict"]
    by_verdict = client.get(
        "/api/radar/techs", params={"limit": 100, "verdict": verdict}
    ).json()
    assert by_verdict["total"] == len(by_verdict["items"])
    assert by_verdict["total"] >= 1
    assert all(row["verdict"] == verdict for row in by_verdict["items"])

    direction = next(row["direction"] for row in full["items"] if row["direction"])
    by_direction = client.get(
        "/api/radar/techs", params={"limit": 100, "direction": direction}
    ).json()
    assert by_direction["total"] >= 1
    assert all(row["direction"] == direction for row in by_direction["items"])

    second = client.get("/api/radar/techs", params={"limit": 1, "page": 2}).json()
    assert [row["tech_slug"] for row in second["items"]] == [full["items"][1]["tech_slug"]]

    out_of_range = client.get("/api/radar/techs", params={"limit": 100, "page": 99}).json()
    assert out_of_range["items"] == []

    bad_verdict = client.get("/api/radar/techs", params={"verdict": "not-a-verdict"})
    assert bad_verdict.status_code == 400
    bad_direction = client.get("/api/radar/techs", params={"direction": "不存在的方向"})
    assert bad_direction.status_code == 400


def test_exam_pool_excludes_radar_questions(radar_env: None) -> None:
    radar_question = {
        "id": "radar-test-q1",
        "direction": "AI 工程",
        "sub_direction": "",
        "kind": "single",
        "difficulty": "basic",
        "essentiality": "advanced",
        "prompt": "雷达生成的题目只应出现在练习池里，不应进入笔试卷面。",
        "options": [{"key": "A", "text": "对"}, {"key": "B", "text": "错"}],
        "answer": ["A"],
        "source": "radar",
        "language": "",
        "explanation": EXPLANATION,
    }
    repository.insert_questions([radar_question])
    ids_all = {row["id"] for row in question_bank.load_questions()}
    ids_exam = {row["id"] for row in question_bank.exam_pool()}
    ids_practice = {row["id"] for row in question_bank.practice_pool()}
    assert "radar-test-q1" in ids_all
    assert "radar-test-q1" not in ids_exam
    assert "radar-test-q1" in ids_practice


def test_manual_then_generate_then_adopt_only_practice(
    client: TestClient, radar_env: None, fake_radar_ai: None
) -> None:
    manual = client.post(
        "/api/radar/manual",
        json={"name": "离线演示技术", "url": "https://example.test/tech", "summary": "演示用"},
    )
    assert manual.status_code == 200, manual.text
    slug = manual.json()["tech_slug"]
    assert manual.json()["verdict_label"]

    accepted = client.post("/api/radar/generate", json={"tech_slug": slug})
    assert accepted.status_code == 200, accepted.text
    job = _wait_job(client, accepted.json()["job_id"])
    assert job["status"] == "succeeded", job
    assert job["chapter"]["id"].startswith(f"radar-{job['job_id']}-chapter")
    assert job["discarded_count"] == 1  # 答案键不在选项里的那条被自检丢弃
    assert len(job["questions"]) == 2

    adopted = client.post(f"/api/radar/jobs/{job['job_id']}/adopt")
    assert adopted.status_code == 200, adopted.text
    assert adopted.json()["status"] == "adopted"
    ids_practice = {row["id"] for row in question_bank.practice_pool()}
    ids_exam = {row["id"] for row in question_bank.exam_pool()}
    for sample in job["questions"]:
        assert sample["id"] in ids_practice
        assert sample["id"] not in ids_exam


def test_github_repo_url_is_normalized() -> None:
    """只有仓库链接才补元数据：用户主页 / issue / 非 github 链接一律返回空串。"""
    assert sources.github_full_name("https://github.com/HKUDS/LightRAG") == "HKUDS/LightRAG"
    assert sources.github_full_name("https://github.com/HKUDS/LightRAG.git") == "HKUDS/LightRAG"
    assert sources.github_full_name("https://github.com/HKUDS/LightRAG/tree/main") == "HKUDS/LightRAG"
    assert sources.github_full_name("https://github.com/HKUDS") == ""
    assert sources.github_full_name("https://example.test/HKUDS/LightRAG") == ""


def test_manual_github_url_uses_repo_metadata(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """粘贴 GitHub 仓库链接时补 star / 库龄：热门仓库不该再按 0 star 被判成「跳过」。"""
    monkeypatch.setenv("RADAR_OFFLINE", "0")
    monkeypatch.setenv("RADAR_SCHEDULE", "off")
    monkeypatch.setenv("RADAR_MAX_ASSESS_PER_ROUND", "0")
    get_settings.cache_clear()

    async def _fake_repo(full_name: str, _settings: Any = None) -> dict[str, Any] | None:
        assert full_name == "HKUDS/LightRAG"
        return sources._github_item(
            {
                "full_name": "HKUDS/LightRAG",
                "html_url": "https://github.com/HKUDS/LightRAG",
                "description": "Simple and Fast Retrieval-Augmented Generation",
                "topics": ["llm", "rag"],
                "stargazers_count": 40642,
                "forks_count": 5321,
                "created_at": "2024-10-02T06:14:44Z",
                "pushed_at": "2026-11-10T09:00:00Z",
            }
        )

    monkeypatch.setattr(sources, "fetch_repo", _fake_repo)
    response = client.post(
        "/api/radar/manual",
        json={"name": "LightRAG", "url": "https://github.com/HKUDS/LightRAG"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["tech_slug"] == "github:HKUDS/LightRAG"
    assert body["verdict"] != "skip"
    assert body["adoption"] >= 3


def test_manual_github_url_stays_offline_in_offline_mode(
    client: TestClient, radar_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """离线模式（AC-1）下即使粘贴仓库链接也不出网，按手工字段兜底。"""

    async def _no_network(*_args: Any, **_kwargs: Any) -> dict[str, Any] | None:
        raise AssertionError("离线模式不应联网")

    monkeypatch.setattr(sources, "fetch_repo", _no_network)
    response = client.post(
        "/api/radar/manual",
        json={"name": "LightRAG", "url": "https://github.com/HKUDS/LightRAG"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["tech_slug"].startswith("manual:")


def test_create_job_reuses_active_row(radar_env: None) -> None:
    """复用逻辑在仓储层直测：接口层的后台任务太快，`queued/running` 窗口抓不稳。"""
    slug = "manual:reuse-demo"
    first_id, first_reused = store.create_job(slug)
    assert first_reused is False
    second_id, second_reused = store.create_job(slug)
    assert second_reused is True
    assert second_id == first_id


def test_create_job_blocks_other_user(radar_env: None) -> None:
    """别人正在生成的技术，当前账号不能拿到那个 job_id（读路径按账号隔离）。"""
    slug = "manual:occupied-demo"
    first_id, _ = store.create_job(slug)
    context.set_current_user_id("someone-else")
    try:
        with pytest.raises(ValueError):
            store.create_job(slug)
    finally:
        context.reset_current_user_id()
    assert store.get_job(first_id) is not None


def test_adopt_and_discard_are_mutually_exclusive(
    client: TestClient, radar_env: None, fake_radar_ai: None
) -> None:
    manual = client.post("/api/radar/manual", json={"name": "互斥测试技术"})
    slug = manual.json()["tech_slug"]
    job_id = client.post("/api/radar/generate", json={"tech_slug": slug}).json()["job_id"]
    _wait_job(client, job_id)
    adopted = client.post(f"/api/radar/jobs/{job_id}/adopt")
    assert adopted.status_code == 200
    discarded = client.post(f"/api/radar/jobs/{job_id}/discard")
    assert discarded.status_code == 409
    assert "不能废弃" in discarded.json()["error"]["message"]


def test_generate_unknown_tech_is_not_found(client: TestClient, radar_env: None) -> None:
    response = client.post("/api/radar/generate", json={"tech_slug": "github:no/such"})
    assert response.status_code == 404
    assert "技术不存在" in response.json()["error"]["message"]


def test_radar_requires_login(client: TestClient) -> None:
    client.cookies.clear()
    response = client.get("/api/radar/techs")
    assert response.status_code in (401, 403)


def test_next_run_at_cross_day() -> None:
    slots = schedule.parse_slots("08:00, 12:00, 18:00, bad")
    assert [slot.strftime("%H:%M") for slot in slots] == ["08:00", "12:00", "18:00"]
    late = datetime(2026, 11, 10, 20, 0, tzinfo=schedule.CN_TZ)
    assert schedule.next_run_at(late, slots) == "2026-11-11T08:00:00+08:00"
    noon = datetime(2026, 11, 11, 9, 30, tzinfo=schedule.CN_TZ)
    assert schedule.next_run_at(noon, slots) == "2026-11-11T12:00:00+08:00"
    assert schedule.next_run_at(late, []) is None


def test_job_requires_owner(client: TestClient, radar_env: None, fake_radar_ai: None) -> None:
    manual = client.post("/api/radar/manual", json={"name": "归属测试技术"})
    slug = manual.json()["tech_slug"]
    job_id = client.post("/api/radar/generate", json={"tech_slug": slug}).json()["job_id"]
    _wait_job(client, job_id)
    context.set_current_user_id("someone-else")
    try:
        assert store.get_job(job_id) is None
        with pytest.raises(AppError):
            jobs._require(job_id)
    finally:
        context.reset_current_user_id()


def test_previous_stars_reports_delta(radar_env: None) -> None:
    """第二次快照的 star 增量 = 本次 - 上一次（首条快照没有上一条，按 0 处理）。"""
    first = asyncio.run(
        radar.ingest_manual(
            {"name": "delta", "url": "https://example.test/delta", "stars": 0}, user=None
        )
    )
    slug = first["tech_slug"]
    assert first["star_delta_7d"] == 0
    store.upsert_tech(
        {
            "slug": slug, "name": "delta", "direction": "AI 工程", "sub_direction": "",
            "source_key": "manual", "url": "https://example.test/delta", "summary": "",
        }
    )
    store.insert_snapshot(
        {"slug": slug, "stars": 300, "forks": 0, "repo_created_at": "", "pushed_at": "",
         "suspect": False}
    )
    rows = [row for row in store.list_techs(100) if row["tech_slug"] == slug]
    assert rows and rows[0]["star_delta_7d"] == 300


def test_round_marks_degraded_when_one_source_fails(
    monkeypatch: pytest.MonkeyPatch, radar_env: None
) -> None:
    """单源失败不连坐（AC-2）：本轮仍落全部条目，来源面板逐源如实记账，轮次行记 degraded。"""
    monkeypatch.setenv("RADAR_OFFLINE", "0")
    get_settings.cache_clear()
    db.init_db()
    items = sources.load_samples()

    async def fake_fetch_all(_settings: Any = None, **_kwargs: Any) -> Any:
        return items, [
            {"source_key": "github", "status": "ok", "items": len(items), "latency_ms": 12,
             "message": ""},
            {"source_key": "arxiv", "status": "failed", "items": 0, "latency_ms": 8000,
             "message": "上游超时"},
        ], True

    monkeypatch.setattr(sources, "fetch_all", fake_fetch_all)
    summary = asyncio.run(radar.run_round(trigger="manual", user=None))
    assert summary["degraded"] is True
    assert "部分信息源本轮不可用" in summary["notice"]
    assert [row["status"] for row in summary["sources"]] == ["ok", "failed"]
    assert summary["techs_seen"] >= 10
    assert len(store.list_techs(100)) >= 10


def test_discard_writes_no_questions(client: TestClient, radar_env: None, fake_radar_ai: None) -> None:
    """废弃只改任务状态（AC-7）：题目不入练习池、章节不留档。"""
    manual = client.post("/api/radar/manual", json={"name": "废弃测试技术"})
    slug = manual.json()["tech_slug"]
    job_id = client.post("/api/radar/generate", json={"tech_slug": slug}).json()["job_id"]
    job = _wait_job(client, job_id)
    assert job["status"] == "succeeded"
    assert len(job["questions"]) == 2

    discarded = client.post(f"/api/radar/jobs/{job_id}/discard")
    assert discarded.status_code == 200, discarded.text
    assert discarded.json()["status"] == "discarded"
    ids_all = {row["id"] for row in question_bank.load_questions()}
    assert not any(question_id.startswith(f"radar-{job_id}") for question_id in ids_all)


def test_generate_failure_is_visible(
    client: TestClient, radar_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """生成失败落中文原因（AC-4），不会停在「生成中」。"""

    class _Boom:
        async def complete_model(self, *_args: Any, **_kwargs: Any) -> Any:
            raise RuntimeError("upstream down")

    monkeypatch.setattr(user_ai, "client_for", lambda _user, _tier: _Boom())
    manual = client.post("/api/radar/manual", json={"name": "失败样例技术"})
    slug = manual.json()["tech_slug"]
    job_id = client.post("/api/radar/generate", json={"tech_slug": slug}).json()["job_id"]
    job = _wait_job(client, job_id)
    assert job["status"] == "failed"
    assert "样例生成失败" in job["error_message"]


def test_stale_running_job_is_swept_to_failed(client: TestClient, radar_env: None) -> None:
    """卡死治理（AC-4）：读路径把超过阈值的 running 惰性清扫为 failed，并给中文原因。"""
    slug = "manual:stale-demo"
    job_id, _ = store.create_job(slug)
    stale = (datetime.now(UTC) - timedelta(minutes=40)).isoformat()
    with db.connection() as conn:
        conn.execute(
            "UPDATE radar_jobs SET status = 'running', created_at = ?, updated_at = ?"
            " WHERE job_id = ?",
            (stale, stale, job_id),
        )
    body = client.get(f"/api/radar/jobs/{job_id}").json()
    assert body["status"] == "failed"
    assert "生成中断" in body["error_message"]


def test_sample_file_shape() -> None:
    items = json.loads(SEED_PATH.read_text("utf-8"))["items"]
    assert len(items) == 20
    for item in items:
        assert item["source_key"] in sources.SOURCE_KEYS
        assert item["name"] and item["url"]


def test_fetch_all_tls_verify_switch(radar_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """`RADAR_INSECURE_TLS` 只作用于采集客户端：默认校验，显式打开才跳过（仅内网排障）。"""
    captured: dict[str, Any] = {}

    class _Stop(Exception):
        pass

    class _RecordingClient:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

        async def __aenter__(self) -> None:
            raise _Stop

        async def __aexit__(self, *_args: Any) -> bool:
            return False

    monkeypatch.setattr(sources.httpx, "AsyncClient", _RecordingClient)
    monkeypatch.setenv("RADAR_OFFLINE", "0")
    monkeypatch.setenv("RADAR_INSECURE_TLS", "false")
    get_settings.cache_clear()
    with pytest.raises(_Stop):
        asyncio.run(sources.fetch_all())
    assert captured["verify"] is True

    monkeypatch.setenv("RADAR_INSECURE_TLS", "true")
    get_settings.cache_clear()
    with pytest.raises(_Stop):
        asyncio.run(sources.fetch_all())
    assert captured["verify"] is False


def test_is_due_after_restart(radar_env: None) -> None:
    """重启补跑只看「上一轮是否早于最近一个已到的时点」：早于 → 补跑；已跑过 → 不重复。"""
    slots = schedule.parse_slots("08:00")
    now = datetime(2026, 11, 10, 9, 0, tzinfo=UTC)  # 东八区 17:00
    assert schedule.is_due("", now, slots) is True  # 从未跑过
    assert schedule.is_due((now - timedelta(hours=10)).isoformat(), now, slots) is True  # 07:00
    assert schedule.is_due((now - timedelta(minutes=5)).isoformat(), now, slots) is False


def test_round_with_direction_filters_items(radar_env: None) -> None:
    """指定方向只保留该方向条目；方向没有样本时如实提示，不伪造条目。"""
    summary = asyncio.run(radar.run_round(trigger="manual", user=None, direction="SQL 与数据库"))
    assert summary["techs_seen"] == 2
    assert "SQL 与数据库" in summary["notice"]
    assert all(row["direction"] == "SQL 与数据库" for row in store.list_techs(100))

    empty = asyncio.run(radar.run_round(trigger="manual", user=None, direction="前端"))
    assert empty["techs_seen"] == 0
    assert "没有匹配到条目" in empty["notice"]


def test_fetch_all_with_repo_reads_single_repository(
    radar_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """指定仓库就只跑一次 `GET /repos/{owner}/{repo}`，不扫其他来源。"""
    monkeypatch.setenv("RADAR_OFFLINE", "0")
    get_settings.cache_clear()

    async def _fake_repo(full_name: str, _settings: Any = None) -> dict[str, Any] | None:
        assert full_name == "HKUDS/LightRAG"
        return sources._github_item(
            {
                "full_name": "HKUDS/LightRAG",
                "html_url": "https://github.com/HKUDS/LightRAG",
                "description": "Simple and Fast Retrieval-Augmented Generation",
                "topics": ["llm", "rag"],
                "stargazers_count": 40642,
                "forks_count": 5321,
                "created_at": "2024-10-02T06:14:44Z",
                "pushed_at": "2026-11-10T09:00:00Z",
            }
        )

    monkeypatch.setattr(sources, "fetch_repo", _fake_repo)
    items, status, degraded = asyncio.run(sources.fetch_all(repo="HKUDS/LightRAG"))
    assert len(items) == 1
    assert items[0]["slug"] == "github:HKUDS/LightRAG"
    assert status[0]["source_key"] == "github"
    assert degraded is False


def test_run_api_accepts_repo_and_direction(
    client: TestClient, radar_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`POST /run` 带 `repo` 时只采该仓库；非法方向 / 仓库地址按 400 挡住（不落空轮次）。"""
    monkeypatch.setenv("RADAR_OFFLINE", "0")
    get_settings.cache_clear()

    async def _fake_repo(full_name: str, _settings: Any = None) -> dict[str, Any] | None:
        assert full_name == "HKUDS/LightRAG"
        return sources._github_item(
            {
                "full_name": "HKUDS/LightRAG",
                "html_url": "https://github.com/HKUDS/LightRAG",
                "description": "Simple and Fast Retrieval-Augmented Generation",
                "topics": ["llm", "rag"],
                "stargazers_count": 40642,
                "forks_count": 5321,
                "created_at": "2024-10-02T06:14:44Z",
                "pushed_at": "2026-11-10T09:00:00Z",
            }
        )

    monkeypatch.setattr(sources, "fetch_repo", _fake_repo)
    response = client.post(
        "/api/radar/run", json={"repo": "https://github.com/HKUDS/LightRAG", "direction": "AI 工程"}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["techs_seen"] == 1
    assert "HKUDS/LightRAG" in body["notice"]

    bad_direction = client.post("/api/radar/run", json={"direction": "区块链"})
    assert bad_direction.status_code == 400
    assert "方向" in bad_direction.json()["error"]["message"]

    bad_repo = client.post("/api/radar/run", json={"repo": "https://github.com/HKUDS"})
    assert bad_repo.status_code == 400
    assert "仓库" in bad_repo.json()["error"]["message"]


def test_run_api_without_body_keeps_default_round(client: TestClient, radar_env: None) -> None:
    """老调用（不带请求体）仍是全源默认轮次，不需要前端同步改造。"""
    response = client.post("/api/radar/run")
    assert response.status_code == 200, response.text
    assert response.json()["techs_seen"] >= 10
