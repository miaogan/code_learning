"""性能基准（独立产物）：零网络、零 FastAPI，三个场景全部跑在临时 SQLite 库上。

用法：
    python -X utf8 scripts/benchmark.py            # 全部场景 + 生成 docs/eval/PERF-REPORT.md
    python -X utf8 scripts/benchmark.py --quick    # 缩小规模
    python -X utf8 scripts/benchmark.py --json     # stdout 打印机器可读 JSON
    python -X utf8 scripts/benchmark.py --check    # 只读：打印指标、不写报告、退出 0

诚实边界：本机单盘 / 临时库 / 合成负载，不代表生产 QPS；不做网络 / HTTP 压测。
所有 SQLite 文件由 tempfile.TemporaryDirectory 创建并随进程退出删除，绝不触碰开发库。
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import platform
import sqlite3
import statistics
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SEED_PATH = ROOT / "backend" / "app" / "seed" / "questions.json"
REPORT_PATH = ROOT / "docs" / "eval" / "PERF-REPORT.md"

BUSY_TIMEOUT_MS = 3000
THREADS = 8
LOOPS = 50
REPEATS = 20
QUICK_THREADS = 4
QUICK_LOOPS = 12
QUICK_REPEATS = 5

#: 8 个固定中文关键词（>=3 字，trigram 可命中；命中数来自题库实测）。
KEYWORDS: tuple[str, ...] = (
    "副作用",
    "响应式",
    "事件循环",
    "中间件",
    "序列化",
    "时间复杂度",
    "内存泄漏",
    "分布式锁",
)

PERCENTILE_ALGORITHM = (
    "p50/p95/p99 = 样本升序排序后取第 ceil(q*n)-1 个（0-based，q 分别 0.50/0.95/0.99，"
    "越界夹到 [0, n-1]）；与 backend/app/core/repository.py::_percentile 同口径。"
)

LIMITATIONS: tuple[str, ...] = (
    "本机单盘：临时库位于同一块系统临时盘，IO 争用与生产多盘 / 网络存储不可比。",
    "合成负载：写入是固定短事务 INSERT，检索是固定 8 个中文关键词，不是真实业务流量。",
    "临时库：SQLite 文件由 tempfile.TemporaryDirectory 创建并随进程退出删除，绝不触碰开发库。",
    (
        "不代表生产 QPS：没有连接池、没有 WAL 调优、没有长事务 / 大字段，"
        "数字只用于量化 busy_timeout 的相对收益。"
    ),
    "不做网络 / HTTP 压测：无 FastAPI 进程、无 uvicorn、无端口监听、零网络调用。",
    (
        "分位样本：并发写锁的 p50/p95/p99 只统计成功写入，失败（locked）不计入，"
        "故两组延迟不能当作同一负载下的等值对比，核心结论看成功率与 locked 次数。"
    ),
    (
        "冷热抖动：单次运行未做多轮预热取中位数，微秒级数字受本机调度 / 缓存影响，"
        "宜看量级而非绝对值。"
    ),
)

# --- SQL：与 backend/app/core/db.py 的 R51_SCHEMA / questions 表 / FTS5 虚表等价 -------

_AI_LOG_SCHEMA = """
CREATE TABLE ai_call_logs (
    id           TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL DEFAULT 'default',
    request_id   TEXT NOT NULL DEFAULT '-',
    provider     TEXT NOT NULL,
    model        TEXT NOT NULL,
    kind         TEXT NOT NULL,
    status_code  INTEGER,
    elapsed_ms   INTEGER NOT NULL,
    attempt      INTEGER NOT NULL DEFAULT 1,
    prompt_chars INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL
);
CREATE INDEX idx_ai_call_logs_created ON ai_call_logs (created_at);
CREATE INDEX idx_ai_call_logs_user_model ON ai_call_logs (user_id, model, kind);
"""

_AI_LOG_INSERT = (
    "INSERT INTO ai_call_logs "
    "(id, user_id, request_id, provider, model, kind, status_code, elapsed_ms, "
    "attempt, prompt_chars, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)

_QUESTION_SCHEMA = """
CREATE TABLE questions (
    id            TEXT PRIMARY KEY,
    direction     TEXT NOT NULL,
    sub_direction TEXT,
    kind          TEXT NOT NULL,
    difficulty    TEXT NOT NULL,
    essentiality  TEXT NOT NULL,
    prompt        TEXT NOT NULL,
    options       TEXT NOT NULL,
    answer        TEXT NOT NULL,
    source        TEXT NOT NULL,
    language      TEXT NOT NULL DEFAULT '',
    explanation   TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
"""

_QUESTION_INSERT = (
    "INSERT OR IGNORE INTO questions "
    "(id, direction, sub_direction, kind, difficulty, essentiality, prompt, options, "
    "answer, source, language, explanation, created_at, updated_at) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)

_FTS_SCHEMA = (
    "CREATE VIRTUAL TABLE question_search USING fts5("
    "question_id UNINDEXED, prompt, explanation, direction UNINDEXED, "
    "sub_direction UNINDEXED, tokenize = 'trigram')"
)

_FTS_INSERT = (
    "INSERT INTO question_search "
    "(question_id, prompt, explanation, direction, sub_direction) VALUES (?, ?, ?, ?, ?)"
)

_FTS_MATCH = (
    "SELECT question_id, bm25(question_search) AS rank FROM question_search "
    "WHERE question_search MATCH ? ORDER BY rank LIMIT 5"
)

_LOCK_COLUMNS = (
    "组", "timeout(ms)", "写入", "成功", "成功率", "locked",
    "其它错误", "样本", "均值(us)", "p50", "p95", "p99",
)
_LOCK_HEADER = "| " + " | ".join(_LOCK_COLUMNS) + " |"
_LOCK_SEPARATOR = "| " + " | ".join(["---"] * len(_LOCK_COLUMNS)) + " |"

logger = logging.getLogger("benchmark")


# --- 通用 -------------------------------------------------------------------


def _percentile(values: list[int], quantile: float) -> int:
    """分位：排序取第 ceil(q*n)-1 个（0-based）；空样本返回 0。"""
    if not values:
        return 0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(quantile * len(ordered)) - 1))
    return ordered[index]


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _seed_rows() -> list[dict[str, Any]]:
    rows = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise TypeError(f"题库种子顶层必须是列表：{SEED_PATH}")
    return rows


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())


def _detect_environment() -> dict[str, Any]:
    return {
        "python": platform.python_version(),
        "sqlite": sqlite3.sqlite_version,
        "cpu_count": os.cpu_count(),
        "os": platform.platform(),
    }


def _probe_fts5() -> dict[str, Any]:
    """探测 ENABLE_FTS5 编译选项与 trigram tokenizer 是否真的能建虚表。"""
    conn = sqlite3.connect(":memory:")
    try:
        row = conn.execute(
            "SELECT sqlite_compileoption_used('ENABLE_FTS5')"
        ).fetchone()
        compile_enabled = bool(row and row[0])
        trigram_ok = False
        reason = ""
        if not compile_enabled:
            reason = "SQLite 未编译 ENABLE_FTS5（compileoption_used=0）"
        else:
            try:
                conn.execute(_FTS_SCHEMA)
                trigram_ok = True
            except sqlite3.OperationalError as exc:
                reason = f"FTS5 虚表创建失败：{type(exc).__name__}: {exc}"
        return {
            "compile_enabled": compile_enabled,
            "trigram_ok": trigram_ok,
            "reason": reason,
        }
    finally:
        conn.close()


# --- 场景 1：并发写锁 --------------------------------------------------------


def _run_concurrent_writes(
    db_path: str, *, threads: int, loops: int, busy_timeout_ms: int
) -> dict[str, Any]:
    start_gate = threading.Event()

    def writer(thread_id: int) -> list[tuple[bool, int, str]]:
        conn = sqlite3.connect(db_path, timeout=0)
        conn.execute(f"PRAGMA busy_timeout = {busy_timeout_ms}")
        records: list[tuple[bool, int, str]] = []
        try:
            start_gate.wait()
            for seq in range(loops):
                started = time.perf_counter()
                try:
                    conn.execute(
                        _AI_LOG_INSERT,
                        (
                            f"{thread_id}-{seq}",
                            "default",
                            "-",
                            "bench",
                            "model-x",
                            "success",
                            200,
                            7,
                            1,
                            0,
                            "2026-11-09T00:00:00+00:00",
                        ),
                    )
                    conn.commit()
                    elapsed = int((time.perf_counter() - started) * 1_000_000)
                    records.append((True, elapsed, ""))
                except sqlite3.OperationalError as exc:
                    elapsed = int((time.perf_counter() - started) * 1_000_000)
                    message = str(exc).lower()
                    kind = "locked" if ("locked" in message or "busy" in message) else "other"
                    records.append((False, elapsed, kind))
                    conn.rollback()
        finally:
            conn.close()
        return records

    with ThreadPoolExecutor(max_workers=threads) as pool:
        futures = [pool.submit(writer, index) for index in range(threads)]
        start_gate.set()
        batches = [future.result() for future in futures]

    flat = [record for batch in batches for record in batch]
    success = [elapsed for ok, elapsed, _ in flat if ok]
    locked = sum(1 for ok, _, kind in flat if not ok and kind == "locked")
    other = sum(1 for ok, _, kind in flat if not ok and kind == "other")
    total = len(flat)
    return {
        "busy_timeout_ms": busy_timeout_ms,
        "threads": threads,
        "loops": loops,
        "total": total,
        "success": len(success),
        "locked": locked,
        "other_errors": other,
        "success_rate": round(len(success) / total, 4) if total else 0.0,
        "samples": len(success),
        "mean_us": round(statistics.mean(success), 1) if success else 0.0,
        "p50_us": _percentile(success, 0.5),
        "p95_us": _percentile(success, 0.95),
        "p99_us": _percentile(success, 0.99),
    }


def _scenario_write_lock(tmp: Path, *, threads: int, loops: int) -> dict[str, Any]:
    groups: dict[str, Any] = {}
    for label, timeout_ms in (("no_timeout", 0), ("with_timeout", BUSY_TIMEOUT_MS)):
        db_path = tmp / f"write_{label}.db"
        conn = sqlite3.connect(str(db_path), timeout=0)
        try:
            conn.executescript(_AI_LOG_SCHEMA)
            conn.commit()
        finally:
            conn.close()
        groups[label] = _run_concurrent_writes(
            str(db_path), threads=threads, loops=loops, busy_timeout_ms=timeout_ms
        )
    return {"groups": groups}


# --- 场景 2：题库导入幂等 -----------------------------------------------------


def _scenario_idempotent_import(tmp: Path) -> dict[str, Any]:
    rows = _seed_rows()
    now = _now()
    params = [
        (
            str(row["id"]),
            str(row["direction"]),
            row.get("sub_direction"),
            str(row["kind"]),
            str(row["difficulty"]),
            str(row["essentiality"]),
            str(row["prompt"]),
            json.dumps(row.get("options") or [], ensure_ascii=False),
            json.dumps(row.get("answer") or [], ensure_ascii=False),
            str(row.get("source") or "seed"),
            str(row.get("language") or ""),
            str(row.get("explanation") or ""),
            now,
            now,
        )
        for row in rows
    ]
    db_path = tmp / "import.db"
    conn = sqlite3.connect(str(db_path), timeout=0)
    try:
        conn.executescript(_QUESTION_SCHEMA)
        conn.commit()
        started = time.perf_counter()
        before = conn.total_changes
        conn.executemany(_QUESTION_INSERT, params)
        conn.commit()
        first_ms = round((time.perf_counter() - started) * 1000, 2)
        first_inserted = conn.total_changes - before
        existing_before_second = int(
            conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
        )

        started = time.perf_counter()
        before = conn.total_changes
        conn.executemany(_QUESTION_INSERT, params)
        conn.commit()
        second_ms = round((time.perf_counter() - started) * 1000, 2)
        second_inserted = conn.total_changes - before
        final_rows = int(
            conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
        )
    finally:
        conn.close()

    ok = (
        first_inserted == len(rows)
        and second_inserted == 0
        and existing_before_second == len(rows)
        and final_rows == len(rows)
        and existing_before_second == final_rows
    )
    if not ok:
        raise AssertionError(
            f"题库导入幂等断言失败：first={first_inserted} second={second_inserted} "
            f"before={existing_before_second} final={final_rows} seed={len(rows)}"
        )
    return {
        "seed_count": len(rows),
        "first_ms": first_ms,
        "second_ms": second_ms,
        "first_inserted": first_inserted,
        "second_inserted": second_inserted,
        "existing_before_second": existing_before_second,
        "final_rows": final_rows,
        "idempotent_ok": ok,
    }


# --- 场景 3：FTS5 trigram 检索延迟 -------------------------------------------


def _scenario_search(
    tmp: Path, *, repeats: int, fts: dict[str, Any]
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "available": False,
        "skip_reason": "",
        "keywords": list(KEYWORDS),
        "repeats": repeats,
        "samples": 0,
        "rows": 0,
        "total_hits": 0,
        "mean_us": 0.0,
        "p50_us": 0,
        "p95_us": 0,
        "p99_us": 0,
    }
    if not (fts["compile_enabled"] and fts["trigram_ok"]):
        result["skip_reason"] = fts["reason"] or "本机无 FTS5 trigram 能力"
        return result

    rows = _seed_rows()
    db_path = tmp / "search.db"
    conn = sqlite3.connect(str(db_path), timeout=0)
    try:
        conn.execute(_FTS_SCHEMA)
        conn.executemany(
            _FTS_INSERT,
            [
                (
                    str(row["id"]),
                    str(row["prompt"]),
                    str(row.get("explanation") or ""),
                    str(row["direction"]),
                    str(row.get("sub_direction") or ""),
                )
                for row in rows
            ],
        )
        conn.commit()
        latencies: list[int] = []
        total_hits = 0
        for keyword in KEYWORDS:
            match = "\"" + keyword.replace("\"", "\"\"") + "\""
            for _ in range(repeats):
                started = time.perf_counter()
                found = conn.execute(_FTS_MATCH, (match,)).fetchall()
                latencies.append(int((time.perf_counter() - started) * 1_000_000))
                total_hits += len(found)
    except sqlite3.OperationalError as exc:
        result["skip_reason"] = f"FTS5 检索执行失败：{type(exc).__name__}: {exc}"
        return result
    finally:
        conn.close()

    result.update(
        {
            "available": True,
            "rows": len(rows),
            "samples": len(latencies),
            "total_hits": total_hits,
            "mean_us": round(statistics.mean(latencies), 1) if latencies else 0.0,
            "p50_us": _percentile(latencies, 0.5),
            "p95_us": _percentile(latencies, 0.95),
            "p99_us": _percentile(latencies, 0.99),
        }
    )
    return result


# --- 编排 -------------------------------------------------------------------


def run_benchmark(quick: bool) -> dict[str, Any]:
    threads = QUICK_THREADS if quick else THREADS
    loops = QUICK_LOOPS if quick else LOOPS
    repeats = QUICK_REPEATS if quick else REPEATS

    with tempfile.TemporaryDirectory(prefix="perf-bench-") as tmp_name:
        tmp = Path(tmp_name)
        environment = _detect_environment()
        fts = _probe_fts5()
        environment["fts5_compile_enabled"] = fts["compile_enabled"]
        environment["fts5_trigram_ok"] = fts["trigram_ok"]
        environment["fts5_reason"] = fts["reason"]

        logger.info("场景 1：并发写锁（%s 线程 x %s 次，两组）", threads, loops)
        write_lock = _scenario_write_lock(tmp, threads=threads, loops=loops)
        logger.info("场景 2：题库导入幂等（读 %s）", SEED_PATH.name)
        imported = _scenario_idempotent_import(tmp)
        logger.info(
            "场景 3：FTS5 trigram 检索（%s 关键词 x %s 次）",
            len(KEYWORDS),
            repeats,
        )
        search = _scenario_search(tmp, repeats=repeats, fts=fts)
        if not search["available"]:
            logger.info("场景 3 跳过：%s", search["skip_reason"])

    return {
        "environment": environment,
        "params": {
            "mode": "quick" if quick else "default",
            "threads": threads,
            "loops": loops,
            "writes_per_group": threads * loops,
            "busy_timeout_ms": BUSY_TIMEOUT_MS,
            "keywords": len(KEYWORDS),
            "repeats": repeats,
            "queries_total": len(KEYWORDS) * repeats,
            "seed_path": SEED_PATH.relative_to(ROOT).as_posix(),
            "seed_count": imported["seed_count"],
        },
        "percentile_algorithm": PERCENTILE_ALGORITHM,
        "scenario1": write_lock,
        "scenario2": imported,
        "scenario3": search,
        "limitations": list(LIMITATIONS),
    }


# --- 输出 -------------------------------------------------------------------


def _lock_row(label: str, group: dict[str, Any]) -> str:
    cells = (
        f"`{label}`",
        str(group["busy_timeout_ms"]),
        str(group["total"]),
        str(group["success"]),
        _pct(group["success_rate"]),
        str(group["locked"]),
        str(group["other_errors"]),
        str(group["samples"]),
        str(group["mean_us"]),
        str(group["p50_us"]),
        str(group["p95_us"]),
        str(group["p99_us"]),
    )
    return "| " + " | ".join(cells) + " |"


def render_report(results: dict[str, Any]) -> str:
    env = results["environment"]
    params = results["params"]
    groups = results["scenario1"]["groups"]
    no = groups["no_timeout"]
    yes = groups["with_timeout"]
    s2 = results["scenario2"]
    s3 = results["scenario3"]

    if env["fts5_compile_enabled"] and env["fts5_trigram_ok"]:
        fts_text = "启用（compileoption_used=1），trigram 虚表创建成功"
    else:
        fts_text = f"未启用或 trigram 不可用（{env['fts5_reason']}）"

    lines = [
        "# 性能基准报告（工具生成，勿手改）",
        "",
        "> 生成命令：`python -X utf8 scripts/benchmark.py`",
        f"> 运行模式：`{params['mode']}`；全部数字来自本次实跑；",
        "> 临时 SQLite 库用完即删，绝不触碰开发库 `app.core.db`。",
        "",
        "## 0 环境与口径",
        "",
        "| 项 | 值 |",
        "| --- | --- |",
        f"| Python 版本 | `{env['python']}` |",
        f"| SQLite 版本 | `{env['sqlite']}` |",
        f"| ENABLE_FTS5 探测 | {fts_text} |",
        f"| CPU 核数 | {env['cpu_count']} |",
        f"| 操作系统 | `{env['os']}` |",
        f"| 分位算法 | {results['percentile_algorithm']} |",
        "| 延迟单位 | 微秒（us）；题库导入总耗时用毫秒（ms） |",
        "",
        "## 1 并发写锁（核心结论）",
        "",
        (
            f"参数：N={params['threads']} 线程 x 每线程 M={params['loops']} 次短事务 INSERT "
            f"= 每组 {params['writes_per_group']} 次写入；两组各用独立临时 DB 文件。"
        ),
        (
            "`no_timeout` 显式 `PRAGMA busy_timeout=0`；"
            f"`with_timeout` 设 `PRAGMA busy_timeout={BUSY_TIMEOUT_MS}`。"
        ),
        "",
        _LOCK_HEADER,
        _LOCK_SEPARATOR,
        _lock_row("no_timeout", no),
        _lock_row("with_timeout", yes),
        "",
        "### 对比结论",
        "",
        (
            f"- `no_timeout`：成功率 {_pct(no['success_rate'])}"
            f"（{no['success']}/{no['total']}），`database is locked` {no['locked']} 次。"
        ),
        (
            f"- `with_timeout={BUSY_TIMEOUT_MS}`：成功率 {_pct(yes['success_rate'])}"
            f"（{yes['success']}/{yes['total']}），`database is locked` {yes['locked']} 次。"
        ),
        (
            "- 量化收益：`busy_timeout` 把成功率提升 "
            f"{round((yes['success_rate'] - no['success_rate']) * 100, 1)} 个百分点"
            f"（{_pct(no['success_rate'])} → {_pct(yes['success_rate'])}），"
            f"把 `database is locked` 从 {no['locked']} 次降到 {yes['locked']} 次，"
            f"本次消除 {no['locked'] - yes['locked']} 次写失败。"
        ),
        (
            f"- 长尾：`with_timeout` 需排队等锁，p99 从 {no['p99_us']} us 变为 "
            f"{yes['p99_us']} us、p95 从 {no['p95_us']} us 变为 "
            f"{yes['p95_us']} us；两组分位只统计成功写入且样本口径不同，"
            "延迟数字不可直接等值比较，也不代表延迟改善或恶化。"
        ),
        (
            "- 口径：分位只统计成功写入，`no_timeout` 的失败写入不计入，"
            "故两组延迟不是同一负载下的等值对比，核心结论以成功率与 locked 次数为准。"
        ),
        "",
        "## 2 题库导入幂等",
        "",
        (
            f"参数：`{params['seed_path']}` 共 {params['seed_count']} 题，"
            "整批 `INSERT OR IGNORE` 导入两次（第二次为幂等跳过路径）。"
        ),
        (
            "第一次导入前已存在 0 行；第二次导入前已存在 "
            f"{s2['existing_before_second']} 行（据此判定全部跳过）。"
        ),
        "",
        "| 轮次 | 耗时(ms) | 新增行 | 导入前行数 | 导入后行数 |",
        "| --- | --- | --- | --- | --- |",
        (
            f"| 第一次 | {s2['first_ms']} | {s2['first_inserted']} | 0 | "
            f"{s2['existing_before_second']} |"
        ),
        (
            f"| 第二次（幂等） | {s2['second_ms']} | {s2['second_inserted']} | "
            f"{s2['existing_before_second']} | {s2['final_rows']} |"
        ),
        "",
        (
            f"断言：两次结果一致（第一次新增 {s2['first_inserted']}、第二次新增 "
            f"{s2['second_inserted']}、最终 {s2['final_rows']} 行 == 种子 "
            f"{s2['seed_count']} 题）→ {'通过' if s2['idempotent_ok'] else '失败'}。"
        ),
        "",
        "## 3 FTS5 trigram 检索延迟",
        "",
        (
            f"参数：{params['keywords']} 个固定中文关键词 x 每词 {params['repeats']} 次 "
            f"= {params['queries_total']} 次 MATCH 查询；虚表灌入 {params['seed_count']} 题。"
        ),
        "",
    ]
    if s3["available"]:
        lines.extend(
            [
                "| 样本量 | 命中总数 | 均值(us) | p50(us) | p95(us) | p99(us) |",
                "| --- | --- | --- | --- | --- | --- |",
                (
                    f"| {s3['samples']} | {s3['total_hits']} | {s3['mean_us']} | "
                    f"{s3['p50_us']} | {s3['p95_us']} | {s3['p99_us']} |"
                ),
                "",
                "关键词：" + "、".join(f"`{k}`" for k in s3["keywords"]) + "。",
                "",
            ]
        )
    else:
        lines.extend(
            [
                f"**跳过（不算失败）**：{s3['skip_reason']}。",
                "本机无 FTS5 trigram 能力，未采集 MATCH 分位。",
                "",
            ]
        )
    lines.extend(["## 4 解读限制", ""])
    lines.extend(f"- {item}" for item in results["limitations"])
    lines.append("")
    return "\n".join(lines)


def _print_summary(results: dict[str, Any]) -> None:
    env = results["environment"]
    params = results["params"]
    groups = results["scenario1"]["groups"]
    no = groups["no_timeout"]
    yes = groups["with_timeout"]
    s2 = results["scenario2"]
    s3 = results["scenario3"]
    print(
        f"环境：Python {env['python']} / SQLite {env['sqlite']} / "
        f"ENABLE_FTS5={'1' if env['fts5_compile_enabled'] else '0'} / "
        f"CPU {env['cpu_count']} / {env['os']}"
    )
    print(
        f"场景1 并发写锁（N={params['threads']}, M={params['loops']}, "
        f"每组 {params['writes_per_group']} 次）："
    )
    print(
        f"  无 busy_timeout      : 成功率 {_pct(no['success_rate'])} "
        f"({no['success']}/{no['total']}), locked={no['locked']}, "
        f"p50={no['p50_us']}us p95={no['p95_us']}us p99={no['p99_us']}us"
    )
    print(
        f"  有 busy_timeout={BUSY_TIMEOUT_MS} : 成功率 {_pct(yes['success_rate'])} "
        f"({yes['success']}/{yes['total']}), locked={yes['locked']}, "
        f"p50={yes['p50_us']}us p95={yes['p95_us']}us p99={yes['p99_us']}us"
    )
    print(
        f"场景2 题库导入幂等（{s2['seed_count']} 题 x2）："
        f"首次 {s2['first_ms']}ms / 新增 {s2['first_inserted']}，"
        f"二次 {s2['second_ms']}ms / 新增 {s2['second_inserted']}，"
        f"最终 {s2['final_rows']} 行，一致={'是' if s2['idempotent_ok'] else '否'}"
    )
    if s3["available"]:
        print(
            f"场景3 FTS5 trigram 检索（{s3['samples']} 次查询）："
            f"p50={s3['p50_us']}us p95={s3['p95_us']}us p99={s3['p99_us']}us"
        )
    else:
        print(f"场景3 FTS5 trigram 检索：跳过（{s3['skip_reason']}）")
    print(f"分位算法：{results['percentile_algorithm']}")


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(
        description="性能基准（零网络 / 零 FastAPI；临时 SQLite 库）"
    )
    parser.add_argument("--quick", action="store_true", help="缩小规模")
    parser.add_argument(
        "--json", action="store_true", dest="as_json", help="stdout 打印机器可读 JSON"
    )
    parser.add_argument(
        "--check", action="store_true", help="只读：打印指标、不写报告、退出 0"
    )
    args = parser.parse_args(argv)

    results = run_benchmark(args.quick)

    if args.as_json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        _print_summary(results)

    if not args.check:
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(render_report(results), encoding="utf-8", newline="\n")
        if not args.as_json:
            print(f"报告已生成：{REPORT_PATH.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
