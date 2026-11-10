"""r67 技术雷达编排层：采集 → 归一化 → 评估 → 清单；定时轮次与应用内调度生命周期。

一轮的顺序是**先读旧快照再写新快照**（`previous_stars` 要在 `insert_snapshot` 之前取），
否则「7 日 star 增量」永远是 0。评估分两轨：规则基线全量写入，模型细化只给本轮排名最前的
`RADAR_MAX_ASSESS_PER_ROUND` 条（r53 的「离线回归 ≠ 模型质量」同源纪律：模型不可用时规则结论就是结论）。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

from app.core.config import get_settings
from app.core.errors import AppError
from app.services.ai import user_ai
from app.services.radar import assess, normalize, rules, schedule, sources, store

logger = logging.getLogger("app.radar")

PROMPT_VERSION = assess.PROMPT_VERSION

_scheduler: asyncio.Task[None] | None = None


async def run_round(trigger: str = "schedule", user: dict[str, Any] | None = None) -> dict[str, Any]:
    """跑一轮采集 + 评估，返回 `{run_id, started_at, finished_at, sources, notice, ...}`。"""
    settings = get_settings()
    run_id = store.create_run(trigger)
    items, status, degraded = await sources.fetch_all(settings)
    summary = assess.profile_summary()
    digest = assess.profile_digest(summary)
    notes: list[str] = []
    pending: list[dict[str, Any]] = []

    for item in items[: max(int(settings.radar_run_max_techs), 1)]:
        store.upsert_tech(item)
        previous = store.previous_stars(item["slug"])
        store.insert_snapshot(item)
        signals = normalize.signals_of(item, previous)
        result = rules.rule_assess(signals, summary)
        sha = assess.input_sha256(item, signals, digest)
        store.insert_assessment(
            item["slug"],
            run_id,
            result,
            input_sha256=sha,
            profile_digest=digest,
            prompt_version=PROMPT_VERSION,
            model="rule",
            rule_based=True,
        )
        pending.append({"item": item, "signals": signals, "sha": sha, "result": result})

    dropped_total = await _refine_top(pending, summary, digest, run_id, user, notes)

    if settings.radar_offline:
        notes.insert(0, "当前为离线模式，本轮只读取内置样本")
    elif degraded:
        notes.insert(0, "部分信息源本轮不可用，只覆盖可用的来源")
    if dropped_total:
        notes.append(f"已丢弃 {dropped_total} 条无依据的模型引用")

    store.finish_run(run_id, status, bool(degraded or settings.radar_offline), len(pending))
    return {**store.latest_run(), "notice": "；".join(notes)}


async def _refine_top(
    pending: list[dict[str, Any]],
    summary: dict[str, Any],
    digest: str,
    run_id: int,
    user: dict[str, Any] | None,
    notes: list[str],
) -> int:
    """对本轮排名最前的几条做模型细化；无 Key / 无账号 / 模型失败都**静默回落规则结论**。"""
    settings = get_settings()
    limit = max(int(settings.radar_max_assess_per_round), 0)
    if user is None or limit == 0 or not pending:
        return 0
    ranked = sorted(pending, key=lambda row: rules.sort_key({**row["item"], **row["result"]}))
    try:
        client = user_ai.client_for(user, "light")
    except AppError as error:
        notes.append(f"未做模型细化：{error.message}")
        return 0
    model = str(getattr(settings.resolve_ai(), "model", "") or "")
    dropped = 0
    for row in ranked[:limit]:
        try:
            refined = await assess.model_assess(row["item"], row["signals"], summary, client)
        except asyncio.CancelledError:
            raise
        except AppError as error:
            notes.append(f"模型细化中断：{error.message}")
            break
        except Exception:  # noqa: BLE001 — 单条细化失败不该让整轮采集失败
            logger.exception("radar.assess.model_failed slug=%s", row["item"].get("slug"))
            notes.append("模型细化中断，本轮其余条目只用规则结论")
            break
        dropped += int(refined.pop("dropped_evidence", 0))
        store.insert_assessment(
            row["item"]["slug"],
            run_id,
            refined,
            input_sha256=assess.model_sha(row["sha"]),
            profile_digest=digest,
            prompt_version=PROMPT_VERSION,
            model=model or "model",
            rule_based=False,
        )
    return dropped


async def ingest_manual(entry: dict[str, Any], user: dict[str, Any] | None = None) -> dict[str, Any]:
    """手工录入一条线索：不联网，直接落清单 + 规则评估（可选模型细化），回读完整投影。

    返回的形状与 `store.list_techs` 的单条一致（含 `verdict`），路由再补 `verdict_label`。
    """
    raw = {**entry, "source_key": "manual"}
    item = normalize.normalize_item(raw)
    summary = assess.profile_summary()
    digest = assess.profile_digest(summary)
    run_id = store.create_run("manual")
    store.upsert_tech(item)
    previous = store.previous_stars(item["slug"])
    store.insert_snapshot(item)
    signals = normalize.signals_of(item, previous)
    result = rules.rule_assess(signals, summary)
    sha = assess.input_sha256(item, signals, digest)
    store.insert_assessment(
        item["slug"],
        run_id,
        result,
        input_sha256=sha,
        profile_digest=digest,
        prompt_version=PROMPT_VERSION,
        model="rule",
        rule_based=True,
    )
    notes: list[str] = []
    await _refine_top(
        [{"item": item, "signals": signals, "sha": sha, "result": result}],
        summary,
        digest,
        run_id,
        user,
        notes,
    )
    store.finish_run(
        run_id,
        [{"source_key": "manual", "status": "ok", "items": 1, "latency_ms": 0,
          "message": "手工录入"}],
        False,
        1,
    )
    rows = store.list_techs(1, tech_slug=item["slug"])
    return rows[0] if rows else {
        **item,
        "tech_slug": item["slug"],
        **{key: result[key] for key in ("verdict", "relevance", "adoption", "maturity", "effort",
                                        "reasons", "evidence")},
    }


async def _scheduled_round() -> None:
    await run_round(trigger="schedule", user=None)


def start_scheduler() -> None:
    """应用内定时：`RADAR_SCHEDULE=inapp` 才启动（`off` 时完全由手动按钮驱动）。"""
    global _scheduler
    if _scheduler is not None or get_settings().radar_schedule != "inapp":
        return
    _scheduler = asyncio.create_task(schedule.run_forever(_scheduled_round))


async def stop_scheduler() -> None:
    global _scheduler
    task, _scheduler = _scheduler, None
    if task is None:
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await task


__all__ = [
    "PROMPT_VERSION",
    "ingest_manual",
    "rules",
    "run_round",
    "start_scheduler",
    "stop_scheduler",
    "store",
]
