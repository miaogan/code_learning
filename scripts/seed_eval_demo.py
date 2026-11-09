"""往 ai_call_logs 插入合成调用日志，让 /eval 看板可演示指标。

数据全部为合成元数据：只有 provider / model / kind / status_code / elapsed_ms /
attempt / prompt_chars / request_id / created_at，**不含任何 Key、Prompt、简历正文**。

复用 backend/app/core/repository.py 的 connection() 与 insert_ai_call_log()：
- 幂等：每次先删除 provider='demo' 的旧行（DELETE 走 repository 的 connection()）；
- 插入走 repository.insert_ai_call_log()，不手写 INSERT SQL；
- insert_ai_call_log 内部用模块级 _now() 取当前时间，为演示 7 天每日趋势，
  写入时临时替换该函数为合成时间戳（不改 app 代码、不写额外 SQL）。

运行（仓库根目录）：
    # 1) 先看输出，不写库（推荐）
    python -X utf8 scripts/seed_eval_demo.py --days 7 --count 120 --dry-run
    # 2) 真正写入：务必把 DB_PATH 指向独立/临时且已初始化 ai_call_logs 的库，
    #    不要直接写开发库，避免污染真实数据
    DB_PATH=/path/to/eval_demo.db python -X utf8 scripts/seed_eval_demo.py \
        --days 7 --count 120

重复运行幂等（先删 demo 旧行再插），不会累积。数据为合成数据，仅用于本地演示 /
回归检测，不是能力宣传。
"""

from __future__ import annotations

import argparse
import math
import random
import sqlite3
import sys
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"

SEED = 20261109
DEMO_PROVIDER = "demo"
MODELS = ("demo-fast", "demo-quality")
KIND_WEIGHTS = (
    ("success", 0.78),
    ("timeout", 0.06),
    ("connect", 0.05),
    ("upstream", 0.06),
    ("rejected", 0.05),
)
LATENCY_RANGE = {
    "success": (180, 1200),
    "timeout": (3000, 8000),
    "connect": (500, 2000),
    "upstream": (1500, 4000),
    "rejected": (50, 300),
}
STATUS_CODE = {
    "success": 200,
    "timeout": 504,
    "connect": 502,
    "upstream": 503,
    "rejected": 429,
}


def load_repository():
    """把 backend/ 加入 sys.path 后导入 repository（唯一 SQL 出口）。"""
    backend = str(BACKEND)
    if backend not in sys.path:
        sys.path.insert(0, backend)
    import app.core.repository as repo

    return repo


def percentile(values, quantile):
    """与 repository._percentile 同口径，保证摘要与 /eval 看板一致。"""
    if not values:
        return 0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(quantile * len(ordered)) - 1))
    return ordered[index]


def build_rows(days, count, seed=SEED):
    rng = random.Random(seed)
    kinds = [k for k, _ in KIND_WEIGHTS]
    weights = [w for _, w in KIND_WEIGHTS]
    now = datetime.now(UTC)
    rows = []
    for i in range(count):
        kind = rng.choices(kinds, weights=weights, k=1)[0]
        low, high = LATENCY_RANGE[kind]
        day_offset = rng.randint(0, days - 1)
        day_start = (now - timedelta(days=day_offset)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        span = (
            max(0, int((now - day_start).total_seconds()))
            if day_offset == 0
            else 86399
        )
        moment = day_start + timedelta(seconds=rng.randint(0, span))
        rows.append(
            {
                "provider": DEMO_PROVIDER,
                "model": rng.choice(MODELS),
                "kind": kind,
                "elapsed_ms": rng.randint(low, high),
                "status_code": STATUS_CODE[kind],
                "attempt": 2 if kind != "success" and rng.random() < 0.2 else 1,
                "prompt_chars": rng.randint(200, 2000),
                "request_id": "demo-" + str(i + 1).zfill(4),
                "created_at": moment.isoformat(),
            }
        )
    return rows


def write_rows(repo, rows):
    """幂等写入：先删 demo 旧行，再逐条走 insert_ai_call_log()。"""
    with repo.connection() as conn:
        cursor = conn.execute(
            "DELETE FROM ai_call_logs WHERE provider = ?", (DEMO_PROVIDER,)
        )
        removed = max(cursor.rowcount, 0)

    # insert_ai_call_log 内部用模块级 _now() 写 created_at，不接受时间参数。
    # 仅运行时替换为合成时间戳，让 /eval 的每日趋势可见；不改 app 代码。
    clock = {"value": ""}

    def demo_now():
        return clock["value"]

    original = repo._now
    repo._now = demo_now
    try:
        for row in rows:
            clock["value"] = row["created_at"]
            repo.insert_ai_call_log(
                provider=row["provider"],
                model=row["model"],
                kind=row["kind"],
                elapsed_ms=row["elapsed_ms"],
                status_code=row["status_code"],
                attempt=row["attempt"],
                prompt_chars=row["prompt_chars"],
                request_id=row["request_id"],
            )
    finally:
        repo._now = original
    return removed


def build_summary(rows):
    total = len(rows)
    by_kind = Counter(r["kind"] for r in rows)
    by_model = Counter(r["model"] for r in rows)
    by_day = Counter(r["created_at"][:10] for r in rows)
    latencies = [r["elapsed_ms"] for r in rows]
    p50 = percentile(latencies, 0.5)
    p95 = percentile(latencies, 0.95)
    success_rate = by_kind.get("success", 0) / total if total else 0.0
    return {
        "total": total,
        "p50": p50,
        "p95": p95,
        "success_rate_pct": format(success_rate * 100, ".1f") + "%",
        "ratio": p95 / p50 if p50 else 0.0,
        "kind_text": ", ".join(
            k + "=" + str(by_kind.get(k, 0)) for k, _ in KIND_WEIGHTS
        ),
        "model_text": ", ".join(
            m + "=" + str(by_model.get(m, 0)) for m in MODELS
        ),
        "trend_text": ", ".join(
            day + "=" + str(num) for day, num in sorted(by_day.items())
        ),
        "model_names": ", ".join(MODELS),
    }


def compact(row):
    return (
        "request_id="
        + row["request_id"]
        + " model="
        + row["model"]
        + " kind="
        + row["kind"]
        + " elapsed="
        + str(row["elapsed_ms"])
        + "ms status="
        + str(row["status_code"])
        + " at="
        + row["created_at"][:19]
    )


def print_summary(rows, days, dry_run):
    s = build_summary(rows)
    tag = "dry-run，未写库" if dry_run else "已写入目标库"
    lines = [
        "=" * 64,
        " /eval 看板演示数据（全部为合成元数据；" + tag + "）",
        "=" * 64,
        " 条数: {}   时间窗口: 最近 {} 天   模型: {}".format(
            s["total"], days, s["model_names"]
        ),
        " 成功率: {}   p50: {}ms   p95: {}ms   p95/p50: {:.1f}x".format(
            s["success_rate_pct"], s["p50"], s["p95"], s["ratio"]
        ),
        " kind 分布: " + s["kind_text"],
        " 按模型: " + s["model_text"],
        " 每日趋势: " + s["trend_text"],
        " 示例行(前 3 条, 合成元数据, 不含 Key / Prompt / 简历正文):",
    ]
    for row in rows[:3]:
        lines.append("   " + compact(row))
    lines.append("=" * 64)
    print("\n".join(lines))


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="往 ai_call_logs 插入合成演示日志（/eval 看板）",
        epilog=(
            "先跑 dry-run 看输出：python -X utf8 scripts/seed_eval_demo.py "
            "--days 7 --count 120 --dry-run；真正写入请用 DB_PATH 指向独立/临时"
            "且已初始化 ai_call_logs 的库，避免污染开发库。"
        ),
    )
    parser.add_argument("--days", type=int, default=7, help="最近 N 天，默认 7")
    parser.add_argument("--count", type=int, default=120, help="合成条数，默认 120")
    parser.add_argument("--dry-run", action="store_true", help="只打印，不写库")
    args = parser.parse_args(argv)
    if args.days < 1 or args.count < 1:
        parser.error("--days 与 --count 必须 >= 1")

    rows = build_rows(args.days, args.count)

    if args.dry_run:
        print_summary(rows, args.days, dry_run=True)
        print(
            "提示：以上均为合成数据，未连接/写入任何数据库；仅用于演示 / 回归检测，"
            "不是能力宣传。真正写入请设置 DB_PATH 指向独立库后去掉 --dry-run。"
        )
        return 0

    repo = load_repository()
    try:
        removed = write_rows(repo, rows)
    except sqlite3.Error as exc:
        print(
            "写入失败：请确认 DB_PATH 指向已初始化 ai_call_logs 表的库"
            "（可先启动后端建表）。原始错误：" + str(exc),
            file=sys.stderr,
        )
        return 2
    print_summary(rows, args.days, dry_run=False)
    print(
        "幂等：本次先删除旧 demo 行 " + str(removed) + " 条，再插入合成行 "
        + str(len(rows)) + " 条；provider 标记为 demo，重复运行不会累积。"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
