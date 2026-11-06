"""r11 数据层与存量升级（AC-5 / AC-16 · TECHNICAL §2.1/§2.2/§2.3）。

这一层的证明对象只有四个，且都必须**真跑库**才能证伪：

1. **存量库升级**：`CREATE TABLE IF NOT EXISTS` 不会给老表补列，所以用例先按 r6 时代的
   DDL 造一个「没有 language / explanation / source 的老库」，再跑 `init_db()`。
   幂等用 `PRAGMA schema_version` 判定 —— 第二次 `init_db()` 若真发了 DDL，版本号必然变
   （`CREATE INDEX IF NOT EXISTS` 对已存在的索引是空操作，不会虚增）。
2. **只补空列**：`fill_empty_question_columns()` 绝不改写非空值，且第二次返回 0
   （语言 `''` 是通用题的**合法值**，因此 WHERE 守卫必须带 `? <> ''`，否则永远补不完）。
3. **作答事件来源**：`source` 缺省 `'exam'`、练习写 `'practice'`，读侧以列为准。
4. **已练题数**：`count_practiced_questions()` 按**题**去重（同题重练不虚增）。

库落点沿用 `conftest.SCRATCH_DIR`（本机沙箱拒写系统 Temp），每例独立库文件。
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from app.core import repository
from app.core.config import get_settings
from app.core.db import _ADDED_COLUMNS, init_db

#: 临时库落点（与 conftest 同一处 scratch 目录，见其注释里的沙箱原因）。
SCRATCH_DIR = Path(__file__).resolve().parent / ".tmp"

#: r6 时代的 `questions` / `question_attempts` DDL（**没有** r11 三列），用于造存量库。
LEGACY_SCHEMA = """
CREATE TABLE questions (
    id           TEXT PRIMARY KEY,
    direction    TEXT NOT NULL,
    kind         TEXT NOT NULL,
    difficulty   TEXT NOT NULL,
    essentiality TEXT NOT NULL,
    prompt       TEXT NOT NULL,
    options      TEXT NOT NULL,
    answer       TEXT NOT NULL,
    source       TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
CREATE INDEX idx_questions_pool ON questions (direction, difficulty);

CREATE TABLE question_attempts (
    id          TEXT PRIMARY KEY,
    question_id TEXT NOT NULL,
    run_id      TEXT NOT NULL,
    correct     INTEGER NOT NULL,
    answered_at TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    UNIQUE (question_id, run_id)
);
CREATE INDEX idx_attempts_question ON question_attempts (question_id, answered_at);
"""

#: 存量库里的一行「老题」：升级后必须一字不变（题面 / 答案 / 难度都不碰）。
LEGACY_QUESTION = {
    "id": "legacy-q1",
    "direction": "前端",
    "kind": "single",
    "difficulty": "basic",
    "essentiality": "must_know",
    "prompt": "HTTP 状态码 401 表示什么？",
    "options": [{"key": "A", "text": "未认证"}, {"key": "B", "text": "未授权"}],
    "answer": ["A"],
}


def _connect(db_file: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    return conn


def _columns(db_file: Path, table: str) -> list[str]:
    conn = _connect(db_file)
    try:
        return [row["name"] for row in conn.execute(f"PRAGMA table_info({table})")]
    finally:
        conn.close()


def _schema_version(db_file: Path) -> int:
    conn = _connect(db_file)
    try:
        row = conn.execute("PRAGMA schema_version").fetchone()
        return int(row[0])
    finally:
        conn.close()


@pytest.fixture()
def legacy_db(monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """按 r6 DDL 造一个**未升级**的库，并塞一行存量题（不跑 `init_db()`）。"""
    SCRATCH_DIR.mkdir(exist_ok=True)
    db_file = SCRATCH_DIR / f"r11-legacy-{uuid4().hex}.db"
    conn = _connect(db_file)
    try:
        conn.executescript(LEGACY_SCHEMA)
        row = LEGACY_QUESTION
        conn.execute(
            "INSERT INTO questions (id, direction, kind, difficulty, essentiality, prompt, "
            "options, answer, source, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'seed', '2026-10-01T00:00:00Z', '2026-10-01T00:00:00Z')",
            (
                row["id"],
                row["direction"],
                row["kind"],
                row["difficulty"],
                row["essentiality"],
                row["prompt"],
                '[{"key": "A", "text": "未认证"}, {"key": "B", "text": "未授权"}]',
                '["A"]',
            ),
        )
        conn.commit()
    finally:
        conn.close()
    assert "language" not in _columns(db_file, "questions"), "前置条件：存量库不应有新列"
    monkeypatch.setenv("DB_PATH", str(db_file))
    get_settings.cache_clear()
    try:
        yield db_file
    finally:
        get_settings.cache_clear()
        db_file.unlink(missing_ok=True)


def test_init_db_adds_columns_idempotently(legacy_db: Path) -> None:
    """AC-5：存量库跑 `init_db()` 即补三列，且第二次执行 0 条 DDL（schema_version 不变）。"""
    init_db()
    assert {"language", "explanation"} <= set(_columns(legacy_db, "questions"))
    assert "source" in _columns(legacy_db, "question_attempts")
    # 三列都来自 `_ADDED_COLUMNS` 这一份清单（加列只改那里，不允许旁路 ALTER）
    for table, column, _ddl in _ADDED_COLUMNS:
        assert column in _columns(legacy_db, table), f"{table}.{column} 未按 _ADDED_COLUMNS 补齐"

    version_after_first = _schema_version(legacy_db)
    columns_after_first = {
        table: _columns(legacy_db, table) for table, _column, _ddl in _ADDED_COLUMNS
    }

    init_db()  # 第二次：缺列判定为「已存在」→ 不应再发任何 DDL

    assert _schema_version(legacy_db) == version_after_first, "第二次 init_db 不得再改 schema"
    for table, _column, _ddl in _ADDED_COLUMNS:
        assert _columns(legacy_db, table) == columns_after_first[table], "列集合必须稳定"


def test_init_db_builds_r11_indexes_on_legacy_db(legacy_db: Path) -> None:
    """索引引用新列，故必须在补列之后建：存量库升级后新索引一定存在。"""
    init_db()
    conn = _connect(legacy_db)
    try:
        names = {row["name"] for row in conn.execute("PRAGMA index_list(questions)")}
        names |= {row["name"] for row in conn.execute("PRAGMA index_list(question_attempts)")}
    finally:
        conn.close()
    assert {"idx_questions_lang_pool", "idx_attempts_run"} <= names
    # 老索引不因迁移丢失（反复 init 是同一份 SCHEMA_INDEXES）
    assert {"idx_questions_pool", "idx_attempts_question"} <= names


def test_new_columns_default_empty_on_upgraded_rows(legacy_db: Path) -> None:
    """升级不重导：存量行保留原值，新列取列默认值（`language=''`、解析空、来源 exam）。"""
    init_db()
    stored = {row["id"]: row for row in repository.list_questions()}["legacy-q1"]
    assert stored["prompt"] == LEGACY_QUESTION["prompt"], "题面不得被升级改写"
    assert stored["answer"] == LEGACY_QUESTION["answer"], "答案不得被升级改写"
    assert stored["difficulty"] == LEGACY_QUESTION["difficulty"]
    assert stored["language"] == "", "存量题的 language 应为列默认空串（通用题）"
    assert stored["explanation"] == "", "存量题的 explanation 应为列默认空串"


def test_insert_question_writes_new_columns(tmp_db: Path) -> None:
    """新题随行写入 language / explanation，`list_questions()` 原样读回。"""
    assert repository.count_questions() == 0
    assert repository.insert_question(
        {
            "id": "js-q1",
            "direction": "前端",
            "kind": "single",
            "difficulty": "basic",
            "essentiality": "must_know",
            "prompt": "`const` 声明会阻止对象属性修改吗？",
            "options": [{"key": "A", "text": "会"}, {"key": "B", "text": "不会"}],
            "answer": ["B"],
            "language": "js",
            "explanation": "`const` 只锁定绑定的引用，对象属性仍可修改。",
        }
    )
    row = repository.list_questions()[0]
    assert row["language"] == "js"
    assert row["explanation"] == "`const` 只锁定绑定的引用，对象属性仍可修改。"
    assert row["source"] == "seed"


def test_insert_question_is_idempotent(tmp_db: Path) -> None:
    """重复导入 0 新增（AC-5）：同 `id` 第二次返回 False，行数不变、非空值不被覆盖。"""
    base = {
        "id": "dup-q1",
        "direction": "后端",
        "kind": "single",
        "difficulty": "basic",
        "essentiality": "advanced",
        "prompt": "Go 的 goroutine 由谁调度？",
        "options": [{"key": "A", "text": "运行时"}, {"key": "B", "text": "内核"}],
        "answer": ["A"],
        "language": "go",
        "explanation": "Go 运行时用 M:N 调度器调度 goroutine。",
    }
    assert repository.insert_question(base) is True
    assert repository.insert_question({**base, "prompt": "被改写的新题面"}) is False
    rows = repository.list_questions()
    assert len(rows) == 1
    assert rows[0]["prompt"] == base["prompt"], "ON CONFLICT DO NOTHING 不得覆盖既有行"


def test_fill_empty_columns_never_overwrites(tmp_db: Path) -> None:
    """只补空单元格：非空值原样保留，缺的那列才被种子填上。"""
    repository.insert_question(
        {
            "id": "q-filled",
            "direction": "前端",
            "kind": "single",
            "difficulty": "basic",
            "essentiality": "must_know",
            "prompt": "既有的题面",
            "options": [{"key": "A", "text": "x"}],
            "answer": ["A"],
            "language": "python",  # 已有值，种子给别的语言也必须不动
            "explanation": "",     # 空 → 应被补
        }
    )
    filled = repository.fill_empty_question_columns(
        [{"id": "q-filled", "language": "java", "explanation": "补上的解析"}]
    )
    assert filled == 1
    row = repository.list_questions()[0]
    assert row["language"] == "python", "非空 language 不得被种子覆盖"
    assert row["explanation"] == "补上的解析"
    assert row["prompt"] == "既有的题面", "对齐题面 / 答案一列都不碰"


def test_fill_empty_columns_is_idempotent(tmp_db: Path) -> None:
    """幂等：第二次补列返回 0（`language=''` 是通用题的合法值，不会被反复改写）。"""
    repository.insert_question(
        {
            "id": "generic-q1",
            "direction": "算法",
            "kind": "single",
            "difficulty": "basic",
            "essentiality": "nice_to_know",
            "prompt": "冒泡排序最坏时间复杂度？",
            "options": [{"key": "A", "text": "O(n log n)"}, {"key": "B", "text": "O(n^2)"}],
            "answer": ["B"],
            "language": "",
            "explanation": "",
        }
    )
    seed_rows: list[dict[str, Any]] = [
        {"id": "generic-q1", "language": "", "explanation": "最坏逆序时需 O(n^2) 次比较。"}
    ]
    assert repository.fill_empty_question_columns(seed_rows) == 1
    assert repository.fill_empty_question_columns(seed_rows) == 0, "第二次必须 0 变更"
    row = repository.list_questions()[0]
    assert row["explanation"] == "最坏逆序时需 O(n^2) 次比较。"
    assert row["language"] == "", "通用题的 language 保持空串（不得被当成未填反复改写）"


def test_fill_empty_columns_skips_rows_without_seed_values(tmp_db: Path) -> None:
    """种子两个字段都为空 → 一句 SQL 都不发（返回 0，不白写 updated_at）。"""
    repository.insert_question(
        {
            "id": "q-blank",
            "direction": "前端",
            "kind": "single",
            "difficulty": "basic",
            "essentiality": "advanced",
            "prompt": "题面",
            "options": [{"key": "A", "text": "x"}],
            "answer": ["A"],
        }
    )
    conn = _connect(tmp_db)
    try:
        before = conn.execute("SELECT updated_at FROM questions WHERE id = 'q-blank'").fetchone()[0]
    finally:
        conn.close()
    assert repository.fill_empty_question_columns([{"id": "q-blank", "language": "", "explanation": ""}]) == 0
    assert repository.fill_empty_question_columns([]) == 0
    conn = _connect(tmp_db)
    try:
        after = conn.execute("SELECT updated_at FROM questions WHERE id = 'q-blank'").fetchone()[0]
    finally:
        conn.close()
    assert after == before, "无种子值不得触碰 updated_at"


def test_attempt_source_defaults_to_exam(tmp_db: Path) -> None:
    """AC-16：`source` 缺省 exam，练习显式写 practice；读侧以列为准。"""
    written = repository.insert_attempts(
        [
            {
                "id": "att-1",
                "question_id": "js-q1",
                "run_id": "exam-1",
                "correct": 1,
                "answered_at": "2026-11-01T10:00:00Z",
            },
            {
                "id": "att-2",
                "question_id": "js-q2",
                "run_id": "practice:ps_1",
                "correct": 0,
                "answered_at": "2026-11-01T10:05:00Z",
                "source": "practice",
            },
        ]
    )
    assert written == 2
    by_run = {row["run_id"]: row for row in repository.list_attempts()}
    assert by_run["exam-1"]["source"] == "exam"
    assert by_run["practice:ps_1"]["source"] == "practice"


def test_attempt_source_column_default_exam(tmp_db: Path) -> None:
    """列默认值本身也是 exam（漏传 source 的旧调用方拿到 exam，不会写成空串）。"""
    conn = _connect(tmp_db)
    try:
        conn.execute(
            "INSERT INTO question_attempts (id, question_id, run_id, correct, answered_at, created_at) "
            "VALUES ('att-raw', 'q1', 'run-old', 1, '2026-11-01T09:00:00Z', '2026-11-01T09:00:00Z')"
        )
        conn.commit()
    finally:
        conn.close()
    assert repository.list_attempts()[0]["source"] == "exam"


def test_attempts_keep_single_event_per_run(tmp_db: Path) -> None:
    """同会话同题重复提交不写第二条（UNIQUE 兜底），跨会话重练才记新事件。"""
    def attempt(attempt_id: str, run_id: str) -> dict[str, Any]:
        return {
            "id": attempt_id,
            "question_id": "css-q1",
            "run_id": run_id,
            "correct": 1,
            "answered_at": "2026-11-01T11:00:00Z",
            "source": "practice",
        }

    assert repository.insert_attempts([attempt("a1", "practice:ps_1")]) == 1
    assert repository.insert_attempts([attempt("a2", "practice:ps_1")]) == 0
    assert repository.insert_attempts([attempt("a3", "practice:ps_2")]) == 1
    assert len(repository.list_attempts()) == 2


def test_count_practiced_questions_distinct(tmp_db: Path) -> None:
    """`practiced` 按题去重：同题多事件算 1，跨题累加，空库 0。"""
    assert repository.count_practiced_questions() == 0
    rows = [
        {
            "id": f"att-{index}",
            "question_id": question_id,
            "run_id": run_id,
            "correct": 1,
            "answered_at": f"2026-11-01T12:0{index}:00Z",
            "source": "practice" if run_id.startswith("practice:") else "exam",
        }
        for index, (question_id, run_id) in enumerate(
            [
                ("q-a", "practice:ps_1"),
                ("q-a", "practice:ps_2"),  # 同题重练 → 不虚增
                ("q-b", "exam-1"),         # 笔试做过的题也算「已练」
            ]
        )
    ]
    assert repository.insert_attempts(rows) == 3
    assert repository.count_practiced_questions() == 2


def test_list_questions_carries_new_columns(tmp_db: Path) -> None:
    """读侧形状：`list_questions()` 恒带 language / explanation（不再有旧形状分支）。"""
    repository.insert_question(
        {
            "id": "vue-q1",
            "direction": "前端",
            "kind": "judge",
            "difficulty": "intermediate",
            "essentiality": "must_know",
            "prompt": "Vue 3 的 ref 与 reactive 都能创建响应式数据。",
            "options": [{"key": "A", "text": "正确"}, {"key": "B", "text": "错误"}],
            "answer": ["A"],
            "language": "vue3",
            "explanation": "ref 包裹任意值、reactive 只接受对象；两者都创建响应式数据。",
        }
    )
    row = repository.list_questions()[0]
    assert set(row) >= {"language", "explanation", "kind", "answer"}
    assert row["kind"] == "judge"
    assert row["language"] == "vue3"
    assert row["explanation"].startswith("ref 包裹任意值")
