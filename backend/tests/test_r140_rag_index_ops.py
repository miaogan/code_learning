"""r140 内网 RAG 索引运维：状态口径 / 启动补建 / CLI 重建。

全零网络：faiss 档走本地文件（真跑），CLI 走 `admin_cli.main()` 进程内调用，
配置隔离沿用 r117 的 `get_settings.cache_clear()` 模式。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app import admin_cli
from app.core import db as database, repository
from app.core.config import get_settings
from app.schemas import RagStatus
from app.services.retrieval import indexer
from app.services.retrieval.embeddings import resolve_embedder
from app.services.retrieval.vector_backends import FaissStore, resolve_vector_store


@pytest.fixture()
def faiss_env(
    tmp_db: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """单机 SQLite + 显式 faiss + 临时索引目录（与 r117 同款，退出恢复配置）。"""
    database.activate_sqlite()
    monkeypatch.setenv("VECTOR_MODE", "faiss")
    monkeypatch.setenv("VECTOR_FAISS_DIR", str(tmp_path / "vectors"))
    get_settings.cache_clear()
    yield tmp_path / "vectors"
    get_settings.cache_clear()


def _insert_question(qid: str, prompt: str) -> None:
    with repository.connection() as conn:
        conn.execute(
            "INSERT INTO questions (id, direction, sub_direction, kind, difficulty,"
            " essentiality, prompt, options, answer, source, language, explanation,"
            " created_at, updated_at) VALUES (?, 'sql', '', 'single', 'basic', 'must_know',"
            " ?, '[]', '[\"A\"]', 'seed', '', '解析略',"
            " '2026-11-15T00:00:00+00:00', '2026-11-15T00:00:00+00:00')",
            (qid, prompt),
        )


# --- 1. 状态展示：派生索引健康进 schema 与 built --------------------------------


def test_index_status_carries_vector_fields(faiss_env: Path) -> None:
    """index_status 的三个 vector_* 字段能被 RagStatus 投影保留（不被 schema 丢弃）。"""
    status = indexer.index_status()
    assert status["vector_mode"] == "faiss"
    assert status["vector_engine"] == "faiss"
    assert "vector_notice" in status

    projected = RagStatus(**status).model_dump()
    assert projected["vector_mode"] == "faiss"
    assert projected["vector_engine"] == "faiss"
    assert projected["vector_notice"] == status["vector_notice"]


def test_built_false_when_question_faiss_missing(faiss_env: Path) -> None:
    """教程 seed 写了 rag_state、但 question.faiss 缺失 → built 必须为 False。"""
    _insert_question("q-001", "数据库慢查询如何排查？")
    # 手工建「只有 tutorial」的半构建状态：用 FaissStore.write 写一条教程 chunk。
    runtime = resolve_embedder()
    store = FaissStore(str(faiss_env))
    store.write(
        [
            {
                "id": "tutorial:ch-1:s-1",
                "kind": "tutorial",
                "ref_id": "ch-1",
                "section_id": "s-1",
                "title": "SQL",
                "content": "索引加速查询",
                "content_sha": "x" * 8,
                "embedder": runtime.name,
                "created_at": "2026-11-15T00:00:00+00:00",
                "embedding": [1.0] + [0.0] * (runtime.dim - 1),
            }
        ],
        kind="tutorial",
        embedder=runtime.name,
        dim=runtime.dim,
    )
    repository.rag_state_put(runtime.name, runtime.dim, 1, "2026-11-15T00:00:00+00:00")

    status = indexer.index_status()
    assert status["tutorial_chunks"] == 1
    assert status["built"] is False, "元数据齐但题库 faiss 没建，不能显示已构建"
    assert "题库向量索引尚未构建" in status["vector_notice"]


def test_status_honest_after_auto_seed(faiss_env: Path) -> None:
    """自动补建后 built 翻 True、vector_notice 清空——两个页面结论一致。"""
    _insert_question("q-001", "数据库慢查询如何排查？")
    summary = indexer.ensure_question_indexed()
    assert summary is not None and summary["skipped"] is False
    assert (faiss_env / "question.faiss").exists()

    status = indexer.index_status()
    assert status["built"] is True
    assert status["vector_notice"] == ""
    assert status["question_chunks"] == 1


def test_evidence_api_exposes_vector_fields(client) -> None:
    """证据中心与 RAG status 两个端点都把 vector_* 交给前端（契约不丢字段）。"""
    for path in ("/api/rag/status", "/api/evidence/summary"):
        response = client.get(path)
        assert response.status_code == 200, path
        rag = response.json() if path.endswith("status") else response.json()["rag"]
        assert "vector_mode" in rag
        assert "vector_engine" in rag
        assert "vector_notice" in rag


# --- 2. 启动补建：幂等 -----------------------------------------------------------


def test_ensure_question_indexed_is_idempotent(faiss_env: Path) -> None:
    """缺则建、有则跳；重复调用不得让 chunk 或文件翻倍。"""
    _insert_question("q-001", "数据库慢查询如何排查？")

    first = indexer.ensure_question_indexed()
    assert first is not None and first["skipped"] is False
    assert first["question_chunks"] == 1

    again = indexer.ensure_question_indexed()
    assert again is not None and again["skipped"] is True
    assert indexer.index_status()["question_chunks"] == 1


def test_ensure_question_indexed_skips_when_backend_unready(
    faiss_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """后端未就绪（如 faiss 未装）时不盲目重建，返回 None 让状态页报原因。"""
    _insert_question("q-001", "数据库慢查询如何排查？")

    class _Unready:
        mode = "faiss"
        engine = "faiss"
        store = None
        ready = False
        reason = "faiss 未安装"

    monkeypatch.setattr(indexer, "resolve_vector_store", lambda: _Unready())
    assert indexer.ensure_question_indexed() is None
    assert not (faiss_env / "question.faiss").exists()


# --- 3. admin_cli rebuild-index --------------------------------------------------


@pytest.fixture()
def cli_on_sqlite(faiss_env: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """CLI 入口自己会 `bootstrap()`（生产需要），这里抑制它、沿用 fixture 已激活的 SQLite。"""
    monkeypatch.setattr(admin_cli, "_prepare_database", lambda: None)
    monkeypatch.setattr(admin_cli, "_sync_replica", lambda: None)
    return faiss_env


def test_admin_cli_rebuild_index_question(cli_on_sqlite: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """CLI 重建题库索引：退出码 0、文件生成、输出含可诊断的 mode/embedder。"""
    _insert_question("q-001", "数据库慢查询如何排查？")
    assert admin_cli.main(["rebuild-index", "--kind", "question"]) == 0
    out = capsys.readouterr().out
    assert "题库索引已重建" in out
    assert "vector_mode=faiss" in out
    assert (cli_on_sqlite / "question.faiss").exists()
    assert indexer.index_status()["question_chunks"] == 1


def test_admin_cli_rebuild_index_all_without_tutorial_seed(
    cli_on_sqlite: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--kind all` 在教程种子缺失时跳过教程不报错，题库仍建成。"""
    from app.services.retrieval import tutorial_seed

    _insert_question("q-001", "数据库慢查询如何排查？")
    monkeypatch.setattr(tutorial_seed, "load_items", lambda: [])
    assert admin_cli.main(["rebuild-index", "--kind", "all"]) == 0
    out = capsys.readouterr().out
    assert "题库索引已重建" in out
    assert "没有教程种子" in out
    assert (cli_on_sqlite / "question.faiss").exists()


def test_admin_cli_rebuild_index_bad_kind_returns_1(cli_on_sqlite: Path) -> None:
    """非法 kind 由 argparse 拒绝（SystemExit 2），不误写成成功。"""
    with pytest.raises(SystemExit) as exc:
        admin_cli.main(["rebuild-index", "--kind", "bogus"])
    assert exc.value.code == 2
