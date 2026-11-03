"""唯一 SQL 出口（TECHNICAL §1.4）。

本次 5 个路由器（画像 / 面试 / 笔试 / 报告 / 历史）都读写同一批表：SQL 一旦散在路由层，
字段名、排序口径与 JSON 反序列化就会各写一遍并各自漂移。因此这里集中：

- 所有 `INSERT / SELECT / UPDATE` 只出现在本文件；
- `payload JSON` 列的 `model_validate_json` / `json.loads` 也只在这里；
- **查不到返回 `None`，不抛异常** —— 由路由层翻成 `NOT_FOUND` 中文提示，这是错误映射的唯一分工点。
"""

import json
import sqlite3
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import get_settings
from .context import DEFAULT_USER_ID, get_current_user_id
from .db import connection
from .schemas import Profile, Report, ResumeMeta, TimelineEvent

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
    "INSERT INTO questions (id, direction, kind, difficulty, essentiality, prompt, "
    "options, answer, source, language, explanation, created_at, updated_at) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
    "ON CONFLICT(id) DO NOTHING"
)

_QUESTION_SELECT = (
    "SELECT id, direction, kind, difficulty, essentiality, prompt, options, answer, source, "
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
    "updated_at = ? "
    "WHERE id = ? "
    "AND ((language = '' AND ? <> '') OR (explanation = '' AND ? <> ''))"
)


def insert_question(question: dict[str, Any]) -> bool:
    """幂等导入单题：新增 `True`，同 `id` 已存在 `False`（**绝不覆盖**既有行，AC-1）。

    幂等的最终真值是 `questions.id` 主键 + `ON CONFLICT(id) DO NOTHING`：重复导入既不新增
    也不改写，标签回填只在首次导入那一刻生效。r11 起 `language` / `explanation` 随行写入，
    缺省空串（`language=''` 表示通用/算法题，是闭集里的合法成员而非"未填"）。
    """
    now = _now()
    with connection() as conn:
        cursor = conn.execute(
            _QUESTION_INSERT,
            (
                question["id"],
                question["direction"],
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
            ),
        )
        return cursor.rowcount > 0


def _question_of(row: sqlite3.Row) -> dict[str, Any]:
    """questions 行 → 组卷字典（`options` / `answer` 就地解码，服务层不再碰 JSON 文本）。"""
    return {
        "id": row["id"],
        "direction": row["direction"],
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
    """把种子的 `language` / `explanation` 补到**空单元格**上，返回实际补齐的行数。

    `ON CONFLICT DO NOTHING` 只保证「不新增、不覆盖」，不补列 —— 存量 80 题若不补，
    筛选与解析会全空。这里题面 / 选项 / 答案 / 难度 / 必备度一律不碰（r6 AC-1 不回退）；
    种子给空串的字段跳过（`language=''` 是通用题的合法取值）。
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
            if not question_id or not (language or explanation):
                continue
            cursor = conn.execute(
                _QUESTION_FILL,
                (language, language, explanation, explanation, now, question_id, language, explanation),
            )
            filled += max(cursor.rowcount, 0)
    return filled


_QUESTION_REFRESH = (
    "UPDATE questions SET direction = ?, kind = ?, difficulty = ?, essentiality = ?, prompt = ?, "
    "options = ?, answer = ?, source = ?, language = ?, explanation = ?, updated_at = ? "
    "WHERE id = ?"
)


def _normalized_question(question: dict[str, Any]) -> dict[str, Any]:
    """种子行 / 库行 → 可逐字段比对的扁平字典（JSON 列统一按序列化文本比，避免 list/dict 顺序噪声）。"""
    return {
        "direction": str(question.get("direction") or ""),
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
    由 `question_bank.ensure_seeded()` 在启动时调用 —— 让已部署的 `app.db` 也能刷到当前种子
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
