"""PostgreSQL / Redis 故障：完整 SQLite 副本接管读写，恢复后重放并回切。

测试使用会话级临时副本，不接触开发数据。SQLite 只接受带 complete 标记的
持久化副本；首次故障且没有副本时仍给明确的可重试错误，不伪造空业务数据。
"""

from __future__ import annotations

import asyncio
import sqlite3
import threading
import time
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from app import admin_cli
from app.core import db, redis_cache, repository
from app.core.auth import COOKIE_NAME, new_session_token, session_expiry
from app.core.config import get_settings
from app.core.errors import AppError
from app.main import _RECOVERY_BACKOFF_CAP_S, _backoff_delay, _exc_brief, _recover_database, app
from app.schemas import Profile, Report, ResumeMeta
from app.services.retrieval import indexer
from app.services.retrieval.hybrid import search_chunks


@pytest.fixture()
def unavailable_dependencies(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """依赖不可达且副本不存在：绝不复用其他用例已同步好的 SQLite 文件。"""
    monkeypatch.setenv("DATABASE_URL", "postgresql://postgres:postgres@127.0.0.1:1/sc_app")
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")
    monkeypatch.setenv("DB_RECOVERY_INTERVAL_S", "0.05")
    # r114：宽限期决定「要不要等 PG 才建单机库」。用例本身在验判定逻辑，
    # 不该真等 15s；真实宽限期的行为由 test_db_standalone 的日志断言覆盖。
    monkeypatch.setenv("DB_STANDALONE_GRACE_S", "0")
    monkeypatch.setenv("RADAR_SCHEDULE", "off")
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "no-replica" / "fallback.db"))
    get_settings.cache_clear()
    db.close_pool()
    # 环境已指向不存在的副本：重算 replica_ready，避免沿用上一个用例同步好的状态。
    db.reset_runtime()
    redis_cache.reset_client()
    yield
    db.close_pool()
    redis_cache.reset_client()
    get_settings.cache_clear()


@pytest.fixture()
def replica(tmp_db: str) -> Iterator[str]:
    """建立含当前用例历史数据的完整副本；每个用例都有独立文件。"""
    db.sync_sqlite_from_pg()
    assert db.runtime_state()["replica_ready"] is True
    yield tmp_db


@pytest.fixture()
def isolated_replica(
    tmp_db: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[str]:
    """独立副本文件：损坏类用例不能把会话级共享副本一起写坏。"""
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "isolated" / "fallback.db"))
    get_settings.cache_clear()
    db.close_pool()
    db.reset_runtime()
    db.sync_sqlite_from_pg()
    assert db.runtime_state()["replica_ready"] is True
    yield str(tmp_path / "isolated" / "fallback.db")


def _activate_sqlite() -> None:
    db.activate_sqlite()
    assert db.active_backend() == "sqlite"


def _recover() -> None:
    with db.recovery():
        db.init_db()
        db.replay_pending()
        db.sync_sqlite_from_pg()
        db.activate_postgresql()


def _question(question_id: str, prompt: str) -> dict[str, Any]:
    return {
        "id": question_id,
        "direction": "sql",
        "sub_direction": "postgresql",
        "kind": "single",
        "difficulty": "basic",
        "essentiality": "must_know",
        "prompt": prompt,
        "options": [{"key": "A", "text": "使用索引"}],
        "answer": ["A"],
        "source": "seed",
        "language": "sql",
        "explanation": "通过执行计划定位慢查询原因。",
    }


def _user(user_id: str) -> None:
    repository.create_user(
        user_id=user_id,
        email=f"{user_id}@example.com",
        password_hash="not-a-real-password-hash",
        display_name="离线测试用户",
        role="member",
        key_mode="own",
    )


def _create_radar_run() -> int:
    run_id = repository.radar_create_run("offline-test")
    item = {
        "slug": "offline-repo",
        "name": "Offline Repo",
        "direction": "ai",
        "sub_direction": "agent",
        "source_key": "test",
        "url": "https://example.com/offline-repo",
        "summary": "用于验证离线写入的样本",
    }
    repository.radar_upsert_tech(item)
    repository.radar_insert_snapshot({**item, "stars": 12, "forks": 2})
    assert repository.radar_insert_assessment(
        item["slug"],
        run_id,
        {
            "verdict": "watch",
            "relevance": 2,
            "adoption": 2,
            "maturity": 2,
            "effort": 2,
            "reasons": ["离线评估"],
            "evidence": [],
        },
        input_sha256=f"offline-{run_id}",
        profile_digest="test",
        prompt_version="test",
        model="rule",
        rule_based=True,
    )
    return run_id


def test_complete_replica_preserves_history_and_replays_offline_writes(
    replica: str, auth_user: dict[str, Any]
) -> None:
    repository.save_learn_progress("online", {"online": {"seen": ["before"], "updated_at": 1}})
    db.sync_sqlite_from_pg()
    _activate_sqlite()
    assert repository.get_user_by_id(auth_user["id"]) is not None
    assert repository.get_learn_progress()["last_chapter_id"] == "online"

    _user("offline-user")
    repository.create_session(
        token_hash="offline-session", user_id="offline-user", expires_at="2099-01-01T00:00:00+00:00"
    )
    repository.save_learn_progress(
        "offline-chapter",
        {"offline-chapter": {"seen": ["s1", "s2"], "last_section_id": "s2", "updated_at": 2}},
    )
    assert repository.insert_question(_question("offline-q1", "SQLite 如何定位慢查询？"))
    assert repository.search_questions("慢查询")["total"] == 1
    run_id = _create_radar_run()
    assert repository.radar_latest_run()["run_id"] == run_id
    operations = db.pending_operations()
    assert len(operations) >= 10
    assert all(operation["op_id"] for operation in operations)

    _recover()
    assert db.active_backend() == "postgresql"
    assert repository.get_user_by_id("offline-user") is not None
    assert repository.get_session("offline-session")["user_id"] == "offline-user"
    assert repository.get_learn_progress()["chapters"]["offline-chapter"]["seen"] == ["s1", "s2"]
    assert repository.search_questions("慢查询")["total"] == 1
    assert repository.radar_previous_stars("offline-repo") == 12
    assert repository.radar_latest_run()["run_id"] == run_id
    assert db.pending_operations() == []


def test_sqlite_rag_json_vectors_feedback_and_replay(replica: str) -> None:
    repository.insert_question(_question("rag-q1", "数据库慢查询如何排查？"))
    indexer.rebuild_question_index()
    db.sync_sqlite_from_pg()
    _activate_sqlite()

    assert repository.insert_question(
        _question("rag-offline", "RAG 向量如何离线重建索引并回同步？")
    )
    rebuilt = indexer.rebuild_question_index()
    assert rebuilt["written"] == 2
    ingested = indexer.ingest_tutorial_chunks([
        {
            "chapter_id": "offline-guide",
            "section_id": "replica",
            "title": "SQLite 离线副本",
            "content": "离线业务行与操作日志必须在同一个事务中提交。",
        }
    ])
    assert ingested["written"] == 1
    assert ingested["tutorial_chunks"] == 1
    assert search_chunks(
        "离线业务行与操作日志", mode="keyword", kinds=["tutorial"]
    )["items"][0]["ref_id"] == "offline-guide"

    semantic = search_chunks("数据库慢查询", mode="semantic", top_k=3)
    assert semantic["engine"] == "python-cosine"
    assert semantic["items"][0]["ref_id"] == "rag-q1"
    feedback = repository.rag_feedback_upsert(
        query="数据库慢查询", chunk_id=semantic["items"][0]["chunk_id"], verdict="down", surface="search"
    )
    assert feedback["down"] == 1
    assert repository.rag_feedback_summary()["down"] == 1
    assert repository.rag_feedback_summary()["top_downvoted"]

    _recover()
    assert search_chunks("数据库慢查询", mode="hybrid", top_k=3)["items"]
    assert search_chunks("离线业务行与操作日志", mode="hybrid", kinds=["tutorial"])["items"]
    assert repository.get_question("rag-offline") is not None
    assert repository.rag_feedback_summary()["down"] == 1
    with psycopg.connect(replica) as raw:
        embeddings = raw.execute(
            "SELECT embedding FROM rag_chunks WHERE kind = 'tutorial'"
        ).fetchall()
        assert len(embeddings) == 1
        assert len(embeddings[0][0]) > 0


def _profile(profile_id: str = "offline-profile", resume_id: str = "offline-resume") -> Profile:
    from tests.conftest import DRAFT_PAYLOAD

    return Profile(
        id=profile_id,
        resume_id=resume_id,
        updated_at="2026-11-16T00:00:00+00:00",
        **DRAFT_PAYLOAD,
    )


def test_offline_business_write_paths_replay_without_dialect_drift(
    replica: str, auth_user: dict[str, Any]
) -> None:
    """覆盖非 RAG 的核心业务写入族，不调用外部 AI 或上传服务。"""
    db.sync_sqlite_from_pg()
    _activate_sqlite()

    meta = ResumeMeta(
        resume_id="offline-resume", file_name="offline.txt", chars=42, sections=3
    )
    repository.insert_document(meta, "离线简历正文", mime="text/plain")
    repository.insert_profile(_profile())
    repository.save_profile(_profile())
    assert repository.insert_profile_job("offline-profile-job", meta.resume_id, meta.file_name, 42, 3)
    assert not repository.insert_profile_job("offline-profile-job", meta.resume_id, meta.file_name, 42, 3)
    repository.finish_profile_job(
        "offline-profile-job", _profile().model_dump_json(), user_id="default"
    )
    assert repository.insert_resume_job("offline-resume-job", meta.file_name, 1, "offline-hash")
    repository.touch_resume_job("offline-resume-job", user_id="default")
    repository.finish_resume_job("offline-resume-job", meta.model_dump_json(), user_id="default")
    assert repository.expire_stale_resume_jobs(0) == 0

    repository.insert_run("offline-run", "exam", "offline-profile", {"questions": ["offline-q1"]})
    repository.save_run("offline-run", {"questions": ["offline-q1"], "total": 90}, "completed")
    repository.insert_report(
        Report(id="offline-report", shortfalls=[], generated_at="2026-11-16T00:00:00+00:00")
    )
    assert repository.insert_attempts([
        {
            "id": "offline-attempt",
            "question_id": "offline-q1",
            "run_id": "offline-run",
            "correct": 1,
            "answered_at": "2026-11-16T00:00:00+00:00",
            "source": "exam",
        }
    ]) == 1
    repository.save_plan_state("offline-report", 45, {"day-1": True}, "2026-11-16")
    repository.insert_taifu_message(role="user", content="离线问题")
    repository.insert_taifu_message(role="assistant", content="离线回答")
    repository.save_taifu_summary("离线摘要")
    memory = repository.insert_taifu_memory("偏好从实际项目学习")
    repository.delete_taifu_memory(memory["id"])
    repository.insert_taifu_memory("保留长期记忆")
    repository.save_coach_run(
        "offline-coach", question="如何学习事务？", goal="掌握事务",
        status="completed", steps=[{"kind": "plan"}], answer="先写测试",
        citations=[{"label": "教程", "href": "/learn"}],
    )

    assert repository.get_document(meta.resume_id)["text"] == "离线简历正文"
    assert repository.latest_profile().id == "offline-profile"
    assert repository.get_profile_job("offline-profile-job")["status"] == "completed"
    assert repository.get_resume_job("offline-resume-job")["status"] == "completed"
    assert repository.get_run("offline-run")["status"] == "completed"
    assert repository.latest_report().id == "offline-report"
    assert repository.list_attempts()[0]["correct"] == 1
    assert repository.get_plan_state("offline-report")["done"] == {"day-1": True}
    assert repository.get_taifu_summary() == "离线摘要"
    assert len(repository.list_taifu_memories()) == 1
    assert repository.coach_run_row("offline-coach")["answer"] == "先写测试"

    _recover()
    assert repository.get_document(meta.resume_id)["text"] == "离线简历正文"
    assert repository.latest_profile().id == "offline-profile"
    assert repository.get_profile_job("offline-profile-job")["status"] == "completed"
    assert repository.get_resume_job("offline-resume-job")["status"] == "completed"
    assert repository.get_run("offline-run")["status"] == "completed"
    assert repository.latest_report().id == "offline-report"
    assert repository.list_attempts()[0]["correct"] == 1
    assert repository.get_plan_state("offline-report")["done"] == {"day-1": True}
    assert repository.get_taifu_summary() == "离线摘要"
    assert [row["content"] for row in repository.list_taifu_memories()] == ["保留长期记忆"]
    assert repository.coach_run_row("offline-coach")["steps"] == [{"kind": "plan"}]
    assert db.pending_operations() == []


def test_redis_reconnect_serializes_replay_with_later_invalidation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BlockingRedis:
        def __init__(self) -> None:
            self.values = {"sc:session": '{"user_id":"default"}'}
            self.replayed = threading.Event()
            self.release = threading.Event()

        def delete(self, *names: str) -> int:
            deleted = 0
            for name in names:
                deleted += int(self.values.pop(name, None) is not None)
            return deleted

        def set(self, name: str, payload: str, *, ex: int) -> bool:
            self.replayed.set()
            assert self.release.wait(timeout=5)
            self.values[name] = payload
            return True

        def get(self, name: str) -> str | None:
            return self.values.get(name)

        def scan_iter(self, *, match: str, count: int) -> Iterator[str]:
            return iter(())

    fake = BlockingRedis()
    monkeypatch.setattr(redis_cache, "get_client", lambda: fake)
    redis_cache.reset_client()
    redis_cache.cache_set_json("sc:session", {"user_id": "default"}, ttl_s=60)
    redis_cache._mark_offline(ConnectionError("test reconnect"))
    errors: list[Exception] = []

    def replay() -> None:
        try:
            redis_cache._replay_memory_to_redis(fake)
        except Exception as exc:  # noqa: BLE001 - 跨线程转交断言
            errors.append(exc)

    worker = threading.Thread(target=replay)
    worker.start()
    assert fake.replayed.wait(timeout=2)
    deleted = threading.Event()

    def invalidate() -> None:
        redis_cache.cache_delete("sc:session")
        deleted.set()

    later = threading.Thread(target=invalidate)
    later.start()
    assert not deleted.wait(timeout=0.1), "回放期间不能让后续删除越过写回顺序"
    fake.release.set()
    worker.join(timeout=5)
    later.join(timeout=5)
    assert deleted.is_set()
    assert not errors
    assert fake.get("sc:session") is None
    assert redis_cache.cache_get_json("sc:session") is None


def test_redis_prefix_invalidation_preserves_later_memory_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeRedis:
        def __init__(self) -> None:
            self.values: dict[str, str] = {}

        def set(self, name: str, payload: str, *, ex: int) -> bool:
            self.values[name] = payload
            return True

        def get(self, name: str) -> str | None:
            return self.values.get(name)

        def delete(self, *names: str) -> int:
            return sum(int(self.values.pop(name, None) is not None) for name in names)

        def scan_iter(self, *, match: str, count: int) -> Iterator[str]:
            return iter(tuple(name for name in self.values if name.startswith(match[:-1])))

    fake = FakeRedis()
    monkeypatch.setattr(redis_cache, "get_client", lambda: fake)
    redis_cache.reset_client()
    redis_cache.cache_set_json("sc:report:one", {"version": "old"}, ttl_s=60)
    redis_cache.cache_delete_prefix("sc:report")
    redis_cache.cache_set_json("sc:report:one", {"version": "new"}, ttl_s=60)
    assert redis_cache.cache_get_json("sc:report:one") == {"version": "new"}
    assert fake.get("sc:report:one") == '{"version":"new"}'


def test_http_auth_sessions_do_not_revive_after_redis_reconnect(
    replica: str, auth_user: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.test_r98_redis import REDIS_TEST_URL

    monkeypatch.setenv("REDIS_URL", REDIS_TEST_URL)
    monkeypatch.setenv("REDIS_PREFIX", "sc-test-auth-outage")
    monkeypatch.setenv("RADAR_SCHEDULE", "off")
    get_settings.cache_clear()
    redis_cache.reset_client()
    client = redis_cache.get_client()
    if client is None:
        pytest.skip("未配置 Redis")
    try:
        client.ping()
    except Exception as exc:  # noqa: BLE001 - 环境能力探测
        pytest.skip(f"连不上 Redis（{type(exc).__name__}）")
    original = client.execute_command
    try:
        with TestClient(app) as current:
            other = TestClient(app)
            login = current.post(
                "/api/auth/login",
                json={"email": "member@example.com", "password": "test-password-123"},
            )
            assert login.status_code == 200, login.text
            raw, digest = new_session_token()
            repository.create_session(
                token_hash=digest, user_id="default", expires_at=session_expiry()
            )
            other.cookies.set(COOKIE_NAME, raw)
            assert current.get("/api/me").status_code == 200
            assert other.get("/api/me").status_code == 200  # 两个会话都进入 Redis

            def fail_redis(*args: Any, **kwargs: Any) -> Any:
                raise ConnectionError("simulated redis outage")

            monkeypatch.setattr(client, "execute_command", fail_redis)
            changed = current.patch(
                "/api/me/password",
                json={"old_password": "test-password-123", "new_password": "new-password-123"},
            )
            assert changed.status_code == 204, changed.text
            assert current.get("/api/me").status_code == 200
            assert other.get("/api/me").status_code == 401

            monkeypatch.setattr(client, "execute_command", original)
            assert client.get(repository._session_cache_name(digest)) is not None
            redis_cache._offline_until = 0.0
            assert redis_cache.status() == "up"
            assert client.get(repository._session_cache_name(digest)) is None
            assert other.get("/api/me").status_code == 401

            # 管理员停用走 CLI 而非 HTTP；重新启用后旧 Cookie 仍必须已撤销。
            assert admin_cli.main(["disable", "--email", "member@example.com"]) == 0
            assert current.get("/api/me").status_code == 401
            assert admin_cli.main(["disable", "--email", "member@example.com", "--undo"]) == 0
            assert current.get("/api/me").status_code == 401
            login = current.post(
                "/api/auth/login",
                json={"email": "member@example.com", "password": "new-password-123"},
            )
            assert login.status_code == 200, login.text
            assert current.post("/api/auth/logout").status_code == 204
            assert current.get("/api/me").status_code == 401
    finally:
        monkeypatch.undo()
        redis_cache.cache_delete_prefix(redis_cache.key(""))
        redis_cache.reset_client()
        get_settings.cache_clear()


def test_redis_deletion_barrier_outlives_ttl_until_replayed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.test_r98_redis import REDIS_TEST_URL

    monkeypatch.setenv("REDIS_URL", REDIS_TEST_URL)
    monkeypatch.setenv("REDIS_PREFIX", "sc-test-barrier")
    monkeypatch.setenv("SESSION_CACHE_TTL_S", "1")
    monkeypatch.setenv("READ_CACHE_TTL_S", "1")
    monkeypatch.setenv("MEMORY_CACHE_MAX_ENTRIES", "1")
    get_settings.cache_clear()
    redis_cache.reset_client()
    client = redis_cache.get_client()
    if client is None:
        pytest.skip("未配置 Redis")
    try:
        client.ping()
    except Exception as exc:  # noqa: BLE001 - 环境能力探测
        pytest.skip(f"连不上 Redis（{type(exc).__name__}）")
    name = redis_cache.key("sess", "long-outage")
    original = client.execute_command
    original_monotonic = time.monotonic
    try:
        redis_cache.cache_set_json(name, {"user_id": "default"}, ttl_s=60)

        def fail_redis(*args: Any, **kwargs: Any) -> Any:
            raise ConnectionError("simulated redis outage")

        monkeypatch.setattr(client, "execute_command", fail_redis)
        redis_cache.cache_delete(name)
        assert redis_cache._cache_sync_pending
        # 连续删除另一个 key，验证容量为 1 也不会挤掉未同步的安全屏障。
        redis_cache.cache_delete(redis_cache.key("sess", "other"))
        monkeypatch.setattr(redis_cache.time, "monotonic", lambda: original_monotonic() + 5)
        assert redis_cache._is_tombstoned(name)
        monkeypatch.setattr(client, "execute_command", original)
        redis_cache._offline_until = 0.0
        redis_cache._replay_memory_to_redis(client)
        assert client.get(name) is None
        assert not redis_cache._cache_sync_pending
        assert not redis_cache._TOMBSTONES
    finally:
        monkeypatch.undo()
        redis_cache.cache_delete_prefix(redis_cache.key(""))
        redis_cache.reset_client()
        get_settings.cache_clear()


def test_offline_transaction_rollback_keeps_data_and_log_atomic(replica: str) -> None:
    _activate_sqlite()
    before = db.pending_operations()
    with pytest.raises(RuntimeError, match="force rollback"), db.connection() as conn:
        with db.connection() as nested:
            assert nested is conn
            nested.execute(
                "INSERT INTO users (id, email, password_hash, display_name, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                ("rolled-back", "rolled-back@example.com", "hash", "回滚用户", "2026-01-01"),
            )
        raise RuntimeError("force rollback")
    assert db.pending_operations() == before
    assert repository.get_user_by_id("rolled-back") is None


def test_offline_integrity_error_does_not_commit_partial_log(replica: str) -> None:
    _activate_sqlite()
    _user("duplicate")
    before = len(db.pending_operations())
    with pytest.raises(db.IntegrityError):
        _user("duplicate")
    assert len(db.pending_operations()) == before
    assert len([user for user in repository.list_users() if user["id"] == "duplicate"]) == 1


def test_replay_failure_keeps_pending_and_does_not_return_to_sqlite(
    replica: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _activate_sqlite()
    _user("replay-retry")
    original = db._execute_raw
    failed = False

    def fail_once(raw: Any, backend: str, sql: str, params: Any = None) -> Any:
        nonlocal failed
        if backend == "postgresql" and sql.startswith("INSERT INTO users") and not failed:
            failed = True
            raise psycopg.OperationalError("simulated replay interruption")
        return original(raw, backend, sql, params)

    monkeypatch.setattr(db, "_execute_raw", fail_once)
    with pytest.raises(AppError):
        _recover()
    assert db.runtime_state()["ready"] is False
    assert db.pending_operations()
    _recover()
    assert repository.get_user_by_id("replay-retry") is not None
    assert db.pending_operations() == []


def test_replay_integrity_conflict_is_not_silently_dropped(replica: str) -> None:
    _activate_sqlite()
    _user("conflict-user")
    db.close_pool()
    with psycopg.connect(replica) as raw:
        raw.execute(
            "INSERT INTO users (id, email, password_hash, display_name, created_at) "
            "VALUES (%s, %s, %s, %s, %s)",
            ("other-user", "conflict-user@example.com", "other", "冲突账号", "2026-01-01"),
        )
    with pytest.raises(RuntimeError, match="约束冲突"):
        _recover()
    assert db.runtime_state()["ready"] is False
    assert db.pending_operations()
    assert db.active_backend() == "postgresql"


def test_replay_receipts_are_idempotent(replica: str) -> None:
    _activate_sqlite()
    _user("once-only")
    operations = db.pending_operations()
    first = db.replay_pending()
    assert first["replayed"] == len(operations)
    assert db.pending_operations() == []
    second = db.replay_pending()
    assert second == {"replayed": 0, "conflicts": 0}
    assert len([user for user in repository.list_users() if user["id"] == "once-only"]) == 1


def test_shared_radar_ids_do_not_reuse_online_values(replica: str) -> None:
    online_run = _create_radar_run()
    db.sync_sqlite_from_pg()
    _activate_sqlite()
    offline_run = _create_radar_run()
    assert offline_run > online_run
    _recover()
    assert _create_radar_run() > offline_run


def test_recovery_excludes_business_transactions(replica: str) -> None:
    entered = threading.Event()
    release = threading.Event()

    def slow_recovery() -> None:
        with db.recovery():
            entered.set()
            assert release.wait(timeout=5)

    worker = threading.Thread(target=slow_recovery)
    worker.start()
    assert entered.wait(timeout=2)
    blocked = threading.Event()

    def business_read() -> None:
        with db.connection() as conn:
            conn.execute("SELECT 1")
        blocked.set()

    reader = threading.Thread(target=business_read)
    reader.start()
    assert not blocked.wait(timeout=0.1)
    release.set()
    worker.join(timeout=5)
    reader.join(timeout=5)
    assert blocked.is_set()
    assert not worker.is_alive()
    assert not reader.is_alive()


def test_first_outage_without_replica_does_not_block_lifespan(
    unavailable_dependencies: None,
) -> None:
    """首次启动连不上 PG 且没有副本：不阻塞启动，自动落到 SQLite 单机库。

    r114 起此处行为变了：这正是「这台机器没有 PG」的典型场景，宽限期一过就建单机库
    （用户要的开箱能跑）。但**启动不能被那次等待卡住** —— lifespan 最多等 2.5s 就放流量。
    """
    started = time.monotonic()
    with TestClient(app) as client:
        body = client.get("/health").json()
        assert body["db"] == "sqlite"
        # 单机模式下没有「副本」这个概念
        assert body["db_replica"] == "na"
        business = client.post(
            "/api/auth/login", json={"email": "member@example.com", "password": "bad-password"}
        )
        # 库可用时登录失败是账号/口令问题（401/422），不该再是「数据服务不可用」
        assert business.status_code != 503
        assert "127.0.0.1" not in business.text
    assert time.monotonic() - started < 8.0


def test_outage_with_complete_replica_still_serves_business_reads(
    replica: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _user("offline-health")
    db.sync_sqlite_from_pg()
    monkeypatch.setenv("DATABASE_URL", "postgresql://postgres:postgres@127.0.0.1:1/sc_app")
    monkeypatch.setenv("REDIS_URL", "memory://")
    monkeypatch.setenv("RADAR_SCHEDULE", "off")
    get_settings.cache_clear()
    db.close_pool()
    with TestClient(app) as client:
        for _ in range(100):
            body = client.get("/health").json()
            if body["db"] == "sqlite":
                break
            time.sleep(0.05)
        assert body["db"] == "sqlite"
        assert body["status"] == "ok"
        assert body["db_status"] == "up"
        _user("offline-restored")
        assert repository.get_user_by_id("offline-restored") is not None

        monkeypatch.setenv("DATABASE_URL", replica)
        get_settings.cache_clear()
        db.close_pool()
        for _ in range(150):
            body = client.get("/health").json()
            if body["db"] == "postgresql" and body["db_status"] == "up":
                break
            time.sleep(0.05)
        assert body["db"] == "postgresql"
        assert body["db_status"] == "up"
        assert repository.get_user_by_id("offline-restored") is not None
        assert db.pending_operations() == []


def _corrupt_replica() -> None:
    """把副本文件写成垃圾，模拟磁盘损坏 / 副本被外部改坏。"""
    path = db._sqlite_path()
    for suffix in ("-wal", "-shm"):
        Path(f"{path}{suffix}").unlink(missing_ok=True)
    path.write_bytes(b"not a sqlite database" * 64)


def test_corrupt_replica_keeps_healthy_primary_serving(isolated_replica: str) -> None:
    """副本损坏只该失去兜底：主库健康时业务写入必须继续成功，不能被 fail-stop 打成 503。"""
    _corrupt_replica()

    _user("primary-keeps-serving")
    assert repository.get_user_by_id("primary-keeps-serving") is not None
    assert db.active_backend() == "postgresql"
    assert db.runtime_state()["ready"] is True
    # 镜像失败会把副本标脏，供 /health 暴露「主库正常但已失去兜底」。
    assert db.runtime_state()["replica_ready"] is False
    assert TestClient(app).get("/health").json()["db_replica"] == "stale"

    with pytest.raises((sqlite3.Error, RuntimeError, psycopg.Error)):
        _recover()
    assert db.active_backend() == "postgresql"
    assert db.runtime_state()["ready"] is True


def test_corrupt_replica_returns_retryable_503_instead_of_500(isolated_replica: str) -> None:
    """副本接管期间文件损坏：给可重试 503，绝不把 sqlite3 原始异常冒成 500。"""
    _activate_sqlite()
    _corrupt_replica()

    with pytest.raises(AppError) as excinfo:
        _user("offline-after-corruption")
    assert excinfo.value.code == "DATABASE_UNAVAILABLE"
    assert excinfo.value.status == 503
    assert excinfo.value.retryable is True


def test_replica_copy_reports_table_name_on_unique_conflict(tmp_path: Path) -> None:
    """副本侧撞唯一约束必须报出表名。

    生产事故：主库 `radar_techs_pkey` 在目录里 valid，实际却不拦重复（索引缺条目），
    副本重建时只抛 `IntegrityError` 类型名，日志看不出该去修哪张表。
    """
    conn = sqlite3.connect(tmp_path / "copy.db")
    try:
        conn.execute('CREATE TABLE radar_techs (tech_slug TEXT PRIMARY KEY, name TEXT NOT NULL)')
        payload = [["github:dup", "a"], ["github:dup", "b"]]
        with pytest.raises(db.ReplicaSyncError) as excinfo:
            db._copy_rows(conn, "radar_techs", ["tech_slug", "name"], payload)
        assert excinfo.value.table == "radar_techs"
        assert "radar_techs" in str(excinfo.value)
        assert "UNIQUE" in str(excinfo.value).upper()
    finally:
        conn.close()


def test_admin_cli_write_refreshes_replica(replica: str) -> None:
    """旁路进程（admin CLI）写主库后必须自己补齐副本。

    生产演练暴露的缺口：CLI 是新进程，`replica_ready` 初值 False，镜像分支静默跳过，
    而服务进程的 `/health` 仍报 ready —— 直到 PG 真挂了才发现副本少一个账号。
    """
    code = admin_cli.main(["create-user", "--email", "cli-replica@example.com"])
    assert code == 0
    assert db.runtime_state()["replica_ready"] is True

    with closing(db._open_sqlite()) as conn:
        row = conn.execute(
            "SELECT email FROM users WHERE email = ?", ("cli-replica@example.com",)
        ).fetchone()
    assert row is not None


def test_backoff_delay_grows_and_caps() -> None:
    """确定性失败不该每 2s 全量重拷一遍：间隔指数增长并封顶。"""
    assert _backoff_delay(2.0, 0) == 2.0
    assert _backoff_delay(2.0, 1) == 2.0
    assert _backoff_delay(2.0, 3) == 8.0
    assert _backoff_delay(2.0, 40) == _RECOVERY_BACKOFF_CAP_S


def test_exc_brief_keeps_message_on_one_line() -> None:
    """日志里要能直接读到原因，而不是只有异常类型名。"""
    err = RuntimeError("table=radar_techs detail=UNIQUE constraint failed\nsecond line")
    brief = _exc_brief(err)
    assert brief.startswith("RuntimeError: ")
    assert "radar_techs" in brief
    assert "\n" not in brief
    assert len(_exc_brief(RuntimeError("x" * 1000))) <= 300


def test_unreachable_pg_skips_exclusive_recovery_window(
    replica: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PG 不可达时只做无锁探活；抢占写锁跑初始化会把 SQLite 写请求卡到超时。"""
    _activate_sqlite()
    monkeypatch.setenv("DB_RECOVERY_INTERVAL_S", "0.01")
    get_settings.cache_clear()

    def unavailable() -> None:
        raise psycopg.OperationalError("simulated unavailable")

    entered: list[int] = []
    monkeypatch.setattr(db, "ping_postgresql", unavailable)
    # r114：启动决策已由 `db.bootstrap()` 完成，这里直接固定成「副本接管」，
    # 让用例只测「恢复循环不会抢占写锁去跑初始化」这一件事。
    monkeypatch.setattr(db, "bootstrap", lambda: "sqlite")
    monkeypatch.setattr("app.main._seed_business_data", lambda **_: None)
    monkeypatch.setattr("app.main._initialize_pg_database", lambda: entered.append(1))

    async def verify() -> None:
        task = asyncio.create_task(_recover_database())
        for _ in range(80):
            if entered or db.runtime_state()["ready"] is False:
                break
            await asyncio.sleep(0.01)
        await asyncio.sleep(0.05)
        assert entered == []
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(verify())
    assert db.active_backend() == "sqlite"
    assert db.runtime_state()["ready"] is True

    started = time.monotonic()
    for index in range(3):
        _user(f"offline-probe-{index}")
    assert time.monotonic() - started < 1.5
    assert repository.get_user_by_id("offline-probe-2") is not None


def test_database_recovery_retries_until_initialization_succeeds(
    unavailable_dependencies: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempts = 0
    # 预探活只负责判断 PG 是否值得进入恢复窗口；本用例单独验证初始化重试。
    monkeypatch.setattr(db, "ping_postgresql", lambda: None)
    # 启动决策固定为「PG 已选定」：这个用例测的是恢复窗口里的重试，不是选库。
    monkeypatch.setattr(db, "bootstrap", lambda: "postgresql")
    monkeypatch.setattr("app.main._seed_business_data", lambda **_: None)

    def eventually_available() -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise psycopg.OperationalError("simulated unavailable")

    monkeypatch.setattr("app.main._initialize_pg_database", eventually_available)

    async def verify_retry() -> None:
        task = asyncio.create_task(_recover_database())
        for _ in range(100):
            if attempts >= 2:
                break
            await asyncio.sleep(0.01)
        assert attempts == 2
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(verify_retry())


def test_lifespan_waits_for_recovery_worker_before_closing_pool(
    unavailable_dependencies: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    entered = threading.Event()
    release = threading.Event()
    worker: threading.Thread | None = None
    closed_after_worker: list[bool] = []

    def slow_initialize() -> None:
        entered.set()
        assert release.wait(timeout=5)

    def checked_close_pool() -> None:
        assert worker is not None
        closed_after_worker.append(not worker.is_alive())
        db.close_pool()

    monkeypatch.setattr(db, "ping_postgresql", lambda: None)
    # 启动决策固定成「PG 已选定」，让恢复窗口立刻拿到 slow_initialize 这个阻塞点。
    monkeypatch.setattr(db, "bootstrap", lambda: "postgresql")
    monkeypatch.setattr("app.main._seed_business_data", lambda **_: None)
    monkeypatch.setattr("app.main._initialize_pg_database", slow_initialize)
    monkeypatch.setattr("app.main.close_pool", checked_close_pool)
    monkeypatch.setenv("RADAR_SCHEDULE", "off")
    get_settings.cache_clear()

    with TestClient(app):
        assert entered.wait(timeout=2)
        worker = db.recovery_thread
        assert worker is not None and worker.is_alive()
        # __exit__ 会取消恢复协程，但同步恢复仍占着工作线程；稍后放行，
        # 证明 close_pool 发生在真实线程退出之后，而不是只取消了 await。
        releaser = threading.Timer(0.2, release.set)
        releaser.start()

    release.set()
    releaser.join(timeout=2)
    assert not worker.is_alive()
    assert closed_after_worker == [True]


def test_pg_arriving_within_grace_period_still_wins(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """PG 比 backend 晚几秒就绪时，宽限期内连上就仍用 PG，不留下单机库。

    这是 `DB_STANDALONE_GRACE_S` 存在的理由：容器编排里 postgres 常常比 backend 晚几秒
    启动。若第一次探测失败就急着重库，就再也不会切回 PG，数据会留在本地文件里形成分叉。
    """
    from tests.conftest import EMPTY_DSN, _ensure_database_exists, _reset_schema

    _ensure_database_exists(EMPTY_DSN)
    _reset_schema(EMPTY_DSN)
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "no-replica" / "fallback.db"))
    monkeypatch.setenv("DATABASE_URL", "postgresql://postgres:postgres@127.0.0.1:1/sc_app")
    monkeypatch.setenv("REDIS_URL", "memory://")
    monkeypatch.setenv("DB_STANDALONE_GRACE_S", "3")
    monkeypatch.setenv("RADAR_SCHEDULE", "off")
    get_settings.cache_clear()
    db.close_pool()

    real_probe = db.probe_postgresql_quiet
    attempts = {"n": 0}

    def probe_after_first() -> bool:
        """第一次探测失败（PG 还没起来），宽限期内的下一次用真实探测连空库。"""
        attempts["n"] += 1
        if attempts["n"] == 1:
            return False
        monkeypatch.setenv("DATABASE_URL", EMPTY_DSN)
        get_settings.cache_clear()
        return real_probe()

    monkeypatch.setattr(db, "probe_postgresql_quiet", probe_after_first)
    try:
        assert db.bootstrap() == "postgresql"
        assert db.active_backend() == "postgresql"
        assert db.is_standalone() is False
        # 关键：没有顺手留下一个单机库（那会让下次启动走上单机，再也回不到 PG）。
        assert db.sqlite_marker("standalone") is None
    finally:
        db.close_pool()
        get_settings.cache_clear()


def test_redis_degraded_uses_real_memory_cache(unavailable_dependencies: None) -> None:
    assert redis_cache.status() == "degraded"
    redis_cache.cache_set_json("sc:test", {"value": 1}, ttl_s=30)
    assert redis_cache.cache_get_json("sc:test") == {"value": 1}
    redis_cache.cache_delete("sc:test")
    assert redis_cache.cache_get_json("sc:test") is None
    assert redis_cache.window_hit("sc:test:window", 60, 1) is None
    with redis_cache.lock("test:unavailable", ttl_s=5, wait_s=0) as acquired:
        assert acquired is True


def test_memory_cache_ttl_lru_and_prefix_invalidation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REDIS_URL", "memory://")
    monkeypatch.setenv("MEMORY_CACHE_MAX_ENTRIES", "2")
    get_settings.cache_clear()
    redis_cache.reset_client()
    redis_cache.cache_set_json("sc:a", {"n": 1}, ttl_s=30)
    redis_cache.cache_set_json("sc:b", {"n": 2}, ttl_s=30)
    assert redis_cache.cache_get_json("sc:a") == {"n": 1}
    redis_cache.cache_set_json("sc:c", {"n": 3}, ttl_s=30)
    assert redis_cache.cache_get_json("sc:b") is None, "最近访问 a 后应先淘汰 b"
    redis_cache.cache_set_json("sc:expired", {"n": 4}, ttl_s=1)
    redis_cache._memory_set("sc:expired", '{"n":4}', -1)
    assert redis_cache.cache_get_json("sc:expired") is None
    assert redis_cache.cache_get_json("sc:c") == {"n": 3}
    assert redis_cache.cache_delete_prefix("sc:") == 1
    assert redis_cache.cache_get_json("sc:a") is None
    assert redis_cache.cache_get_json("sc:c") is None


def test_memory_redis_status_is_not_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REDIS_URL", "memory://")
    get_settings.cache_clear()
    redis_cache.reset_client()
    assert redis_cache.status() == "memory"
