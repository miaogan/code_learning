"""r98 Redis 四类能力的集成验证：限流窗口 / 读缓存 / 分布式锁 / 降级。

**为什么单独一个文件**：`conftest` 的 `_isolate_redis` 把 `REDIS_URL` 默认设成 `memory://`
（否则限流窗口与会话缓存会跨用例串味）。这里显式切回真实实例，验证的是
「多副本共享」这条能力本身——它恰恰是进程内实现永远测不出来的部分。

没有 Redis 时 `skip` 而不是 `fail`：CI 可能只起 PG。但**降级用例必须始终能跑**，
它们验证的正是「没有 Redis 时行为仍然正确」。
"""

from __future__ import annotations

import os
import time

import pytest

from app.core import redis_cache
from app.core.config import get_settings
from app.services import rate_limit

REDIS_TEST_URL = os.environ.get("REDIS_TEST_URL", "redis://127.0.0.1:6380/0")


@pytest.fixture()
def real_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    """切到真实 Redis 并清掉本套件的 key；连不上就 skip。"""
    monkeypatch.setenv("REDIS_URL", REDIS_TEST_URL)
    monkeypatch.setenv("REDIS_PREFIX", "sc-test")
    get_settings.cache_clear()
    redis_cache.reset_client()
    client = redis_cache.get_client()
    if client is None:
        pytest.skip("未配置 Redis")
    try:
        client.ping()
    except Exception as exc:  # noqa: BLE001 - 连不上即 skip，不是失败
        pytest.skip(f"连不上 Redis（{type(exc).__name__}）")
    redis_cache.cache_delete_prefix(redis_cache.key(""))
    yield
    redis_cache.cache_delete_prefix(redis_cache.key(""))
    redis_cache.reset_client()
    get_settings.cache_clear()


def test_window_counts_across_processes(real_redis: None) -> None:
    """滑动窗口在 Redis 里是**同一个计数器**：这正是多副本限流能成立的原因。"""
    name = redis_cache.key("rl", "api", "203.0.113.9")

    results = [redis_cache.window_hit(name, window_s=60, limit=3) for _ in range(4)]

    assert [allowed for allowed, _ in results] == [True, True, True, False]
    retry = results[-1][1]
    assert 1 <= retry <= 60, "拒绝时必须给出合理的重试秒数"


def test_window_entries_expire(real_redis: None) -> None:
    """窗口滑过之后额度自动恢复，且 key 自带 TTL（不会永久占内存）。"""
    name = redis_cache.key("rl", "auth", "203.0.113.10")
    assert redis_cache.window_hit(name, window_s=1, limit=1) == (True, 0)
    assert redis_cache.window_hit(name, window_s=1, limit=1)[0] is False

    time.sleep(1.2)

    assert redis_cache.window_hit(name, window_s=1, limit=1)[0] is True


def test_rate_limit_uses_shared_window(real_redis: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """`rate_limit.hit()` 在 Redis 可用时走共享窗口（返回 0 表示放行，>0 表示要等）。"""
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("RATE_LIMIT_API_PER_WINDOW", "2")
    monkeypatch.setenv("RATE_LIMIT_WINDOW_S", "60")
    get_settings.cache_clear()
    rate_limit.reset_all()

    waits = [rate_limit.hit("198.51.100.7", rate_limit.BUCKET_API) for _ in range(3)]

    assert waits[0] == 0
    assert waits[1] == 0
    assert waits[2] >= 1, "第三个请求必须被拒（上限 2）"


def test_cache_roundtrip_and_prefix_invalidation(real_redis: None) -> None:
    """读缓存写入后能读回；按前缀失效一次性清掉同一账号下的所有产物。"""
    name = redis_cache.key("report", "u1", "latest")
    redis_cache.cache_set_json(name, {"id": "rep-1", "payload": "中文"}, ttl_s=30)

    assert redis_cache.cache_get_json(name) == {"id": "rep-1", "payload": "中文"}

    deleted = redis_cache.cache_delete_prefix(redis_cache.key("report", "u1"))

    assert deleted >= 1
    assert redis_cache.cache_get_json(name) is None


def test_cache_disabled_when_ttl_is_zero(real_redis: None) -> None:
    """`READ_CACHE_TTL_S=0` 是读缓存的总开关，此时不得写入任何 key。"""
    name = redis_cache.key("profile", "u2", "latest")

    redis_cache.cache_set_json(name, {"id": "p1"}, ttl_s=0)

    assert redis_cache.cache_get_json(name) is None


def test_lock_is_mutually_exclusive(real_redis: None) -> None:
    """同一把锁在持有期间不可重入：第二个获取者拿不到（`wait_s=0` 立即返回）。"""
    with redis_cache.lock("job:profile:abc", ttl_s=30, wait_s=0) as first:
        assert first is True
        with redis_cache.lock("job:profile:abc", ttl_s=30, wait_s=0) as second:
            assert second is False

    # 释放后可以再次获取
    with redis_cache.lock("job:profile:abc", ttl_s=30, wait_s=0) as third:
        assert third is True


def test_lock_released_even_on_exception(real_redis: None) -> None:
    """持锁块内抛异常也要释放：否则一次失败会把任务永久锁死。"""
    with pytest.raises(RuntimeError), redis_cache.lock("job:radar:xyz", ttl_s=30, wait_s=0):
        raise RuntimeError("boom")

    with redis_cache.lock("job:radar:xyz", ttl_s=30, wait_s=0) as again:
        assert again is True


# --- 降级：没有 Redis 时行为仍然正确 -----------------------------------------


def test_memory_mode_falls_back_to_local_window(monkeypatch: pytest.MonkeyPatch) -> None:
    """`memory://` 下 `window_hit` 返回 None，`hit()` 回落进程内窗口，仍然能限流。"""
    monkeypatch.setenv("REDIS_URL", "memory://")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("RATE_LIMIT_API_PER_WINDOW", "1")
    get_settings.cache_clear()
    redis_cache.reset_client()
    rate_limit.reset_all()

    assert redis_cache.window_hit(redis_cache.key("rl", "api", "x"), 60, 1) is None
    assert rate_limit.hit("192.0.2.1", rate_limit.BUCKET_API) == 0
    assert rate_limit.hit("192.0.2.1", rate_limit.BUCKET_API) >= 1


def test_unreachable_redis_degrades_instead_of_raising(monkeypatch: pytest.MonkeyPatch) -> None:
    """Redis 地址不可达时：缓存当未命中、锁放行、窗口返回 None——**绝不抛给调用方**。"""
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")  # 1 号端口必然关闭
    get_settings.cache_clear()
    redis_cache.reset_client()

    assert redis_cache.cache_get_json("sc:whatever") is None
    redis_cache.cache_set_json("sc:whatever", {"a": 1}, ttl_s=10)  # 不抛
    assert redis_cache.window_hit("sc:rl:x", 60, 1) is None
    with redis_cache.lock("sc:lock:x", ttl_s=5, wait_s=0) as acquired:
        # 降级为「允许继续」：宁可少一层互斥，也不让后台任务因缓存故障停摆
        assert acquired is True

    redis_cache.reset_client()
    get_settings.cache_clear()


# --- 会话缓存与读缓存的失效口径 ----------------------------------------------


def test_session_cache_hit_after_row_removed(tmp_db: str, real_redis: None) -> None:
    """缓存命中时不再打库：把行删掉仍能读到，证明走的不是数据库。

    这条用「删行后仍可见」来证明命中，比数调用次数更直接，也不依赖 mock。
    """
    from app.core import repository
    from app.core.auth import new_session_token, session_expiry
    from app.core.db import connection

    _raw, digest = new_session_token()
    repository.create_session(token_hash=digest, user_id="default", expires_at=session_expiry())
    assert repository.get_session(digest) is not None  # 首次：查库并写缓存

    with connection() as conn:
        conn.execute("DELETE FROM sessions WHERE token_hash = ?", (digest,))

    assert repository.get_session(digest) is not None, "第二次应命中缓存"

    repository.delete_session(digest)  # 登出：必须同时清缓存
    assert repository.get_session(digest) is None, "登出后缓存必须立刻失效"


def test_report_cache_invalidation_clears_latest(tmp_db: str, real_redis: None) -> None:
    """写报告按前缀失效：`latest` 是与 id 无关的另一个 key，漏掉它首页会一直显示旧报告。"""
    from app.core import repository

    latest = repository._report_cache_name("latest")
    by_id = repository._report_cache_name("rep-1")
    redis_cache.cache_set_json(latest, {"id": "rep-1"}, ttl_s=30)
    redis_cache.cache_set_json(by_id, {"id": "rep-1"}, ttl_s=30)

    repository._invalidate_reports()

    assert redis_cache.cache_get_json(latest) is None
    assert redis_cache.cache_get_json(by_id) is None
