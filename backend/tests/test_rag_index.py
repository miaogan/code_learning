"""r100 RAG 索引与检索测试（真 PG）：重建 / 摄取 / 三态检索 / 状态口径。

造数口径：直接向 `questions` 插少量题目（不动 1284 道的完整种子——这里测的是
索引与检索管线本身，题库内容工程已有自己的门禁）。
"""


import pytest

from app.core import repository
from app.core.db import rag_embedding_mode
from app.services.retrieval import indexer
from app.services.retrieval.hybrid import search_chunks


def _insert_question(conn, question_id: str, prompt: str, explanation: str, direction: str) -> None:
    conn.execute(
        "INSERT INTO questions (id, direction, sub_direction, kind, difficulty, essentiality,"
        " prompt, options, answer, source, language, explanation, created_at, updated_at) "
        "VALUES (?, ?, ?, 'single', 'basic', 'must_know', ?, '[]', '[\"A\"]', 'seed', '', ?,"
        " '2026-11-15T00:00:00+00:00', '2026-11-15T00:00:00+00:00')",
        (question_id, direction, "", prompt, explanation),
    )


@pytest.fixture()
def rag_db(tmp_db):
    """3 道不同主题的题 + 重建索引：语义腿有区分度、关键词腿有精确命中。"""
    with repository.connection() as conn:
        _insert_question(
            conn, "t-001", "如何排查数据库慢查询？", "用执行计划与索引分析", "sql",
        )
        _insert_question(
            conn, "t-002", "慢查询的常见优化手段有哪些？", "加索引、减少回表", "sql",
        )
        _insert_question(
            conn, "t-003", "React 虚拟滚动的实现原理是什么？", "只渲染可视区行", "frontend",
        )
    indexer.rebuild_question_index()
    yield


def test_embedding_mode_is_pgvector_or_degraded(rag_db):
    """引擎形态二选一，且与状态报告一致：pgvector 索引内算，或降级取回后算。"""
    mode = rag_embedding_mode()
    assert mode in ("pgvector", "array")
    status = indexer.index_status()
    assert status["engine"] == mode


def test_rebuild_writes_state_and_counts(rag_db):
    """重建：题库 chunk 数 = 题数、状态单行写入、可重复执行（幂等替换不翻倍）。"""
    status = indexer.rebuild_question_index()
    assert status["question_chunks"] == 3
    assert status["tutorial_chunks"] == 0
    assert status["written"] == 3
    assert status["stale"] is False
    state = repository.rag_state_get()
    assert state is not None and state["chunk_count"] >= 3
    again = indexer.rebuild_question_index()
    assert again["question_chunks"] == 3, "重复重建不得让 chunk 翻倍"


def test_semantic_search_prefers_topic(rag_db):
    """语义检索：与查询主题一致的题排在前（同主题双题都应召回，跨主题靠后）。"""
    result = search_chunks("数据库慢查询排查", mode="semantic", top_k=3)
    assert result["mode"] == "semantic"
    assert result["items"], "语义腿必须召回同主题 chunk"
    ids = [item["ref_id"] for item in result["items"]]
    assert ids[0] in ("t-001", "t-002")
    assert set(ids) >= {"t-001", "t-002"}


def test_keyword_search_exact_substring(rag_db):
    """关键词腿：子串精确命中，分数恒 1.0（与既有题目检索同口径）。"""
    result = search_chunks("虚拟滚动", mode="keyword", top_k=3)
    assert [item["ref_id"] for item in result["items"]] == ["t-003"]
    assert all(item["score"] == 1.0 for item in result["items"])
    assert result["engine"] == "sql-ilike"


def test_hybrid_fuses_both_legs(rag_db):
    """混合模式：两腿各自 top-K 后 RRF 融合；同主题命中稳定领先跨主题。"""
    result = search_chunks("数据库慢查询", mode="hybrid", top_k=3)
    assert result["mode"] == "hybrid"
    ids = [item["ref_id"] for item in result["items"]]
    assert ids[0] in ("t-001", "t-002")
    assert set(ids) >= {"t-001", "t-002"}


def test_search_without_index(tmp_db):
    """未建索引：不 500，返回空集 + 中文提示（模式与引擎如实报告）。"""
    result = search_chunks("任意词", mode="hybrid", top_k=3)
    assert result["items"] == []
    assert result["total"] == 0
    assert "索引" in result["notice"]


def test_search_rejects_empty_query(rag_db):
    """空查询：空集 + 中文提示，不发任何 SQL 检索。"""
    result = search_chunks("   ", mode="semantic", top_k=3)
    assert result["items"] == []
    assert "关键词" in result["notice"]


def test_tutorial_ingest_full_replace_and_search(rag_db):
    """教程摄取：整份替换（第二次少推一节，旧节消失）+ 可被检索命中。"""
    items = [
        {
            "chapter_id": "ch-sql",
            "section_id": "sec-1",
            "title": "SQL · 索引",
            "content": "索引是加速查询的物理结构，慢查询排查的第一步是看执行计划。",
        },
        {
            "chapter_id": "ch-sql",
            "section_id": "sec-2",
            "title": "SQL · 事务",
            "content": "事务保证原子性与隔离性。",
        },
    ]
    result = indexer.ingest_tutorial_chunks(items)
    assert result["written"] == 2
    assert result["tutorial_chunks"] == 2
    hit = search_chunks("执行计划", mode="hybrid", top_k=5)
    assert any(item["kind"] == "tutorial" for item in hit["items"])
    # 整份替换：少推一节后，sec-2 的 chunk 必须消失（不残留旧数据）。
    indexer.ingest_tutorial_chunks(items[:1])
    assert indexer.index_status()["tutorial_chunks"] == 1
    gone = search_chunks("原子性与隔离性", mode="hybrid", top_k=20)
    assert not any(item["section_id"] == "sec-2" for item in gone["items"])


def test_stale_index_detected(rag_db):
    """混入旧 embedder 的行 → status 亮 stale + 中文提示（不静默丢检索结果）。"""
    from app.core.config import get_settings

    mode = rag_embedding_mode()
    dim = get_settings().ai_embed_dim
    repository.rag_write_chunks(
        [
            {
                "id": "question:ghost-1",
                "kind": "question",
                "ref_id": "ghost-1",
                "section_id": "",
                "title": "旧向量",
                "content": "旧 embedding 时代的 chunk",
                "content_sha": "x",
                "embedder": "hash-bigram-8",
                "created_at": "2026-11-15T00:00:00+00:00",
                "embedding": [0.0] * dim,
            }
        ],
        mode=mode,
    )
    status = indexer.index_status()
    assert status["stale"] is True
    assert "重建" in status["notice"]


def test_engine_upgrade_wipes_and_rebuilds_column(legacy_db_dsn, neutral_ai_env, monkeypatch):
    """array → pgvector 引擎升级自愈：旧向量无法无损转换，清空派生索引并按新形态重建列。

    复现路径：先伪装「镜像不带 pgvector」（`_try_create_vector` 返回 False）建出
    array 列 → 灌一行 chunk → 恢复真扩展（模拟换 pgvector 镜像）→ 再 `init_db()`：
    列形态必须变为 vector、chunk 与状态行清零（status 回到「未构建」）。

    为什么用打补丁而不是「真找一个没扩展的实例」：扩展是**服务器级安装**的，
    同一实例上所有库都能建，没法在测试里造出「服务端没有扩展」的库；
    而 `_try_create_vector` 正是那道「有没有扩展」的判定口，替它返回 False 等价于旧镜像。
    """
    from app.core import db as db_module
    from app.core.db import connection as _conn, init_db as _init

    original_create = db_module._try_create_vector
    monkeypatch.setattr(db_module, "_try_create_vector", lambda: False)
    # 第一步：旧镜像（无 pgvector）建库 → array 降级形态。
    _init()
    with _conn() as conn:
        conn.execute(
            "INSERT INTO rag_chunks (id, kind, ref_id, section_id, title, content, "
            "content_sha, embedder, created_at, embedding) "
            "VALUES ('q:legacy-1', 'question', 'legacy-1', '', '旧', '旧向量', 'sha', "
            "'hash-bigram-256', '2026-11-15T00:00:00+00:00', ?::float8[])",
            ([0.1] * 8,),
        )
    # 第二步：换 pgvector 镜像（恢复真实判定）再跑 init_db —— 自愈迁移必须触发。
    monkeypatch.setattr(db_module, "_try_create_vector", original_create)
    _init()
    with _conn() as conn:
        row = conn.execute(
            "SELECT udt_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'rag_chunks' "
            "AND column_name = 'embedding'"
        ).fetchone()
        chunks = conn.execute("SELECT count(*) AS n FROM rag_chunks").fetchone()["n"]
        state = conn.execute("SELECT count(*) AS n FROM rag_index_state").fetchone()["n"]
    assert str(row["udt_name"]) == "vector", "升级后列必须是 vector 形态"
    assert int(chunks) == 0, "旧向量不可无损转换，派生索引必须清空"
    assert int(state) == 0, "状态行随索引一起清零（status 回到未构建）"


def test_ingest_blocks_chunked_by_type(rag_db):
    """r103：结构化 block 摄取——代码按行、表格重复表头、正文可切多片。

    旧客户端只给 content 时仍是「整段一个 chunk」（上面那条用例覆盖），
    给 blocks 时同一小节会变成多个子片（section_id 加 `#n` 后缀保证唯一）。
    """
    code = "\n".join(["const value" + str(i) + " = " + str(i) for i in range(90)])
    rows = [["GET", "读取资源", "是"] for _ in range(120)]
    result = indexer.ingest_tutorial_chunks(
        [
            {
                "chapter_id": "ch-mix",
                "section_id": "sec-1",
                "title": "SQL · 混合小节",
                "content": "占位（旧字段，block 优先）",
                "blocks": [
                    {"kind": "text", "text": "正文段落。" * 120},
                    {"kind": "code", "caption": "示例", "code": code},
                    {"kind": "table", "headers": ["方法", "语义", "幂等"], "rows": rows},
                ],
            }
        ]
    )
    assert result["tutorial_chunks"] >= 3, "长正文 / 长代码 / 大表格都该被切开"
    with repository.connection() as conn:
        rows_db = conn.execute(
            "SELECT section_id, content FROM rag_chunks WHERE ref_id = 'ch-mix' "
            "ORDER BY section_id"
        ).fetchall()
    section_ids = [str(row["section_id"]) for row in rows_db]
    assert all(sid.startswith("sec-1#") for sid in section_ids)
    assert any("const value89" in str(row["content"]) for row in rows_db), "代码行不得被切断"
    assert any("方法 | 语义 | 幂等" in str(row["content"]) for row in rows_db), "表格必须带表头"


def test_dim_change_wipes_and_rebuilds_column(legacy_db_dsn, neutral_ai_env, monkeypatch):
    """维度变化自愈：`vector(8)` → 配置改成 16 维后，旧列必须被重建（否则插入报维度不符）。

    这是「换真语义模型」的必经路径（哈希 256 维 → bge-small 512 维）：
    `ADD COLUMN IF NOT EXISTS` 不会改已有列的维度，必须提前清空派生索引并重建。
    """
    from app.core.config import get_settings
    from app.core.db import connection as _conn, init_db as _init

    monkeypatch.setenv("AI_EMBED_DIM", "8")
    get_settings.cache_clear()
    _init()
    with _conn() as conn:
        conn.execute(
            "INSERT INTO rag_chunks (id, kind, ref_id, section_id, title, content, content_sha,"
            " embedder, created_at, embedding) VALUES ('q:dim-1', 'question', 'dim-1', '',"
            " '旧维度', '旧向量', 'sha', 'hash-bigram-8', '2026-11-15T00:00:00+00:00', ?::vector)",
            ("[" + ",".join(["0.1"] * 8) + "]",),
        )

    monkeypatch.setenv("AI_EMBED_DIM", "16")
    get_settings.cache_clear()
    _init()

    with _conn() as conn:
        row = conn.execute(
            "SELECT format_type(a.atttypid, a.atttypmod) AS col_type FROM pg_attribute a "
            "WHERE a.attrelid = 'rag_chunks'::regclass AND a.attname = 'embedding'"
        ).fetchone()
        chunks = conn.execute("SELECT count(*) AS n FROM rag_chunks").fetchone()["n"]
    assert str(row["col_type"]) == "vector(16)", "维度变化后列必须按新维度重建"
    assert int(chunks) == 0, "旧维度向量不可比，派生索引必须清空"

    # 收尾：把配置还原成默认，避免污染同进程后续用例的 get_settings 快照。
    monkeypatch.delenv("AI_EMBED_DIM", raising=False)
    get_settings.cache_clear()


def test_duplicate_question_ids_are_deduped(tmp_db, monkeypatch):
    """题库历史脏数据（重复 id 行）不得让「写入条数」虚高：chunk 按 id 先到先得。

    生产实测过 CTE 之外的现象：questions 表存在 64 对重复行（早期迁移重复导入），
    `INSERT ... ON CONFLICT(id)` 会静默合并，导致 rebuild 报 written 1348 / stored 1284。
    索引器显式去重后两个数字必须一致。
    """
    from app.core import repository as repo

    real_rows = repo.question_chunk_rows()

    def _rows_with_dup():
        base = real_rows[0] if real_rows else {
            "id": "dup-1", "direction": "backend", "sub_direction": "",
            "prompt": "重复题", "explanation": "",
        }
        return [dict(base), dict(base), {**base, "id": "dup-2", "prompt": "另一道题"}]

    monkeypatch.setattr(repo, "question_chunk_rows", _rows_with_dup)
    result = indexer.rebuild_question_index()
    assert result["written"] == 2, "重复 id 必须只写一次"
    assert result["question_chunks"] == 2


def test_kind_filter_is_applied_inside_vector_search(rag_db):
    """`kinds` 过滤必须在向量检索内部生效，而不是「先取全局 top-K 再筛」。

    复现过的问题：查询与该 kind 相关、但该 kind 排不进全局前 K 时，过滤后直接空结果
    （生产上「只搜教程 + 长问句」就会空）。现在过滤下沉到 SQL / 扫描层，
    只要该 kind 里有数据就必须能取到。
    """
    indexer.ingest_tutorial_chunks(
        [
            {
                "chapter_id": "ch-ev",
                "section_id": "sec-1",
                "title": "JavaScript · 事件循环",
                "content": "事件循环把微任务排在本轮宏任务之后执行。",
            }
        ]
    )
    # 查询强相关于题库（三题都命中）、与教程只有弱相关：全局 top-2 必是题。
    result = search_chunks("数据库慢查询", mode="semantic", top_k=2, kinds=["tutorial"])
    assert result["items"], "带 kinds 过滤时不得因为全局排名而返回空"
    assert all(item["kind"] == "tutorial" for item in result["items"])
    assert result["items"][0]["ref_id"] == "ch-ev"
