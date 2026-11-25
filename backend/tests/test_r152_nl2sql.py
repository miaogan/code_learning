"""r152 nl2sql：只读数据问答的闸门、隔离与执行（AC-1 ~ AC-6）。

分层断言：
- **纯函数层**（`check_sql` / `inline_views`）：零 IO，逐条钉住「哪些 SQL 能过」；
- **执行层**（`db.readonly_query`）：只读是真的只读、且**不持写锁**；
- **端到端**（`nl2sql.query` + `FakeAI`）：生成 → 校验 → 执行 → 审计四段连通，
  并验证「另一个账号的行查不到」这条产品承诺。

本文件不产生任何外网请求：模型一律用 `FakeAI` 注入。
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.core import db, repository
from app.core.config import get_settings
from app.services import nl2sql

UID = "default"
OTHER_UID = "someone-else"


def _responder(sql: str, explain: str = "统计口径") -> Any:
    """构造一个只会给出指定 SQL 的假模型（签名与 conftest.FakeAI 的 responder 一致）。"""

    def _make(model_cls: Any, _user: str) -> dict[str, Any]:
        return {"sql": sql, "explain": explain}

    return _make


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _seed_attempts() -> None:
    """造 6 条作答：本账号 5 条（缓存 3 / 数据库 2），另一账号 1 条用于验证隔离。

    题库行按 `question_id` 去重后单独插入：两个账号可能答同一道题，
    `questions` 的主键会撞（这张表本来就是全站共享的，没有 user_id）。
    """
    rows = [
        ("qa-1", UID, "q-cache-1", "缓存", 1),
        ("qa-2", UID, "q-cache-2", "缓存", 0),
        ("qa-3", UID, "q-cache-3", "缓存", 1),
        ("qa-4", UID, "q-db-1", "数据库", 1),
        ("qa-5", UID, "q-db-2", "数据库", 0),
        ("qa-x", OTHER_UID, "q-cache-1", "缓存", 1),
    ]
    questions = {question_id: direction for _, _, question_id, direction, _ in rows}
    with db.connection() as conn:
        for question_id, direction in questions.items():
            stamp = "2026-11-01T00:00:00.000+00:00"
            conn.execute(
                "INSERT INTO questions (id, direction, sub_direction, kind, difficulty, "
                "essentiality, prompt, options, answer, source, language, explanation, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    question_id, direction, "redis", "single", "basic", "must_know",
                    f"{direction}题 {question_id}", "[]", "[]", "seed", "", "解析",
                    stamp, stamp,
                ),
            )
        for index, (attempt_id, user_id, question_id, _direction, correct) in enumerate(rows):
            stamp = f"2026-11-{index + 1:02d}T00:00:00.000+00:00"
            # `question_attempts` 有 `UNIQUE (question_id, run_id)`：另一账号答同一道题时
            # 必须给它另一个场次 id，否则撞的是唯一约束而不是「用户隔离没生效」。
            run_id = "exam:1" if user_id == UID else "exam:2"
            conn.execute(
                "INSERT INTO question_attempts (id, user_id, question_id, run_id, correct, "
                "answered_at, created_at, source) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (attempt_id, user_id, question_id, run_id, correct, stamp, stamp, "exam"),
            )


# --- 第 1 层：纯函数闸门 --------------------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT count(*) FROM my_attempts",
        "SELECT direction, sum(correct) AS ok FROM my_attempts GROUP BY direction",
        "SELECT * FROM my_attempts WHERE answered_at >= '2026-11-01'",
        "SELECT count(*) FROM my_attempts WHERE prompt LIKE '%redis%'",
        "SELECT a.direction, count(*) AS n FROM my_attempts a GROUP BY a.direction ORDER BY n DESC LIMIT 5",
        "SELECT cast(sum(correct) AS double) / count(*) AS rate FROM my_attempts",
    ],
)
def test_check_sql_accepts_plain_select(sql: str) -> None:
    assert nl2sql.check_sql(nl2sql._normalize_sql(sql)) is None


@pytest.mark.parametrize(
    ("sql", "fragment"),
    [
        ("SELECT count(*) FROM my_attempts; DROP TABLE runs", "一条语句"),
        ("DELETE FROM question_attempts", "查询语句"),
        ("UPDATE runs SET status = 'x'", "查询语句"),
        ("SELECT * FROM users", "users"),
        ("SELECT * FROM documents", "documents"),
        ("SELECT * FROM sessions", "sessions"),
        ("SELECT * FROM (SELECT user_id FROM ai_call_logs) t", "ai_call_logs"),
        ("SELECT count(*) FROM my_attempts -- 注释", "注释"),
        ("SELECT count(*) FROM my_attempts /* x */", "注释"),
        ("SELECT count(*) FROM my_attempts WHERE id = ?", "占位符"),
        ('SELECT count(*) FROM "my_attempts"', "引号"),
        ("SELECT pg_read_file('/etc/passwd')", "不被允许"),
        ("SELECT pg_sleep(3)", "不被允许"),
        ("SELECT date_trunc('day', answered_at) FROM my_attempts", "函数 date_trunc"),
        ("WITH t AS (SELECT 1 AS n) SELECT * FROM t", "查询语句"),
        ("SELECT * FROM my_attempts UNION SELECT * FROM users", "users"),
    ],
)
def test_check_sql_rejects(sql: str, fragment: str) -> None:
    reason = nl2sql.check_sql(nl2sql._normalize_sql(sql))
    assert reason is not None, f"应当被拒绝：{sql}"
    assert fragment in reason, reason


def test_inline_views_binds_user_id_in_order() -> None:
    """参数顺序必须与 SQL 文本里 `?` 出现的顺序一致（两库的占位符翻译都靠它）。"""
    sql = (
        "SELECT a.direction, b.direction FROM my_attempts a "
        "JOIN my_attempts b ON a.question_id = b.question_id"
    )
    out, params = nl2sql.inline_views(sql, UID)
    assert "my_attempts" not in out.replace("_nl2sql", "")
    assert "qa.user_id = ?" in out
    assert params == [UID, UID]


def test_inline_views_ignores_string_literals() -> None:
    """只在 `FROM/JOIN` 后面内联：字面量里出现同名词不能被替换掉。"""
    sql = "SELECT * FROM my_attempts WHERE prompt LIKE '%my_attempts%'"
    out, params = nl2sql.inline_views(sql, UID)
    assert "'%my_attempts%'" in out
    assert params == [UID]


# --- 第 2 层：只读连接 ----------------------------------------------------------


def test_readonly_query_returns_dict_rows(tmp_db: Any) -> None:
    _seed_attempts()
    data = db.readonly_query("SELECT count(*) AS n FROM question_attempts WHERE user_id = ?", (UID,))
    assert data["columns"] == ["n"]
    assert data["rows"] == [{"n": 5}]


def test_readonly_query_cannot_write(tmp_db: Any) -> None:
    """只读是数据库层强制的，不依赖上层校验。"""
    with pytest.raises(Exception) as caught:
        db.readonly_query(
            "INSERT INTO taifu_memories (id, user_id, content, created_at, updated_at) "
            "VALUES ('x', 'default', 'x', 'x', 'x')"
        )
    assert not isinstance(caught.value, SystemExit)


def test_readonly_query_does_not_take_writer_lock(tmp_db: Any, monkeypatch: Any) -> None:
    """**r152 的核心约束**：分析查询绝不能持 `_WRITER_LOCK`。

    单进程单 worker 下，那把锁是全局串行的；一条 3 秒的查询持有它，
    就等于 3 秒内所有业务请求排队。这里直接观测执行时刻的持有状态。
    """
    seen: dict[str, bool] = {}
    original = db._execute_raw

    def spy(raw: Any, backend: str, sql: str, params: Any = None) -> Any:
        seen["lock_held"] = db._WRITER_LOCK._is_owned()
        return original(raw, backend, sql, params)

    monkeypatch.setattr(db, "_execute_raw", spy)
    db.readonly_query("SELECT 1 AS n")
    assert seen["lock_held"] is False


def test_business_connection_does_take_writer_lock(tmp_db: Any, monkeypatch: Any) -> None:
    """对照组：证明上一例的观测手法是有效的（不然「没持锁」可能是没测到）。"""
    seen: dict[str, bool] = {}
    original = db._execute_raw

    def spy(raw: Any, backend: str, sql: str, params: Any = None) -> Any:
        seen["lock_held"] = db._WRITER_LOCK._is_owned()
        return original(raw, backend, sql, params)

    monkeypatch.setattr(db, "_execute_raw", spy)
    with db.connection() as conn:
        conn.execute("SELECT 1 AS n")
    assert seen["lock_held"] is True


# --- 第 3 层：端到端 ------------------------------------------------------------


def test_query_returns_counts_and_isolates_user(tmp_db: Any, fake_ai: Any) -> None:
    _seed_attempts()
    fake_ai.responder = _responder(
        "SELECT direction, count(*) AS total, sum(correct) AS ok "
        "FROM my_attempts GROUP BY direction ORDER BY direction"
    )
    result = _run(nl2sql.query("按方向统计我的答题数", client=fake_ai))

    assert result["ok"] is True
    assert result["row_count"] == 2
    by_direction = {row["direction"]: row for row in result["rows"]}
    # 缓存 3 题对 2、数据库 2 题对 1 —— 另一账号那条 correct=1 不能混进来
    assert by_direction["缓存"]["total"] == 3
    assert by_direction["缓存"]["ok"] == 2
    assert by_direction["数据库"]["total"] == 2

    audit = repository_rows()
    assert audit[-1]["status"] == "ok"
    assert audit[-1]["row_count"] == 2
    assert audit[-1]["user_id"] == UID


def test_query_rejects_unknown_table_and_audits(tmp_db: Any, fake_ai: Any) -> None:
    _seed_attempts()
    fake_ai.responder = _responder("SELECT * FROM users")
    result = _run(nl2sql.query("看看所有用户", client=fake_ai))

    assert result["ok"] is False
    assert "users" in result["reason"]
    audit = repository_rows()
    assert audit[-1]["status"] == "rejected"
    # 被拒时：实际执行语句为空，模型原文仍然留档（排查要看模型到底想查什么）
    assert audit[-1]["sql_text"] == ""
    assert audit[-1]["draft_sql"] == "SELECT * FROM users"
    assert "users" in audit[-1]["reject_reason"]


def test_query_enforces_row_cap(tmp_db: Any, fake_ai: Any, monkeypatch: Any) -> None:
    """模型自己写 `LIMIT 9999` 也只拿到配置的行数 —— 外层包裹是服务端说了算。"""
    _seed_attempts()
    fake_ai.responder = _responder("SELECT question_id FROM my_attempts LIMIT 9999")
    # 用 context() 而不是 undo()：undo 会把 autouse fixture 设的 REDIS_URL 等一起撤掉。
    with monkeypatch.context() as scoped:
        scoped.setenv("NL2SQL_MAX_ROWS", "2")
        get_settings.cache_clear()
        result = _run(nl2sql.query("列一下我的作答", client=fake_ai))
    get_settings.cache_clear()
    assert result["ok"] is True
    assert result["row_count"] == 2


def test_query_disabled_by_switch(tmp_db: Any, fake_ai: Any, monkeypatch: Any) -> None:
    with monkeypatch.context() as scoped:
        scoped.setenv("NL2SQL_ENABLED", "false")
        get_settings.cache_clear()
        result = _run(nl2sql.query("随便问", client=fake_ai))
    get_settings.cache_clear()
    assert result["ok"] is False
    assert "未开启" in result["reason"]
    # 开关关掉时连模型都不该调
    assert fake_ai.calls == []


def test_query_survives_audit_failure(tmp_db: Any, fake_ai: Any, monkeypatch: Any) -> None:
    """审计是观测手段，不是业务前置条件：它坏了不能把查询结果一起吞掉。"""
    _seed_attempts()

    def boom(**_kwargs: Any) -> str:
        raise RuntimeError("audit down")

    monkeypatch.setattr(repository, "insert_nl2sql_query", boom)
    fake_ai.responder = _responder("SELECT count(*) AS n FROM my_attempts")
    result = _run(nl2sql.query("一共多少", client=fake_ai))
    assert result["ok"] is True
    assert result["rows"] == [{"n": 5}]


def repository_rows() -> list[dict[str, Any]]:
    with db.connection() as conn:
        rows = conn.execute(
            "SELECT user_id, status, draft_sql, sql_text, reject_reason, row_count "
            "FROM nl2sql_queries ORDER BY created_at, id"
        ).fetchall()
    return [dict(row) for row in rows]


# --- 工具注册 ------------------------------------------------------------------


def test_tool_registered_and_labelled() -> None:
    from app.services.taifu import tools

    assert "query_my_data" in tools.TOOL_NAMES
    assert tools.TOOL_LABELS["query_my_data"] == "数据查询"
    names = {spec["function"]["name"] for spec in tools.TOOL_SPECS}
    assert "query_my_data" in names


def test_tool_specs_hides_tool_when_disabled(monkeypatch: Any) -> None:
    """开关关掉时 schema 不下发；`TOOL_NAMES` 仍保留（幻觉调用拿到可读提示而非「没这工具」）。"""
    from app.services.taifu import tools

    with monkeypatch.context() as scoped:
        scoped.setenv("NL2SQL_ENABLED", "false")
        get_settings.cache_clear()
        names = [spec["function"]["name"] for spec in tools.tool_specs()]
    get_settings.cache_clear()

    assert "query_my_data" not in names
    assert "remember" in names
    assert "query_my_data" in tools.TOOL_NAMES


def test_tool_returns_unified_result(tmp_db: Any, fake_ai: Any) -> None:
    from app.services.taifu import tools

    _seed_attempts()
    fake_ai.responder = _responder("SELECT count(*) AS n FROM my_attempts")
    context = tools.ToolContext(
        profile=None, report=None, attempts=[], memories=[], client=fake_ai
    )
    result = _run(tools.run("query_my_data", '{"question": "我一共做了多少题"}', context))

    assert result["ok"] is True
    assert result["label"].startswith("数据查询")
    assert result["href"] is None
    assert result["content"]


def test_tool_reports_failure_without_raising(tmp_db: Any, fake_ai: Any) -> None:
    from app.services.taifu import tools

    fake_ai.responder = _responder("SELECT * FROM users")
    context = tools.ToolContext(
        profile=None, report=None, attempts=[], memories=[], client=fake_ai
    )
    result = _run(tools.run("query_my_data", '{"question": "查用户"}', context))

    assert result["ok"] is False
    assert any("未读到" in line for line in result["content"])
