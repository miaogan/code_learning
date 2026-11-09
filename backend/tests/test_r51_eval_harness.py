"""r51 评测日志 / 题目检索门禁：零网络、零 Key，全部走 `tmp_db`。

覆盖三条硬约束：
- 指标分母写死（成功率 / p50 / p95 / 失败分类），且按 user_id 隔离；
- 日志落库 best-effort，写库异常绝不改变 AI 主链路；
- 题目检索永不回传 answer，FTS5 不可用时降级为 LIKE 且给中文提示。
"""

import logging
import re
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.core import db, repository
from app.main import app
from app.services.ai import ai as ai_module


def _log(kind: str, elapsed_ms: int, *, model: str = "m1") -> None:
    repository.insert_ai_call_log(
        provider="test", model=model, kind=kind, elapsed_ms=elapsed_ms
    )


def test_init_db_is_idempotent_with_r51_tables(tmp_db) -> None:
    db.init_db()
    with repository.connection() as conn:
        names = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    assert "ai_call_logs" in names


def test_summary_metric_definitions(tmp_db) -> None:
    for index, latency in enumerate((100, 200, 300, 400, 500)):
        _log("success" if index < 4 else "timeout", latency)
    result = repository.ai_call_log_summary(7)
    assert result["total"] == 5
    assert result["success_rate"] == 0.8
    assert result["p50_ms"] == 300
    assert result["p95_ms"] == 500
    assert result["by_kind"] == {"success": 4, "timeout": 1}
    assert result["by_model"]["m1"]["success_rate"] == 0.8
    assert result["by_model"]["m1"]["p95_ms"] == 500
    assert result["trend"][0]["total"] == 5
    assert result["notice"] == ""


def test_empty_window_has_chinese_notice(tmp_db) -> None:
    result = repository.ai_call_log_summary()
    assert result["total"] == 0
    assert "暂无" in result["notice"]
    assert result["trend"] == []


def test_summary_is_scoped_to_current_user(tmp_db, monkeypatch) -> None:
    monkeypatch.setattr(repository, "_uid", lambda: "alice")
    _log("success", 100, model="alice-model")
    monkeypatch.setattr(repository, "_uid", lambda: "bob")
    _log("timeout", 200, model="bob-model")
    result = repository.ai_call_log_summary()
    assert result["total"] == 1
    assert list(result["by_model"]) == ["bob-model"]


def test_persist_failure_is_best_effort(tmp_db, monkeypatch, caplog) -> None:
    def boom(**_kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(repository, "insert_ai_call_log", boom)
    with caplog.at_level(logging.WARNING):
        ai_module._persist_call_log(
            SimpleNamespace(provider="test", model="test-model"), kind="success"
        )
    assert "ai.log.persist_failed" in caplog.text


def test_summary_endpoint_requires_login(tmp_db) -> None:
    with TestClient(app) as unauthenticated:
        response = unauthenticated.get("/api/eval/summary")
    assert response.status_code == 401


def test_summary_endpoint_contract(client) -> None:
    response = client.get("/api/eval/summary?days=7")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "window_days",
        "total",
        "success_rate",
        "p50_ms",
        "p95_ms",
        "by_kind",
        "by_model",
        "trend",
        "notice",
    }
    assert body["window_days"] == 7
    assert "暂无" in body["notice"]


def test_summary_endpoint_rejects_bad_window(client) -> None:
    response = client.get("/api/eval/summary?days=0")
    assert response.status_code == 422
    assert "error" in response.json()


def test_search_endpoint_never_exposes_answer(client, seed_questions) -> None:
    token = re.sub(r"[^一-鿿A-Za-z0-9]", "", str(seed_questions[0]["prompt"]))[:6]
    response = client.post("/api/search/questions", json={"query": token, "limit": 3})
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"items", "total", "mode", "notice"}
    assert body["mode"] in {"fts5", "like"}
    for item in body["items"]:
        assert set(item) == {
            "question_id",
            "prompt",
            "direction",
            "sub_direction",
            "score",
        }


def test_search_dirty_filters_are_silently_ignored(client) -> None:
    response = client.post(
        "/api/search/questions",
        json={
            "query": "索引",
            "direction": "不存在的方向",
            "sub_direction": "脏值",
            "limit": 3,
        },
    )
    assert response.status_code == 200
    assert response.json()["total"] >= 0


def test_short_query_degrades_to_like(client) -> None:
    body = client.post("/api/search/questions", json={"query": "ab"}).json()
    assert body["mode"] == "like"
    assert "全文索引" in body["notice"]


def test_missing_virtual_table_degrades_to_like(client, monkeypatch) -> None:
    monkeypatch.setattr(repository, "_question_search_table_exists", lambda _conn: False)
    body = client.post("/api/search/questions", json={"query": "索引"}).json()
    assert body["mode"] == "like"
    assert body["notice"]


def test_fts_rebuild_tolerates_environment(client, seed_questions) -> None:
    mode, rows = repository.rebuild_question_search()
    assert mode in {"fts5", "like"}
    assert rows == (len(seed_questions) if mode == "fts5" else 0)
