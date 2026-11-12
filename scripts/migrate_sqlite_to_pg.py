#!/usr/bin/env python3
"""r98 一次性数据迁移：SQLite → PostgreSQL。

用法（**先停后端**，避免迁移过程中仍有写入）：

    python scripts/migrate_sqlite_to_pg.py \
        --sqlite /data/app.db \
        --pg postgresql://postgres:***@postgres:5432/sc_app

设计取舍：

- **幂等可重跑**：每张表用 `ON CONFLICT DO NOTHING`，中途失败直接再跑一次即可续上，
  不会因为主键重复而中断，也不会覆盖 PG 里已有的行。
- **列取交集**：SQLite 老库可能缺后来补的列（`user_id` / `language` / `started_on`…），
  PG 表由 `init_db()` 建成"新全列"。只搬两边都有的列，缺的列落 PG 默认值。
- **缺列兜底**：少数列是 `NOT NULL` 又**没有 DEFAULT**（`users.display_name`），
  老库连列都没有，取交集后会落 `null` 直接违约。这类列按类型补安全占位值
  （文本 `''` / 整数 `0` / 布尔 `false` / json `{}`），并逐列打印出来。
- **逐行降级**：批次插入走 SAVEPOINT，整批失败时降级为逐行重试，单行脏数据只丢该行，
  不牵连整张表；末尾汇总跳过的行（带主键）并非 0 退出。
- **自增序列复位**：`radar_snapshots` / `radar_assessments` / `radar_runs` 用
  `IDENTITY` 主键，显式插入旧 id 后序列仍停在 1，下一次插入必然主键冲突。
  迁移末尾按 `MAX(id)` 重置，这是最容易漏、又必然在"迁移后第一次采集"炸掉的一步。
- **行数校验**：逐表比对源/目标计数，不一致就非 0 退出，不留下"看起来成功了"的假象。
- **不搬 `question_search`**：SQLite 的 FTS5 虚表在 PG 没有对应物，检索改由
  `pg_trgm` 索引支撑，数据源仍是 `questions`，不需要迁移。
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

#: FTS5 虚表及其影子表不迁移（`question_search_*` 是 SQLite 的内部索引）。
SKIP_TABLES = {"question_search"}
SKIP_PREFIXES = ("question_search_", "sqlite_")

#: 带自增主键的表 → 主键列名，迁移后需要复位序列。
IDENTITY_TABLES = {
    "radar_snapshots": "id",
    "radar_assessments": "id",
    "radar_runs": "run_id",
}

#: 报错时用来指认是哪一行的候选列（按优先级）。
LABEL_COLUMNS = ("id", "run_id", "user_id", "email", "doc_id", "code", "name", "question_id")


def sqlite_tables(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")
    names: list[str] = []
    for row in rows:
        name = str(row["name"])
        if name in SKIP_TABLES or name.startswith(SKIP_PREFIXES):
            continue
        names.append(name)
    return names


def pg_column_meta(conn: psycopg.Connection, table: str) -> dict[str, Mapping[str, Any]]:
    """目标表的列元数据：列名 → `{is_nullable, column_default, is_identity, data_type, udt_name}`。"""
    rows = conn.execute(
        "SELECT column_name, is_nullable, column_default, is_identity, data_type, udt_name "
        "FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = %s",
        (table,),
    ).fetchall()
    return {str(row["column_name"]): row for row in rows}


def pg_columns(conn: psycopg.Connection, table: str) -> set[str]:
    return set(pg_column_meta(conn, table))


def default_value(meta: Mapping[str, Any]) -> Any:
    """从 `column_default` 里抠出可用的字面量；解析不出来返回 `None`，由类型占位兜底。

    PG 的默认值表达式长这样：`'member'::text` / `0` / `true` / `'[]'::text`。
    宁可补成列自己的默认值（`role` 补 `member`），也不要补成空串丢掉语义。
    """
    raw = meta.get("column_default")
    if not raw:
        return None
    text = str(raw).strip()
    if "::" in text:
        text = text.split("::", 1)[0].strip()
    if len(text) >= 2 and text.startswith("'") and text.endswith("'"):
        return text[1:-1].replace("''", "'")
    lowered = text.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    for cast in (int, float):
        try:
            return cast(text)
        except ValueError:
            continue
    return None  # now() / nextval(...) 这类，交给类型占位


def fill_value(meta: Mapping[str, Any]) -> Any:
    """`NOT NULL` 无默认列的安全占位值，按 PG 类型给。

    只返回 sqlite3 能绑定的标量（`str` / `int` / `bool` / `bytes`）——占位值要先经过
    SQLite 的 SELECT 参数，`dict` 这类对象在这一步就会 TypeError。
    json 列给空对象的字符串，PG 收到 text 会按目标列类型隐式转成 json/jsonb。
    """
    udt = str(meta.get("udt_name") or "").lower()
    dtype = str(meta.get("data_type") or "").lower()
    if udt in {"json", "jsonb"}:
        return "{}"
    if udt in {"int2", "int4", "int8"} or dtype in {"smallint", "integer", "bigint"}:
        return 0
    if udt in {"float4", "float8", "numeric"} or dtype in {"real", "double precision", "numeric"}:
        return 0
    if udt == "bool" or dtype == "boolean":
        return False
    if udt == "bytea" or dtype == "bytea":
        return b""
    return ""


def patch_value(meta: Mapping[str, Any]) -> Any:
    """给非空列补值的口径：有 DEFAULT 用 DEFAULT，没有才按类型给安全值。"""
    value = default_value(meta)
    return fill_value(meta) if value is None else value


def row_label(columns: Sequence[str], row: Sequence[Any]) -> str:
    values = dict(zip(columns, row))
    for name in LABEL_COLUMNS:
        if name in values:
            return f"{name}={values[name]!r}"
    return repr(tuple(row))[:80]


def insert_batch(
    dst: psycopg.Connection,
    statement: sql.Composed,
    payload: Sequence[Sequence[Any]],
    columns: Sequence[str],
) -> tuple[int, list[str]]:
    """先整批插入，失败则逐行重试；返回 `(写入行数, 跳过行说明)`。

    批次用 `dst.transaction()` 包住——连接已处于事务中时它就是 SAVEPOINT，
    失败只回滚这一段，连接仍可继续用（否则 aborted 事务会连带后面全部失败）。
    """
    try:
        with dst.transaction(), dst.cursor() as cur:
            cur.executemany(statement, payload)
            return max(cur.rowcount, 0), []
    except psycopg.Error as exc:
        reason = str(exc).strip().splitlines()[0]
        print(f"    整批插入失败（{reason}），降级为逐行重试")

    written = 0
    skipped: list[str] = []
    for row in payload:
        try:
            with dst.transaction(), dst.cursor() as cur:
                cur.execute(statement, row)
                written += max(cur.rowcount, 0)
        except psycopg.Error as exc:
            reason = str(exc).strip().splitlines()[0]
            skipped.append(f"{row_label(columns, row)} ← {reason}")
    return written, skipped


def copy_table(
    src: sqlite3.Connection,
    dst: psycopg.Connection,
    table: str,
    batch: int,
) -> tuple[int, int, list[str]]:
    """搬一张表，返回 `(源行数, 写入行数, 跳过行说明)`。目标表不存在时返回 `(0, 0, [])`。"""
    src_columns = [str(row["name"]) for row in src.execute(f'PRAGMA table_info("{table}")')]
    if not src_columns:
        return 0, 0, []
    meta = pg_column_meta(dst, table)
    if not meta:
        print(f"  跳过 {table}：目标库没有这张表（可能不属于当前版本）")
        return 0, 0, []
    columns = [name for name in src_columns if name in meta]
    if not columns:
        print(f"  跳过 {table}：没有可对应的列")
        return 0, 0, []

    # PG 侧 NOT NULL 的列（IDENTITY 除外）分两种兜底，少了任何一种都会整行违约：
    #   1. 源库缺这列 → 常量占位（有 DEFAULT 的让 PG 自己填，不插手）
    #   2. 源库有这列但值为 NULL → COALESCE 补空值。**有 DEFAULT 也要补**：
    #      DEFAULT 只在 INSERT 不列该列时生效，显式传 NULL 照样撞约束。
    required = [
        name
        for name, info in meta.items()
        if info["is_nullable"] == "NO"
        # information_schema 的 is_identity 是 'YES'/'NO' 字符串，`not "NO"` 恒为假
        and info["is_identity"] != "YES"
    ]
    missing = [
        name for name in required if name not in columns and meta[name]["column_default"] is None
    ]
    null_guard = [name for name in required if name in columns]
    if missing:
        print(f"  {table} 缺列补默认值：{', '.join(sorted(missing))}")
    for name in null_guard:
        blanks = int(
            src.execute(f'SELECT COUNT(*) FROM "{table}" WHERE "{name}" IS NULL').fetchone()[0]
        )
        if blanks:
            print(f"  {table}.{name}：{blanks} 行为空，迁移时补默认值")

    all_columns = columns + missing

    # SELECT 列表与参数一一对应，一次遍历同时产出两者，避免顺序错位：
    # 普通列直接取；非空列套 COALESCE 补空值；缺列用常量占位（排在最后）。
    select_parts: list[str] = []
    fill_values: list[Any] = []
    for name in columns:
        if name in null_guard:
            select_parts.append(f'COALESCE("{name}", ?)')
            fill_values.append(patch_value(meta[name]))
        else:
            select_parts.append(f'"{name}"')
    for name in missing:
        select_parts.append("?")
        fill_values.append(fill_value(meta[name]))

    total = int(src.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
    if total == 0:
        return 0, 0, []

    statement = sql.SQL("INSERT INTO {} ({}) VALUES ({}) ON CONFLICT DO NOTHING").format(
        sql.Identifier(table),
        sql.SQL(", ").join(sql.Identifier(name) for name in all_columns),
        sql.SQL(", ").join(sql.Placeholder() for _ in all_columns),
    )
    select_sql = f'SELECT {", ".join(select_parts)} FROM "{table}"'
    cursor = src.execute(select_sql, fill_values)

    written = 0
    skipped: list[str] = []
    while True:
        rows = cursor.fetchmany(batch)
        if not rows:
            break
        payload = [tuple(row) for row in rows]
        batch_written, batch_skipped = insert_batch(dst, statement, payload, all_columns)
        written += batch_written
        skipped.extend(batch_skipped)
    return total, written, skipped


def reset_identity(dst: psycopg.Connection, table: str, column: str) -> None:
    """把 IDENTITY 序列推到 `MAX(column)+1`，否则后续插入会撞旧 id。"""
    dst.execute(
        sql.SQL(
            "SELECT setval("
            "  pg_get_serial_sequence(%s, %s),"
            "  COALESCE((SELECT MAX({col}) FROM {tbl}), 0) + 1,"
            "  false"
            ")"
        ).format(col=sql.Identifier(column), tbl=sql.Identifier(table)),
        (table, column),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SQLite → PostgreSQL 一次性数据迁移")
    parser.add_argument("--sqlite", required=True, help="源 SQLite 文件路径")
    parser.add_argument("--pg", required=True, help="目标 PostgreSQL 连接串")
    parser.add_argument("--batch", type=int, default=500, help="每批行数（默认 500）")
    parser.add_argument("--dry-run", action="store_true", help="只报告将迁移哪些表与行数")
    args = parser.parse_args(argv)
    # 管道里 stdout 默认块缓冲，会和后面写 stderr 的汇总错序，看着像"先报错后干活"
    sys.stdout.reconfigure(line_buffering=True)

    source_path = Path(args.sqlite)
    if not source_path.is_file():
        print(f"源库不存在：{source_path}", file=sys.stderr)
        return 1

    src = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    try:
        tables = sqlite_tables(src)
        print(f"源库 {source_path.name}：{len(tables)} 张表")
        if args.dry_run:
            for table in tables:
                count = int(src.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
                print(f"  {table}: {count} 行")
            return 0

        mismatches: list[str] = []
        skipped_total: dict[str, list[str]] = {}
        with psycopg.connect(args.pg, autocommit=False, row_factory=dict_row) as dst:
            for table in tables:
                total, written, skipped = copy_table(src, dst, table, args.batch)
                if total == 0:
                    continue
                print(f"  {table}: 源 {total} 行 → 写入 {written} 行")
                if skipped:
                    print(f"    {len(skipped)} 行因约束失败被跳过")
                    skipped_total[table] = skipped
                elif written < total:
                    # 目标库已有同主键行（重跑）属正常，不记为失败
                    print(f"    （{total - written} 行已在目标库中，按幂等跳过）")
            for table, column in IDENTITY_TABLES.items():
                if table in tables:
                    reset_identity(dst, table, column)
            dst.commit()

            print("校验行数：")
            for table in tables:
                src_total = int(src.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
                if src_total == 0:
                    continue
                if not pg_columns(dst, table):
                    continue
                dst_total = int(dst.execute(
                    sql.SQL("SELECT COUNT(*) FROM {}").format(sql.Identifier(table))
                ).fetchone()["count"])
                mark = "OK" if dst_total >= src_total else "缺行"
                print(f"  {table}: 源 {src_total} / 目标 {dst_total} {mark}")
                if dst_total < src_total:
                    mismatches.append(table)

        if skipped_total:
            print("以下行未能迁移（需人工处理）：", file=sys.stderr)
            for table, items in skipped_total.items():
                for item in items[:20]:
                    print(f"  {table}: {item}", file=sys.stderr)
                if len(items) > 20:
                    print(f"  {table}: ……另有 {len(items) - 20} 行", file=sys.stderr)
        if mismatches:
            print(f"迁移不完整：{', '.join(mismatches)}", file=sys.stderr)
            return 1
        print("迁移完成，逐表行数均不少于源库。")
        return 0
    finally:
        src.close()


if __name__ == "__main__":
    raise SystemExit(main())
