"""登录失败限流（r23 P2）：按邮箱做滑动窗口计数，达到阈值后锁定一段时间。

内存实现即可：本产品是单进程 uvicorn 部署，进程重启时锁定状态随之清空是可接受的；
多进程部署前需要换成共享存储（SQLite 表或 Redis），届时只改本模块内部即可。

防枚举口径：调用方对「邮箱不存在」与「密码不正确」一视同仁地记一次失败，
限流因此不会额外泄漏账号是否存在。
"""

from __future__ import annotations

import threading
import time

from ..config import get_settings

#: 窗口内保留的时间戳；进程被多请求并发读写，需加锁。
_LOCK = threading.Lock()
_FAILURES: dict[str, list[float]] = {}

#: 防御性上限：异常多的邮箱（如攻击者随便填）不应把内存撑爆。
_MAX_ENTRIES = 5000


def _window_seconds() -> float:
    """失败计数窗口 = 锁定时长（同一口径，避免出现「窗口已过但仍在锁」的空档）。"""
    return max(1, get_settings().login_lockout_minutes) * 60.0


def _prune(stamps: list[float], now: float, window: float) -> list[float]:
    return [stamp for stamp in stamps if now - stamp < window]


def retry_after(email: str) -> int:
    """距离解锁还需的秒数；`0` 表示当前可继续尝试登录。"""
    limit = get_settings().login_max_failures
    if limit <= 0:
        return 0
    now = time.monotonic()
    window = _window_seconds()
    with _LOCK:
        stamps = _prune(_FAILURES.get(email, []), now, window)
        if len(stamps) < limit:
            _store(email, stamps)
            return 0
        locked_until = stamps[-limit] + window
        remaining = locked_until - now
        if remaining <= 0:
            _FAILURES.pop(email, None)
            return 0
        return int(remaining) + 1


def register_failure(email: str) -> None:
    """记录一次失败；窗口外的旧记录顺带清掉。"""
    now = time.monotonic()
    window = _window_seconds()
    with _LOCK:
        stamps = _prune(_FAILURES.get(email, []), now, window)
        stamps.append(now)
        _store(email, stamps)


def clear(email: str) -> None:
    """登录成功后清零，避免偶发失败的累计影响下一次。"""
    with _LOCK:
        _FAILURES.pop(email, None)


def reset_all() -> None:
    """清空全部状态（测试与排障用）。"""
    with _LOCK:
        _FAILURES.clear()


def _store(email: str, stamps: list[float]) -> None:
    """写入（调用方必须持锁）；空列表即删除，并顺带做一次容量保护。"""
    if stamps:
        _FAILURES[email] = stamps
    else:
        _FAILURES.pop(email, None)
    if len(_FAILURES) > _MAX_ENTRIES:
        # 只按窗口清理一次即可，极端场景下仍可能超限，但足以避免无界增长。
        now = time.monotonic()
        window = _window_seconds()
        stale = [key for key, value in _FAILURES.items() if not _prune(value, now, window)]
        for key in stale:
            _FAILURES.pop(key, None)
