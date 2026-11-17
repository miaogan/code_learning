"""r114 冒烟：完全没有 PostgreSQL / Redis / 既有数据目录时的冷启动。

模拟「用户拿到代码，在自己的机器 / 容器里直接跑」的场景：
- `DATABASE_URL` 指向一个不存在的端口（PG 不可达）
- `REDIS_URL` 留空（无 Redis）
- `SQLITE_PATH` 指向一个全新空目录（没有可接管的副本）
- `DB_MODE=auto`（不显式声明单机，考察自动识别）

期望：Web 可服务、`/health` 正常、能建用户、能登录、能读业务数据、
离线重放日志不增长（没有 PG 可回放）。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import uuid
from pathlib import Path

# 脚本住在仓库的 logs/ 下，不在 backend 包内：显式把 backend 加进 sys.path，
# 这样从任何工作目录直接 `python smoke_standalone.py` 都能跑。
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "backend"))

TMP = Path(tempfile.mkdtemp(prefix="sc-standalone-"))
os.environ.update(
    {
        "DB_MODE": "auto",
        "DATABASE_URL": "postgresql://nobody:nobody@127.0.0.1:5999/nodb",
        "SQLITE_PATH": str(TMP / "app.db"),
        "REDIS_URL": "",
        "APP_ENV": "development",
        # 生产默认给 PG 15s 宽限期（覆盖「PG 比 backend 晚几秒就绪」）；冒烟场景是
        # 压根没有 PG，缩短到 2s 以免白等，同时仍然走完整的宽限期判断逻辑。
        "DB_STANDALONE_GRACE_S": "2",
        "AI_API_KEY": "",
        "AI_DEEPSEEK_API_KEY": "",
    }
)

from fastapi.testclient import TestClient  # noqa: E402

from app.core import db, repository  # noqa: E402
from app.core.auth import hash_password  # noqa: E402
from app.main import app  # noqa: E402

EMAIL = "standalone@test.local"
PASSWORD = "standalone-pw-1234"

failures: list[str] = []


def check(label: str, ok: bool, detail: object = "") -> None:
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {label}" + (f" → {detail}" if detail != "" else ""))
    if not ok:
        failures.append(label)


with TestClient(app) as client:
    # 首次启动要先探一次 PG（connect_timeout=2s）才判定不可达，期间 /health 报
    # recovering 是**如实**的。真实部署里 docker healthcheck 有 start_period，
    # 这里轮询等它转好，最多 15s。
    health: dict = {}
    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline:
        health = client.get("/health").json()
        if health["db_status"] == "up":
            break
        time.sleep(0.3)
    print("HEALTH:", json.dumps(health, ensure_ascii=False))
    check("进程可服务", client.get("/health").status_code == 200)
    check("业务库为 sqlite", health["db"] == "sqlite", health["db"])
    check("db_status=up", health["db_status"] == "up", health["db_status"])
    check("db_replica=na（没有副本这个概念）", health["db_replica"] == "na", health["db_replica"])
    check("redis_status=memory（无 Redis 自动进程内）", health["redis_status"] == "memory")
    check("整体 status=ok", health["status"] == "ok", health["status"])
    check("运行时标记为单机", db.is_standalone() is True)
    check("活动后端为 sqlite", db.active_backend() == "sqlite")

    user_id = uuid.uuid4().hex
    repository.create_user(
        user_id=user_id,
        email=EMAIL,
        password_hash=hash_password(PASSWORD),
        display_name="单机用户",
    )
    check("能写入用户", True)

    login = client.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})
    check("能登录", login.status_code == 200, f"{login.status_code} {login.text[:120]}")
    me = client.get("/api/me")
    check("能读当前用户", me.status_code == 200 and me.json().get("email") == EMAIL, me.status_code)

    stats = client.get("/api/practice/stats")
    check("能读业务统计", stats.status_code == 200, f"{stats.status_code} {stats.text[:120]}")

    questions = repository.count_questions()
    check("题库种子已写入", questions > 0, f"{questions} 题")

    with db.connection() as conn:
        pending = conn.execute(
            "SELECT count(*) AS n FROM _offline_operations"
        ).fetchone()["n"]
    check("离线重放日志不增长", pending == 0, f"{pending} 条")

print()
print("SQLITE_PATH:", TMP / "app.db")
print("size:", (TMP / "app.db").stat().st_size if (TMP / "app.db").exists() else "missing")
print()
print("RESULT:", "ALL PASS" if not failures else f"{len(failures)} FAILED → {failures}")
raise SystemExit(0 if not failures else 1)
