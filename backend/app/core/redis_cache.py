"""r98 Redis 接入层：限流窗口 / 会话缓存 / 业务读缓存 / 分布式锁。

**降级口径**：Redis 是加速与共享协调组件，不是业务数据源。连不上时 JSON 缓存
退回有 TTL / LRU 的进程内副本，限流回落本地窗口，锁按单进程语义放行，**不把 503
抛给用户**。会话与业务行的真值在当前活动数据库（PostgreSQL 或其完整 SQLite 副本）；
缓存重连必须先回放失效和新值，不能让旧会话复活。

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
from collections import OrderedDict
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import redis

from app.core.config import get_settings

logger = logging.getLogger("app.redis")

#: 曾经连不上就置一个截止时间，避免每个请求都去撞一次超时（socket 超时会叠加成延迟）。
#: 不是永久熔断：`_RETRY_AFTER_S` 之后允许再试，Redis 恢复后自动回到共享模式。
_offline_until = 0.0
_probe_at = 0.0
_RETRY_AFTER_S = 30.0
_PROBE_TTL_S = 15.0

_client: redis.Redis | None = None
_client_lock = threading.Lock()
#: Redis 故障 / 显式 memory 模式的真正进程内副本，不是简单跳过缓存。
_MEMORY: OrderedDict[str, tuple[float, Any]] = OrderedDict()
#: Redis 断线期间的删除屏障：防止重连后又读回旧会话。屏障只覆盖远端旧值，
#: 同 key 的新内存值仍优先返回；前缀失效不能因为单 key 新写入而被整体取消。
#: 未同步的屏障不能按 TTL / 容量淘汰：短故障窗口可能比会话 TTL 更长，正确性优先于
#: 这部分异常日志的内存上限。全部回放成功后统一解除，正常运行不会无限积累。
_TOMBSTONES: OrderedDict[str, float] = OrderedDict()
_PREFIX_TOMBSTONES: OrderedDict[str, float] = OrderedDict()
_MEMORY_LOCK = threading.RLock()
#: 本地变更、重连回放和远端调用按同一顺序执行。否则回放快照可能在并发删除之后
#: 才把旧内存值写回 Redis，让已经失效的会话复活。
_cache_sync_lock = threading.RLock()
_cache_sync_pending = False


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


def status() -> str:
    """up / degraded / memory；15s TTL 的真实 ping，离线期间只探测一次避免惊群。

    不直接调 `_call`：健康检查需要返回 down 而非异常，且不能绕过离线退避。
    探测失败 1s 上限，正常容器探活间隔 30s；无 Redis 配置永不产生网络行为。
    """
    global _probe_at
    if not enabled():
        return "memory"
    if _offline_until > time.monotonic():
        return "degraded"
    now = time.monotonic()
    # 有待回放的失效/新值时不能走探活缓存捷径：那会把「尚未同步」误报成 up，
    # 而随后的读取仍可能命中 Redis 里的旧值。
    if not _cache_sync_pending and now - _probe_at < _PROBE_TTL_S:
        return "up"
    with _client_lock:
        if not _cache_sync_pending and now - _probe_at < _PROBE_TTL_S:
            return "up"
        _probe_at = now
    try:
        client = get_client()
        if client is None:
            return "degraded"
        client.ping()
        # 探活成功不等于缓存已同步；必须先回放失效与新值，再公开 up。
        # 否则 ping 后的 _probe_at 会让其他 health 请求直接返回 up，而此时尚未
        # 回放的删除屏障又可能因 TTL 清理，造成旧会话复活。
        _replay_memory_to_redis(client)
        _mark_online()
    except Exception as exc:  # noqa: BLE001 - 探活如实降级，不向调用方抛 Redis 异常
        _mark_offline(exc)
        return "degraded"
    return "up"


def reset_client() -> None:
    """丢弃客户端与离线标记（进程退出 / 测试切换实例后调用）。"""
    global _client, _offline_until, _probe_at, _cache_sync_pending
    with _client_lock:
        client, _client = _client, None
    _offline_until = 0.0
    _probe_at = 0.0
    _cache_sync_pending = False
    with _MEMORY_LOCK:
        _MEMORY.clear()
        _TOMBSTONES.clear()
        _PREFIX_TOMBSTONES.clear()
    if client is not None:
        # 关闭失败不影响后续，连接会随 GC 释放（退出路径不抛异常更重要）。
        with contextlib.suppress(Exception):
            client.close()


def _mark_online() -> None:
    """真实业务调用也算探活证据：成功即退出退避，避免 health 再发无意义 ping。"""
    global _offline_until, _probe_at
    _offline_until = 0.0
    _probe_at = time.monotonic()


def _mark_offline(exc: BaseException) -> None:
    global _offline_until, _cache_sync_pending
    _offline_until = time.monotonic() + _RETRY_AFTER_S
    _cache_sync_pending = True
    logger.warning("redis.unavailable error=%s retry_in=%.0fs", type(exc).__name__, _RETRY_AFTER_S)


def key(*parts: str) -> str:
    """拼一个带环境前缀的 key：`sc:report:abc`。"""
    prefix = get_settings().redis_prefix.strip() or "sc"
    return ":".join((prefix, *parts))


def _replay_memory_to_redis(client: redis.Redis) -> None:
    """重连后先落实离线期间的失效和新值，再放行普通远端读写。"""
    global _cache_sync_pending
    with _cache_sync_lock:
        if not _cache_sync_pending:
            return
        with _MEMORY_LOCK:
            now = time.monotonic()
            # 屏障即使过了原 TTL 也必须继续回放：Redis 上的旧值可能尚未过期。
            # 同 key 的精确删除优先于新值；前缀删除与后续写入按 sync lock 排序，
            # 先删前缀再写新值，不能把这个新值也过滤掉。
            prefixes = list(_PREFIX_TOMBSTONES)
            deleted = list(_TOMBSTONES)
            values = [
                (name, payload, expiry)
                for name, (expiry, payload) in _MEMORY.items()
                if expiry > now and name not in _TOMBSTONES
            ]
            for prefix in prefixes:
                _delete_remote_prefix(client, prefix)
            if deleted:
                client.delete(*deleted)
            for name, payload, expiry in values:
                client.set(name, payload, ex=max(1, int(expiry - now) + 1))
            _PREFIX_TOMBSTONES.clear()
            _TOMBSTONES.clear()
            _cache_sync_pending = False


def _call(operation: str, fn: Any) -> Any:
    """执行一次 Redis 调用；未启用返回 None，失败记日志并抛 `_Unavailable`。

    刻意捕获 `Exception` 而不是 `redis.RedisError`：DNS 解析失败、TLS 握手失败、socket
    超时在 redis-py 里分属不同异常族，漏一个就会把缓存故障放大成 500。
    """
    client = get_client()
    if client is None:
        return None
    try:
        if _cache_sync_pending:
            _replay_memory_to_redis(client)
        result = fn(client)
        _mark_online()
        return result
    except Exception as exc:  # noqa: BLE001 - 见 docstring
        _mark_offline(exc)
        logger.warning("redis.%s_failed error=%s", operation, type(exc).__name__)
        raise _Unavailable(operation) from exc


# --- 业务读缓存 ---------------------------------------------------------------


def _memory_get(name: str) -> Any | None:
    now = time.monotonic()
    with _MEMORY_LOCK:
        entry = _MEMORY.get(name)
        if entry is None:
            return None
        expires, payload = entry
        if expires <= now:
            _MEMORY.pop(name, None)
            return None
        _MEMORY.move_to_end(name)
        try:
            return json.loads(payload)
        except (TypeError, ValueError):
            _MEMORY.pop(name, None)
            return None


def _memory_set(name: str, payload: str, ttl_s: int) -> None:
    limit = max(1, get_settings().memory_cache_max_entries)
    with _MEMORY_LOCK:
        _MEMORY[name] = (time.monotonic() + ttl_s, payload)
        _MEMORY.move_to_end(name)
        while len(_MEMORY) > limit:
            _MEMORY.popitem(last=False)


def _tombstone(names: Iterator[str] | tuple[str, ...]) -> None:
    """屏蔽远端旧值；未成功同步前不按 TTL / LRU 丢弃这条安全屏障。"""
    settings = get_settings()
    ttl = max(1, settings.session_cache_ttl_s, settings.read_cache_ttl_s)
    limit = max(1, settings.memory_cache_max_entries)
    with _MEMORY_LOCK:
        if not _cache_sync_pending:
            now = time.monotonic()
            for barriers in (_TOMBSTONES, _PREFIX_TOMBSTONES):
                expired = [name for name, expiry in barriers.items() if expiry <= now]
                for name in expired:
                    barriers.pop(name, None)
                while len(barriers) > limit:
                    barriers.popitem(last=False)
        for name in names:
            _MEMORY.pop(name, None)
            _TOMBSTONES[name] = time.monotonic() + ttl
            _TOMBSTONES.move_to_end(name)


def _is_tombstoned(name: str) -> bool:
    with _MEMORY_LOCK:
        now = time.monotonic()
        for prefix, expiry in tuple(_PREFIX_TOMBSTONES.items()):
            if expiry <= now and not _cache_sync_pending:
                _PREFIX_TOMBSTONES.pop(prefix, None)
            elif name.startswith(prefix):
                _PREFIX_TOMBSTONES.move_to_end(prefix)
                return True
        expires = _TOMBSTONES.get(name)
        if expires is None:
            return False
        if expires <= now and not _cache_sync_pending:
            _TOMBSTONES.pop(name, None)
            return False
        _TOMBSTONES.move_to_end(name)
        return True


def cache_get_json(name: str) -> Any | None:
    """优先读进程内副本；Redis 重连不能覆盖更新值或让已删会话复活。"""
    with _cache_sync_lock:
        local = _memory_get(name)
        if local is not None or _is_tombstoned(name) or get_client() is None:
            return local
        try:
            raw = _call("cache_get", lambda client: client.get(name))
        except _Unavailable:
            return None
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        cache_delete(name)
        return None


def cache_set_json(name: str, value: Any, ttl_s: int) -> None:
    """双写 Redis / 内存副本；Redis 后续故障时仍可读已缓存的会话和报告。"""
    if ttl_s <= 0:
        return
    try:
        payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        return
    with _cache_sync_lock:
        with _MEMORY_LOCK:
            _TOMBSTONES.pop(name, None)
            # 保留前缀屏障：回放时先清掉同前缀旧值，再按顺序写入这个新值。
            _memory_set(name, payload, ttl_s)
        try:
            _call("cache_set", lambda client: client.set(name, payload, ex=ttl_s))
        except _Unavailable:
            return


def cache_delete(*names: str) -> None:
    """两个缓存层同时失效，避免 Redis 恢复后读到旧会话。"""
    names = tuple(name for name in names if name)
    if not names:
        return
    _tombstone(names)
    try:
        with _cache_sync_lock:
            _call("cache_delete", lambda client: client.delete(*names))
    except _Unavailable:
        return


def _delete_remote_prefix(client: redis.Redis, prefix: str) -> int:
    deleted = 0
    batch: list[str] = []
    for found in client.scan_iter(match=f"{prefix}*", count=200):
        batch.append(found)
        if len(batch) >= 200:
            deleted += int(client.delete(*batch))
            batch.clear()
    if batch:
        deleted += int(client.delete(*batch))
    return deleted


def cache_delete_prefix(prefix: str) -> int:
    """Redis 用 SCAN；内存层同前缀即时清理。"""
    settings = get_settings()
    with _MEMORY_LOCK:
        names = tuple(name for name in _MEMORY if name.startswith(prefix))
        _PREFIX_TOMBSTONES[prefix] = time.monotonic() + max(
            1, settings.session_cache_ttl_s, settings.read_cache_ttl_s
        )
        _PREFIX_TOMBSTONES.move_to_end(prefix)
    _tombstone(iter(names))
    deleted = len(names)
    try:
        client = get_client()
        if client is None:
            return deleted
        with _cache_sync_lock:
            if _cache_sync_pending:
                _replay_memory_to_redis(client)
            deleted += _delete_remote_prefix(client, prefix)
            _mark_online()
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
    remote_acquired = False
    deadline = time.monotonic() + max(0.0, wait)
    try:
        while True:
            try:
                acquired = bool(client.set(full, token, nx=True, ex=ttl))
                remote_acquired = acquired
            except Exception as exc:  # noqa: BLE001 - 见 _call 的说明
                _mark_offline(exc)
                acquired = True  # 降级：允许继续，不因 Redis 故障阻塞后台任务
                break
            if acquired or time.monotonic() >= deadline:
                break
            time.sleep(0.05)
        yield acquired
    finally:
        if remote_acquired:
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
