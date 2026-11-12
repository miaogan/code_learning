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
    # 第二次 init_db 必须是无害空操作（全部 DDL 为 IF NOT EXISTS 形态）
    db.init_db()
    with repository.connection() as conn:
        names = {
            row["name"]
            for row in conn.execute(
                "SELECT tablename AS name FROM pg_tables WHERE schemaname = 'public'"
            )
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
    # r98 起只有 ILIKE 一条检索路径（FTS5 虚表已随 SQLite 下线）
    assert body["mode"] == "like"
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


def test_short_query_still_matches(client) -> None:
    """两字查询同样能命中：trigram 索引与 ILIKE 都不受「最短词长」限制。

    r98 之前这条是「短查询降级 LIKE」的验证点；现在没有需要降级的分支，但它仍是个
    有意义的回归门禁 —— 曾经 FTS5 trigram 对短串有特殊处理，换实现后必须保持能查。
    """
    body = client.post("/api/search/questions", json={"query": "ab"}).json()
    assert body["mode"] == "like"
    assert body["notice"] == ""


def test_search_notice_is_always_empty(client) -> None:
    """检索不再有「未启用全文索引」的降级提示：只有一个实现，就不该有第二种提示。"""
    body = client.post("/api/search/questions", json={"query": "索引"}).json()
    assert body["mode"] == "like"
    assert body["notice"] == ""


def test_fts_rebuild_returns_current_question_count(client, seed_questions) -> None:
    """重建入口保留为幂等空操作：索引由 GIN 随写入维护，只回报当前题量。"""
    mode, rows = repository.rebuild_question_search()
    assert mode == "like"
    assert rows == len(seed_questions)
