"""r105 教程语料种子：导出文件可用、启动摄取幂等、不覆盖用户推送的索引。"""

from app.core import repository
from app.services.retrieval import indexer, tutorial_seed


def test_seed_file_loads_with_blocks():
    """种子可解析：条数合理、字段齐、block 结构在位（不是一坨纯文本）。"""
    items = tutorial_seed.load_items()
    assert len(items) > 100, "教程小节数异常偏少，检查导出脚本"
    first = items[0]
    assert first["chapter_id"] and first["section_id"]
    assert first["content"].strip()
    assert isinstance(first["blocks"], list) and first["blocks"]


def test_ensure_tutorials_indexed_is_idempotent(tmp_db):
    """首次调用灌种子（skipped=False），再次调用直接跳过（skipped=True，条数不变）。"""
    first = indexer.ensure_tutorials_indexed()
    assert first is not None
    assert first["skipped"] is False
    assert first["tutorial_chunks"] > 100, "165 个小节切分后应远多于 100 条 chunk"

    again = indexer.ensure_tutorials_indexed()
    assert again is not None and again["skipped"] is True
    assert again["tutorial_chunks"] == first["tutorial_chunks"]


def test_existing_tutorial_chunks_are_kept(tmp_db):
    """已有教程 chunk（例如用户从考工页推送的）不被启动任务覆盖。"""
    indexer.ingest_tutorial_chunks(
        [
            {
                "chapter_id": "ch-manual",
                "section_id": "sec-1",
                "title": "手工推送",
                "content": "这条来自考工页的手工推送，启动任务不得覆盖它。",
            }
        ]
    )
    before = indexer.index_status()["tutorial_chunks"]
    result = indexer.ensure_tutorials_indexed()
    assert result is not None and result["skipped"] is True
    assert indexer.index_status()["tutorial_chunks"] == before == 1
    with repository.connection() as conn:
        row = conn.execute(
            "SELECT count(*) AS n FROM rag_chunks WHERE ref_id = 'ch-manual'"
        ).fetchone()
    assert int(row["n"]) == 1
