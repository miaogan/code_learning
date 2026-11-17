"""r100 评测脚本共享件：评测库准备（eval_rag.py 与 eval_rag_judge.py 共用同一套口径）。

只做三件事：建库（不存在则创建）→ 重建 schema → `init_db` 建表 + `ensure_seeded`
灌题库 + `rebuild_question_index` 重建 RAG 向量索引。每次从头构建而非复用：题库、
建表语句或 embedding 任一变化，旧库残留都会让评测数字失真。

DSN 优先级：`EVAL_DATABASE_URL` > `DATABASE_URL` > 本地 compose 默认（127.0.0.1:5433）。
连不上即抛错（调用方退出 2），绝不静默跳过——「门禁没跑」被当成「门禁通过」
是最坏的失败模式。
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

import psycopg

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend"))

DEFAULT_DSN = "postgresql://postgres:postgres@127.0.0.1:5433/sc_eval"
_SAFE_DB_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def eval_dsn() -> str:
    return os.environ.get("EVAL_DATABASE_URL") or os.environ.get("DATABASE_URL") or DEFAULT_DSN


def redact(dsn: str) -> str:
    """去掉口令后的 DSN，用于报告与日志（评测记录要能公开）。"""
    parsed = urlparse(dsn)
    auth = (parsed.username or "") + "@" if parsed.username else ""
    port = ":" + str(parsed.port) if parsed.port else ""
    return parsed._replace(netloc=auth + (parsed.hostname or "") + port).geturl()


def _ensure_database(dsn: str) -> None:
    parsed = urlparse(dsn)
    name = parsed.path.lstrip("/")
    if not _SAFE_DB_NAME.match(name):
        raise RuntimeError("评测库名不合法：" + repr(name) + "（只允许字母、数字、下划线）")
    admin = parsed._replace(path="/postgres").geturl()
    try:
        with psycopg.connect(admin, autocommit=True, connect_timeout=5) as conn:
            found = conn.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s", (name,)
            ).fetchone()
            if not found:
                conn.execute('CREATE DATABASE "' + name + '"')
    except psycopg.OperationalError as exc:
        raise RuntimeError(
            "RAG 评测需要 PostgreSQL，但连不上 "
            + redact(admin)
            + "（"
            + type(exc).__name__
            + "）。请先启动 docker compose -f docker-compose.yml "
            "-f docker-compose.dev.yml up -d postgres，"
            "或用 EVAL_DATABASE_URL 指向一个可用实例。"
        ) from exc


def prepare_eval_db() -> dict:
    """重建评测库并返回 RAG 索引状态快照（embedder / 引擎 / chunk 数）。"""
    from app.core.config import get_settings
    from app.core.db import close_pool, init_db
    from app.services.assessment import question_bank
    from app.services.retrieval import indexer

    dsn = eval_dsn()
    _ensure_database(dsn)
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")
    os.environ["DATABASE_URL"] = dsn
    get_settings.cache_clear()
    close_pool()
    try:
        init_db()
        question_bank.ensure_seeded()
        indexer.rebuild_question_index()
        # r105：教程语料种子若存在则一并灌入 —— 评测库与生产同为「题库 + 教程」双语料，
        # 题目金标（混合检索）与教程金标（kinds=tutorial）才有真实口径。
        tutorial_summary = indexer.ensure_tutorials_indexed()
        status = indexer.index_status()
        status["dsn"] = redact(dsn)
        status["tutorial_ingested"] = bool(tutorial_summary and not tutorial_summary.get("skipped"))
        return status
    finally:
        close_pool()
