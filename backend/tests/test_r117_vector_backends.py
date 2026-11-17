"""r117 向量检索后端：四档分派、faiss 文件索引、Milvus 契约、auto 优先级。

全零网络：faiss 档是本地文件索引（真跑）；Milvus 档用假 client 录调用（不打真实服务）；
分派用 `get_settings.cache_clear()` 隔离环境变量。r115 的零遥测守卫对新增模块依然生效
（faiss / pymilvus 都不往 `app/` 源码里引入出网调用）。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.core import db as database, repository
from app.core.config import Settings, get_settings
from app.core.db import rag_embedding_mode
from app.services.retrieval import indexer
from app.services.retrieval.embeddings import resolve_embedder
from app.services.retrieval.hybrid import search_chunks
from app.services.retrieval.vector_backends import (
    VECTOR_MODES,
    FaissStore,
    MilvusStore,
    resolve_vector_store,
)


@pytest.fixture()
def faiss_env(
    tmp_db: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """切到单机 SQLite + 显式 faiss 档 + 临时索引目录；退出时恢复 PG 与配置快照。"""
    database.activate_sqlite()
    monkeypatch.setenv("VECTOR_MODE", "faiss")
    monkeypatch.setenv("VECTOR_FAISS_DIR", str(tmp_path / "vectors"))
    get_settings.cache_clear()
    yield tmp_path / "vectors"
    get_settings.cache_clear()


def _insert_question(
    conn: Any, qid: str, prompt: str, explanation: str, direction: str
) -> None:
    """口径与 `test_rag_index._insert_question` 一致（两边同方言、时间用字面量）。"""
    conn.execute(
        "INSERT INTO questions (id, direction, sub_direction, kind, difficulty, essentiality,"
        " prompt, options, answer, source, language, explanation, created_at, updated_at) "
        "VALUES (?, ?, ?, 'single', 'basic', 'must_know', ?, '[]', '[\"A\"]', 'seed', '', ?,"
        " '2026-11-15T00:00:00+00:00', '2026-11-15T00:00:00+00:00')",
        (qid, direction, "", prompt, explanation),
    )


def _seed_questions(*rows: tuple[str, str, str, str]) -> None:
    with repository.connection() as conn:
        for qid, prompt, explanation, direction in rows:
            _insert_question(conn, qid, prompt, explanation, direction)


def _chunk_row(chunk_id: str, kind: str, content: str) -> dict[str, Any]:
    """直接喂 `FaissStore.write` 的完整行（`rag_write_chunks` 需要全部元数据列）。"""
    return {
        "id": chunk_id,
        "kind": kind,
        "ref_id": chunk_id.split(":", 1)[-1],
        "section_id": "",
        "title": kind,
        "content": content,
        "content_sha": "x" * 8,
        "embedder": "hash-bigram-256",
        "created_at": "2026-11-17T00:00:00+00:00",
        "embedding": [1.0] + [0.0] * 255,
    }


# --- 配置与分派 ----------------------------------------------------------------


def test_vector_mode_closed_set_is_pinned() -> None:
    """`VECTOR_MODE` 闭集与 config 的 Literal 必须同步：改一边不改另一边要当场红。"""
    assert VECTOR_MODES == ("auto", "pgvector", "sqlite", "faiss", "milvus")
    for _mode in VECTOR_MODES:
        assert Settings.model_fields["vector_mode"].annotation is not None


def test_invalid_vector_mode_is_rejected_at_startup() -> None:
    """非法档位在 Settings 构造期就炸（Literal 校验），不等到第一次检索才炸。"""
    with pytest.raises(ValidationError):
        Settings(_env_file=None, vector_mode="chroma")


def test_vector_mode_strips_padded_env() -> None:
    """`VECTOR_MODE= faiss`（复制带空格）必须能启动 —— r115 的布尔开关踩过同款坑。"""
    assert Settings(_env_file=None, vector_mode=" faiss ").vector_mode == "faiss"


def test_auto_prefers_pg_when_postgres_is_active(tmp_db: str) -> None:
    """auto 展开第一条：有 PostgreSQL 就把向量留在 PG（与业务数据同源、可进副本）。"""
    assert resolve_vector_store().mode == "pgvector"


def test_auto_prefers_faiss_on_sqlite(tmp_db: str) -> None:
    """auto 展开第二条：单机（内网默认形态）且装了 faiss → faiss。"""
    database.activate_sqlite()
    assert resolve_vector_store().mode == "faiss"


def test_explicit_faiss_without_package_reports_reason(
    tmp_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """显式 faiss 但包没装：不崩，`ready=False` + 可直接展示的中文原因。"""
    database.activate_sqlite()
    monkeypatch.setenv("VECTOR_MODE", "faiss")
    get_settings.cache_clear()
    monkeypatch.setattr(
        "app.services.retrieval.vector_backends._load_faiss", lambda: None
    )
    handle = resolve_vector_store()
    assert handle.ready is False
    assert handle.store is None
    assert "faiss-cpu" in handle.reason


def test_milvus_without_uri_reports_reason(tmp_db: str) -> None:
    handle = resolve_vector_store(Settings(_env_file=None, vector_mode="milvus"))
    assert handle.ready is False
    assert "VECTOR_MILVUS_URI" in handle.reason


def test_milvus_rejects_bad_collection_name(tmp_db: str) -> None:
    """collection 名进 Milvus 的 filter 表达式，非标识符字符必须当场拒。"""
    handle = resolve_vector_store(
        Settings(
            _env_file=None,
            vector_mode="milvus",
            vector_milvus_uri="http://milvus:19530",
            vector_milvus_collection="bad-name",
        )
    )
    assert handle.ready is False
    assert "VECTOR_MILVUS_COLLECTION" in handle.reason


def test_milvus_without_package_reports_reason(
    tmp_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.services.retrieval.vector_backends._load_milvus", lambda: None
    )
    handle = resolve_vector_store(
        Settings(
            _env_file=None,
            vector_mode="milvus",
            vector_milvus_uri="http://milvus:19530",
        )
    )
    assert handle.ready is False
    assert "pymilvus" in handle.reason


# --- faiss：真建索引、真检索 ----------------------------------------------------


def _tutorial_payload() -> dict[str, Any]:
    return {
        "chapter_id": "guide-1",
        "section_id": "sec-1",
        "title": "SQLite 离线副本",
        "content": "离线业务行与操作日志必须在同一个事务中提交。",
    }


def test_faiss_round_trip_and_engine_label(faiss_env: Path) -> None:
    """建索引 → 语义检索 top1 命中，`engine` 如实报告 faiss。"""
    _seed_questions(
        ("t-001", "如何排查数据库慢查询？", "用执行计划与索引分析", "sql"),
        ("t-002", "慢查询的常见优化手段有哪些？", "加索引、减少回表", "sql"),
        ("t-003", "React 虚拟滚动的实现原理是什么？", "只渲染可视区行", "frontend"),
    )
    summary = indexer.rebuild_question_index()
    assert summary["written"] == 3
    assert summary["vector_mode"] == "faiss"

    result = search_chunks("数据库慢查询", mode="semantic", top_k=3)
    assert result["engine"] == "faiss"
    assert result["items"], result
    assert result["items"][0]["ref_id"] == "t-001"
    # 索引文件与对账文件都真实存在（单文件、可随 data/ 目录一起备份）。
    assert (faiss_env / "question.faiss").exists()
    assert (faiss_env / "question.json").exists()


def test_faiss_kinds_filter_is_exact(faiss_env: Path) -> None:
    """kinds 过滤必须按文件精确：先取全局 top-K 再筛会让教程挤不进候选（既有教训）。"""
    _seed_questions(
        ("t-001", "数据库慢查询排查与执行计划分析", "加索引减少回表", "sql"),
    )
    indexer.rebuild_question_index()
    indexer.ingest_tutorial_chunks([_tutorial_payload()])

    tutorial = search_chunks("数据库慢查询", mode="semantic", kinds=["tutorial"], top_k=5)
    assert [item["kind"] for item in tutorial["items"]] == ["tutorial"], tutorial
    assert tutorial["items"][0]["ref_id"] == "guide-1"

    questions = search_chunks("数据库慢查询", mode="semantic", kinds=["question"], top_k=5)
    assert [item["kind"] for item in questions["items"]] == ["question"]


def test_faiss_hybrid_mode_fuses_both_legs(faiss_env: Path) -> None:
    _seed_questions(("t-001", "数据库慢查询排查", "加索引减少回表", "sql"))
    indexer.rebuild_question_index()
    indexer.ingest_tutorial_chunks([_tutorial_payload()])

    result = search_chunks("数据库慢查询", mode="hybrid", top_k=5)
    kinds = {item["kind"] for item in result["items"]}
    assert kinds == {"question", "tutorial"}, result


def test_faiss_stale_embedder_file_is_skipped(faiss_env: Path) -> None:
    """sidecar 记的 embedder 与当前不一致 → 该文件当不存在，notice 提示重建。"""
    _seed_questions(("t-001", "数据库慢查询排查", "加索引减少回表", "sql"))
    indexer.rebuild_question_index()
    sidecar = faiss_env / "question.json"
    meta = json.loads(sidecar.read_text(encoding="utf-8"))
    meta["embedder"] = "remote:another-model"
    sidecar.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")

    result = search_chunks("数据库慢查询", mode="semantic", top_k=3)
    assert result["items"] == []
    store = FaissStore(str(faiss_env))
    assert "请重建索引" in store.notice(
        embedder=resolve_embedder().name, dim=resolve_embedder().dim
    )


def test_faiss_notice_reports_count_mismatch(faiss_env: Path) -> None:
    """索引写成功但业务库行数没跟上（写入中断）→ 对账报不一致，提示重建。"""
    _seed_questions(("t-001", "数据库慢查询排查", "加索引减少回表", "sql"))
    indexer.rebuild_question_index()
    with repository.connection() as conn:
        conn.execute("DELETE FROM rag_chunks WHERE kind = 'question'")
    store = FaissStore(str(faiss_env))
    assert "行数不一致" in store.notice(
        embedder=resolve_embedder().name, dim=resolve_embedder().dim
    )


def test_faiss_empty_replace_removes_derived_files(faiss_env: Path) -> None:
    """全量替换成空集：删掉派生文件，不留一个「0 向量空索引」冒充已建。"""
    _seed_questions(("t-001", "数据库慢查询排查", "加索引减少回表", "sql"))
    indexer.rebuild_question_index()
    store = FaissStore(str(faiss_env))
    store.write([], kind="question", embedder="hash-bigram-256", dim=256)
    assert not (faiss_env / "question.faiss").exists()
    assert not (faiss_env / "question.json").exists()


def test_faiss_unsourced_dir_notice(faiss_env: Path) -> None:
    """目录还没建过索引：notice 给「先重建」而不是静默空结果。"""
    store = FaissStore(str(faiss_env))
    assert "尚未构建" in store.notice(
        embedder=resolve_embedder().name, dim=resolve_embedder().dim
    )


def test_faiss_index_is_exact_cosine(faiss_env: Path) -> None:
    """IndexFlatIP + L2 归一化 = 精确余弦：与 Python 参照实现对齐到小数点后 6 位。"""
    import math

    import faiss as faiss_lib
    import numpy as np

    rows = [
        _chunk_row("question:a", "question", "向量 a（与查询同向）"),
        _chunk_row("question:b", "question", "向量 b（正交）"),
        _chunk_row("question:c", "question", "向量 c（45 度）"),
    ]
    # 三个向量方向各自不同：a=(1,0)，b=(0,1)，c=(1,1)/√2。
    rows[1]["embedding"] = [0.0, 1.0] + [0.0] * 254
    rows[2]["embedding"] = [1.0, 1.0] + [0.0] * 254
    store = FaissStore(str(faiss_env))
    store.write(rows, kind="question", embedder="hash-bigram-256", dim=256)

    query = np.array([[1.0, 0.3] + [0.0] * 254], dtype="float32")
    faiss_lib.normalize_L2(query)
    loaded = store._load("question", embedder="hash-bigram-256", dim=256)
    assert loaded is not None
    index, ids = loaded
    scores, ordinals = index.search(query, 3)
    # 参照值手算：cos(a,q)=1/√1.09，cos(c,q)=1.3/(√2·√1.09)，cos(b,q)=0.3/√1.09。
    reference = [1 / math.sqrt(1.09), 1.3 / (math.sqrt(2) * math.sqrt(1.09)), 0.3 / math.sqrt(1.09)]
    got = {ids[o]: s for s, o in zip(scores[0].tolist(), ordinals[0].tolist(), strict=False)}
    assert got["question:a"] == pytest.approx(reference[0], abs=1e-6)
    assert got["question:c"] == pytest.approx(reference[1], abs=1e-6)
    assert got["question:b"] == pytest.approx(reference[2], abs=1e-6)


# --- milvus：契约与调用序列（假 client，零网络） --------------------------------


class _FakeSchema:
    def add_field(self, *_args: Any, **_kwargs: Any) -> None:
        return None


class _FakeIndexParams:
    """真实 pymilvus 的 `prepare_index_params()` 返回对象（有 `.add_index`），不是 dict。"""

    def __init__(self, owner: _FakeMilvus) -> None:
        self._owner = owner

    def add_index(self, **kwargs: Any) -> None:
        self._owner.calls.append(("add_index", kwargs.get("metric_type")))


class _FakeMilvus:
    """录调用序的假 client：`write` 必须先删该 kind 再插，`search` 必须带 embedder 过滤。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        self._collections: set[str] = set()
        self._hits: list[dict[str, Any]] = []

    def set_hits(self, hits: list[dict[str, Any]]) -> None:
        self._hits = hits

    def has_collection(self, name: str) -> bool:
        return name in self._collections

    def create_schema(self, **_kwargs: Any) -> _FakeSchema:
        return _FakeSchema()

    def prepare_index_params(self) -> _FakeIndexParams:
        return _FakeIndexParams(self)

    def create_collection(self, name: str, **_kwargs: Any) -> None:
        self._collections.add(name)

    def delete(self, name: str, *, filter: str) -> None:  # noqa: A002 - pymilvus 关键字
        self.calls.append(("delete", name, filter))

    def insert(self, name: str, *, data: list[dict[str, Any]]) -> None:
        self.calls.append(("insert", name, data))

    def search(self, name: str, **kwargs: Any) -> list[list[dict[str, Any]]]:
        self.calls.append(("search", name, str(kwargs.get("filter")), kwargs.get("limit")))
        return [self._hits]


@pytest.fixture()
def fake_milvus(monkeypatch: pytest.MonkeyPatch) -> _FakeMilvus:
    fake = _FakeMilvus()
    monkeypatch.setattr(MilvusStore, "_client", lambda self: fake)
    return fake


def test_milvus_write_deletes_kind_then_inserts(fake_milvus: _FakeMilvus, tmp_db: str) -> None:
    """全量替换语义：先按 kind 删（Boolean 表达式），再插 chunk_id + 向量。"""
    _seed_questions(("t-001", "数据库慢查询排查", "加索引减少回表", "sql"))
    rows = indexer._question_chunk_rows(resolve_embedder())
    store = MilvusStore(uri="http://milvus:19530", collection="rag_chunks")
    written = store.write(
        rows, kind="question", embedder="hash-bigram-256", dim=256
    )
    assert written == 1
    # 元数据行也写进了业务库（faiss / milvus 都只是派生索引）。
    assert repository.rag_chunk_counts()["question"] == 1
    kinds_of_calls = [call[0] for call in fake_milvus.calls]
    assert kinds_of_calls == ["add_index", "delete", "insert"], fake_milvus.calls
    assert fake_milvus.calls[1][2] == 'kind == "question"'
    inserted = fake_milvus.calls[2][2]
    assert inserted[0]["id"] == "question:t-001"
    assert inserted[0]["embedder"] == "hash-bigram-256"
    assert len(inserted[0]["vector"]) == 256


def test_milvus_search_filters_by_embedder_and_kinds(
    fake_milvus: _FakeMilvus, tmp_db: str
) -> None:
    fake_milvus._collections.add("rag_chunks")
    fake_milvus.set_hits([{"id": "tutorial:guide-1:sec-1", "distance": 0.97}])
    # 命中后的元数据回业务库取：先把这条 chunk 真实写进 rag_chunks，否则孤儿 id 会被丢弃。
    repository.rag_write_chunks(
        [
            _chunk_row("tutorial:guide-1:sec-1", "tutorial", "离线业务行与操作日志。")
        ],
        mode=rag_embedding_mode(),
        replace_kind=None,
    )
    store = MilvusStore(uri="http://milvus:19530", collection="rag_chunks")

    result = store.search(
        [0.0] * 256, embedder="hash-bigram-256", dim=256, top_k=5, kinds=["tutorial"]
    )

    assert result[0]["id"] == "tutorial:guide-1:sec-1"
    assert result[0]["score"] == pytest.approx(0.97)
    search_call = fake_milvus.calls[0]
    assert 'embedder == "hash-bigram-256"' in search_call[2]
    assert 'kind in ["tutorial"]' in search_call[2]
    assert search_call[3] == 5


def test_milvus_search_without_collection_returns_empty(
    fake_milvus: _FakeMilvus, tmp_db: str
) -> None:
    """collection 还没建过：空结果而不是异常（检索入口已有中文 notice 兜底）。"""
    store = MilvusStore(uri="http://milvus:19530", collection="rag_chunks")
    assert store.search(
        [0.0] * 256, embedder="hash-bigram-256", dim=256, top_k=5, kinds=None
    ) == []


def test_milvus_collection_defaults_and_custom_name(tmp_db: str) -> None:
    custom = MilvusStore(uri="http://milvus:19530", collection="sc_rag")
    assert custom._collection == "sc_rag"
    default = MilvusStore(uri="http://milvus:19530", collection="")
    assert default._collection == "rag_chunks"


# --- 启动清单：规范化的「启用了哪些存储组件」---------------------------------


def _summary_records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [record for record in caplog.records if "[启动清单]" in record.getMessage()]


def test_startup_summary_lists_all_components(
    faiss_env: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """db / cache / vector 三项都在：一行结构化 key（可 grep）+ 一行中文清单。"""
    from app.main import _report_runtime_summary

    caplog.set_level(logging.INFO, logger="app.runtime")
    _report_runtime_summary("memory")

    records = _summary_records(caplog)
    assert len(records) == 2, [r.getMessage() for r in records]
    assert all(record.levelno == logging.INFO for record in records)
    head = records[0].getMessage()
    assert "db=sqlite" in head and "vector=faiss" in head
    detail = records[1].getMessage()
    # faiss_env 激活的 sqlite 可能是单机库也可能是完整副本（tmp_db 会先同步一份副本），
    # 两种形态都合法；这里只钉「数据库这一项确实说了 SQLite」。
    assert "数据库=SQLite" in detail
    assert "缓存=进程内缓存" in detail
    assert "向量库=faiss（" in detail


def test_startup_summary_warns_when_vector_not_ready(
    tmp_db: str, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """faiss 没装 / Milvus 地址没填必须在启动时可见（WARNING），不是第一次检索才炸。"""
    from app.main import _report_runtime_summary

    database.activate_sqlite()
    monkeypatch.setenv("VECTOR_MODE", "milvus")
    get_settings.cache_clear()
    caplog.set_level(logging.INFO, logger="app.runtime")

    _report_runtime_summary("memory")

    records = _summary_records(caplog)
    assert records and all(record.levelno == logging.WARNING for record in records)
    assert any("VECTOR_MILVUS_URI" in record.getMessage() for record in records)
    get_settings.cache_clear()


def test_startup_summary_reports_postgres_primary(
    tmp_db: str, caplog: pytest.LogCaptureFixture
) -> None:
    """PG 档：数据库 = PostgreSQL 权威主库、缓存 = Redis（up）、向量 = pgvector。"""
    from app.main import _report_runtime_summary

    caplog.set_level(logging.INFO, logger="app.runtime")
    _report_runtime_summary("up")

    detail = _summary_records(caplog)[1].getMessage()
    assert "数据库=PostgreSQL 权威主库" in detail
    assert "缓存=Redis" in detail
    assert "向量库=pgvector" in detail
