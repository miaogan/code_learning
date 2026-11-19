"""r138 活跃日聚合：把测评 / 演武 / 学堂三类原始时间折成用户时区的日键。

前端 `StreakBadge` 过去的口径只有「已完成面试/笔试」，与「连续学习」这个名字不符；
这里从 `repository.activity_timestamps()` 取三类原始时间，按调用方给的**当前时区偏移**
折算本机日键再去重。偏移由浏览器 `getTimezoneOffset()` 提供（分钟，UTC+8 = -480），
服务端不做 IANA 时区库依赖，也不做历史 DST 还原——这个徽章只看最近几百天的活跃日，
用当前偏移足够且跨平台一致。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from typing import Any

from app.core import repository

#: 默认覆盖 400 天：比旧 `/api/history?limit=200` 的硬上限更宽，又不至于把响应撑大。
DEFAULT_DAY_LIMIT = 400
MAX_DAY_LIMIT = 1000
_MIN_OFFSET_MIN = -840
_MAX_OFFSET_MIN = 840


def _local_zone(tz_offset: int) -> timezone:
    """越界偏移夹到合法区间，避免构造 timezone 时抛栈（路由层已校验，这里是防御）。"""
    # 浏览器 getTimezoneOffset 的符号与 Python 相反：UTC+8 → -480 → Python +480。
    minutes = -max(_MIN_OFFSET_MIN, min(_MAX_OFFSET_MIN, int(tz_offset)))
    return timezone(timedelta(minutes=minutes))


def _day_key(raw: str, source: str, zone: timezone) -> str | None:
    """原始时间 → 本地 YYYY-MM-DD；脏值返回 None（徽章是锦上添花，绝不因此报错）。"""
    try:
        if source == "tutorial":
            millis = int(str(raw).strip())
            if millis <= 0:
                return None
            moment = datetime.fromtimestamp(millis / 1000, tz=UTC)
        else:
            text = str(raw or "").strip()
            if not text:
                return None
            moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=UTC)
    except (ValueError, OverflowError, OSError):
        return None
    return moment.astimezone(zone).date().isoformat()


def activity_days(*, tz_offset: int, limit: int = DEFAULT_DAY_LIMIT) -> dict[str, Any]:
    """返回按本地日键去重的活跃日（新→旧），`total` 是去重后总天数（截断前）。"""
    zone = _local_zone(tz_offset)
    days: set[str] = set()
    for raw, source in repository.activity_timestamps():
        key = _day_key(raw, source, zone)
        if key is not None:
            days.add(key)
    ordered = sorted(days, reverse=True)[: max(1, min(int(limit), MAX_DAY_LIMIT))]
    return {"days": ordered, "total": len(days), "tz_offset": int(tz_offset)}
