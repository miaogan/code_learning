"""唯一 SQL 出口（TECHNICAL §1.4）。

本次 5 个路由器（画像 / 面试 / 笔试 / 报告 / 历史）都读写同一批表：SQL 一旦散在路由层，
字段名、排序口径与 JSON 反序列化就会各写一遍并各自漂移。因此这里集中：

- 所有 `INSERT / SELECT / UPDATE` 只出现在本文件；
- `payload JSON` 列的 `model_validate_json` / `json.loads` 也只在这里；
- **查不到返回 `None`，不抛异常** —— 由路由层翻成 `NOT_FOUND` 中文提示，这是错误映射的唯一分工点。
"""

import json
import sqlite3
from datetime import UTC, datetime
from typing import Any

from .db import connection
from .schemas import Profile, Report, ResumeMeta

RUN_RUNNING = "running"
RUN_COMPLETED = "completed"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _row_payload(row: sqlite3.Row) -> dict[str, Any]:
    payload = json.loads(row["payload"])
    return payload if isinstance(payload, dict) else {}


def _run_dict(row: sqlite3.Row) -> dict[str, Any]:
    """runs 行 → 服务层通用字典（payload 已解析，供面试 / 笔试 / 报告 / 历史共用）。"""
    return {
        "id": row["id"],
        "kind": row["kind"],
        "profile_id": row["profile_id"],
        "payload": _row_payload(row),
        "status": row["status"],
        "created_at": row["created_at"],
    }


# --- documents -----------------------------------------------------------


def insert_document(meta: ResumeMeta, text: str, *, mime: str = "application/octet-stream") -> None:
    """抽取正文入库（原文件不落盘）。

    `ResumeMeta` 无 mime 字段，故 mime 由调用方传入，缺省记通用二进制 MIME；
    上传路由传真实 `content_type`，与 `documents.mime` 列口径保持一致。
    """
    with connection() as conn:
        conn.execute(
            "INSERT INTO documents (id, file_name, mime, chars, sections, text, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                meta.resume_id,
                meta.file_name,
                mime,
                meta.chars,
                meta.sections,
                text,
                _now(),
            ),
        )


def get_document_text(document_id: str) -> str | None:
    with connection() as conn:
        row = conn.execute("SELECT text FROM documents WHERE id = ?", (document_id,)).fetchone()
    return None if row is None else str(row["text"])


# --- profiles ------------------------------------------------------------

_PROFILE_UPSERT = (
    "INSERT INTO profiles (id, document_id, payload, created_at, updated_at) "
    "VALUES (?, ?, ?, ?, ?) "
    "ON CONFLICT(id) DO UPDATE SET payload = excluded.payload, updated_at = excluded.updated_at"
)


def insert_profile(profile: Profile) -> None:
    now = _now()
    with connection() as conn:
        conn.execute(
            _PROFILE_UPSERT,
            (
                profile.id,
                profile.resume_id,
                profile.model_dump_json(),
                now,
                profile.updated_at or now,
            ),
        )


def save_profile(profile: Profile) -> None:
    """编辑后覆盖写：`updated_at` 由调用方刷新，payload 以调用方传入为唯一真值。"""
    insert_profile(profile)


def _profile_of(row: sqlite3.Row) -> Profile:
    return Profile.model_validate_json(row["payload"])


def get_profile(profile_id: str) -> Profile | None:
    with connection() as conn:
        row = conn.execute("SELECT payload FROM profiles WHERE id = ?", (profile_id,)).fetchone()
    return None if row is None else _profile_of(row)


def latest_profile() -> Profile | None:
    with connection() as conn:
        row = conn.execute(
            "SELECT payload FROM profiles ORDER BY updated_at DESC LIMIT 1"
        ).fetchone()
    return None if row is None else _profile_of(row)


# --- runs ----------------------------------------------------------------


def insert_run(run_id: str, kind: str, profile_id: str, payload: dict[str, Any]) -> None:
    with connection() as conn:
        conn.execute(
            "INSERT INTO runs (id, kind, profile_id, payload, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                run_id,
                kind,
                profile_id,
                json.dumps(payload, ensure_ascii=False),
                RUN_RUNNING,
                _now(),
            ),
        )


def get_run(run_id: str) -> dict[str, Any] | None:
    with connection() as conn:
        row = conn.execute(
            "SELECT id, kind, profile_id, payload, status, created_at FROM runs WHERE id = ?",
            (run_id,),
        ).fetchone()
    return None if row is None else _run_dict(row)


def save_run(run_id: str, payload: dict[str, Any], status: str) -> None:
    with connection() as conn:
        conn.execute(
            "UPDATE runs SET payload = ?, status = ? WHERE id = ?",
            (json.dumps(payload, ensure_ascii=False), status, run_id),
        )


def list_runs(kind: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    """按创建时间倒序（报告与历史页都依赖这个顺序，调用方不得二次排序）。"""
    sql = "SELECT id, kind, profile_id, payload, status, created_at FROM runs"
    params: tuple[Any, ...]
    if kind is None:
        sql += " ORDER BY created_at DESC LIMIT ?"
        params = (limit,)
    else:
        sql += " WHERE kind = ? ORDER BY created_at DESC LIMIT ?"
        params = (kind, limit)
    with connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_run_dict(row) for row in rows]


# --- reports -------------------------------------------------------------


def insert_report(report: Report) -> None:
    with connection() as conn:
        conn.execute(
            "INSERT INTO reports (id, payload, created_at) VALUES (?, ?, ?)",
            (report.id, report.model_dump_json(), report.generated_at or _now()),
        )


def _report_of(row: sqlite3.Row) -> Report:
    return Report.model_validate_json(row["payload"])


def get_report(report_id: str) -> Report | None:
    with connection() as conn:
        row = conn.execute("SELECT payload FROM reports WHERE id = ?", (report_id,)).fetchone()
    return None if row is None else _report_of(row)


def latest_report() -> Report | None:
    with connection() as conn:
        row = conn.execute(
            "SELECT payload FROM reports ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    return None if row is None else _report_of(row)
