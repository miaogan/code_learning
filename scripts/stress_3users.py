#!/usr/bin/env python
"""三用户并发压测（一次性工具，参数化后入库供复用）。

用法：
    STRESS_BASE_URL=https://43.166.23.144 \
    STRESS_USERS='[["a@x", "pw"], ["b@x", "pw"], ["c@x", "pw"]]' \
    python -X utf8 scripts/stress_3users.py

设计口径：
- 3 个账号各自独立会话（Cookie），并发推进，模拟三个真实用户；
- 请求量刻意压在限流阈值内（API 120 次/分钟/IP），避免把「限流生效」误读成「服务挂了」；
- 覆盖读（status/evidence/history/courses）、写（feedback）、检索（rag/search）、
  SSE（interview 错误帧）四类路径；
- 同时打印服务器侧容器状态便于对照。
"""



import asyncio
import json
import os
import statistics
import time

import httpx

BASE = os.environ.get("STRESS_BASE_URL", "https://43.166.23.144")
_default_users = json.dumps(
    [
        ["lt1@skillcoach.local", os.environ.get("STRESS_PW_1", "")],
        ["lt2@skillcoach.local", os.environ.get("STRESS_PW_2", "")],
        ["lt3@skillcoach.local", os.environ.get("STRESS_PW_3", "")],
    ]
)
USERS = [(u, p) for u, p in json.loads(os.environ.get("STRESS_USERS", _default_users))]
ROUNDS = 2
QUERIES = ["数据库慢查询", "虚拟滚动", "幂等设计", "事务隔离级别"]


async def login(client: httpx.AsyncClient, email: str, password: str) -> bool:
    resp = await client.post("/api/auth/login", json={"email": email, "password": password})
    return resp.status_code == 200


async def call(client: httpx.AsyncClient, method: str, url: str, *, name: str, **kwargs):
    start = time.perf_counter()
    try:
        resp = await client.request(method, url, timeout=30.0, **kwargs)
        elapsed = (time.perf_counter() - start) * 1000
        return {"name": name, "status": resp.status_code, "ms": elapsed, "error": ""}
    except Exception as exc:  # noqa: BLE001 - 压测要把任何异常都记成失败样本
        elapsed = (time.perf_counter() - start) * 1000
        return {"name": name, "status": 0, "ms": elapsed, "error": type(exc).__name__}


async def user_worker(email: str, password: str, results: list, barrier: asyncio.Barrier) -> None:
    async with httpx.AsyncClient(base_url=BASE, verify=False, follow_redirects=False) as client:
        ok = await login(client, email, password)
        results.append({"name": "login", "status": 200 if ok else 401, "ms": 0, "error": ""})
        if not ok:
            return
        await barrier.wait()  # 三个用户同时开始，制造真实并发
        for round_no in range(ROUNDS):
            query = QUERIES[round_no % len(QUERIES)]
            plan = [
                ("GET", "/api/me", "me", None),
                ("GET", "/api/evidence/summary", "evidence", None),
                ("GET", "/api/rag/status", "rag-status", None),
                (
                    "POST",
                    "/api/rag/search",
                    "rag-search",
                    {"query": query, "mode": "hybrid", "limit": 5},
                ),
                ("GET", "/api/history?limit=5", "history", None),
                ("GET", "/api/courses", "courses", None),
                (
                    "POST",
                    "/api/rag/feedback",
                    "feedback",
                    {"query": query, "chunk_id": "question:__probe__", "verdict": "up"},
                ),
                ("GET", "/api/jobs/profile/__probe__/stream", "sse-404", None),
            ]
            for method, url, name, body in plan:
                kwargs = {"json": body} if body is not None else {}
                results.append(await call(client, method, url, name=name, **kwargs))


async def main() -> None:
    results: list[dict] = []
    barrier = asyncio.Barrier(len(USERS))
    started = time.perf_counter()
    await asyncio.gather(
        *(user_worker(email, password, results, barrier) for email, password in USERS)
    )
    total_s = time.perf_counter() - started

    ok = [r for r in results if 200 <= r["status"] < 300]
    expected_404 = [r for r in results if r["status"] == 404 and r["name"] in ("feedback", "sse-404")]
    failed = [r for r in results if r not in ok and r not in expected_404]
    latencies = [r["ms"] for r in results if r["ms"] > 0]
    print(f"总请求 {len(results)} · 耗时 {total_s:.1f}s · 并发用户 3")
    print(
        f"成功 {len(ok)} · 预期 404 {len(expected_404)} · 失败 {len(failed)}"
    )
    if latencies:
        ordered = sorted(latencies)
        p95 = ordered[max(0, int(len(ordered) * 0.95) - 1)]
        print(
            f"延迟 中位 {statistics.median(latencies):.0f}ms · p95 {p95:.0f}ms · 最大 {max(latencies):.0f}ms"
        )
    print("--- 按接口 ---")
    by_name: dict[str, list[dict]] = {}
    for row in results:
        by_name.setdefault(row["name"], []).append(row)
    for name, rows in sorted(by_name.items()):
        codes = sorted({row["status"] for row in rows})
        times = [row["ms"] for row in rows if row["ms"] > 0]
        print(
            f" {name:<12} n={len(rows)} 状态={codes} 中位={statistics.median(times) if times else 0:.0f}ms"
        )
    if failed:
        print("--- 失败样本 ---")
        for row in failed[:10]:
            print(" {} {} {} {}".format(row["name"], row["status"], row["error"], int(row["ms"])))


if __name__ == "__main__":
    asyncio.run(main())
