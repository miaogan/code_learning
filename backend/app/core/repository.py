"""唯一 SQL 出口（TECHNICAL §1.4）。

本次 5 个路由器（画像 / 面试 / 笔试 / 报告 / 历史）都读写同一批表：SQL 一旦散在路由层，
字段名、排序口径与 JSON 反序列化就会各写一遍并各自漂移。因此这里集中：

- 所有 `INSERT / SELECT / UPDATE` 只出现在本文件；
- `payload JSON` 列的 `model_validate_json` / `json.loads` 也只在这里；
- **查不到返回 `None`，不抛异常** —— 由路由层翻成 `NOT_FOUND` 中文提示，这是错误映射的唯一分工点。
"""

import json
import math
import sqlite3
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.core.context import DEFAULT_USER_ID, get_current_user_id
from app.core.db import connection
from app.schemas import Profile, Report, ResumeMeta, TimelineEvent

RUN_RUNNING = "running"
RUN_COMPLETED = "completed"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _uid() -> str:
    """当前用户 id（`deps.current_user` 写入 ContextVar；默认 `'default'` 供 CLI / 存量数据）。"""
    return get_current_user_id()


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
            "INSERT INTO documents "
            "(id, user_id, file_name, mime, chars, sections, text, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                meta.resume_id,
                _uid(),
                meta.file_name,
                mime,
                meta.chars,
                meta.sections,
                text,
                _now(),
            ),
        )


def get_document(document_id: str) -> dict[str, Any] | None:
    """文档元信息 + 正文：`{text, file_name, created_at}`，查不到 `None`。

    画像合并要「来源文件名 / 抓取时间」写进证据链，润色要正文与文件名 —— 三者同一行，
    故一次读出；`get_document_text` 复用它，读路径因此只有一份 SQL。
    """
    with connection() as conn:
        row = conn.execute(
            "SELECT text, file_name, created_at FROM documents WHERE id = ? AND user_id = ?",
            (document_id, _uid()),
        ).fetchone()
    if row is None:
        return None
    return {
        "text": str(row["text"]),
        "file_name": row["file_name"],
        "created_at": row["created_at"],
    }


def get_document_text(document_id: str) -> str | None:
    document = get_document(document_id)
    return None if document is None else str(document["text"])


def get_document_stats(document_id: str) -> dict[str, Any] | None:
    """文档展示元信息（file_name / chars / sections），查不到 `None`。

    异步画像任务（r30）受理时用它把展示元信息定格进 `profile_jobs` 行，
    轮询响应无需再回查 documents 表。
    """
    with connection() as conn:
        row = conn.execute(
            "SELECT file_name, chars, sections FROM documents WHERE id = ? AND user_id = ?",
            (document_id, _uid()),
        ).fetchone()
    if row is None:
        return None
    return {
        "file_name": str(row["file_name"]),
        "chars": int(row["chars"]),
        "sections": int(row["sections"]),
    }


def get_document_version(document_id: str) -> dict[str, Any] | None:
    """简历版本详情元信息（`get_document_stats` 的补集：含 mime 与上传时间，仍不含正文）。"""
    with connection() as conn:
        row = conn.execute(
            "SELECT file_name, mime, chars, sections, created_at FROM documents "
            "WHERE id = ? AND user_id = ?",
            (document_id, _uid()),
        ).fetchone()
    if row is None:
        return None
    return {
        "file_name": str(row["file_name"]),
        "mime": str(row["mime"] or ""),
        "chars": int(row["chars"]),
        "sections": int(row["sections"]),
        "created_at": str(row["created_at"]),
    }


def list_documents(limit: int = 20) -> list[dict[str, Any]]:
    """简历版本列表（上传时间倒序）：只取展示元信息，正文不参与（r60 版本对比）。"""
    with connection() as conn:
        rows = conn.execute(
            "SELECT id, file_name, mime, chars, sections, created_at FROM documents "
            "WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
            (_uid(), limit),
        ).fetchall()
    return [
        {
            "resume_id": row["id"],
            "file_name": row["file_name"],
            "mime": str(row["mime"] or ""),
            "chars": int(row["chars"]),
            "sections": int(row["sections"]),
            "created_at": str(row["created_at"]),
        }
        for row in rows
    ]


# --- profiles ------------------------------------------------------------

_PROFILE_UPSERT = (
    "INSERT INTO profiles (id, user_id, document_id, payload, created_at, updated_at) "
    "VALUES (?, ?, ?, ?, ?, ?) "
    "ON CONFLICT(id) DO UPDATE SET payload = excluded.payload, updated_at = excluded.updated_at "
    "WHERE profiles.user_id = excluded.user_id"
)


def insert_profile(profile: Profile) -> None:
    now = _now()
    with connection() as conn:
        conn.execute(
            _PROFILE_UPSERT,
            (
                profile.id,
                _uid(),
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
        row = conn.execute(
            "SELECT payload FROM profiles WHERE id = ? AND user_id = ?", (profile_id, _uid())
        ).fetchone()
    return None if row is None else _profile_of(row)


def latest_profile() -> Profile | None:
    with connection() as conn:
        row = conn.execute(
            "SELECT payload FROM profiles WHERE user_id = ? ORDER BY updated_at DESC LIMIT 1",
            (_uid(),),
        ).fetchone()
    return None if row is None else _profile_of(row)


def latest_profile_for_document(document_id: str) -> Profile | None:
    """某份简历最近一次生成的画像（r60 版本对比：同一份简历多次重算时取最新）。"""
    with connection() as conn:
        row = conn.execute(
            "SELECT payload FROM profiles WHERE user_id = ? AND document_id = ? "
            "ORDER BY updated_at DESC LIMIT 1",
            (_uid(), document_id),
        ).fetchone()
    return None if row is None else _profile_of(row)


# --- profile_jobs（r30 异步画像任务）---------------------------------------


def insert_profile_job(
    job_id: str,
    document_id: str,
    file_name: str,
    chars: int,
    sections: int,
) -> bool:
    """受理一个画像生成后台任务（status=running），返回是否真的新建了任务行。

    受理发生在请求上下文里，`_uid()` 即当前用户；后台任务写状态时显式传
    `user_id`（见 `finish_profile_job` / `fail_profile_job`），不依赖 ContextVar
    在 `asyncio.create_task` 里的隐式传播。

    r42：`(user_id, document_id) WHERE status='running'` 是部分唯一索引，同一简历已有
    在途任务时插入会撞唯一约束 —— 捕获后返回 `False`，由路由层复用既有任务（幂等）。
    """
    try:
        with connection() as conn:
            conn.execute(
                "INSERT INTO profile_jobs "
                "(id, user_id, document_id, file_name, chars, sections, status, error, result, "
                " created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, '', '', ?, ?)",
                (job_id, _uid(), document_id, file_name, chars, sections, "running", _now(), _now()),
            )
        return True
    except sqlite3.IntegrityError:
        return False


def find_running_profile_job(document_id: str) -> dict[str, Any] | None:
    """同一份简历当前在途的画像任务（幂等受理用）；没有则 `None`。"""
    with connection() as conn:
        row = conn.execute(
            "SELECT id, user_id, document_id, file_name, chars, sections, status, error, "
            "result, created_at, updated_at FROM profile_jobs "
            "WHERE user_id = ? AND document_id = ? AND status = 'running' "
            "ORDER BY created_at DESC LIMIT 1",
            (_uid(), document_id),
        ).fetchone()
    return None if row is None else _job_dict(row)


def get_profile_job(job_id: str) -> dict[str, Any] | None:
    """按 id 读任务行（当前用户隔离），查不到 `None`。"""
    with connection() as conn:
        row = conn.execute(
            "SELECT id, user_id, document_id, file_name, chars, sections, status, error, "
            "result, created_at, updated_at FROM profile_jobs WHERE id = ? AND user_id = ?",
            (job_id, _uid()),
        ).fetchone()
    return None if row is None else _job_dict(row)


def latest_profile_job() -> dict[str, Any] | None:
    """当前用户最近一次画像任务（任意状态）：前端「回到上传页自动接上进度」用。"""
    with connection() as conn:
        row = conn.execute(
            "SELECT id, user_id, document_id, file_name, chars, sections, status, error, "
            "result, created_at, updated_at FROM profile_jobs "
            "WHERE user_id = ? ORDER BY created_at DESC LIMIT 1",
            (_uid(),),
        ).fetchone()
    return None if row is None else _job_dict(row)


def expire_stale_profile_jobs(stale_seconds: int) -> int:
    """把停滞的 running 任务行标记为 failed（惰性清扫），返回本次标记的行数。

    后台任务活在进程内存里：uvicorn 重启 / 进程被杀后，没有任何代码会把任务行
    推进到终态，行会永远停在 running —— 前端轮询与重接入都会无限等（r32）。
    读路径上先做一次廉价清扫：`updated_at` 超过 `stale_seconds` 仍 running 的行
    按失败落库（中文原因），轮询与重接入从此拿到确定的 failed 终态。
    """
    cutoff = (datetime.now(UTC) - timedelta(seconds=stale_seconds)).isoformat()
    with connection() as conn:
        cursor = conn.execute(
            "UPDATE profile_jobs SET status = 'failed', error = ?, updated_at = ? "
            "WHERE user_id = ? AND status = 'running' AND updated_at < ?",
            (
                "后台任务长时间没有进展（可能因服务重启而中断），请重新生成画像",
                _now(),
                _uid(),
                cutoff,
            ),
        )
        return cursor.rowcount


def finish_profile_job(job_id: str, result_json: str, *, user_id: str) -> None:
    """后台任务成功：写入 `ProfileWithMerge` JSON（含一次性 merge_summary）。"""
    with connection() as conn:
        conn.execute(
            "UPDATE profile_jobs SET status = 'completed', result = ?, updated_at = ? "
            "WHERE id = ? AND user_id = ?",
            (result_json, _now(), job_id, user_id),
        )


def fail_profile_job(job_id: str, error: str, *, user_id: str) -> None:
    """后台任务失败：落中文原因供轮询端展示；任务本身不重试（前端重试=重新受理）。"""
    with connection() as conn:
        conn.execute(
            "UPDATE profile_jobs SET status = 'failed', error = ?, updated_at = ? "
            "WHERE id = ? AND user_id = ?",
            (error, _now(), job_id, user_id),
        )


def _job_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "job_id": row["id"],
        "document_id": row["document_id"],
        "file_name": row["file_name"],
        "chars": row["chars"],
        "sections": row["sections"],
        "status": row["status"],
        "error": row["error"],
        "result": str(row["result"]) if row["result"] else "",
        "created_at": row["created_at"],
    }


# --- resume_jobs（r42 图片识别后台任务）--------------------------------------


def insert_resume_job(
    job_id: str,
    file_name: str,
    image_count: int,
    content_hash: str,
) -> bool:
    """受理一个图片识别后台任务（status=running），返回是否真的新建了任务行。

    幂等口径与 `insert_profile_job` 一致：`(user_id, content_hash) WHERE status='running'`
    是部分唯一索引，同一批图片已有在途任务时返回 `False`，由路由层复用既有任务。
    """
    try:
        with connection() as conn:
            conn.execute(
                "INSERT INTO resume_jobs "
                "(id, user_id, file_name, image_count, content_hash, status, error, result, "
                " created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'running', '', '', ?, ?)",
                (job_id, _uid(), file_name, image_count, content_hash, _now(), _now()),
            )
        return True
    except sqlite3.IntegrityError:
        return False


def find_running_resume_job(content_hash: str) -> dict[str, Any] | None:
    """同一批图片当前在途的识别任务（幂等受理用）；没有则 `None`。"""
    with connection() as conn:
        row = conn.execute(
            "SELECT id, user_id, file_name, image_count, content_hash, status, error, result, "
            "created_at, updated_at FROM resume_jobs "
            "WHERE user_id = ? AND content_hash = ? AND status = 'running' "
            "ORDER BY created_at DESC LIMIT 1",
            (_uid(), content_hash),
        ).fetchone()
    return None if row is None else _resume_job_dict(row)


def get_resume_job(job_id: str) -> dict[str, Any] | None:
    """按 id 读图片识别任务行（当前用户隔离），查不到 `None`。"""
    with connection() as conn:
        row = conn.execute(
            "SELECT id, user_id, file_name, image_count, content_hash, status, error, result, "
            "created_at, updated_at FROM resume_jobs WHERE id = ? AND user_id = ?",
            (job_id, _uid()),
        ).fetchone()
    return None if row is None else _resume_job_dict(row)


def latest_resume_job() -> dict[str, Any] | None:
    """当前用户最近一次图片识别任务（任意状态）：回上传页自动接上进度用。"""
    with connection() as conn:
        row = conn.execute(
            "SELECT id, user_id, file_name, image_count, content_hash, status, error, result, "
            "created_at, updated_at FROM resume_jobs "
            "WHERE user_id = ? ORDER BY created_at DESC LIMIT 1",
            (_uid(),),
        ).fetchone()
    return None if row is None else _resume_job_dict(row)


def expire_stale_resume_jobs(stale_seconds: int) -> int:
    """把长期无进展（`updated_at` 超阈值）的 running 识别任务标记为 failed。

    任务每识别完一页写一次 `updated_at`（心跳），因此这里衡量的是「无进展」而不是
    「总耗时」；进程重启 / 被回收后无人推进的行同样会在读路径上被收敛，不留永远进行中。
    """
    cutoff = (datetime.now(UTC) - timedelta(seconds=stale_seconds)).isoformat()
    with connection() as conn:
        cursor = conn.execute(
            "UPDATE resume_jobs SET status = 'failed', error = ?, updated_at = ? "
            "WHERE user_id = ? AND status = 'running' AND updated_at < ?",
            (
                "图片识别长时间没有进展（可能因服务重启而中断），请重新上传图片",
                _now(),
                _uid(),
                cutoff,
            ),
        )
        return cursor.rowcount


def touch_resume_job(job_id: str, *, user_id: str) -> None:
    """一页识别完成后的心跳：推进 `updated_at`，让惰性清扫按「无进展」而非总耗时判死。"""
    with connection() as conn:
        conn.execute(
            "UPDATE resume_jobs SET updated_at = ? WHERE id = ? AND user_id = ? AND status = 'running'",
            (_now(), job_id, user_id),
        )


def finish_resume_job(job_id: str, result_json: str, *, user_id: str) -> None:
    """识别成功：写入 `ResumeMeta` JSON（正文已在此之前入库）。"""
    with connection() as conn:
        conn.execute(
            "UPDATE resume_jobs SET status = 'completed', result = ?, updated_at = ? "
            "WHERE id = ? AND user_id = ?",
            (result_json, _now(), job_id, user_id),
        )


def fail_resume_job(job_id: str, error: str, *, user_id: str) -> None:
    """识别失败：落中文原因供轮询端展示；不自动重试（前端重试=重新受理）。"""
    with connection() as conn:
        conn.execute(
            "UPDATE resume_jobs SET status = 'failed', error = ?, updated_at = ? "
            "WHERE id = ? AND user_id = ?",
            (error, _now(), job_id, user_id),
        )


def _resume_job_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "job_id": row["id"],
        "file_name": row["file_name"],
        "image_count": row["image_count"],
        "content_hash": row["content_hash"],
        "status": row["status"],
        "error": row["error"],
        "result": str(row["result"]) if row["result"] else "",
        "created_at": row["created_at"],
    }


# --- runs ----------------------------------------------------------------


def insert_run(run_id: str, kind: str, profile_id: str, payload: dict[str, Any]) -> None:
    with connection() as conn:
        conn.execute(
            "INSERT INTO runs (id, user_id, kind, profile_id, payload, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                _uid(),
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
            "SELECT id, kind, profile_id, payload, status, created_at FROM runs "
            "WHERE id = ? AND user_id = ?",
            (run_id, _uid()),
        ).fetchone()
    return None if row is None else _run_dict(row)


def save_run(run_id: str, payload: dict[str, Any], status: str) -> None:
    with connection() as conn:
        conn.execute(
            "UPDATE runs SET payload = ?, status = ? WHERE id = ? AND user_id = ?",
            (json.dumps(payload, ensure_ascii=False), status, run_id, _uid()),
        )


def list_runs(kind: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    """按创建时间倒序（报告与历史页都依赖这个顺序，调用方不得二次排序）。"""
    sql = "SELECT id, kind, profile_id, payload, status, created_at FROM runs WHERE user_id = ?"
    params: tuple[Any, ...]
    if kind is None:
        sql += " ORDER BY created_at DESC LIMIT ?"
        params = (_uid(), limit)
    else:
        sql += " AND kind = ? ORDER BY created_at DESC LIMIT ?"
        params = (_uid(), kind, limit)
    with connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_run_dict(row) for row in rows]


def _history_kinds(kinds: str | Sequence[str] | None) -> list[str]:
    """归一历史页类型多选：闭集外丢弃；两种类型都选中等价于不筛选（返回空列表）。"""
    picked = [kinds] if isinstance(kinds, str) else list(kinds or [])
    allowed = [kind for kind in picked if kind in ("interview", "exam")]
    return [] if len(set(allowed)) >= 2 else allowed


def history_rows(
    kinds: str | Sequence[str] | None = None, limit: int = 10, offset: int = 0
) -> list[dict[str, Any]]:
    """历史页分页：已完成且 `kind ∈ {interview, exam}` 的 run，倒序（与报告页口径一致）。

    `kinds` 是多选类型（空 = 不筛选 / 全选）；单值字符串仍可用（旧调用方兼容）。
    """
    sql = (
        "SELECT id, kind, profile_id, payload, status, created_at FROM runs"
        " WHERE user_id = ? AND status = ? AND kind IN (?, ?)"
    )
    params: list[Any] = [_uid(), RUN_COMPLETED, "interview", "exam"]
    picked = _history_kinds(kinds)
    if picked:
        sql += " AND kind IN (" + ", ".join("?" for _ in picked) + ")"
        params.extend(picked)
    sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    with connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_run_dict(row) for row in rows]


def count_history_rows(kinds: str | Sequence[str] | None = None) -> int:
    """历史页总数：与 `history_rows` 同一过滤口径，供分页器算总页数。"""
    sql = (
        "SELECT count(*) AS n FROM runs"
        " WHERE user_id = ? AND status = ? AND kind IN (?, ?)"
    )
    params: list[Any] = [_uid(), RUN_COMPLETED, "interview", "exam"]
    picked = _history_kinds(kinds)
    if picked:
        sql += " AND kind IN (" + ", ".join("?" for _ in picked) + ")"
        params.extend(picked)
    with connection() as conn:
        row = conn.execute(sql, params).fetchone()
    return int(row["n"])


def list_runs_for_document(document_id: str, limit: int = 100) -> list[dict[str, Any]]:
    """某份简历关联的**已完成** run（经 `profiles.document_id` 关联，倒序）。

    r60 版本对比要拿「这个简历版本下的测评成绩」：`runs` 只带 `profile_id`，
    而一份简历可能重算过多次画像，故按 `document_id` 聚合（`r.status` 过滤掉在途卷子）。
    """
    with connection() as conn:
        rows = conn.execute(
            "SELECT r.id, r.kind, r.profile_id, r.payload, r.status, r.created_at "
            "FROM runs r JOIN profiles p ON p.id = r.profile_id "
            "WHERE r.user_id = ? AND p.document_id = ? AND r.status = ? "
            "ORDER BY r.created_at DESC LIMIT ?",
            (_uid(), document_id, RUN_COMPLETED, limit),
        ).fetchall()
    return [_run_dict(row) for row in rows]


# --- reports -------------------------------------------------------------


def insert_report(report: Report) -> None:
    with connection() as conn:
        conn.execute(
            "INSERT INTO reports (id, user_id, payload, created_at) VALUES (?, ?, ?, ?)",
            (report.id, _uid(), report.model_dump_json(), report.generated_at or _now()),
        )


def _report_of(row: sqlite3.Row) -> Report:
    return Report.model_validate_json(row["payload"])


def get_report(report_id: str) -> Report | None:
    with connection() as conn:
        row = conn.execute(
            "SELECT payload FROM reports WHERE id = ? AND user_id = ?", (report_id, _uid())
        ).fetchone()
    return None if row is None else _report_of(row)


def latest_report() -> Report | None:
    with connection() as conn:
        row = conn.execute(
            "SELECT payload FROM reports WHERE user_id = ? ORDER BY created_at DESC LIMIT 1",
            (_uid(),),
        ).fetchone()
    return None if row is None else _report_of(row)


def list_reports(limit: int = 2) -> list[Report]:
    """最近 N 份报告（新→旧）。r83 的 `compare_reports` 工具靠它做跨报告对比。

    `brief` 仍只读 `latest_report()`：对比是「用户主动要看」的能力，不该抬高每轮问答的取料成本。
    """
    rows = limit if limit > 0 else 0
    with connection() as conn:
        cursor = conn.execute(
            "SELECT payload FROM reports WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
            (_uid(), rows),
        )
        fetched = cursor.fetchall()
    return [_report_of(row) for row in fetched]


# --- timeline ------------------------------------------------------------

_TIMELINE_INSERT = (
    "INSERT INTO timeline_events (id, user_id, type, ref_id, occurred_at, payload, created_at) "
    "VALUES (?, ?, ?, ?, ?, ?, ?) "
    "ON CONFLICT(type, ref_id) DO NOTHING"
)


def insert_timeline_event(event: TimelineEvent) -> bool:
    """幂等写入时间线事件：插入成功 `True`，同 `(type, ref_id)` 已存在 `False`。

    幂等的最终真值是 `db.py` 的 `UNIQUE(type, ref_id)` 索引，`ON CONFLICT DO NOTHING`
    只负责「撞了也不抛」——写入钩子因此不会因为重复调用把业务流打断（AC-3）。
    """
    with connection() as conn:
        cursor = conn.execute(
            _TIMELINE_INSERT,
            (
                event.id,
                _uid(),
                event.type,
                event.ref_id,
                event.occurred_at,
                event.model_dump_json(),
                _now(),
            ),
        )
        return cursor.rowcount > 0


def _timeline_of(row: sqlite3.Row) -> TimelineEvent:
    return TimelineEvent.model_validate_json(row["payload"])


def get_timeline_event(event_type: str, ref_id: str) -> TimelineEvent | None:
    with connection() as conn:
        row = conn.execute(
            "SELECT payload FROM timeline_events WHERE type = ? AND ref_id = ? AND user_id = ?",
            (event_type, ref_id, _uid()),
        ).fetchone()
    return None if row is None else _timeline_of(row)


def list_timeline_events(limit: int = 20, event_type: str | None = None) -> list[TimelineEvent]:
    """时间线**唯一排序点**（`occurred_at DESC, created_at DESC`）：服务层与前端不得二次排序。"""
    sql = "SELECT payload FROM timeline_events WHERE user_id = ?"
    params: tuple[Any, ...]
    if event_type is None:
        sql += " ORDER BY occurred_at DESC, created_at DESC LIMIT ?"
        params = (_uid(), limit)
    else:
        sql += " AND type = ? ORDER BY occurred_at DESC, created_at DESC LIMIT ?"
        params = (_uid(), event_type, limit)
    with connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_timeline_of(row) for row in rows]


def previous_timeline_event(
    event_type: str, before: str, exclude_id: str = ""
) -> TimelineEvent | None:
    """同类型里严格早于 `before` 的上一条事件（`exclude_id` 排除本次事件，重试时不自比较）。

    严格 `<` 而非 `<=`：同一时刻的事件不构成「上一次」，避免自身/并列事件被当成对比基准。
    """
    with connection() as conn:
        row = conn.execute(
            "SELECT payload FROM timeline_events "
            "WHERE user_id = ? AND type = ? AND occurred_at < ? AND id != ? "
            "ORDER BY occurred_at DESC, created_at DESC LIMIT 1",
            (_uid(), event_type, before, exclude_id),
        ).fetchone()
    return None if row is None else _timeline_of(row)


# --- questions / attempts（r6 题库与作答事件） -------------------------------


def _json_text(value: Any) -> str:
    """JSON 列的唯一编码口径：list → JSON 文本；已是字符串时原样存（调用方自带序列化）。"""
    if isinstance(value, str):
        return value
    return json.dumps(value if value is not None else [], ensure_ascii=False)


def _json_list(value: Any) -> list[Any]:
    """JSON 列的唯一解码口径：坏值 / 非列表一律退化为 `[]`（查不到不抛异常）。"""
    if isinstance(value, list):
        return value
    if not isinstance(value, str):
        return []
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return []
    return decoded if isinstance(decoded, list) else []


_QUESTION_INSERT = (
    "INSERT INTO questions (id, direction, sub_direction, kind, difficulty, essentiality, prompt, "
    "options, answer, source, language, explanation, created_at, updated_at) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
    "ON CONFLICT(id) DO NOTHING"
)

_QUESTION_SELECT = (
    "SELECT id, direction, sub_direction, kind, difficulty, essentiality, prompt, options, answer, source, "
    "language, explanation "
    "FROM questions"
)

#: 存量行「只补空列」的定向 UPDATE（AC-16 / TECHNICAL §2.3）：
#: - `SET` 侧两个 `CASE WHEN col = '' AND ? <> ''` 保证**非空值永不被改写**；
#: - `WHERE` 侧同样要求「该列为空**且**种子给了非空值」，否则 SQLite 会按「匹配到的行」
#:   计 rowcount —— 语言 `''`（通用/算法题）是合法值，缺了这层守卫第二次运行仍会返回 >0，
#:   「幂等（第二次 0 变更）」就不成立。
_QUESTION_FILL = (
    "UPDATE questions SET "
    "language = CASE WHEN language = '' AND ? <> '' THEN ? ELSE language END, "
    "explanation = CASE WHEN explanation = '' AND ? <> '' THEN ? ELSE explanation END, "
    "sub_direction = CASE WHEN sub_direction IS NULL AND ? IS NOT NULL THEN ? ELSE sub_direction END, "
    "updated_at = ? "
    "WHERE id = ? "
    "AND ((language = '' AND ? <> '') OR (explanation = '' AND ? <> '') OR (sub_direction IS NULL AND ? IS NOT NULL))"
)


def _question_insert_row(question: dict[str, Any], now: str) -> tuple[Any, ...]:
    """一条 `questions` 行 → `_QUESTION_INSERT` 的参数元组（单条与批量共用同一形状）。"""
    return (
        question["id"],
        question["direction"],
        question.get("sub_direction"),
        question["kind"],
        question["difficulty"],
        question["essentiality"],
        question["prompt"],
        _json_text(question.get("options")),
        _json_text(question.get("answer")),
        question.get("source") or "seed",
        str(question.get("language") or ""),
        str(question.get("explanation") or ""),
        now,
        now,
    )


def insert_question(question: dict[str, Any]) -> bool:
    """幂等导入单题：新增 `True`，同 `id` 已存在 `False`（**绝不覆盖**既有行，AC-1）。

    幂等的最终真值是 `questions.id` 主键 + `ON CONFLICT(id) DO NOTHING`：重复导入既不新增
    也不改写，标签回填只在首次导入那一刻生效。r11 起 `language` / `explanation` 随行写入，
    缺省空串（`language=''` 表示通用/算法题，是闭集里的合法成员而非"未填"）。
    """
    now = _now()
    with connection() as conn:
        cursor = conn.execute(_QUESTION_INSERT, _question_insert_row(question, now))
        return cursor.rowcount > 0


def insert_questions(questions: Sequence[dict[str, Any]]) -> int:
    """批量幂等导入（r43）：一个连接、一个事务，`executemany` 写完全部行，返回新增行数。

    与逐条 `insert_question()` **同 SQL、同语义**（`ON CONFLICT(id) DO NOTHING`，只增不覆盖）：
    冲突行不产生变更，因此 `total_changes` 的差值就是新增数，重复导入恒 `0`（AC-1 不回退）。
    动机是启动耗时：1088 条逐条写入要 1088 次开连接 / 提事务（实测 11.26s），批量后是亚秒级。
    """
    if not questions:
        return 0
    now = _now()
    rows = [_question_insert_row(question, now) for question in questions]
    with connection() as conn:
        before = conn.total_changes
        conn.executemany(_QUESTION_INSERT, rows)
        return conn.total_changes - before


def _question_of(row: sqlite3.Row) -> dict[str, Any]:
    """questions 行 → 组卷字典（`options` / `answer` 就地解码，服务层不再碰 JSON 文本）。"""
    return {
        "id": row["id"],
        "direction": row["direction"],
        "sub_direction": row["sub_direction"],
        "kind": row["kind"],
        "difficulty": row["difficulty"],
        "essentiality": row["essentiality"],
        "prompt": row["prompt"],
        "options": _json_list(row["options"]),
        "answer": _json_list(row["answer"]),
        "source": row["source"],
        "language": str(row["language"] or ""),
        "explanation": str(row["explanation"] or ""),
    }


def fill_empty_question_columns(rows: list[dict[str, Any]]) -> int:
    """把种子的 `language` / `explanation` / `sub_direction` 补到**空单元格**上，返回实际补齐的行数。

    `ON CONFLICT DO NOTHING` 只保证「不新增、不覆盖」，不补列 —— 存量行若不补，
    筛选与解析会全空。这里题面 / 选项 / 答案 / 难度 / 必备度一律不碰（r6 AC-1 不回退）；
    种子给空串的字段跳过（`language=''` 是通用题的合法取值，`sub_direction=None` 是通用兜底）。
    幂等真值：补齐后该列不再为空，第二次调用返回 0。
    """
    if not rows:
        return 0
    now = _now()
    filled = 0
    with connection() as conn:
        for row in rows:
            question_id = row.get("id")
            language = str(row.get("language") or "")
            explanation = str(row.get("explanation") or "")
            sub_direction = row.get("sub_direction")
            if not question_id or not (language or explanation or sub_direction):
                continue
            cursor = conn.execute(
                _QUESTION_FILL,
                (
                    language, language,
                    explanation, explanation,
                    sub_direction, sub_direction,
                    now, question_id,
                    language, explanation, sub_direction,
                ),
            )
            filled += max(cursor.rowcount, 0)
    return filled


_QUESTION_REFRESH = (
    "UPDATE questions SET direction = ?, sub_direction = ?, kind = ?, difficulty = ?, essentiality = ?, "
    "prompt = ?, options = ?, answer = ?, source = ?, language = ?, explanation = ?, updated_at = ? "
    "WHERE id = ?"
)


def _normalized_question(question: dict[str, Any]) -> dict[str, Any]:
    """种子行 / 库行 → 可逐字段比对的扁平字典（JSON 列统一按序列化文本比，避免 list/dict 顺序噪声）。"""
    return {
        "direction": str(question.get("direction") or ""),
        "sub_direction": question.get("sub_direction"),
        "kind": str(question.get("kind") or ""),
        "difficulty": str(question.get("difficulty") or ""),
        "essentiality": str(question.get("essentiality") or ""),
        "prompt": str(question.get("prompt") or ""),
        "options": _json_text(question.get("options")),
        "answer": _json_text(question.get("answer")),
        "source": str(question.get("source") or "seed"),
        "language": str(question.get("language") or ""),
        "explanation": str(question.get("explanation") or ""),
    }


def refresh_questions(rows: list[dict[str, Any]]) -> int:
    """把种子行**覆写**到已存在的同 id 行，返回真正发生改写的行数（r14 · P3-1）。

    与 `insert_question()` 的分工：导入只增不覆盖（AC-1），这里只覆盖**已存在**的行、绝不新增，
    由 `question_bank.ensure_seeded()` 在启动时调用 —— 让已部署的 `app.core.db` 也能刷到当前种子
    （选项顺序 / 判断题极性 / 答案）。幂等真值：库内已与种子逐字段一致时返回 `0` 且不写 `updated_at`。
    历史 `question_attempts` 只存 `correct`（不存作答 key），覆写题目行不会让历史判分错位。
    """
    if not rows:
        return 0
    changed = 0
    now = _now()
    with connection() as conn:
        existing = {str(row["id"]): _question_of(row) for row in conn.execute(_QUESTION_SELECT).fetchall()}
        for question in rows:
            question_id = str(question.get("id") or "").strip()
            current = existing.get(question_id)
            if current is None:
                continue
            expected = _normalized_question(question)
            if _normalized_question(current) == expected:
                continue
            conn.execute(
                _QUESTION_REFRESH,
                (
                    expected["direction"],
                    expected["sub_direction"],
                    expected["kind"],
                    expected["difficulty"],
                    expected["essentiality"],
                    expected["prompt"],
                    expected["options"],
                    expected["answer"],
                    expected["source"],
                    expected["language"],
                    expected["explanation"],
                    now,
                    question_id,
                ),
            )
            changed += 1
    return changed


def refresh_question(question: dict[str, Any]) -> bool:
    """单题版的 `refresh_questions()`：返回是否发生改写（不新增、无差异不写）。"""
    return refresh_questions([question]) > 0


def list_questions() -> list[dict[str, Any]]:
    """全表按 `id` 升序（排序口径单一来源，服务层不得二次排序）。"""
    with connection() as conn:
        rows = conn.execute(_QUESTION_SELECT + " ORDER BY id").fetchall()
    return [_question_of(row) for row in rows]


def get_question(question_id: str) -> dict[str, Any] | None:
    """单题读取（r82 太傅明细）：主键命中即返回，不存在返回 `None`。

    与 `list_questions()` 共用 `_QUESTION_SELECT` / `_question_of()`，
    不改排序口径、不做二次统计 —— 明细层要的只是「这一题原本长什么样」。
    """
    key = str(question_id or "").strip()
    if not key:
        return None
    with connection() as conn:
        row = conn.execute(_QUESTION_SELECT + " WHERE id = ?", (key,)).fetchone()
    return None if row is None else _question_of(row)


def count_questions() -> int:
    """表内行数：幂等断言与「空库自动种子」判定的唯一读取口径。"""
    with connection() as conn:
        row = conn.execute("SELECT COUNT(*) AS total FROM questions").fetchone()
    return 0 if row is None else int(row["total"])


#: r12 整源剔除的唯一删除口径（占位符按来源个数拼，SQL 骨架仍是常量）：
#: 按 `source` 删而不是按 id 前缀 / 逐条 id —— 存量 260 行是 `'seed'`，永远不会被误伤；
#: 没跑过 `question_merge --write` 的库删 0 行，天然幂等。
_QUESTION_DELETE_BY_SOURCE = "DELETE FROM questions WHERE source IN ({placeholders})"


class DatabaseNotInitialized(RuntimeError):
    """库文件不存在 / 为 0 字节（尚未 `init_db()`）：离线运维命令无从执行，由调用方翻中文提示。"""


def _db_file() -> Path:
    """库文件落点：唯一来源 `config.db_path`，与 `db.connection()` 同一口径。"""
    return Path(get_settings().db_path)


def delete_questions_by_source(sources: Sequence[str]) -> int:
    """按来源批量删除题库行，返回实际删除条数（幂等：再跑一次删 0 行）。

    `source` 的写入点只有离线工具 `question_merge`（存量行不写，读侧缺省 `'seed'`），
    读取点只有 `question_bank._row_of()`；离线工具不自己写 SQL 是因为
    `tests/test_engineering_gates.py::test_sql_only_through_repository` 把本文件定为唯一出口。
    空输入直接返回 0（不打扰库、也不生成非法占位符）；库还没建好时抛
    `DatabaseNotInitialized`，而不是让 `sqlite3.connect()` 顺手留下一个 0 字节文件。
    """
    unique = list(dict.fromkeys(str(source) for source in sources if str(source)))
    if not unique:
        return 0
    db_file = _db_file()
    if not db_file.is_file() or db_file.stat().st_size == 0:
        raise DatabaseNotInitialized(f"库 {db_file.name} 不存在或为 0 字节（尚未初始化）")
    placeholders = ", ".join("?" for _ in unique)
    with connection() as conn:
        cursor = conn.execute(_QUESTION_DELETE_BY_SOURCE.format(placeholders=placeholders), unique)
    return max(cursor.rowcount, 0)


_ATTEMPT_INSERT = (
    "INSERT INTO question_attempts (id, user_id, question_id, run_id, correct, answered_at, "
    "created_at, source) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
    "ON CONFLICT(question_id, run_id) DO NOTHING"
)


def insert_attempts(rows: list[dict[str, Any]]) -> int:
    """单事务批量写作答事件，返回**实际新增**条数。

    幂等真值同样是 `db.py` 的 `UNIQUE(question_id, run_id)`：同卷同题重复提交不会写出
    第二条、也不抛异常；空列表直接返回 0（不打扰库）。
    r11 起每行可带 `source`（'exam' | 'practice'），缺省 `'exam'` —— 读侧一律以列为准。
    """
    if not rows:
        return 0
    with connection() as conn:
        written = 0
        for row in rows:
            cursor = conn.execute(
                _ATTEMPT_INSERT,
                (
                    row["id"],
                    _uid(),
                    row["question_id"],
                    row["run_id"],
                    int(row.get("correct") or 0),
                    row["answered_at"],
                    row.get("created_at") or row["answered_at"],
                    str(row.get("source") or "exam"),
                ),
            )
            written += max(cursor.rowcount, 0)
    return written


def list_attempts() -> list[dict[str, Any]]:
    """全表作答事件，按 `answered_at` 升序（窗口聚合在服务层；同刻用 `created_at`、`id` 定序）。"""
    with connection() as conn:
        rows = conn.execute(
            "SELECT id, question_id, run_id, correct, answered_at, created_at, source "
            "FROM question_attempts WHERE user_id = ? "
            "ORDER BY answered_at ASC, created_at ASC, id ASC",
            (_uid(),),
        ).fetchall()
    return [
        {
            "id": row["id"],
            "question_id": row["question_id"],
            "run_id": row["run_id"],
            "correct": int(row["correct"]),
            "answered_at": row["answered_at"],
            "created_at": row["created_at"],
            "source": str(row["source"] or "exam"),
        }
        for row in rows
    ]


def count_practiced_questions() -> int:
    """有**任何**作答事件的题数（`COUNT(DISTINCT question_id)`，练习 + 笔试都算）。

    `PracticeStats.practiced` 的唯一读取口径（TECHNICAL §5.4 / AC-18 的 m 值）：
    去重按题而非按事件，「同题重练」不会虚增；空库返回 0。
    """
    with connection() as conn:
        row = conn.execute(
            "SELECT COUNT(DISTINCT question_id) AS total FROM question_attempts WHERE user_id = ?",
            (_uid(),),
        ).fetchone()
    return 0 if row is None else int(row["total"])


def list_recent_exam_question_ids(limit: int) -> list[set[str]]:
    """近 `limit` 卷笔试题 id，返回 **newest-first 的 set 列表**（近卷去重的唯一读取口径）。

    只读 `runs.payload.questions[]`，不回查 `questions` 表：去重要对**历史出题事实**生效，
    题库事后改标签不得改写已出过的卷子。`limit <= 0` 返回空列表。
    """
    if limit <= 0:
        return []
    with connection() as conn:
        rows = conn.execute(
            "SELECT payload FROM runs WHERE user_id = ? AND kind = 'exam' "
            "ORDER BY created_at DESC LIMIT ?",
            (_uid(), limit),
        ).fetchall()
    papers: list[set[str]] = []
    for row in rows:
        questions = _row_payload(row).get("questions") or []
        papers.append(
            {
                str(item.get("id"))
                for item in questions
                if isinstance(item, dict) and item.get("id")
            }
        )
    return papers


# --- users / sessions / ai_usage（r23 认证与多用户） --------------------------

_USER_SELECT = (
    "SELECT id, email, password_hash, display_name, role, key_mode, ai_base_url, ai_model, "
    "ai_api_key_enc, ai_json_mode, ai_updated_at, disabled, created_at FROM users"
)


def _user_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "email": row["email"],
        "password_hash": row["password_hash"],
        "display_name": row["display_name"],
        "role": row["role"],
        "key_mode": row["key_mode"],
        "ai_base_url": row["ai_base_url"],
        "ai_model": row["ai_model"],
        "ai_api_key_enc": row["ai_api_key_enc"],
        "ai_json_mode": row["ai_json_mode"],
        "ai_updated_at": row["ai_updated_at"],
        "disabled": bool(row["disabled"]),
        "created_at": row["created_at"],
    }


def create_user(
    *,
    user_id: str,
    email: str,
    password_hash: str,
    display_name: str,
    role: str = "member",
    key_mode: str = "own",
) -> None:
    with connection() as conn:
        conn.execute(
            "INSERT INTO users "
            "(id, email, password_hash, display_name, role, key_mode, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, email, password_hash, display_name, role, key_mode, _now()),
        )


def get_user_by_email(email: str) -> dict[str, Any] | None:
    with connection() as conn:
        row = conn.execute(_USER_SELECT + " WHERE email = ?", (email,)).fetchone()
    return None if row is None else _user_dict(row)


def get_user_by_id(user_id: str) -> dict[str, Any] | None:
    with connection() as conn:
        row = conn.execute(_USER_SELECT + " WHERE id = ?", (user_id,)).fetchone()
    return None if row is None else _user_dict(row)


def list_users() -> list[dict[str, Any]]:
    with connection() as conn:
        rows = conn.execute(_USER_SELECT + " ORDER BY created_at ASC").fetchall()
    return [_user_dict(row) for row in rows]


def update_user_password(user_id: str, password_hash: str) -> None:
    with connection() as conn:
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?", (password_hash, user_id)
        )


def update_user_ai(
    user_id: str,
    *,
    base_url: str,
    model: str,
    api_key_enc: str,
    json_mode: str,
    updated_at: str,
) -> None:
    with connection() as conn:
        conn.execute(
            "UPDATE users SET ai_base_url = ?, ai_model = ?, ai_api_key_enc = ?, "
            "ai_json_mode = ?, ai_updated_at = ? WHERE id = ?",
            (base_url, model, api_key_enc, json_mode, updated_at, user_id),
        )


def update_user_key_mode(user_id: str, key_mode: str) -> None:
    with connection() as conn:
        conn.execute("UPDATE users SET key_mode = ? WHERE id = ?", (key_mode, user_id))


def clear_user_ai_key(user_id: str) -> None:
    """清除自带 Key：保留 Base URL / 模型便于重新填写，能力随之降为 `none`。"""
    with connection() as conn:
        conn.execute(
            "UPDATE users SET ai_api_key_enc = '', ai_updated_at = '' WHERE id = ?",
            (user_id,),
        )


def set_user_disabled(user_id: str, disabled: bool) -> None:
    with connection() as conn:
        conn.execute(
            "UPDATE users SET disabled = ? WHERE id = ?", (1 if disabled else 0, user_id)
        )


def delete_expired_sessions() -> int:
    """批量清理已过期会话（r23 收口）：登录时顺带执行，避免 sessions 表无限累积。"""
    with connection() as conn:
        cursor = conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (_now(),))
        return max(cursor.rowcount, 0)


def create_session(*, token_hash: str, user_id: str, expires_at: str) -> None:
    delete_expired_sessions()
    prune_ai_call_logs()  # r53：与会话清理同一收口点，避免日志表无限增长
    with connection() as conn:
        conn.execute(
            "INSERT INTO sessions (token_hash, user_id, created_at, expires_at) "
            "VALUES (?, ?, ?, ?)",
            (token_hash, user_id, _now(), expires_at),
        )


def get_session(token_hash: str) -> dict[str, Any] | None:
    with connection() as conn:
        row = conn.execute(
            "SELECT token_hash, user_id, created_at, expires_at FROM sessions WHERE token_hash = ?",
            (token_hash,),
        ).fetchone()
    if row is None:
        return None
    return {
        "token_hash": row["token_hash"],
        "user_id": row["user_id"],
        "created_at": row["created_at"],
        "expires_at": row["expires_at"],
    }


def delete_session(token_hash: str) -> None:
    with connection() as conn:
        conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))


def delete_user_sessions(user_id: str) -> None:
    with connection() as conn:
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))


def delete_other_sessions(user_id: str, keep_token_hash: str) -> None:
    """自助改密后只保留当前这台设备的会话，其他设备的会话立即失效。"""
    with connection() as conn:
        conn.execute(
            "DELETE FROM sessions WHERE user_id = ? AND token_hash <> ?",
            (user_id, keep_token_hash),
        )


def count_ai_usage(user_id: str, day: str) -> int:
    with connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS total FROM ai_usage WHERE user_id = ? AND day = ?",
            (user_id, day),
        ).fetchone()
    return 0 if row is None else int(row["total"])


def record_ai_usage(user_id: str, day: str) -> None:
    with connection() as conn:
        conn.execute(
            "INSERT INTO ai_usage (id, user_id, day, created_at) VALUES (?, ?, ?, ?)",
            (uuid.uuid4().hex, user_id, day, _now()),
        )


# --- 存量数据归属迁移（r23 收口） -------------------------------------------

_USER_DATA_TABLES = (
    "documents",
    "profiles",
    "runs",
    "reports",
    "timeline_events",
    "question_attempts",
)


def adopt_default_data(user_id: str) -> dict[str, int]:
    """把 r23 之前的单用户数据（`user_id='default'`）整体改挂到指定账号。

    返回各表迁移行数；目标 id 不得为空或 `default`。业务 id 全局唯一，
    整行改 `user_id` 不会产生主键冲突。
    """
    migrated: dict[str, int] = {}
    with connection() as conn:
        for table in _USER_DATA_TABLES:
            cursor = conn.execute(
                f"UPDATE {table} SET user_id = ? WHERE user_id = ?",
                (user_id, DEFAULT_USER_ID),
            )
            migrated[table] = max(cursor.rowcount, 0)
    return migrated


# --- r51 模型调用日志 / 题目全文检索 -----------------------------------------

_AI_LOG_INSERT = (
    "INSERT INTO ai_call_logs "
    "(id, user_id, request_id, provider, model, kind, status_code, elapsed_ms, "
    "attempt, prompt_chars, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)


def insert_ai_call_log(
    *,
    provider: str,
    model: str,
    kind: str,
    elapsed_ms: int,
    status_code: int | None = None,
    attempt: int = 1,
    prompt_chars: int = 0,
    request_id: str = "-",
    created_at: str | None = None,
) -> None:
    """写一条模型调用元数据。**调用方必须 best-effort 包裹**：日志失败不得影响主链路。

    `created_at` 仅用于离线回放 / 历史回填（评测脚本与保留期测试），正常调用留空。
    """
    with connection() as conn:
        conn.execute(
            _AI_LOG_INSERT,
            (
                uuid.uuid4().hex,
                _uid(),
                request_id,
                provider,
                model,
                kind,
                status_code,
                max(int(elapsed_ms), 0),
                max(int(attempt), 1),
                max(int(prompt_chars), 0),
                created_at or _now(),
            ),
        )


#: r53 日志保留期：`ai_call_logs` 是高频写入表，不清理会无限增长（sessions 已有同类收口）。
AI_LOG_RETENTION_DAYS = 90


def prune_ai_call_logs(days: int = AI_LOG_RETENTION_DAYS) -> int:
    """删除窗口外的模型调用日志，返回实际删除行数。登录时顺带执行。

    与 `ai_call_log_summary()` 用同一 ISO UTC 时间口径；`days` 夹紧到 [1, 365]，
    避免脏配置把刚写入的日志全删光。
    """
    window = max(1, min(int(days), 365))
    cutoff = (datetime.now(UTC) - timedelta(days=window)).isoformat()
    with connection() as conn:
        cursor = conn.execute("DELETE FROM ai_call_logs WHERE created_at < ?", (cutoff,))
    return max(cursor.rowcount, 0)


def _percentile(values: list[int], quantile: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(quantile * len(ordered)) - 1))
    return ordered[index]


def ai_call_log_summary(days: int = 7) -> dict[str, Any]:
    """按当前用户聚合调用日志：SQL 只取窗口内行，指标全在 Python 里算（分母写死）。"""
    window = max(1, min(int(days), 90))
    cutoff = (datetime.now(UTC) - timedelta(days=window)).isoformat()
    with connection() as conn:
        rows = conn.execute(
            "SELECT provider, model, kind, status_code, elapsed_ms, created_at "
            "FROM ai_call_logs WHERE user_id = ? AND created_at >= ?",
            (_uid(), cutoff),
        ).fetchall()
    total = len(rows)
    if total == 0:
        return {
            "window_days": window,
            "total": 0,
            "success_rate": 0.0,
            "p50_ms": 0,
            "p95_ms": 0,
            "by_kind": {},
            "by_model": {},
            "trend": [],
            "notice": "暂无模型调用记录",
        }
    by_kind: dict[str, int] = {}
    by_model: dict[str, dict[str, Any]] = {}
    trend: dict[str, dict[str, int]] = {}
    for row in rows:
        kind = str(row["kind"])
        model = str(row["model"])
        by_kind[kind] = by_kind.get(kind, 0) + 1
        stat = by_model.setdefault(model, {"total": 0, "success": 0, "latencies": []})
        stat["total"] += 1
        stat["success"] += int(kind == "success")
        stat["latencies"].append(int(row["elapsed_ms"]))
        day = str(row["created_at"])[:10]
        bucket = trend.setdefault(day, {"total": 0, "success": 0})
        bucket["total"] += 1
        bucket["success"] += int(kind == "success")
    latencies = [int(row["elapsed_ms"]) for row in rows]
    return {
        "window_days": window,
        "total": total,
        "success_rate": round(by_kind.get("success", 0) / total, 4),
        "p50_ms": _percentile(latencies, 0.5),
        "p95_ms": _percentile(latencies, 0.95),
        "by_kind": by_kind,
        "by_model": {
            model: {
                "total": stat["total"],
                "success_rate": round(stat["success"] / stat["total"], 4),
                "p95_ms": _percentile(stat["latencies"], 0.95),
            }
            for model, stat in by_model.items()
        },
        "trend": [
            {
                "day": day,
                "total": bucket["total"],
                "success_rate": round(bucket["success"] / bucket["total"], 4),
            }
            for day, bucket in sorted(trend.items())
        ],
        "notice": "",
    }


def _question_search_table_exists(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'question_search'"
    ).fetchone()
    return row is not None


def rebuild_question_search() -> tuple[str, int]:
    """题库幂等导入后重建 FTS 索引；返回 (mode, rows)，无 FTS5 能力时为 ('like', 0)。"""
    with connection() as conn:
        if not _question_search_table_exists(conn):
            return "like", 0
        existing = int(conn.execute("SELECT COUNT(*) AS n FROM question_search").fetchone()["n"])
        total = int(conn.execute("SELECT COUNT(*) AS n FROM questions").fetchone()["n"])
        # 题库导入幂等（只增不改），行数一致即跳过重建，避免每次启动重写 1164 行。
        if existing == total:
            return "fts5", total
        source = conn.execute(
            "SELECT id, prompt, explanation, direction, sub_direction FROM questions"
        ).fetchall()
        conn.execute("DELETE FROM question_search")
        conn.executemany(
            "INSERT INTO question_search "
            "(question_id, prompt, explanation, direction, sub_direction) VALUES (?, ?, ?, ?, ?)",
            [
                (
                    row["id"],
                    row["prompt"],
                    row["explanation"],
                    row["direction"],
                    row["sub_direction"] or "",
                )
                for row in source
            ],
        )
    return "fts5", len(source)


def search_questions(
    query: str,
    directions: Sequence[str] | str | None = None,
    sub_direction: str = "",
    limit: int = 5,
    page: int = 1,
) -> dict[str, Any]:
    """题目检索：FTS5 trigram 优先，短查询 / 无虚表时降级 LIKE；答案列永不入响应。

    `limit` 是每页条数，`page` 从 1 起；`total` 为**命中总数**（不是本页条数），供前端翻页。
    `directions` 是多选方向（空 = 不过滤），SQL 走 `IN (...)`；旧的单值字符串仍可用。
    """
    needle = str(query or "").strip()
    size = max(1, min(int(limit), 20))
    offset = (max(1, int(page)) - 1) * size
    if not needle:
        return {"items": [], "total": 0, "mode": "fts5", "notice": "请输入检索关键词"}
    picked = [directions] if isinstance(directions, str) else list(directions or [])
    filters: list[str] = []
    params: list[Any] = []
    if picked:
        filters.append("direction IN (" + ", ".join("?" for _ in picked) + ")")
        params.extend(picked)
    if sub_direction:
        filters.append("sub_direction = ?")
        params.append(sub_direction)
    where = (" AND " + " AND ".join(filters)) if filters else ""
    with connection() as conn:
        if _question_search_table_exists(conn) and len(needle) >= 3:
            match = '"' + needle.replace('"', '""') + '"'
            total = conn.execute(
                "SELECT count(*) AS n FROM question_search WHERE question_search MATCH ?" + where,
                [match, *params],
            ).fetchone()["n"]
            rows = conn.execute(
                "SELECT question_id, prompt, direction, sub_direction, "
                "bm25(question_search) AS rank FROM question_search "
                "WHERE question_search MATCH ?" + where + " ORDER BY rank ASC LIMIT ? OFFSET ?",
                [match, *params, size, offset],
            ).fetchall()
            mode = "fts5"
        else:
            like = "%" + needle + "%"
            total = conn.execute(
                "SELECT count(*) AS n FROM questions"
                " WHERE (prompt LIKE ? OR explanation LIKE ?)" + where,
                [like, like, *params],
            ).fetchone()["n"]
            rows = conn.execute(
                "SELECT id AS question_id, prompt, direction, sub_direction FROM questions "
                "WHERE (prompt LIKE ? OR explanation LIKE ?)" + where
                + " ORDER BY id LIMIT ? OFFSET ?",
                [like, like, *params, size, offset],
            ).fetchall()
            mode = "like"
    items = [
        {
            "question_id": str(row["question_id"]),
            "prompt": str(row["prompt"]),
            "direction": str(row["direction"]),
            "sub_direction": str(row["sub_direction"] or ""),
            "score": round(-float(row["rank"]), 4) if mode == "fts5" else 1.0,
        }
        for row in rows
    ]
    notice = "" if mode == "fts5" else "当前环境未启用全文索引，已按关键词包含匹配"
    return {"items": items, "total": int(total), "mode": mode, "notice": notice}


def _json_map(value: Any) -> dict[str, bool]:
    """JSON 列解码（对象口径）：坏值 / 非对象一律退化为 `{}`。"""
    if isinstance(value, dict):
        return {str(key): bool(flag) for key, flag in value.items()}
    if not isinstance(value, str):
        return {}
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return {str(key): bool(flag) for key, flag in decoded.items()} if isinstance(decoded, dict) else {}


def get_learn_progress() -> dict[str, Any]:
    """整份阅读进度（r61 上云）：空库返回空状态，由前端把本地进度回推上来。"""
    with connection() as conn:
        meta = conn.execute(
            "SELECT last_chapter_id FROM learn_progress WHERE user_id = ?", (_uid(),)
        ).fetchone()
        rows = conn.execute(
            "SELECT chapter_id, seen, last_section_id, updated_at FROM learn_chapters "
            "WHERE user_id = ? ORDER BY chapter_id",
            (_uid(),),
        ).fetchall()
    chapters = {
        str(row["chapter_id"]): {
            "seen": [str(item) for item in _json_list(row["seen"])],
            "last_section_id": str(row["last_section_id"]) or None,
            "updated_at": int(row["updated_at"] or 0),
        }
        for row in rows
    }
    return {
        "last_chapter_id": (str(meta["last_chapter_id"]) or None) if meta is not None else None,
        "chapters": chapters,
    }


def save_learn_progress(last_chapter_id: str | None, chapters: dict[str, dict[str, Any]]) -> None:
    """整份覆盖写：章节行先清后插（同一条连接内原子生效，章节数上限由服务层夹取）。"""
    with connection() as conn:
        conn.execute(
            "INSERT INTO learn_progress (user_id, last_chapter_id, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET last_chapter_id = excluded.last_chapter_id, "
            "updated_at = excluded.updated_at",
            (_uid(), last_chapter_id or "", _now()),
        )
        conn.execute("DELETE FROM learn_chapters WHERE user_id = ?", (_uid(),))
        conn.executemany(
            "INSERT INTO learn_chapters (user_id, chapter_id, seen, last_section_id, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            [
                (
                    _uid(),
                    chapter_id,
                    _json_text(item.get("seen") or []),
                    str(item.get("last_section_id") or ""),
                    int(item.get("updated_at") or 0),
                )
                for chapter_id, item in chapters.items()
            ],
        )


def get_plan_state(report_id: str) -> dict[str, Any]:
    """某份报告的打卡状态；从未写过时 `updated_at` 为空串（前端据此回推本地记录）。"""
    with connection() as conn:
        row = conn.execute(
            "SELECT daily_minutes, done, updated_at FROM plan_states "
            "WHERE user_id = ? AND report_id = ?",
            (_uid(), report_id),
        ).fetchone()
    if row is None:
        return {"report_id": report_id, "daily_minutes": 30, "done": {}, "updated_at": ""}
    return {
        "report_id": report_id,
        "daily_minutes": int(row["daily_minutes"] or 30),
        "done": _json_map(row["done"]),
        "updated_at": str(row["updated_at"]),
    }


def save_plan_state(report_id: str, daily_minutes: int, done: dict[str, bool]) -> None:
    """整份覆盖写（打卡 map 最多几十条，无需增量）。"""
    with connection() as conn:
        conn.execute(
            "INSERT INTO plan_states (user_id, report_id, daily_minutes, done, updated_at) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT(user_id, report_id) DO UPDATE SET "
            "daily_minutes = excluded.daily_minutes, done = excluded.done, "
            "updated_at = excluded.updated_at",
            (_uid(), report_id, int(daily_minutes), _json_text(done), _now()),
        )


# --- taifu（r77 太傅对话：单账号单线程）-------------------------------------
#
# 只存对话本身：`citations` 是可核对的站内路由，不存画像 / 报告的副本。
# 读路径恒为「本账号最近 N 条」，因此 `list_taifu_messages()` 先倒序取再翻转，
# 保证调用方拿到的时间序与界面展示一致（不在服务层二次排序）。

#: 每账号保留的消息条数上限：超出按时间淘汰最旧，避免常驻件把库撑大。
TAIFU_MESSAGE_LIMIT = 200


def _taifu_message_of(row: sqlite3.Row) -> dict[str, Any]:
    """行 → 通用字典；`citations` 坏值一律退化为空列表（不让脏 JSON 把整个线程读崩）。"""
    raw = row["citations"]
    try:
        decoded = json.loads(raw) if isinstance(raw, str) else []
    except json.JSONDecodeError:
        decoded = []
    citations = [
        {"label": str(item.get("label") or ""), "href": str(item.get("href") or "")}
        for item in (decoded if isinstance(decoded, list) else [])
        if isinstance(item, dict)
    ]
    return {
        "id": row["id"],
        "role": str(row["role"]),
        "content": str(row["content"]),
        "citations": citations,
        "created_at": str(row["created_at"]),
    }


def insert_taifu_message(
    *, role: str, content: str, citations: list[dict[str, str]] | None = None
) -> dict[str, Any]:
    """追加一条对话并裁剪到 `TAIFU_MESSAGE_LIMIT` 条，返回写入行。"""
    message_id = str(uuid.uuid4())
    stamp = _now()
    payload = json.dumps(citations or [], ensure_ascii=False)
    with connection() as conn:
        conn.execute(
            "INSERT INTO taifu_messages (id, user_id, role, content, citations, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (message_id, _uid(), role, content, payload, stamp),
        )
        conn.execute(
            "DELETE FROM taifu_messages WHERE user_id = ? AND id NOT IN ("
            "  SELECT id FROM taifu_messages WHERE user_id = ?"
            "  ORDER BY created_at DESC, id DESC LIMIT ?"
            ")",
            (_uid(), _uid(), TAIFU_MESSAGE_LIMIT),
        )
    return {
        "id": message_id,
        "role": role,
        "content": content,
        "citations": citations or [],
        "created_at": stamp,
    }


def list_taifu_messages(limit: int = 20) -> list[dict[str, Any]]:
    """本账号最近 `limit` 条消息，按时间**升序**返回（先倒序取，再翻转）。"""
    with connection() as conn:
        rows = conn.execute(
            "SELECT id, role, content, citations, created_at FROM taifu_messages "
            "WHERE user_id = ? ORDER BY created_at DESC, id DESC LIMIT ?",
            (_uid(), max(0, int(limit))),
        ).fetchall()
    return [_taifu_message_of(row) for row in reversed(rows)]


def delete_taifu_messages() -> int:
    """清空本账号对话（含 r80 线程摘要），返回删除条数（业务数据一律不动）。

    摘要必须一起清：否则清空后再问，提示词里还挂着上一段对话的要点 ——
    用户看到的是「空对话」，模型看到的不是。
    **r81 长期记忆不清**：那是「你是谁」，不是「这次聊了什么」（见 `delete_taifu_memories`）。
    """
    with connection() as conn:
        cursor = conn.execute("DELETE FROM taifu_messages WHERE user_id = ?", (_uid(),))
        conn.execute("DELETE FROM taifu_threads WHERE user_id = ?", (_uid(),))
        return max(cursor.rowcount, 0)


def get_taifu_summary() -> str:
    """本账号的线程摘要（被窗口挤出后压缩过的早期对话要点）；没有则空串。"""
    with connection() as conn:
        row = conn.execute(
            "SELECT memory FROM taifu_threads WHERE user_id = ?", (_uid(),)
        ).fetchone()
    return str(row["memory"]) if row is not None else ""


def save_taifu_summary(summary: str) -> None:
    """写入/覆盖线程摘要（单行 upsert）。空串由调用方拦截，不在这里猜。"""
    with connection() as conn:
        conn.execute(
            "INSERT INTO taifu_threads (user_id, memory, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET memory = excluded.memory, "
            "updated_at = excluded.updated_at",
            (_uid(), summary, _now()),
        )


# --- 太傅长期记忆（r81）-------------------------------------------------------
#
# 多条、跨对话：记录「用户口头说过、档案里没有」的稳定事实与偏好。
# 去重与条数上限的判定在 `services/taifu/policy.py`（纯函数、可单测），
# 这里只负责读写；`TAIFU_MEMORY_LIMIT` 是**存储层**硬护栏，防止调用方忘了裁剪。


#: 单账号长期记忆上限：再多就不是「记住要点」而是又一份档案，提示词也会被它撑满。
TAIFU_MEMORY_LIMIT = 20


def _taifu_memory_of(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "content": str(row["content"]),
        "created_at": str(row["created_at"]),
    }


def list_taifu_memories(limit: int = TAIFU_MEMORY_LIMIT) -> list[dict[str, Any]]:
    """本账号的长期记忆，按写入时间**升序**（先记的在前，读起来像一条时间线）。"""
    with connection() as conn:
        rows = conn.execute(
            "SELECT id, content, created_at FROM taifu_memories "
            "WHERE user_id = ? ORDER BY created_at DESC, id DESC LIMIT ?",
            (_uid(), max(0, int(limit))),
        ).fetchall()
    return [_taifu_memory_of(row) for row in reversed(rows)]


def insert_taifu_memory(content: str) -> dict[str, Any]:
    """追加一条长期记忆并裁剪到 `TAIFU_MEMORY_LIMIT`（淘汰最旧），返回写入行。"""
    memory_id = str(uuid.uuid4())
    stamp = _now()
    with connection() as conn:
        conn.execute(
            "INSERT INTO taifu_memories (id, user_id, content, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (memory_id, _uid(), content, stamp, stamp),
        )
        conn.execute(
            "DELETE FROM taifu_memories WHERE user_id = ? AND id NOT IN ("
            "  SELECT id FROM taifu_memories WHERE user_id = ?"
            "  ORDER BY created_at DESC, id DESC LIMIT ?"
            ")",
            (_uid(), _uid(), TAIFU_MEMORY_LIMIT),
        )
    return {"id": memory_id, "content": content, "created_at": stamp}


def delete_taifu_memory(memory_id: str) -> int:
    """删掉一条长期记忆（按 id + 账号双条件，不能删别人的）。"""
    with connection() as conn:
        cursor = conn.execute(
            "DELETE FROM taifu_memories WHERE id = ? AND user_id = ?", (memory_id, _uid())
        )
        return max(cursor.rowcount, 0)


def delete_taifu_memories() -> int:
    """忘掉全部长期记忆，返回删除条数（对话与业务数据都不动）。"""
    with connection() as conn:
        cursor = conn.execute("DELETE FROM taifu_memories WHERE user_id = ?", (_uid(),))
        return max(cursor.rowcount, 0)


# --- radar（r67 技术雷达：清单 / 快照 / 评估 / 采集轮次 / 生成任务）----------
#
# 技术清单、快照与评估是**全局知识**（不按账号切）；生成任务 `radar_jobs` 带 `user_id`，
# 读 / 采纳 / 废弃按账号隔离（AC-9）。列名投影与状态语义留在 `services/radar/store.py`，
# 这里按「唯一 SQL 出口」约定只出读写；任务行以 `sqlite3.Row` 返回，JSON 列解码仍归塑形层。


def radar_upsert_tech(item: dict[str, Any]) -> None:
    """按 `tech_slug` 幂等写入：已存在只刷新 last_seen 与可变字段（首次见到的时间不动）。

    英文摘要变了就清空 `summary_zh`（旧译文对应旧原文，留着就是错译），下轮翻译会重算；
    摘要没变则保留已有译文，避免每轮采集重复烧 token。
    """
    stamp = _now()
    with connection() as conn:
        conn.execute(
            "INSERT INTO radar_techs (tech_slug, name, direction, sub_direction, source_key, url,"
            " summary, summary_zh, first_seen_at, last_seen_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, '', ?, ?) "
            "ON CONFLICT(tech_slug) DO UPDATE SET name = excluded.name,"
            " direction = excluded.direction, sub_direction = excluded.sub_direction,"
            " url = excluded.url,"
            # 赋值顺序有意义：SQLite 的 SET 从左到右求值，summary_zh 必须先于 summary 计算。
            " summary_zh = CASE WHEN excluded.summary = radar_techs.summary"
            "   THEN radar_techs.summary_zh ELSE '' END,"
            " summary = excluded.summary, last_seen_at = excluded.last_seen_at",
            (
                item["slug"], item["name"], item["direction"], item["sub_direction"],
                item["source_key"], item["url"], item["summary"], stamp, stamp,
            ),
        )


def radar_insert_snapshot(item: dict[str, Any]) -> None:
    """补一条 star / fork 快照（`star_delta_7d` 由最新两条快照差值推出）。"""
    with connection() as conn:
        conn.execute(
            "INSERT INTO radar_snapshots (tech_slug, taken_at, stars, forks, repo_created_at,"
            " pushed_at, suspect) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                item["slug"], _now(), int(item.get("stars") or 0), int(item.get("forks") or 0),
                str(item.get("repo_created_at") or ""), str(item.get("pushed_at") or ""),
                1 if item.get("suspect") else 0,
            ),
        )


def radar_previous_stars(slug: str) -> int | None:
    """最近一条快照的 star 数（第一条快照返回 None，增速按 0 处理）。"""
    with connection() as conn:
        row = conn.execute(
            "SELECT stars FROM radar_snapshots WHERE tech_slug = ? ORDER BY id DESC LIMIT 1",
            (slug,),
        ).fetchone()
    return None if row is None else int(row["stars"])


def radar_insert_assessment(
    tech_slug: str,
    run_id: int,
    result: dict[str, Any],
    *,
    input_sha256: str,
    profile_digest: str,
    prompt_version: str,
    model: str,
    rule_based: bool,
) -> bool:
    """写一条评估；同 `(tech_slug, input_sha256)` 已存在则跳过（返回 False = 可复算幂等）。"""
    with connection() as conn:
        cursor = conn.execute(
            "INSERT OR IGNORE INTO radar_assessments (tech_slug, run_id, verdict, relevance,"
            " adoption, maturity, effort, reasons_json, evidence_json, profile_digest,"
            " prompt_version, model, input_sha256, rule_based, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                tech_slug, run_id, result["verdict"], int(result["relevance"]),
                int(result["adoption"]), int(result["maturity"]), int(result["effort"]),
                _json_text(result.get("reasons") or []),
                _json_text(result.get("evidence") or []),
                profile_digest, prompt_version, model, input_sha256,
                1 if rule_based else 0, _now(),
            ),
        )
        return cursor.rowcount > 0


_RADAR_TECH_JOIN = (
    " LEFT JOIN radar_assessments a ON a.id = ("
    "   SELECT MAX(a2.id) FROM radar_assessments a2 WHERE a2.tech_slug = t.tech_slug)"
)


def _radar_picks(value: str | Sequence[str] | None) -> list[str]:
    """单选字符串 / 多选列表统一成去重后的列表（空串 / None / 空列表 = 不过滤）。"""
    picked = [value] if isinstance(value, str) else list(value or [])
    return list(dict.fromkeys(item for item in picked if item))


def _radar_tech_where(
    *,
    tech_slug: str = "",
    directions: str | Sequence[str] | None = None,
    verdicts: str | Sequence[str] | None = None,
) -> tuple[str, list[Any]]:
    """技术清单的过滤条件（列表与计数共用，避免两处口径漂移）。

    `directions` / `verdicts` 都是多选，SQL 走 `IN (...)`（单值字符串仍兼容）；
    `verdict` 走 `COALESCE(a.verdict, 'skip')`：还没有评估行的技术按 `skip` 投射，
    筛「跳过」时要一并命中，与列表里的默认结论保持一致。
    """
    clauses: list[str] = []
    params: list[Any] = []
    if tech_slug:
        clauses.append("t.tech_slug = ?")
        params.append(tech_slug)
    picked_directions = _radar_picks(directions)
    if picked_directions:
        clauses.append("t.direction IN (" + ", ".join("?" for _ in picked_directions) + ")")
        params.extend(picked_directions)
    picked_verdicts = _radar_picks(verdicts)
    if picked_verdicts:
        clauses.append(
            "COALESCE(a.verdict, 'skip') IN ("
            + ", ".join("?" for _ in picked_verdicts)
            + ")"
        )
        params.extend(picked_verdicts)
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", params


def radar_list_techs(
    limit: int = 50,
    *,
    tech_slug: str = "",
    directions: str | Sequence[str] | None = None,
    verdicts: str | Sequence[str] | None = None,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """技术清单：最新评估 + 最新快照 + 当前账号最近一条生成任务，按评估时间倒序分页。"""
    where, filter_params = _radar_tech_where(
        tech_slug=tech_slug, directions=directions, verdicts=verdicts
    )
    params: list[Any] = [_uid(), *filter_params, limit, offset]
    with connection() as conn:
        rows = conn.execute(
            "SELECT t.tech_slug, t.name, t.direction, t.sub_direction, t.source_key, t.url,"
            " t.summary, t.summary_zh, a.verdict, a.relevance, a.adoption, a.maturity, a.effort,"
            " a.reasons_json, a.evidence_json, a.rule_based, a.created_at AS assessed_at,"
            " (SELECT s.stars FROM radar_snapshots s WHERE s.tech_slug = t.tech_slug"
            "  ORDER BY s.id DESC LIMIT 1) AS stars,"
            " (SELECT s.stars FROM radar_snapshots s WHERE s.tech_slug = t.tech_slug"
            "  ORDER BY s.id DESC LIMIT 1 OFFSET 1) AS prev_stars,"
            " (SELECT s.suspect FROM radar_snapshots s WHERE s.tech_slug = t.tech_slug"
            "  ORDER BY s.id DESC LIMIT 1) AS suspect,"
            " (SELECT j.job_id FROM radar_jobs j WHERE j.tech_slug = t.tech_slug"
            "  AND j.user_id = ? ORDER BY j.created_at DESC LIMIT 1) AS job_id"
            " FROM radar_techs t"
            f"{_RADAR_TECH_JOIN}"
            f"{where}"
            " ORDER BY a.created_at DESC, t.last_seen_at DESC LIMIT ? OFFSET ?",
            params,
        ).fetchall()
    items: list[dict[str, Any]] = []
    for row in rows:
        items.append(
            {
                "tech_slug": row["tech_slug"],
                "name": row["name"],
                "direction": row["direction"],
                "sub_direction": row["sub_direction"],
                "source_key": row["source_key"],
                "url": row["url"],
                "summary": row["summary"],
                "summary_zh": row["summary_zh"] or "",
                "verdict": row["verdict"] or "skip",
                "relevance": int(row["relevance"] or 1),
                "adoption": int(row["adoption"] or 1),
                "maturity": int(row["maturity"] or 1),
                "effort": int(row["effort"] or 1),
                "reasons": _json_list(row["reasons_json"]),
                "evidence": _json_list(row["evidence_json"]),
                "rule_based": bool(row["rule_based"]),
                "assessed_at": row["assessed_at"] or "",
                "stars": int(row["stars"] or 0),
                "star_delta_7d": max(
                    int(row["stars"] or 0) - int(row["prev_stars"]), 0
                ) if row["prev_stars"] is not None else 0,
                "suspect": bool(row["suspect"]),
                "job_id": row["job_id"] or "",
            }
        )
    return items


def radar_count_techs(
    *,
    tech_slug: str = "",
    directions: str | Sequence[str] | None = None,
    verdicts: str | Sequence[str] | None = None,
) -> int:
    """技术清单总数：与 `radar_list_techs` 同一过滤口径，供分页器算总页数。"""
    where, params = _radar_tech_where(
        tech_slug=tech_slug, directions=directions, verdicts=verdicts
    )
    with connection() as conn:
        row = conn.execute(
            f"SELECT count(*) AS n FROM radar_techs t{_RADAR_TECH_JOIN}{where}", params
        ).fetchone()
    return int(row["n"])


def radar_cross_source_count() -> dict[str, int]:
    """跨源出现次数：同名技术被几个源提到（评估信号之一，无记录记 0）。"""
    with connection() as conn:
        rows = conn.execute(
            "SELECT tech_slug, COUNT(DISTINCT source_key) AS n FROM radar_techs GROUP BY tech_slug"
        ).fetchall()
    return {str(row["tech_slug"]): int(row["n"]) for row in rows}


def radar_create_run(trigger: str) -> int:
    """开一轮采集，返回自增 `run_id`（采集结束后由 `radar_finish_run` 补终态）。"""
    with connection() as conn:
        cursor = conn.execute(
            "INSERT INTO radar_runs (trigger, started_at) VALUES (?, ?)", (trigger, _now())
        )
        return int(cursor.lastrowid or 0)


def radar_finish_run(
    run_id: int, sources: list[dict[str, Any]], degraded: bool, techs_seen: int
) -> None:
    with connection() as conn:
        conn.execute(
            "UPDATE radar_runs SET finished_at = ?, sources_json = ?, degraded = ?, techs_seen = ?"
            " WHERE run_id = ?",
            (_now(), _json_text(sources), 1 if degraded else 0, techs_seen, run_id),
        )


def radar_latest_run() -> dict[str, Any]:
    """最近一轮采集；空库给一份「从未采集」的零值，调用方无需判 None。"""
    with connection() as conn:
        row = conn.execute("SELECT * FROM radar_runs ORDER BY run_id DESC LIMIT 1").fetchone()
    if row is None:
        return {"run_id": 0, "trigger": "", "started_at": "", "finished_at": "",
                "degraded": False, "techs_seen": 0, "sources": []}
    return {
        "run_id": int(row["run_id"]),
        "trigger": row["trigger"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "degraded": bool(row["degraded"]),
        "techs_seen": int(row["techs_seen"]),
        "sources": _json_list(row["sources_json"]),
    }


def radar_insert_job(job_id: str, tech_slug: str, *, trigger: str, parent_job_id: str) -> bool:
    """插入生成任务行；同一技术已有未终态任务时撞部分唯一索引，返回 False（AC-3 幂等）。"""
    stamp = _now()
    try:
        with connection() as conn:
            conn.execute(
                "INSERT INTO radar_jobs (job_id, tech_slug, user_id, status, stage, progress,"
                " trigger, parent_job_id, created_at, updated_at)"
                " VALUES (?, ?, ?, 'queued', 'chapter', 0, ?, ?, ?, ?)",
                (job_id, tech_slug, _uid(), trigger, parent_job_id, stamp, stamp),
            )
        return True
    except sqlite3.IntegrityError:
        return False


def radar_active_job(tech_slug: str) -> dict[str, Any] | None:
    """该技术当前未终态的任务归属（`{job_id, user_id}`），没有则 `None`。"""
    with connection() as conn:
        row = conn.execute(
            "SELECT job_id, user_id FROM radar_jobs WHERE tech_slug = ?"
            " AND status IN ('queued', 'running') ORDER BY created_at DESC LIMIT 1",
            (tech_slug,),
        ).fetchone()
    return None if row is None else {"job_id": str(row["job_id"]), "user_id": str(row["user_id"])}


def radar_get_job_row(job_id: str) -> sqlite3.Row | None:
    """按 id 读任务行（当前账号隔离）；行交给塑形层解析 JSON 列。"""
    with connection() as conn:
        return conn.execute(
            "SELECT * FROM radar_jobs WHERE job_id = ? AND user_id = ?",
            (job_id, _uid()),
        ).fetchone()


def radar_job_rows(limit: int = 20, offset: int = 0) -> list[sqlite3.Row]:
    with connection() as conn:
        return conn.execute(
            "SELECT * FROM radar_jobs WHERE user_id = ? ORDER BY created_at DESC"
            " LIMIT ? OFFSET ?",
            (_uid(), limit, offset),
        ).fetchall()


def radar_count_jobs() -> int:
    """本账号样例任务总数，供分页器算总页数。"""
    with connection() as conn:
        row = conn.execute(
            "SELECT count(*) AS n FROM radar_jobs WHERE user_id = ?", (_uid(),)
        ).fetchone()
    return int(row["n"])


def radar_update_job(job_id: str, payload: dict[str, Any]) -> None:
    """按**字段名白名单**调用方的 payload 更新任务行（列名拼装在 SQL 唯一出口内）。"""
    if not payload:
        return
    values = {**payload, "updated_at": _now()}
    columns = ", ".join(f"{key} = ?" for key in values)
    with connection() as conn:
        conn.execute(
            f"UPDATE radar_jobs SET {columns} WHERE job_id = ?", [*values.values(), job_id]
        )


def radar_sweep_stale_jobs(minutes: int) -> None:
    """读路径惰性清扫（AC-4）：running 超过阈值按 failed 落库，避免僵尸行永远「生成中」。"""
    with connection() as conn:
        conn.execute(
            "UPDATE radar_jobs SET status = 'failed', error_message = '生成中断，请重试',"
            " updated_at = strftime('%Y-%m-%dT%H:%M:%S', 'now') || '+00:00'"
            " WHERE status = 'running'"
            " AND (julianday('now') - julianday(created_at)) * 24 * 60 > ?",
            (minutes,),
        )


def radar_tech_name(tech_slug: str) -> str:
    with connection() as conn:
        row = conn.execute(
            "SELECT name FROM radar_techs WHERE tech_slug = ?", (tech_slug,)
        ).fetchone()
    return "" if row is None else str(row["name"])


def radar_set_summary_zh(tech_slug: str, summary_zh: str) -> None:
    """写一条中文摘要（翻译结果落库后，同一个仓库不再重复翻译）。"""
    with connection() as conn:
        conn.execute(
            "UPDATE radar_techs SET summary_zh = ? WHERE tech_slug = ?",
            (summary_zh, tech_slug),
        )


def radar_pending_translation(limit: int) -> list[dict[str, Any]]:
    """待翻译条目：有英文摘要但还没有中文译文的（r89：标题即简介的交给汇总队列）。"""
    with connection() as conn:
        rows = conn.execute(
            "SELECT tech_slug, summary FROM radar_techs"
            " WHERE summary_zh = '' AND summary <> '' AND trim(summary) <> trim(name)"
            " ORDER BY last_seen_at DESC LIMIT ?",
            (max(int(limit), 1),),
        ).fetchall()
    return [{"slug": row["tech_slug"], "summary": row["summary"]} for row in rows]


def radar_count_pending_translation() -> int:
    """还有多少条「有英文摘要但没有中文译文」且非标题即简介（补翻按钮据此决定是否还能再点）。"""
    with connection() as conn:
        row = conn.execute(
            "SELECT count(*) AS n FROM radar_techs"
            " WHERE summary_zh = '' AND summary <> '' AND trim(summary) <> trim(name)"
        ).fetchone()
    return 0 if row is None else int(row["n"])


def radar_pending_summary(limit: int) -> list[dict[str, Any]]:
    """「标题即简介」且还没有中文概要的条目（r89），按最近出现时间取一页。"""
    with connection() as conn:
        rows = conn.execute(
            "SELECT tech_slug, name, summary, url FROM radar_techs"
            " WHERE summary <> '' AND summary_zh = '' AND trim(summary) = trim(name)"
            " ORDER BY last_seen_at DESC LIMIT ?",
            (max(int(limit), 1),),
        ).fetchall()
    return [
        {"slug": row["tech_slug"], "name": row["name"], "summary": row["summary"], "url": row["url"]}
        for row in rows
    ]


def radar_count_pending_summary() -> int:
    """「标题即简介」且还没有中文概要的条目总数（汇总进度如实回传）。"""
    with connection() as conn:
        row = conn.execute(
            "SELECT count(*) AS n FROM radar_techs"
            " WHERE summary <> '' AND summary_zh = '' AND trim(summary) = trim(name)"
        ).fetchone()
    return 0 if row is None else int(row["n"])


def radar_tech_card(tech_slug: str) -> dict[str, Any] | None:
    """生成用的技术卡片：名称 / 方向 / 简介 / 链接 + 最新评估结论（不存在返回 None）。"""
    with connection() as conn:
        row = conn.execute(
            "SELECT t.tech_slug, t.name, t.direction, t.sub_direction, t.url, t.summary,"
            " t.summary_zh,"
            " a.verdict FROM radar_techs t LEFT JOIN radar_assessments a ON a.id = ("
            "   SELECT MAX(a2.id) FROM radar_assessments a2 WHERE a2.tech_slug = t.tech_slug)"
            " WHERE t.tech_slug = ?",
            (tech_slug,),
        ).fetchone()
    if row is None:
        return None
    return {
        "slug": row["tech_slug"],
        "name": row["name"],
        "direction": row["direction"],
        "sub_direction": row["sub_direction"],
        "url": row["url"],
        "summary": row["summary"],
        "summary_zh": row["summary_zh"] or "",
        "verdict": row["verdict"] or "",
    }
