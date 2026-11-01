"""SQLite 单库访问层：7 张表，结构化产物以 JSON 文本列存（ARCHITECTURE §3.4）。

不做迁移框架：只用 CREATE TABLE IF NOT EXISTS，字段变更需在 memory.md 记录一次性升级说明。
r3 追加 `timeline_events`（成长时间线的事件快照，`(type, ref_id)` 唯一）——对既有 `app.db`
反复执行 `init_db()` 即得新表，无迁移语句。
r6 追加 `questions`（题库，`seed/questions.json` 退为唯一导入源）与 `question_attempts`
（客观题作答事件，`(question_id, run_id)` 唯一）——同样反复执行 `init_db()` 即得新表与新索引，
既有 `app.db` 无需迁移语句；空库由 `services/question_bank.ensure_seeded()` 幂等补 80 行。
r11 追加题库第五维 `questions.language`、逐题解析 `questions.explanation` 与作答事件来源
`question_attempts.source`（TECHNICAL §2.1）。SQLite 的 `CREATE TABLE IF NOT EXISTS` 不会给
**存量**表补列，故 `init_db()` 拆成三步定序：`SCHEMA`（新库即含新列）→ `_ensure_r11_columns()`
（`PRAGMA table_info` 判定后 `ALTER TABLE`，缺列才动，幂等）→ `SCHEMA_INDEXES`（新索引引用
`language` / `source`，必须在补列之后执行）。索引因此从 `SCHEMA` 抽出为独立脚本。
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

-- r6 题库承载：seed JSON 只做导入源。11 个业务列，answer 只服务端可见（不入任何响应模型）。
-- r11 追加两列：language（第五维；'' = 通用/算法题，闭集单一出处 rules.LANGUAGES）与
-- explanation（逐题解析，全库非空 ≥10 字）。
CREATE TABLE IF NOT EXISTS questions (
    id           TEXT PRIMARY KEY,
    direction    TEXT NOT NULL,
    kind         TEXT NOT NULL,
    difficulty   TEXT NOT NULL,   -- basic | intermediate | challenge
    essentiality TEXT NOT NULL,   -- must_know | advanced | nice_to_know
    prompt       TEXT NOT NULL,
    options      TEXT NOT NULL,   -- JSON: [{"key","text"}]
    answer       TEXT NOT NULL,   -- JSON: ["B"] / ["A","B","C"] / []（text 型恒 []）
    source       TEXT NOT NULL,   -- 'seed'（本轮唯一取值，为将来题库管理 UI 留位）
    language     TEXT NOT NULL DEFAULT '',   -- '' = 通用/算法
    explanation  TEXT NOT NULL DEFAULT '',   -- 逐题解析
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

-- r6 作答事件：熟练度判定的唯一事实源（只记客观题，简答不计分故永不写入）。
-- r11 追加 source：'exam' | 'practice'（读侧一律以列为准，`practice:<session>` 前缀只作命名空间）。
CREATE TABLE IF NOT EXISTS question_attempts (
    id          TEXT PRIMARY KEY,
    question_id TEXT NOT NULL,
    run_id      TEXT NOT NULL,
    correct     INTEGER NOT NULL,  -- 0/1
    answered_at TEXT NOT NULL,     -- ISO8601 UTC
    created_at  TEXT NOT NULL,
    source      TEXT NOT NULL DEFAULT 'exam',
    UNIQUE (question_id, run_id)   -- 同一卷同一题只有一条事件（重复提交再兜一层）
);
"""

#: 索引独立成脚本：`idx_questions_lang_pool` / 依赖 `source` 的口径必须在**补列之后**执行，
#: 否则存量库上会因「列不存在」直接报错。顺序即约束，只在 `init_db()` 第 3 步跑。
SCHEMA_INDEXES = """
-- 选池的唯一索引：按 (direction, difficulty) 取候选池时不必扫全表。
-- r11 组卷侧排除开关与按语言筛选都需要 language 进索引。
CREATE INDEX IF NOT EXISTS idx_questions_pool      ON questions (direction, difficulty);
CREATE INDEX IF NOT EXISTS idx_questions_lang_pool ON questions (language, direction, difficulty);

-- 熟练度窗口读取口径：按题取该题的作答序列（`answered_at` 升序）。
-- r11 练习事件按 run 聚合（错题本 / 会话统计）需要 run_id 索引。
CREATE INDEX IF NOT EXISTS idx_attempts_question ON question_attempts (question_id, answered_at);
CREATE INDEX IF NOT EXISTS idx_attempts_run      ON question_attempts (run_id);
"""

#: r11 追加列的唯一清单（表, 列, 列定义）：`_ensure_r11_columns()` 与单测共用同一份，
#: 加一列只改这里，不允许在其他地方再写第二份 ALTER。
_ADDED_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("questions", "language", "TEXT NOT NULL DEFAULT ''"),
    ("questions", "explanation", "TEXT NOT NULL DEFAULT ''"),
    ("question_attempts", "source", "TEXT NOT NULL DEFAULT 'exam'"),
)



@contextmanager
def connection() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(get_settings().db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _ensure_r11_columns(conn: sqlite3.Connection) -> None:
    """存量库补列（幂等）：缺列才 `ALTER TABLE`，第二次启动执行 0 条 DDL。

    SQLite 没有 `ADD COLUMN IF NOT EXISTS`，所以只用 `PRAGMA table_info` 判定后补；
    `ADD COLUMN ... NOT NULL DEFAULT <常量>` 合法且不重建表（沿用 r3「无迁移框架」约定）。
    """
    for table, column, ddl in _ADDED_COLUMNS:
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def init_db() -> None:
    with connection() as conn:
        conn.executescript(SCHEMA)          # 1. 建表（新库即含新列）
        _ensure_r11_columns(conn)           # 2. 存量库补列（幂等）
        conn.executescript(SCHEMA_INDEXES)  # 3. 建索引（引用步骤 2 补出的列）
