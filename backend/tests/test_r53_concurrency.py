"""r53 并发写锁与日志保留期：把 PERF-REPORT 的实测结论变成回归门禁。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

from app.core import db, repository

WORKERS = 8
PER_WORKER = 50


def test_busy_timeout_effective_on_every_connection(tmp_db) -> None:
    """每条连接都要带 busy_timeout：`connect(timeout=)` 与 PRAGMA 双保险。"""
    with db.connection() as conn:
        row = conn.execute("PRAGMA busy_timeout").fetchone()
    assert row is not None
    assert row[0] == db.BUSY_TIMEOUT_MS == 3000


def test_concurrent_ai_log_writes_have_no_lock_failures(tmp_db) -> None:
    """8 线程 × 50 次短事务：无 busy_timeout 时基准成功率仅 28.2%，这里必须 100%。"""
    def write(index: int) -> str:
        try:
            repository.insert_ai_call_log(
                provider="r53-test",
                model="bench-model",
                kind="success",
                elapsed_ms=index % 100,
            )
        except Exception as exc:  # noqa: BLE001 - 基准要统计失败类型而非中断
            return f"{type(exc).__name__}: {exc}"
        return "ok"

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        results = list(pool.map(write, range(WORKERS * PER_WORKER)))
    failures = [item for item in results if item != "ok"]
    assert failures == [], f"并发写出现锁失败：{failures[:5]}"
    assert repository.ai_call_log_summary(90)["total"] == WORKERS * PER_WORKER


def test_prune_removes_only_expired_logs(tmp_db) -> None:
    """保留期清理只删窗口外行；今天的日志一条都不能少。"""
    old = (datetime.now(UTC) - timedelta(days=200)).isoformat()
    repository.insert_ai_call_log(
        provider="r53-old", model="m", kind="success", elapsed_ms=1, created_at=old
    )
    repository.insert_ai_call_log(
        provider="r53-fresh", model="m", kind="timeout", elapsed_ms=2
    )
    assert repository.ai_call_log_summary(90)["total"] == 1
    assert repository.prune_ai_call_logs() == 1
    assert repository.ai_call_log_summary(90)["total"] == 1
    assert repository.prune_ai_call_logs() == 0


def test_prune_clamps_dirty_days_and_keeps_today(tmp_db) -> None:
    """脏参数夹紧到 [1, 365]，不会把刚写入的日志误删。"""
    repository.insert_ai_call_log(provider="r53", model="m", kind="success", elapsed_ms=1)
    assert repository.prune_ai_call_logs(days=0) == 0
    assert repository.prune_ai_call_logs(days=-99) == 0
    assert repository.prune_ai_call_logs(days=99999) == 0
    assert repository.ai_call_log_summary(90)["total"] == 1


def test_create_session_triggers_log_retention(tmp_db) -> None:
    """登录收口点顺带清理日志表（与 sessions 清理同一处）。"""
    old = (datetime.now(UTC) - timedelta(days=200)).isoformat()
    repository.insert_ai_call_log(
        provider="r53-old", model="m", kind="success", elapsed_ms=1, created_at=old
    )
    expires = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    repository.create_session(token_hash="r53-token", user_id="r53-user", expires_at=expires)
    assert repository.prune_ai_call_logs() == 0
