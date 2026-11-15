"""r103 召回反馈测试：换票覆盖 / 排序加权 / 跨用户隔离 / 错误口径 / 看板。

排序断言用关键词腿：两条命中分数恒为 1.0，顺序只由 chunk_id 决定，
反馈加权后必须可预测地翻转——这是「反馈真的参与排序」的最干净证据。
"""

import pytest

from app.core import repository
from app.services.retrieval import indexer
from app.services.retrieval.hybrid import search_chunks

QUERY = "闭环调速"  # 独有词：避免命中种子题库（1284 道）干扰排序断言


@pytest.fixture()
def feedback_db(tmp_db):
    """两道同主题题：关键词腿同时命中、分数相同（顺序由 id 决定）。"""
    with repository.connection() as conn:
        for question_id, prompt in (
            ("t-001", "React 虚拟滚动的闭环调速怎么实现？"),
            ("t-002", "闭环调速的性能优化有哪些？"),
        ):
            conn.execute(
                "INSERT INTO questions (id, direction, sub_direction, kind, difficulty,"
                " essentiality, prompt, options, answer, source, language, explanation,"
                " created_at, updated_at) VALUES (?, 'frontend', '', 'single', 'basic',"
                " 'must_know', ?, '[]', '[\"A\"]', 'seed', '', '',"
                " '2026-11-15T00:00:00+00:00', '2026-11-15T00:00:00+00:00')",
                (question_id, prompt),
            )
    indexer.rebuild_question_index()


def _chunk(question_id: str) -> str:
    return "question:" + question_id


def _vote(client, question_id: str, verdict: str, query: str = QUERY) -> dict:
    response = client.post(
        "/api/rag/feedback",
        json={"query": query, "chunk_id": _chunk(question_id), "verdict": verdict},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_vote_overwrites_instead_of_accumulating(client, feedback_db):
    """换投票＝覆盖：先赞后踩，只应剩一票（同用户同 query 同 chunk 唯一）。"""
    assert _vote(client, "t-001", "up")["up"] == 1
    down = _vote(client, "t-001", "down")
    assert down["up"] == 0 and down["down"] == 1 and down["net"] == -1


def test_downvote_demotes_result(client, feedback_db):
    """点踩：该 chunk 在本人后续同 query 检索里被降权（同分时让位给未踩的）。"""
    before = [item["ref_id"] for item in search_chunks(QUERY, mode="keyword", top_k=5)["items"]]
    assert before[:2] == ["t-001", "t-002"]

    _vote(client, "t-001", "down")
    after = search_chunks(QUERY, mode="keyword", top_k=5)
    assert [item["ref_id"] for item in after["items"]][:2] == ["t-002", "t-001"]
    assert "反馈" in after["notice"], "排序被反馈调整时要如实告知"


def test_upvote_boosts_result(client, feedback_db):
    """点赞：原本排第二的 chunk 被提到第一（1.0 × 1.2 = 1.2 > 1.0）。"""
    _vote(client, "t-002", "up")
    after = search_chunks(QUERY, mode="keyword", top_k=5)
    assert [item["ref_id"] for item in after["items"]][:2] == ["t-002", "t-001"]


def test_votes_are_isolated_between_users(client, feedback_db):
    """别人的踩不影响我的排序：排序只认本人对这条 query 的票。"""
    with repository.connection() as conn:
        conn.execute(
            "INSERT INTO rag_feedback (id, user_id, query, chunk_id, verdict, surface,"
            " created_at) VALUES ('fb-other', 'other-user', ?, ?, 'down', 'search',"
            " '2026-11-15T00:00:00+00:00')",
            (QUERY, _chunk("t-001")),
        )
    after = search_chunks(QUERY, mode="keyword", top_k=5)
    assert [item["ref_id"] for item in after["items"]][:2] == ["t-001", "t-002"]


def test_unknown_chunk_is_404(client, feedback_db, assert_chinese):
    """索引重建过的旧 chunk_id：404 + 中文提示（不让反馈落到幽灵材料上）。"""
    response = client.post(
        "/api/rag/feedback",
        json={"query": QUERY, "chunk_id": "question:not-exist", "verdict": "up"},
    )
    assert response.status_code == 404
    assert_chinese(response.json()["error"]["message"])


def test_bad_verdict_rejected(client, feedback_db):
    """闭集外的态度值：422（契约层拒绝，不写库）。"""
    response = client.post(
        "/api/rag/feedback",
        json={"query": QUERY, "chunk_id": _chunk("t-001"), "verdict": "meh"},
    )
    assert response.status_code == 422


def test_summary_reports_counts_and_top_downvoted(client, feedback_db):
    """看板：总票数 + 被踩最多的 chunk（带标题，供评测挖掘）。"""
    _vote(client, "t-001", "up")
    _vote(client, "t-002", "down")
    summary = client.get("/api/rag/feedback/summary").json()
    assert summary["up"] == 1 and summary["down"] == 1 and summary["net"] == 0
    assert summary["queries"] == 1
    top = summary["top_downvoted"]
    assert top and top[0]["chunk_id"] == _chunk("t-002")
    assert "闭环调速" in top[0]["snippet"]
