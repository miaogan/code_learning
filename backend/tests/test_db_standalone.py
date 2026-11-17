"""r113 单机模式：没有 PostgreSQL、也没有 Redis 时能不能开箱跑起来。

与 `test_dependency_recovery.py` 的分界线刻意划清楚：

- 那边测「PG 是权威主库，故障时由**完整副本**接管」——前提是副本由 PG 同步生成；
- 这边测「**压根没有 PG**」——副本这个概念不存在，SQLite 自己就是权威主库。

两条路径共用同一套方言翻译与事务层，所以这里不再重测 SQL 兼容性，只钉住五件事：
1. 空目录冷启动能建库、能读写、`/health` 语义正确；
2. 离线重放日志不增长（没有 PG 可回放，记录只会无限增长）；
3. 重启后仍认自己是单机库（不能退回「待回放的离线副本」）；
4. **有数据但缺 complete 标记的库仍然拒绝接管**（原有数据安全边界不能破）；
5. 运行中的故障不会把 PG 主库悄悄变成单机库（`allow_bootstrap=False` 的路径）。
"""

from __future__ import annotations

import logging
import sqlite3
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core import db, repository
from app.core.auth import hash_password
from app.core.config import get_settings
from app.main import app

EMAIL = "standalone@test.local"
PASSWORD = "standalone-pw-1234"


def _create_user(email: str = EMAIL) -> str:
    user_id = uuid.uuid4().hex
    repository.create_user(
        user_id=user_id,
        email=email,
        password_hash=hash_password(PASSWORD),
        display_name="单机用户",
    )
    return user_id


def _prepare_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, mode: str
) -> Path:
    """把环境切成「没有 PG、没有 Redis、没有既有数据目录」。

    `DATABASE_URL` 指到 127.0.0.1:1（通常无监听）：`connect_timeout=1`，首次探测会
    快速失败而不会把用例拖成几十秒。宽限期设 0 —— 用例要的是「判定逻辑」而不是
    「等满 15s」，真实宽限期另有一条断言日志的用例覆盖。
    """
    sqlite_path = tmp_path / "standalone.db"
    monkeypatch.setenv("DB_MODE", mode)
    monkeypatch.setenv("DATABASE_URL", "postgresql://nobody:nobody@127.0.0.1:1/nodb")
    monkeypatch.setenv("SQLITE_PATH", str(sqlite_path))
    monkeypatch.setenv("REDIS_URL", "")
    monkeypatch.setenv("DB_STANDALONE_GRACE_S", "0")
    # 教程索引要连 embedding 供应商；单机用例不验证 RAG，直接关掉免得等网络超时。
    monkeypatch.setenv("RAG_SEED_TUTORIALS", "false")
    get_settings.cache_clear()
    db.close_pool()
    db.reset_runtime()
    return sqlite_path


def _cleanup_env() -> None:
    db.close_pool()
    db.reset_runtime()
    get_settings.cache_clear()


@pytest.fixture()
def standalone_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """显式声明单机模式（`DB_MODE=sqlite`）：不探测 PG。"""
    path = _prepare_env(tmp_path, monkeypatch, mode="sqlite")
    try:
        yield path
    finally:
        _cleanup_env()


@pytest.fixture()
def auto_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """默认档（`DB_MODE=auto`）：用户什么都不配时的真实路径 —— 优先 PG，不可用自动切 SQLite。"""
    path = _prepare_env(tmp_path, monkeypatch, mode="auto")
    try:
        yield path
    finally:
        _cleanup_env()


def test_cold_start_without_postgres_or_redis(standalone_env: Path) -> None:
    """空目录启动：能建库、`/health` 报 ok + sqlite + na，而不是 degraded + stale。"""
    with TestClient(app) as client:
        health = client.get("/health").json()

    assert health["db"] == "sqlite"
    assert health["db_status"] == "up"
    # 关键：单机模式没有「副本」这个概念，报 ready 会假装有兜底、报 stale 会假装兜底坏了。
    assert health["db_replica"] == "na"
    assert health["redis_status"] == "memory"
    assert health["status"] == "ok"
    assert db.is_standalone() is True
    assert standalone_env.exists(), "冷启动必须真的把库文件建出来"


def test_business_read_write_works(standalone_env: Path) -> None:
    """完整业务闭环：建用户 → 登录 → 读自身 → 读题库统计。"""
    with TestClient(app) as client:
        _create_user()
        login = client.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})
        assert login.status_code == 200
        me = client.get("/api/me")
        assert me.status_code == 200 and me.json()["email"] == EMAIL
        stats = client.get("/api/practice/stats")
        assert stats.status_code == 200
        assert stats.json()["total"] > 0, "题库种子必须落进单机库"


def test_offline_operation_log_does_not_grow(standalone_env: Path) -> None:
    """单机模式没有 PG 可回放：重放日志必须保持为空，否则会随写入无限增长。"""
    with TestClient(app) as client:
        for index in range(3):
            _create_user(f"u{index}@test.local")
        assert client.get("/api/me").status_code in (200, 401)

    with sqlite3.connect(standalone_env) as raw:
        pending = raw.execute("SELECT count(*) FROM _offline_operations").fetchone()[0]
    assert pending == 0
    assert db.runtime_state()["sync_pending"] == 0


def test_restart_stays_standalone(standalone_env: Path) -> None:
    """重启后仍认自己是单机权威库，而不是「待回放的离线副本」。

    判据看两处：`activate_standalone_sqlite(bootstrap=False)` 不报错（说明 complete
    标记还在），且 `_standalone` 重新为 True（说明识别到了 standalone 标记）。
    """
    db.activate_standalone_sqlite(bootstrap=True)
    _create_user()

    db.reset_runtime()
    assert db.is_standalone() is False, "reset_runtime 必须清掉进程本地的单机标记"

    # bootstrap=False：重启时不该再刷一遍标记，直接沿用库里的标记接管。
    db.activate_standalone_sqlite()
    assert db.is_standalone() is True
    assert db.active_backend() == "sqlite"
    # 已经有业务数据了，不允许再被当成「可以随便新建的单机库」。
    assert db.standalone_bootstrap_allowed() is False


def test_existing_data_without_complete_marker_is_still_rejected(
    standalone_env: Path,
) -> None:
    """有数据但缺 complete 标记 = 来历不明的半同步副本，必须拒绝接管。

    这是 r99 立下的数据安全边界，单机模式不能顺手把它放开：那种库里可能是半份数据，
    用它顶替主库等于静默丢数据。
    """
    db.activate_standalone_sqlite(bootstrap=True)
    _create_user()
    with sqlite3.connect(standalone_env) as raw:
        raw.execute("DELETE FROM _sync_state WHERE key IN ('complete', 'standalone')")
        raw.commit()

    db.reset_runtime()
    assert db.has_sqlite_data() is True
    assert db.standalone_bootstrap_allowed() is False
    assert db.is_standalone() is False

    with pytest.raises(RuntimeError, match="尚未完整同步"):
        db.activate_sqlite()


def test_running_failure_takes_over_as_replica_not_standalone(standalone_env: Path) -> None:
    """运行中 PG 故障只能按**副本**接管，绝不能升格成单机权威库。

    这条对应真实风险：生产 PG 抖动几秒，如果顺手立一个单机库，就再也不会自动切回 PG，
    数据会留在本地文件里形成分叉。启动时的决策由 `db.bootstrap()` 一次做完，运行中
    只允许「用已有副本顶着」这一种动作。
    """
    db.activate_standalone_sqlite(bootstrap=True)
    _create_user()
    # 把库还原成「PG 完整副本」的形态：complete 在、standalone 不在。
    with sqlite3.connect(standalone_env) as raw:
        raw.execute("DELETE FROM _sync_state WHERE key = 'standalone'")
        raw.commit()
    db.reset_runtime()

    db.activate_sqlite()

    assert db.active_backend() == "sqlite"
    assert db.is_standalone() is False, "副本形态不能被当成单机权威库"
    assert db.runtime_state()["mode"] == "online"


def test_replica_sync_is_noop_in_standalone(standalone_env: Path) -> None:
    """单机模式下「从 PG 重建副本」必须是无操作 —— 否则会连 PG 并把权威库覆盖掉。"""
    db.activate_standalone_sqlite(bootstrap=True)
    assert db.sync_sqlite_from_pg() == {}
    assert db.refresh_replica() == {}
    assert db.is_standalone() is True


def test_admin_cli_creates_user_without_postgres(standalone_env: Path) -> None:
    """建号工具在单机模式下必须可用。

    `admin_cli.main()` 原来无条件调 `init_db()`（强制走 PG 连接），在没有 PG 的环境里
    「建号」这种纯本地操作会直接失败 —— 而它恰好是单机部署最需要的第一个命令。
    """
    from app import admin_cli

    code = admin_cli.main(
        ["create-user", "--email", "cli@test.local", "--name", "CLI", "--mode", "own"]
    )
    assert code == 0
    assert db.is_standalone() is True
    # 不只是打印了成功：行必须真的落进单机库。
    assert repository.get_user_by_email("cli@test.local") is not None


def test_admin_cli_bootstraps_empty_directory(standalone_env: Path) -> None:
    """空库时先跑建号（服务还没起过）也要能成 —— CLI 自己把单机库建出来。"""
    from app import admin_cli

    # 注意判据用「有没有业务数据」而不是「文件在不在」：`reset_runtime()` 读 complete
    # 标记时会 `sqlite3.connect`，空路径上已经留下一个 0 字节文件了。
    assert db.has_sqlite_data() is False
    assert db.standalone_bootstrap_allowed() is True
    code = admin_cli.main(
        ["create-user", "--email", "first@test.local", "--name", "First", "--mode", "own"]
    )
    assert code == 0
    # 必须打上权威标记：否则服务启动会把这份库当成「来历不明的半同步副本」拒绝接管。
    with sqlite3.connect(standalone_env) as raw:
        keys = {row[0] for row in raw.execute("SELECT key FROM _sync_state")}
    assert {"complete", "standalone"} <= keys
    assert db.has_sqlite_data() is True


# --- 默认档（DB_MODE=auto）：用户什么都不配时的真实路径 ---------------------------


def test_auto_mode_falls_back_to_sqlite_and_prints_choice(
    auto_env: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """不设 DB_MODE：PG 不可达 → 自动切 SQLite，并打印「实际用了哪个库」。

    这是用户最关心的那条路：不改任何配置，也能起来并看得见结论。
    """
    caplog.set_level(logging.INFO, logger="app.db")
    backend = db.bootstrap()

    assert backend == "sqlite"
    assert db.is_standalone() is True
    messages = [record.getMessage() for record in caplog.records]
    assert any("db.backend.selected" in m for m in messages), messages
    assert any("PostgreSQL 不可用" in m for m in messages), messages


def test_auto_mode_prefers_postgres_when_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """PG 可用时必须优先 PG —— 「优先 pgsql」是这个功能的硬要求。

    这里连的是会话级测试库（`TEST_DATABASE_URL`，conftest 已建好表），
    `init_db()` 的 DDL 全部幂等，不会污染结构。
    """
    monkeypatch.setenv("DB_MODE", "auto")
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "unused.db"))
    get_settings.cache_clear()
    db.close_pool()
    db.reset_runtime()

    caplog.set_level(logging.INFO, logger="app.db")
    backend = db.bootstrap()

    assert backend == "postgresql"
    assert db.active_backend() == "postgresql"
    assert db.is_standalone() is False
    messages = [record.getMessage() for record in caplog.records]
    assert any("PostgreSQL 可用" in m for m in messages), messages


def test_explicit_postgres_mode_never_falls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`DB_MODE=postgres` 连不上就报错，不能偷偷换成 SQLite。"""
    path = _prepare_env(tmp_path, monkeypatch, mode="postgres")
    del path
    with pytest.raises(RuntimeError, match="拒绝降级"):
        db.bootstrap()
    assert db.active_backend() == "postgresql"
    assert db.is_standalone() is False


def test_bootstrap_rejects_unmarked_data_with_actionable_hint(
    auto_env: Path,
) -> None:
    """有数据却缺权威标记时，报错必须给出可执行的处理方式。

    只说「拒绝」会让用户卡死：他手上这份数据很可能是自己的单机库（旧版本留下的）。
    这里必须用 `auto` 档 —— 显式 `DB_MODE=sqlite` 是「用户已经声明这就是权威库」，
    会走信任路径接管，不抛错（另有用例覆盖）。
    """
    db.activate_standalone_sqlite(bootstrap=True)
    _create_user()
    with sqlite3.connect(auto_env) as raw:
        raw.execute("DELETE FROM _sync_state WHERE key IN ('complete', 'standalone')")
        raw.commit()
    db.reset_runtime()

    with pytest.raises(RuntimeError, match="DB_MODE=sqlite"):
        db.bootstrap()


def test_explicit_sqlite_mode_trusts_unmarked_data(standalone_env: Path) -> None:
    """显式声明 `DB_MODE=sqlite` 时接管无标记的库：用户已经说了这就是权威库。

    典型场景是从 r98 之前升级上来的老 `app.db`（没有 `_sync_state` 表），
    它的数据是真的，不该被当成「来历不明」永久拒绝。
    """
    db.activate_standalone_sqlite(bootstrap=True)
    _create_user()
    with sqlite3.connect(standalone_env) as raw:
        raw.execute("DELETE FROM _sync_state WHERE key IN ('complete', 'standalone')")
        raw.commit()
    db.reset_runtime()

    assert db.bootstrap() == "sqlite"
    assert db.is_standalone() is True
    # 接管后必须补上标记，否则下次启动又会走到「无标记」分支。
    assert db.sqlite_marker("complete") == "1"
    assert db.sqlite_marker("standalone") == "1"
