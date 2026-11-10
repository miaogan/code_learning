"""r67 采集排程（**纯函数 + 一个极简循环**）：应用内定时，不引 APScheduler。

口径（TECHNICAL §3）：每天 `RADAR_SLOTS`（默认 `08:00,12:00,18:00`，东八区）各跑一轮；
跨日时「18:00 之后 → 次日 08:00」。停摆 / 重启后的补跑只补**最近一个已到的时点**，
不追补历史窗口（`is_due` 只看「上一轮是否早于最近时点」）。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, time, timedelta, timezone

from app.services.radar import normalize

logger = logging.getLogger("app.radar.schedule")

#: 东八区固定偏移（产品只有一个时区，不引 tz 数据库）。
CN_TZ = timezone(timedelta(hours=8))
#: 循环检查间隔：一分钟一次足够（最粗的时点粒度也是分钟）。
CHECK_INTERVAL_S = 60


def parse_slots(raw: str) -> list[time]:
    """`08:00,12:00,18:00` → 去重升序的 time 列表；非法项静默丢弃（配置脏值不该让服务起不来）。"""
    slots: set[time] = set()
    for piece in (raw or "").split(","):
        text = piece.strip()
        if not text:
            continue
        try:
            slots.add(datetime.strptime(text, "%H:%M").time())
        except ValueError:
            logger.warning("radar.schedule.bad_slot slot=%s", text)
    return sorted(slots)


def last_slot_at(now: datetime, slots: list[time]) -> datetime | None:
    """最近一个「已到」的时点（含当天；当天都还没到则回落到昨天最后一个时点）。"""
    if not slots:
        return None
    local = now.astimezone(CN_TZ)
    for slot in reversed(slots):
        candidate = datetime.combine(local.date(), slot, tzinfo=CN_TZ)
        if candidate <= local:
            return candidate
    return datetime.combine(local.date() - timedelta(days=1), slots[-1], tzinfo=CN_TZ)


def next_run_at(now: datetime, slots: list[time]) -> str | None:
    """下一次时点（东八区 ISO8601）；无有效时点返回 None。"""
    if not slots:
        return None
    local = now.astimezone(CN_TZ)
    for slot in slots:
        candidate = datetime.combine(local.date(), slot, tzinfo=CN_TZ)
        if candidate > local:
            return candidate.isoformat(timespec="seconds")
    return datetime.combine(local.date() + timedelta(days=1), slots[0], tzinfo=CN_TZ).isoformat(
        timespec="seconds"
    )


def is_due(last_started_at: str, now: datetime, slots: list[time]) -> bool:
    """是否该跑：上一轮早于最近时点（或从未跑过 / 时间不可解）即为到期。"""
    slot = last_slot_at(now, slots)
    if slot is None:
        return False
    started = normalize.parse_time(last_started_at)
    if started is None:
        return True
    return started.astimezone(CN_TZ) < slot


async def run_forever(run_round: Callable[[], Awaitable[None]]) -> None:
    """应用内循环：每分钟检查一次，到期就调 `run_round()`；单轮异常只记日志，不终止循环。"""
    from app.core.config import get_settings
    from app.services.radar import store

    while True:
        await asyncio.sleep(CHECK_INTERVAL_S)
        try:
            slots = parse_slots(get_settings().radar_slots)
            latest = store.latest_run()
            started_at = str(latest.get("started_at") or "") if latest else ""
            if not is_due(started_at, datetime.now(UTC), slots):
                continue
            await run_round()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — 定时任务不能因单轮失败而整体退出
            logger.exception("radar.schedule.round_failed")
