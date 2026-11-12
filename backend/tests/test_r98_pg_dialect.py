"""r98 占位符适配层的回归测试（`db.to_pg_sql()`）。

这一层是换库时唯一「看起来能跑、实际会炸」的地方：SQLite 时代 149 处 SQL 都写 `?`，
PG 用 `%` 解析参数，两者语义冲突。适配层把 `?` 翻成 `%s` 时必须同时转义字面量 `%`
（`LIKE '%kw%'`），否则报 `there is no parameter $kw`。

**r98 收尾修过一个反向 bug**：原判据是「含 `?` **或** `%`」，于是直接写 `%s` 的新 SQL
被二次转义成 `%%s`，psycopg 报 `0 placeholders but N parameters` —— 而 `db.py` 顶部与
`memory.md` 都写着「新写的 SQL 直接用 `%s`」，等于文档教人写必崩的代码。判据收紧到
「只看有没有 `?`」后两条路都通。这几个用例锁住的就是那个判据。
"""

from __future__ import annotations

import pytest

from app.core.db import connection, to_pg_sql


@pytest.mark.parametrize(
    ("sql", "expected"),
    [
        # 存量写法：`?` 翻成 `%s`，没有字面量 `%` 时不做额外处理
        ("SELECT 1 WHERE id = ?", "SELECT 1 WHERE id = %s"),
        ("SELECT 1 WHERE a = ? AND b = ?", "SELECT 1 WHERE a = %s AND b = %s"),
        # 存量 + 检索：`?` 照翻，字面量 `%` 必须转成 `%%`，否则 psycopg 当占位符解析
        (
            "SELECT 1 WHERE prompt LIKE '%k%' AND id = ?",
            "SELECT 1 WHERE prompt LIKE '%%k%%' AND id = %s",
        ),
        # 新写法：直写 `%s` 必须原样透传（这是本次修复的核心）
        ("SELECT 1 WHERE id = %s", "SELECT 1 WHERE id = %s"),
        # 无参 SQL（simple protocol）：`%` 不解析，不能转义
        ("SELECT 1 WHERE prompt LIKE '%k%'", "SELECT 1 WHERE prompt LIKE '%k%'"),
        # 无占位符的普通 DDL
        ("CREATE TABLE IF NOT EXISTS t (id TEXT)", "CREATE TABLE IF NOT EXISTS t (id TEXT)"),
    ],
)
def test_placeholder_translation(sql: str, expected: str) -> None:
    assert to_pg_sql(sql) == expected


def test_translation_is_idempotent() -> None:
    """翻译**幂等**：对结果再翻一次必须不变。

    这是判据收紧带来的额外收益。旧判据（含 `%` 就转义）下，`to_pg_sql()` 的结果含 `%%`
    → 再调用会变 `%%%%`，即「翻译两次 = 换一个 SQL」，任何重试/重放路径都会踩到。
    新判据只在出现 `?` 时介入，而翻译结果里已无 `?`，于是天然稳定。
    """
    for sql in (
        "SELECT 1 WHERE a = ? AND b LIKE '%x%'",
        "SELECT 1 WHERE id = %s",
        "CREATE TABLE IF NOT EXISTS t (id TEXT)",
    ):
        once = to_pg_sql(sql)
        assert "?" not in once, "翻译结果不得残留 `?`"
        assert "%%s" not in once, "`%%s` 是二次转义的指纹，出现即说明判据回退了"
        assert to_pg_sql(once) == once, "翻译必须是幂等的"


def test_both_placeholder_styles_execute() -> None:
    """真连库：`?` 与 `%s` 两种写法都必须能跑（不依赖具体表，纯 SELECT）。"""
    with connection() as conn:
        assert conn.execute("SELECT ? AS v", ("qmark",)).fetchone()["v"] == "qmark"
        assert conn.execute("SELECT %s AS v", ("format",)).fetchone()["v"] == "format"

        # 字面量百分号：`?` 写法自动转义，`%s` 写法需自己写 `%%`
        row = conn.execute(
            "SELECT ? AS v WHERE 'abc-key' LIKE '%' || ? || '%'", ("hit", "key")
        ).fetchone()
        assert row["v"] == "hit"
        row = conn.execute(
            "SELECT %s AS v WHERE 'abc-key' LIKE '%%' || %s || '%%'", ("hit", "key")
        ).fetchone()
        assert row["v"] == "hit"
