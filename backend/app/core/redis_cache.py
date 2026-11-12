"""r98 Redis 接入层：限流窗口 / 会话缓存 / 业务读缓存 / 分布式锁。

**降级口径（四类能力共用一条）**：Redis 是加速与跨副本一致性组件，不是数据源。
连不上时退回进程内实现或直接打库，**不把 503 抛给用户**——真正决定正确性的数据
（会话、报告、进度）都在 PostgreSQL 里，Redis 里任何东西丢了行为仍然正确。

三档形态由 `REDIS_URL` 决定：

- 正常：`redis://host:6379/0` 或 `rediss://…`（TLS）；
- 显式单副本：`memory://` —— 不建连接，全部走进程内兜底（部署文档里的单机选项）；
- 未配置：与 `memory://` 同义，生产档会被 `production_blockers` 拦下。

**为什么 key 统一带前缀**：dev / staging / prod 常共用一台 Redis。前缀隔离比「用不同 db
编号」可靠 —— 很多托管 Redis 只给一个 db，`SELECT` 会直接报错。
"""

from __future__ import annotations

import contextlib
import json
import logging
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import redis

from app.core.config import get_settings

logger = logging.getLogger("app.redis")

#: 曾经连不上就置一个截止时间，避免每个请求都去撞一次超时（socket 超时会叠加成延迟）。
#: 不是永久熔断：`_RETRY_AFTER_S` 之后允许再试，Redis 恢复后自动回到共享模式。
_offline_until = 0.0
_RETRY_AFTER_S = 30.0

_client: redis.Redis | None = None
_client_lock = threading.Lock()


class _Unavailable(RuntimeError):
    """Redis 调用失败：由调用点捕获后转成兜底行为（绝不回传给用户）。"""


def _url() -> str:
    return (get_settings().redis_url or "").strip()


def enabled() -> bool:
    """是否配置了真实 Redis（`memory://` 与空串都算未启用）。"""
    url = _url()
    return bool(url) and url != "memory://"


def get_client() -> redis.Redis | None:
    """返回 Redis 客户端；未启用或已知离线时返回 None（调用方走兜底路径）。"""
    global _client
    if not enabled():
        return None
    if _offline_until > time.monotonic():
        return None
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = redis.Redis.from_url(
                    _url(),
                    decode_responses=True,
                    socket_connect_timeout=1.0,
                    socket_timeout=1.0,
                    health_check_interval=30,
                )
    return _client


def reset_client() -> None:
    """丢弃客户端与离线标记（进程退出 / 测试切换实例后调用）。"""
    global _client, _offline_until
    with _client_lock:
        client, _client = _client, None
    _offline_until = 0.0
    if client is not None:
        # 关闭失败不影响后续，连接会随 GC 释放（退出路径不抛异常更重要）。
        with contextlib.suppress(Exception):
            client.close()


def _mark_offline(exc: BaseException) -> None:
    global _offline_until
    _offline_until = time.monotonic() + _RETRY_AFTER_S
    logger.warning("redis.unavailable error=%s retry_in=%.0fs", type(exc).__name__, _RETRY_AFTER_S)


def key(*parts: str) -> str:
    """拼一个带环境前缀的 key：`sc:report:abc`。"""
    prefix = get_settings().redis_prefix.strip() or "sc"
    return ":".join((prefix, *parts))


def _call(operation: str, fn: Any) -> Any:
    """执行一次 Redis 调用；未启用返回 None，失败记日志并抛 `_Unavailable`。

    刻意捕获 `Exception` 而不是 `redis.RedisError`：DNS 解析失败、TLS 握手失败、socket
    超时在 redis-py 里分属不同异常族，漏一个就会把缓存故障放大成 500。
    """
    client = get_client()
    if client is None:
        return None
    try:
        return fn(client)
    except Exception as exc:  # noqa: BLE001 - 见 docstring
        _mark_offline(exc)
        logger.warning("redis.%s_failed error=%s", operation, type(exc).__name__)
        raise _Unavailable(operation) from exc


# --- 业务读缓存 ---------------------------------------------------------------


def cache_get_json(name: str) -> Any | None:
    """读 JSON 缓存；未命中 / 未启用 / 解析失败都返回 None（调用方照常打库）。"""
    try:
        raw = _call("cache_get", lambda client: client.get(name))
    except _Unavailable:
        return None
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        # 缓存内容坏了就当没命中：删掉它，避免每次读都解析失败。
        cache_delete(name)
        return None


def cache_set_json(name: str, value: Any, ttl_s: int) -> None:
    """写 JSON 缓存；`ttl_s <= 0` 直接不写（这是读缓存的总开关）。"""
    if ttl_s <= 0:
        return
    try:
        payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        return  # 不可序列化的产物不缓存，不是错误
    try:
        _call("cache_set", lambda client: client.set(name, payload, ex=ttl_s))
    except _Unavailable:
        return


def cache_delete(*names: str) -> None:
    """删若干 key（写操作后失效）。空参不产生往返。"""
    names = tuple(name for name in names if name)
    if not names:
        return
    try:
        _call("cache_delete", lambda client: client.delete(*names))
    except _Unavailable:
        return


def cache_delete_prefix(prefix: str) -> int:
    """按前缀批量失效，返回删除条数。用 `SCAN` 而不是 `KEYS`：后者在大库上会阻塞 Redis。"""
    deleted = 0
    try:
        client = get_client()
        if client is None:
            return 0
        batch: list[str] = []
        for found in client.scan_iter(match=f"{prefix}*", count=200):
            batch.append(found)
            if len(batch) >= 200:
                deleted += int(client.delete(*batch))
                batch.clear()
        if batch:
            deleted += int(client.delete(*batch))
    except Exception as exc:  # noqa: BLE001
        _mark_offline(exc)
        logger.warning("redis.cache_scan_failed error=%s", type(exc).__name__)
    return deleted


# --- 分布式锁 -----------------------------------------------------------------

#: 释放锁必须校验持有者，否则「A 超时释放了 B 的锁」会让互斥彻底失效。
_RELEASE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
"""


@contextmanager
def lock(name: str, ttl_s: int = 0, wait_s: float = -1.0) -> Iterator[bool]:
    """分布式互斥锁；yield `True` 表示拿到锁，`False` 表示没抢到（调用方自行决定跳过）。

    **未启用 Redis 时恒为 True**：单副本部署本来不需要跨进程互斥，靠进程内去重即可；
    返回 False 会让功能在「没配 Redis」的环境里静默失效，那是更糟的降级。

    `ttl_s` 必须设置（默认取 `LOCK_TTL_S`）：持锁进程被 kill 时，没有过期时间的锁会把
    任务永久锁死。释放走 Lua 比对持有者，避免误删别人的锁。
    """
    settings = get_settings()
    ttl = int(ttl_s or settings.lock_ttl_s)
    wait = settings.lock_wait_s if wait_s < 0 else wait_s
    token = uuid.uuid4().hex
    full = key("lock", name)

    client = get_client()
    if client is None:
        yield True
        return

    acquired = False
    deadline = time.monotonic() + max(0.0, wait)
    try:
        while True:
            try:
                acquired = bool(client.set(full, token, nx=True, ex=ttl))
            except Exception as exc:  # noqa: BLE001 - 见 _call 的说明
                _mark_offline(exc)
                acquired = True  # 降级：允许继续，不因 Redis 故障阻塞后台任务
                break
            if acquired or time.monotonic() >= deadline:
                break
            time.sleep(0.05)
        yield acquired
    finally:
        if acquired:
            try:
                client.eval(_RELEASE_SCRIPT, 1, full, token)
            except Exception as exc:  # noqa: BLE001
                _mark_offline(exc)


# --- 滑动窗口计数（限流用）----------------------------------------------------

#: 原子滑动窗口：清理过期 → 读当前计数 → 记录本次 → 判断是否超限。
#: **被拒绝的请求也写入**：持续洪泛不应在窗口刚滑过时立刻拿回满额（与内存实现语义一致）。
_WINDOW_SCRIPT = """
local name = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]
redis.call('ZREMRANGEBYSCORE', name, 0, now - window)
local count = redis.call('ZCARD', name)
redis.call('ZADD', name, now, member)
redis.call('PEXPIRE', name, window)
if count >= limit then
    local oldest = redis.call('ZRANGE', name, 0, 0, 'WITHSCORES')
    local retry = 1
    if oldest[2] then
        retry = math.max(1, math.ceil((tonumber(oldest[2]) + window - now) / 1000))
    end
    return {0, retry}
end
return {1, 0}
"""


def window_hit(name: str, window_s: int, limit: int) -> tuple[bool, int] | None:
    """记一次请求并判断是否放行；返回 None 表示 Redis 不可用（调用方回落内存实现）。"""
    if limit <= 0:
        return True, 0
    now_ms = int(time.time() * 1000)
    try:
        result = _call(
            "window",
            lambda client: client.eval(
                _WINDOW_SCRIPT,
                1,
                name,
                now_ms,
                max(1, int(window_s)) * 1000,
                int(limit),
                f"{now_ms}-{uuid.uuid4().hex[:8]}",
            ),
        )
    except _Unavailable:
        return None
    if not result:
        return None
    return bool(int(result[0])), int(result[1])
