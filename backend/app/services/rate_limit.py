"""r70 应用层防护：按客户端 IP 的滑动窗口限流 + 全局熔断（单进程内存实现）。

**为什么放在应用层而不是 nginx `limit_req`**：nginx 拒绝时返回 HTML 429/503，会破坏全站
`{"error":{code,message,retryable}}` 的 JSON envelope（`DEPLOY.md` 已记录 413 的同类问题），
前端也无法据 code 给出中文提示。

**客户端 IP 口径**：优先 `X-Real-IP`（`nginx.conf` 用 `$remote_addr` 覆写，且后端 8000 不发布
到宿主机，外部无法伪造）；没有该头时回落连接对端地址（本机 / 测试直连）。注意：经公网隧道
暴露时 `$remote_addr` 是隧道进程地址，全部用户共用一个桶——需按隧道形态放宽上限或让隧道层
透传真实 IP。

**内存实现的前提与 `login_guard.py` 相同**：单进程 uvicorn（uvicorn 默认）；多副本部署前
必须换成共享存储（Redis），否则各副本各自计数。

两个独立能力：

1. `hit()`：同一 IP 在 `rate_limit_window_s` 窗口内的请求数超过分档上限即拒绝（429）；
2. `acquire()/release()`：全局在飞请求上限 + 滚动窗口 5xx 占比阈值，触发后打开熔断（503），
   到 `breaker_open_s` 后放行一个探针，成功即恢复、失败立即再开（半开）。
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from dataclasses import dataclass

from app.core import redis_cache
from app.core.config import get_settings

#: 登录接口单独收紧：暴力破解与 scrypt（n=2^14）计算放大 DoS 都从这里进。
AUTH_PATHS: frozenset[str] = frozenset({"/api/auth/login"})
BUCKET_AUTH = "auth"
BUCKET_API = "api"

#: 防御性上限：来源 IP 异常多时不把内存撑爆（超限时清理已过窗口的键）。
_MAX_ENTRIES = 5000

_LOCK = threading.Lock()
_WINDOWS: dict[tuple[str, str], list[float]] = {}


def _now() -> float:
    """单调时钟（测试可替换，避免 patching 标准库 `time` 影响全进程）。"""
    return time.monotonic()


def bucket_of(path: str) -> str:
    return BUCKET_AUTH if path in AUTH_PATHS else BUCKET_API


def client_ip(real_ip: str | None, fallback: str | None) -> str:
    """`X-Real-IP` 优先；都没有时用连接对端地址，最后兜底 `unknown`。"""
    for candidate in (real_ip, fallback):
        value = (candidate or "").strip()
        if value:
            return value
    return "unknown"


def hit(ip: str, bucket: str) -> int:
    """记一次请求并返回需等待的秒数；`0` = 放行。

    被拒绝的请求同样计入窗口：持续洪泛不应在窗口刚滑过时立刻拿回满额。

    r98：**窗口优先放 Redis**。进程内窗口在多副本下的错误是「每个副本各放 limits 次」，
    实际放行量是配置值的 N 倍——这是限流最容易骗过自己的形态（压测单副本永远看不出）。
    Redis 不可用才回落进程内窗口：宁可限流精度退化，也不能让 Redis 故障变成 503。
    """
    settings = get_settings()
    if not settings.rate_limit_enabled:
        return 0
    limit = _limit_of(bucket)
    if limit <= 0:
        return 0
    window = max(1, int(settings.rate_limit_window_s))
    shared = redis_cache.window_hit(redis_cache.key("rl", bucket, ip), window, limit)
    if shared is not None:
        allowed, retry = shared
        return 0 if allowed else max(1, retry)
    now = _now()
    key = (bucket, ip)
    with _LOCK:
        stamps = [stamp for stamp in _WINDOWS.get(key, []) if now - stamp < window]
        stamps.append(now)
        _store(key, stamps)
        if len(stamps) <= limit:
            return 0
        # 要让窗口内数量降到 limit，须等第 (len - limit) 个最旧时间戳滑出窗口。
        wait = stamps[len(stamps) - limit - 1] + window - now
        return max(1, int(math.ceil(wait)))


def _limit_of(bucket: str) -> int:
    settings = get_settings()
    if bucket == BUCKET_AUTH:
        return int(settings.rate_limit_auth_per_window)
    return int(settings.rate_limit_api_per_window)


def _store(key: tuple[str, str], stamps: list[float]) -> None:
    _WINDOWS[key] = stamps
    if len(_WINDOWS) <= _MAX_ENTRIES:
        return
    window = max(1, int(get_settings().rate_limit_window_s))
    now = _now()
    stale = [name for name, values in _WINDOWS.items() if not values or now - values[-1] >= window]
    for name in stale:
        _WINDOWS.pop(name, None)


@dataclass(frozen=True)
class Passage:
    """一次熔断准入的结果：`allowed=False` 时 `retry_after` 为建议重试秒数。"""

    allowed: bool
    retry_after: int = 0
    probe: bool = False


class _Breaker:
    """在飞上限 + 滚动窗口错误率的熔断状态机（打开 / 半开 / 关闭）。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._inflight = 0
        self._open_until = 0.0
        self._probing = False
        self._samples: deque[tuple[float, bool]] = deque()

    def acquire(self) -> Passage:
        settings = get_settings()
        if not settings.breaker_enabled:
            return Passage(allowed=True)
        now = _now()
        with self._lock:
            if self._open_until > now:
                return Passage(allowed=False, retry_after=max(1, math.ceil(self._open_until - now)))
            if self._open_until:
                # 半开：只放一个探针，其余继续快速失败，避免恢复瞬间被洪峰压垮。
                if self._probing:
                    return Passage(allowed=False, retry_after=1)
                self._probing = True
                return Passage(allowed=True, probe=True)
            if self._inflight >= max(1, int(settings.breaker_max_inflight)):
                return Passage(allowed=False, retry_after=1)
            self._inflight += 1
            return Passage(allowed=True)

    def release(self, passage: Passage, status: int) -> None:
        """归还准入并记录结果；只有 5xx 计入失败（4xx 是正常业务反馈）。"""
        settings = get_settings()
        if not passage.allowed or not settings.breaker_enabled:
            return
        failed = status >= 500
        now = _now()
        with self._lock:
            if passage.probe:
                self._probing = False
                self._samples.clear()
                if failed:
                    self._open_until = now + max(1, int(settings.breaker_open_s))
                else:
                    self._open_until = 0.0
                return
            self._inflight = max(0, self._inflight - 1)
            window = max(1, int(settings.breaker_window_s))
            self._samples.append((now, failed))
            while self._samples and now - self._samples[0][0] >= window:
                self._samples.popleft()
            total = len(self._samples)
            if total < max(1, int(settings.breaker_min_requests)):
                return
            errors = sum(1 for _, is_failed in self._samples if is_failed)
            if errors / total >= float(settings.breaker_error_ratio):
                self._open_until = now + max(1, int(settings.breaker_open_s))
                self._samples.clear()

    def reset(self) -> None:
        with self._lock:
            self._inflight = 0
            self._open_until = 0.0
            self._probing = False
            self._samples.clear()


_BREAKER = _Breaker()


def acquire() -> Passage:
    return _BREAKER.acquire()


def release(passage: Passage, status: int) -> None:
    _BREAKER.release(passage, status)


def reset_all() -> None:
    """清空限流窗口与熔断状态（用例隔离用；生产不调用）。"""
    with _LOCK:
        _WINDOWS.clear()
    _BREAKER.reset()
    redis_cache.cache_delete_prefix(redis_cache.key("rl"))
