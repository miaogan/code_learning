"""r67 雷达仓储层（**委托层**）：塑形 + 状态语义，SQL 全部经 `core/repository.py` 唯一出口。

技术清单 / 快照 / 评估是**全局知识**（不按账号切）；生成任务 `radar_jobs` 带 `user_id`，
读 / 采纳 / 废弃按账号隔离（AC-9）。JSON 列（`chapter_json` / `questions_json` /
`reasons_json` / `sources_json`）的解码归本层，仓储层只负责读写。
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from typing import Any

from app.core import repository
from app.core.context import get_current_user_id

ACTIVE_STATUSES: tuple[str, ...] = ("queued", "running")
TERMINAL_STATUSES: tuple[str, ...] = ("succeeded", "adopted", "discarded", "failed")


def upsert_tech(item: dict[str, Any]) -> None:
    """按 `tech_slug` 幂等写入：已存在只刷新 last_seen 与可变字段（首次见到的时间不动）。"""
    repository.radar_upsert_tech(item)


def insert_snapshot(item: dict[str, Any]) -> None:
    repository.radar_insert_snapshot(item)


def previous_stars(slug: str) -> int | None:
    """最近一条快照的 star 数（第一条快照返回 None，增速按 0 处理）。"""
    return repository.radar_previous_stars(slug)


def insert_assessment(tech_slug: str, run_id: int, result: dict[str, Any], *, input_sha256: str,
                      profile_digest: str, prompt_version: str, model: str,
                      rule_based: bool) -> bool:
    """写一条评估；同 `(tech_slug, input_sha256)` 已存在则跳过（返回 False = 可复算幂等）。"""
    return repository.radar_insert_assessment(
        tech_slug,
        run_id,
        result,
        input_sha256=input_sha256,
        profile_digest=profile_digest,
        prompt_version=prompt_version,
        model=model,
        rule_based=rule_based,
    )


def list_techs(
    limit: int = 50,
    *,
    tech_slug: str = "",
    directions: str | Sequence[str] | None = None,
    verdicts: str | Sequence[str] | None = None,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """技术清单：最新评估 + 最新快照 + 当前在途任务，按评估时间倒序取一页。

    `limit` 是每页条数，`offset` 由调用方按 `(page - 1) * limit` 计算；
    `tech_slug` 非空时只取该条（手工录入后回读用，不让调用方自己拼一份投影）；
    `directions` / `verdicts` 是清单页的多选筛选口径（空 = 不过滤，单值字符串仍兼容）。
    """
    return repository.radar_list_techs(
        limit, tech_slug=tech_slug, directions=directions, verdicts=verdicts, offset=offset
    )


def count_techs(
    *,
    tech_slug: str = "",
    directions: str | Sequence[str] | None = None,
    verdicts: str | Sequence[str] | None = None,
) -> int:
    """技术清单命中总数（与 `list_techs` 同一过滤口径），供分页器算总页数。"""
    return repository.radar_count_techs(
        tech_slug=tech_slug, directions=directions, verdicts=verdicts
    )


def cross_source_count() -> dict[str, int]:
    """跨源出现次数：同名技术被几个源提到（评估信号之一，无记录记 0）。"""
    return repository.radar_cross_source_count()


def create_run(trigger: str) -> int:
    return repository.radar_create_run(trigger)


def finish_run(run_id: int, sources: list[dict[str, Any]], degraded: bool, techs_seen: int) -> None:
    repository.radar_finish_run(run_id, sources, degraded, techs_seen)


def latest_run() -> dict[str, Any]:
    return repository.radar_latest_run()


def create_job(tech_slug: str, *, trigger: str = "manual", parent_job_id: str = "") -> tuple[str, bool]:
    """建生成任务：命中 active 部分唯一索引时返回**已存在**的 job_id（AC-3 不重复烧 token）。

    该技术正被**其他账号**生成时抛 `ValueError('occupied')`，由路由转成 409 中文提示
    （任务行带 user_id，读路径按账号隔离，不能把别人的 job_id 交给当前用户）。
    """
    job_id = f"rj-{uuid.uuid4().hex[:12]}"
    if repository.radar_insert_job(
        job_id, tech_slug, trigger=trigger, parent_job_id=parent_job_id
    ):
        return job_id, False
    active = repository.radar_active_job(tech_slug)
    if active is None or active["user_id"] != get_current_user_id():
        raise ValueError("occupied")
    return active["job_id"], True


def get_job(job_id: str) -> dict[str, Any] | None:
    row = repository.radar_get_job_row(job_id)
    return None if row is None else _job_row(row)


def list_jobs(limit: int = 20, offset: int = 0) -> list[dict[str, Any]]:
    """本账号的样例任务：`limit` 是每页条数，`offset` 由调用方按 `(page - 1) * limit` 计算。"""
    return [_job_row(row) for row in repository.radar_job_rows(limit, offset=offset)]


def count_jobs() -> int:
    """本账号样例任务总数（与 `list_jobs` 同一过滤口径），供分页器算总页数。"""
    return repository.radar_count_jobs()


_JOB_FIELDS = frozenset(
    {"status", "stage", "progress", "chapter_json", "questions_json",
     "discarded_count", "discarded_reasons_json", "error_message"}
)


def update_job(job_id: str, **fields: Any) -> None:
    """按字段名白名单更新任务行（`chapter_json` / `questions_json` 由调用方先序列化）。"""
    payload = {key: value for key, value in fields.items() if key in _JOB_FIELDS}
    repository.radar_update_job(job_id, payload)


def sweep_stale_jobs(minutes: int) -> None:
    """读路径惰性清扫（AC-4）：running 超过阈值按 failed 落库，避免僵尸行永远「生成中」。"""
    repository.radar_sweep_stale_jobs(minutes)


def tech_name(tech_slug: str) -> str:
    return repository.radar_tech_name(tech_slug)


def tech_card(tech_slug: str) -> dict[str, Any] | None:
    """生成用的技术卡片：名称 / 方向 / 简介 / 链接 + 最新评估结论（不存在返回 None）。"""
    return repository.radar_tech_card(tech_slug)


def set_summary_zh(tech_slug: str, summary_zh: str) -> None:
    """写一条中文摘要（r74）：同一个仓库翻译一次即可，之后采集只在原文变化时重翻。"""
    repository.radar_set_summary_zh(tech_slug, summary_zh)


def pending_translation(limit: int) -> list[dict[str, Any]]:
    """有英文摘要但缺中文译文的条目（按最近出现时间取一页），供按需补翻。"""
    return repository.radar_pending_translation(limit)


def count_pending_translation() -> int:
    """待翻译总数（补翻接口回给界面「还剩几条」）。"""
    return repository.radar_count_pending_translation()


def pending_summary(limit: int) -> list[dict[str, Any]]:
    """「标题即简介」的条目（r89）：需要抓正文汇总成中文概要，而不是翻标题。"""
    return repository.radar_pending_summary(limit)


def count_pending_summary() -> int:
    """「标题即简介」条目总数（汇总进度如实回传）。"""
    return repository.radar_count_pending_summary()


def _json_list(text: str | None) -> list[Any]:
    try:
        payload = json.loads(text or "[]")
    except ValueError:
        return []
    return payload if isinstance(payload, list) else []


def _json_counts(text: str | None) -> dict[str, int]:
    """丢弃原因计数：坏值一律当空字典，界面只展示可读的键值对。"""
    try:
        payload = json.loads(text or "{}")
    except ValueError:
        return {}
    if not isinstance(payload, dict):
        return {}
    return {str(key): int(value) for key, value in payload.items() if isinstance(value, int)}


def _job_row(row: Any) -> dict[str, Any]:
    chapter = None
    if row["chapter_json"]:
        try:
            chapter = json.loads(row["chapter_json"])
        except ValueError:
            chapter = None
    return {
        "job_id": row["job_id"],
        "tech_slug": row["tech_slug"],
        "tech_name": tech_name(row["tech_slug"]),
        "status": row["status"],
        "stage": row["stage"],
        "progress": int(row["progress"]),
        "chapter": chapter,
        "questions": _json_list(row["questions_json"]),
        "discarded_count": int(row["discarded_count"]),
        "discarded_reasons": _json_counts(row["discarded_reasons_json"]),
        "error_message": row["error_message"],
        "trigger": row["trigger"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
