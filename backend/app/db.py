"""SQLite 单库访问层：5 张表，结构化产物以 JSON 文本列存（ARCHITECTURE §3.4）。

不做迁移框架：只用 CREATE TABLE IF NOT EXISTS，字段变更需在 memory.md 记录一次性升级说明。
r3 追加 `timeline_events`（成长时间线的事件快照，`(type, ref_id)` 唯一）——对既有 `app.db`
反复执行 `init_db()` 即得新表，无迁移语句。
"""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

from .config import get_settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    file_name TEXT NOT NULL,
    mime TEXT NOT NULL,
    chars INTEGER NOT NULL,
    sections INTEGER NOT NULL,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS profiles (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    profile_id TEXT NOT NULL,
    payload TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reports (
    id TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- 既有列不变，只加幂等索引：对既有 app.db 反复执行同样安全，无需迁移语句。
CREATE INDEX IF NOT EXISTS idx_runs_kind_created ON runs (kind, created_at);
CREATE INDEX IF NOT EXISTS idx_reports_created ON reports (created_at);

-- r3 成长时间线：事件以 JSON 快照定格（重算报告不回写事件，分数不漂移）。
-- 唯一性写两处、语义等价：表内 `UNIQUE (type, ref_id)` 让「建表即唯一」（新库形态），
-- 显式索引让「既有库 / 半升级状态」也一定唯一（CREATE TABLE IF NOT EXISTS 不会补约束）。
CREATE TABLE IF NOT EXISTS timeline_events (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    ref_id TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (type, ref_id)
);

-- 幂等真值：同一 (type, ref_id) 只允许一条事件，`INSERT ... ON CONFLICT DO NOTHING` 依赖它。
CREATE UNIQUE INDEX IF NOT EXISTS idx_timeline_type_ref ON timeline_events (type, ref_id);
-- 读取与「上一次对比」的唯一排序口径：occurred_at DESC, created_at DESC。
CREATE INDEX IF NOT EXISTS idx_timeline_occurred ON timeline_events (occurred_at);
"""


@contextmanager
def connection() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(get_settings().db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connection() as conn:
        conn.executescript(SCHEMA)
