"""r100 RAG 端点测试（TestClient + FakeAI）：status / rebuild / ingest / search / answer + 证据中心。"""

import pytest

from app.core import repository

TUTORIAL_ITEMS = [
    {
        "chapter_id": "ch-sql",
        "section_id": "sec-1",
        "title": "SQL · 索引",
        "content": "索引是加速查询的物理结构，慢查询排查的第一步是看执行计划。",
    }
]


@pytest.fixture()
def rag_ready(client):
    """造 2 道题 + 重建索引 + 摄取 1 条教程 chunk（API 全链路的前置状态）。"""
    with repository.connection() as conn:
        for question_id, prompt, direction in (
            ("t-001", "如何排查数据库慢查询？", "sql"),
            ("t-002", "React 虚拟滚动的实现原理是什么？", "frontend"),
        ):
            conn.execute(
                "INSERT INTO questions (id, direction, sub_direction, kind, difficulty,"
                " essentiality, prompt, options, answer, source, language, explanation,"
                " created_at, updated_at) VALUES (?, ?, '', 'single', 'basic', 'must_know',"
                " ?, '[]', '[\"A\"]', 'seed', '', '解析略',"
                " '2026-11-15T00:00:00+00:00', '2026-11-15T00:00:00+00:00')",
                (question_id, direction, prompt),
            )
    client.post("/api/rag/rebuild")
    client.post("/api/rag/ingest", json={"items": TUTORIAL_ITEMS})
    return client


def test_status_before_build(client):
    """空索引的 status：built=False + 中文提示，不 500。"""
    response = client.get("/api/rag/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["built"] is False
    assert "索引" in payload["notice"]
    assert payload["embedder_kind"] == "hash"


def test_rebuild_and_search_roundtrip(rag_ready):
    """重建 → 状态如数（种子题随 lifespan 灌入，按「≥ 本页插入数」断言）；
    三态检索都可访问，混合与关键词模式都能召回本页插入的题。"""
    client = rag_ready
    status = client.get("/api/rag/status").json()
    assert status["built"] is True
    # lifespan 启动即幂等灌入完整种子题库，question_chunks ≥ 本页插入的 2 道。
    assert status["question_chunks"] >= 2
    assert status["tutorial_chunks"] == 1
    assert status["stale"] is False

    result = client.post(
        "/api/rag/search", json={"query": "数据库慢查询", "mode": "hybrid", "limit": 5}
    ).json()
    assert result["mode"] == "hybrid"
    assert "t-001" in [item["ref_id"] for item in result["items"]], "必须召回本页插入的题"

    keyword = client.post(
        "/api/rag/search", json={"query": "虚拟滚动", "mode": "keyword", "limit": 5}
    ).json()
    assert "t-002" in [item["ref_id"] for item in keyword["items"]]


def test_search_kind_filter(rag_ready):
    client = rag_ready
    """kinds 过滤：只搜教程 chunk 时题目不出现（闭集过滤生效）。"""
    result = client.post(
        "/api/rag/search",
        json={"query": "索引", "mode": "hybrid", "limit": 10, "kinds": ["tutorial"]},
    ).json()
    assert result["items"]
    assert all(item["kind"] == "tutorial" for item in result["items"])


def test_answer_citations_whitelisted(rag_ready, patch_ai):
    """生成答案：引用 m 编号映射回 chunk_id，白名单外的引用被丢弃并计数。"""
    client = rag_ready
    client_request_payload = {"query": "慢查询怎么排查", "mode": "hybrid", "top_k": 3}

    def responder(_model_cls, _user):
        return {"answer": "先看执行计划，再分析索引使用情况。", "citations": ["m1", "m9"]}

    patch_ai(responder)
    response = client.post("/api/rag/answer", json=client_request_payload)
    assert response.status_code == 200
    payload = response.json()
    assert payload["retrieved_count"] >= 1
    assert payload["dropped_citations"] == 1, "m9 不在白名单内必须被丢弃"
    assert len(payload["citations"]) == 1
    cited = payload["citations"][0]
    assert cited["chunk_id"].startswith(("question:", "tutorial:"))
    assert payload["citations"][0]["kind"] in ("question", "tutorial")


def test_answer_without_hits(rag_ready):
    client = rag_ready
    """检索零命中：不调模型，直接给中文说明（省一次 AI 调用与等待）。"""
    response = client.post(
        "/api/rag/answer", json={"query": "量子纠缠", "mode": "keyword", "top_k": 3}
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["citations"] == []
    assert "检索" in payload["answer"] or "材料" in payload["answer"]


def test_evidence_summary(rag_ready):
    """证据中心摘要：行数事实 + 表数 + RAG 状态，全部只读聚合。

    种子题库随 lifespan 灌入，questions 按「≥ 本页插入数」断言。
    """
    client = rag_ready
    response = client.get("/api/evidence/summary")
    assert response.status_code == 200
    payload = response.json()
    assert payload["data_scale"]["questions"] >= 2
    assert payload["data_scale"]["documents"] == 0
    assert payload["tables"] >= 20
    assert payload["rag"]["built"] is True
    assert payload["rag"]["question_chunks"] >= 2
