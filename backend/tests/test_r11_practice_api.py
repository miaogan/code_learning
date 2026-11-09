"""练习四端点契约（r11 · §5 / B-11 / B-14 / B-15）：`/api/practice/paper|answer|stats|wrong-book`。

为什么必须在 HTTP 层再测一遍：服务层绿不代表 envelope 与状态码对 —— 这里钉的是
「参数越界 → 422 既有 envelope」「未作答 → 400 中文」「不存在 → 404」「0 命中 → 200 + notice」
以及「无 Key 也能练」（练习链路零 AI）。响应体还必须**永不含** `answer`（题智隔离）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

from app.core import repository
from app.services.assessment import practice


def _option(key: str, text: str) -> dict[str, str]:
    return {"key": key, "text": text}


def _question(
    question_id: str,
    *,
    kind: str = "single",
    language: str = "python",
    direction: str = "后端",
    difficulty: str = "basic",
    essentiality: str = "must_know",
    answer: list[str] | None = None,
    sub_direction: str = "",
) -> dict[str, Any]:
    options = (
        [_option("A", "正确"), _option("B", "错误")]
        if kind == "judge"
        else [_option("A", "选项 A"), _option("B", "选项 B"), _option("C", "选项 C")]
    )
    return {
        "id": question_id,
        "direction": direction,
        "sub_direction": sub_direction,
        "kind": kind,
        "difficulty": difficulty,
        "essentiality": essentiality,
        "prompt": f"题面 {question_id}",
        "options": options,
        "answer": answer or ["A"],
        "source": "test",
        "language": language,
        "explanation": f"解析 {question_id}",
    }


def _seed(questions: list[dict[str, Any]]) -> None:
    for question in questions:
        assert repository.insert_question(question) is True, f"入库失败：{question['id']}"


PAPER_BODY = {
    "language": "all",
    "direction": "all",
    "difficulty": "all",
    "essentiality": "all",
    "scope": "all",
    "limit": 10,
}


# --- paper -----------------------------------------------------------------


def test_paper_ok_and_no_answer_leak(client: Any) -> None:
    """`POST /api/practice/paper` 200：字段齐全、题单**绝不含** `answer` / `explanation`。"""
    response = client.post("/api/practice/paper", json=PAPER_BODY)
    assert response.status_code == 200, response.text[:300]
    body = response.json()
    assert set(body) == {
        "session_id",
        "questions",
        "hit_count",
        "notice",
        "sub_direction",
        "sub_direction_backfill",
        "filtered_count",
    }
    assert body["sub_direction"] == "" and body["sub_direction_backfill"] == 0
    assert body["filtered_count"] == 0, "种子题库无作答记录时不应有熟练过滤"
    assert body["session_id"].startswith("ps_")
    assert body["questions"], "种子题库应有大量可练习题"
    assert len(body["questions"]) == 10, f"limit=10 应给 10 道：{len(body['questions'])}"
    assert body["hit_count"] >= len(body["questions"])
    for question in body["questions"]:
        assert set(question) == {
            "id",
            "kind",
            "language",
            "direction",
            "difficulty",
            "essentiality",
            "prompt",
            "options",
        }, f"题单字段不得增删（契约镜像）：{sorted(question)}"
        assert "answer" not in question and "explanation" not in question


def test_paper_filters_and_judge_kind(client: Any) -> None:
    """筛选生效；判断题（`judge`）出现在练习里且只有两个选项（单一判分函数的输入端）。"""
    body = client.post(
        "/api/practice/paper", json={**PAPER_BODY, "language": "js", "limit": 0}
    ).json()
    assert body["questions"], "js 语言应命中种子题"
    for question in body["questions"]:
        assert question["language"] == "js"
        if question["kind"] == "judge":
            assert len(question["options"]) == 2, "判断题必须有且仅有两个选项"


def test_paper_empty_result_is_200(client: Any) -> None:
    """B-14 / AC-12：0 命中不是错误 —— 200 + 空数组 + 中文 notice。

    用「语言与方向互斥」的组合取证（`go` 只属于后端方向）：这是**词表级**的空集，
    不依赖种子题量的巧合，题库以后扩容也不会把这个用例变成假绿。
    """
    response = client.post(
        "/api/practice/paper",
        json={**PAPER_BODY, "language": "go", "direction": "算法与数据结构", "limit": 0},
    )
    assert response.status_code == 200, response.text[:300]
    body = response.json()
    assert body["questions"] == []
    assert body["hit_count"] == 0
    assert body["filtered_count"] == 0
    assert body["notice"] == "该组合下没有题目，试试放宽难度或必备度"


def test_paper_invalid_enum_is_422(client: Any) -> None:
    """参数越出闭集 → 422 + 既有 `VALIDATION_ERROR` envelope（不手写第二套校验）。"""
    for body in (
        {**PAPER_BODY, "language": "cobol"},
        {**PAPER_BODY, "limit": 7},
        {**PAPER_BODY, "scope": "solved"},
        {**PAPER_BODY, "direction": "外星方向"},
    ):
        response = client.post("/api/practice/paper", json=body)
        assert response.status_code == 422, f"{body} 应 422，实际 {response.status_code}"
        error = response.json()["error"]
        assert error["code"] == "VALIDATION_ERROR"
        assert error["message"] == "请求参数不合法，请检查后重试"


def test_language_all_versus_generic(client: Any) -> None:
    """`"all"` 与 `""` 是两条不同语义：`""` 只取通用/算法题，`"all"` 不筛（契约门禁的运行时对证）。"""
    generic = client.post("/api/practice/paper", json={**PAPER_BODY, "language": "", "limit": 0})
    assert generic.status_code == 200, generic.text[:300]
    body = generic.json()
    assert body["questions"], "种子题库应有通用（算法/计算机基础）题"
    assert all(question["language"] == "" for question in body["questions"])
    alls = client.post("/api/practice/paper", json={**PAPER_BODY, "language": "all", "limit": 0})
    assert alls.json()["hit_count"] > body["hit_count"], "all 必须比「仅通用题」命中更多"


# --- answer ----------------------------------------------------------------


def test_answer_roundtrip_correct_and_wrong(client: Any) -> None:
    """判分响应字段齐全；正确答案原样回显、解析非空；作答事件写进同一张表。"""
    paper = client.post("/api/practice/paper", json=PAPER_BODY).json()
    session_id = paper["session_id"]
    question = paper["questions"][0]
    stored = repository.list_questions()
    expected = next(row for row in stored if row["id"] == question["id"])["answer"]

    response = client.post(
        "/api/practice/answer",
        json={"session_id": session_id, "question_id": question["id"], "answer": expected},
    )
    assert response.status_code == 200, response.text[:300]
    body = response.json()
    assert set(body) == {"question_id", "correct", "correct_answer", "explanation"}
    assert body["question_id"] == question["id"]
    assert body["correct"] is True
    assert body["correct_answer"] == expected
    assert isinstance(body["explanation"], str)

    wrong = client.post(
        "/api/practice/answer",
        json={"session_id": session_id, "question_id": question["id"], "answer": ["Z"]},
    ).json()
    assert wrong["correct"] is False, "重提照常返回判定（事件不重复写）"

    rows = [row for row in repository.list_attempts() if row["question_id"] == question["id"]]
    assert len(rows) == 1, f"同会话同题只应一条事件：{rows}"
    assert rows[0]["source"] == "practice"
    assert rows[0]["run_id"] == f"practice:{session_id}"


def test_answer_requires_selection(client: Any) -> None:
    """B-15：未作答 → 400 `VALIDATION_ERROR`「先选一个答案，再提交」（服务端兜底）。"""
    paper = client.post("/api/practice/paper", json=PAPER_BODY).json()
    question_id = paper["questions"][0]["id"]
    for answer in (None, "", []):
        payload = {"session_id": paper["session_id"], "question_id": question_id}
        if answer is not None:
            payload["answer"] = answer
        response = client.post("/api/practice/answer", json=payload)
        assert response.status_code == 400, f"{answer!r} 应 400，实际 {response.status_code}"
        error = response.json()["error"]
        assert error["code"] == "VALIDATION_ERROR"
        assert error["message"] == "先选一个答案，再提交"


def test_answer_unknown_question_404(client: Any) -> None:
    """题目不存在 → 404 `NOT_FOUND`「题目不存在或已下线」（零新增错误码）。"""
    response = client.post(
        "/api/practice/answer",
        json={"session_id": "ps_deadbeef", "question_id": "nope-0", "answer": ["A"]},
    )
    assert response.status_code == 404, response.text[:300]
    error = response.json()["error"]
    assert error["code"] == "NOT_FOUND"
    assert error["message"] == "题目不存在或已下线"


def test_answer_rejects_text_kind(tmp_db: Any, client: Any) -> None:
    """非客观题（`text`）判分 → 400「该题不支持练习判分」，且不写事件。"""
    _seed([_question("text-0", kind="text", answer=[])])
    response = client.post(
        "/api/practice/answer",
        json={"session_id": "ps_t", "question_id": "text-0", "answer": ["A"]},
    )
    assert response.status_code == 400, response.text[:300]
    assert response.json()["error"]["message"] == "该题不支持练习判分"
    assert repository.list_attempts() == [], "简答题不得写熟练度事件"


# --- stats / wrong-book -----------------------------------------------------


def test_stats_hit_matches_paper(client: Any) -> None:
    """`/stats.hit` 与 `/paper.hit_count` 同源同值；`/stats` 只读、不写事件。"""
    before = repository.list_attempts()
    response = client.get("/api/practice/stats", params={"language": "js"})
    assert response.status_code == 200, response.text[:300]
    body = response.json()
    assert set(body) == {"total", "practiced", "wrong_total", "hit"}
    assert body["total"] > 0
    assert body["hit"] > 0
    assert client.post("/api/practice/paper", json={**PAPER_BODY, "language": "js"}).json()[
        "hit_count"
    ] == body["hit"]
    assert repository.list_attempts() == before, "/stats 不得写事件"


def test_stats_invalid_enum_is_422(client: Any) -> None:
    """查询串闭集越界同样 422（GET 端点不能只校验 POST 体）。"""
    response = client.get("/api/practice/stats", params={"scope": "solved"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_wrong_book_empty_is_200(client: Any) -> None:
    """空错题本 200 + `items: []`（中文空态，不是错误）。"""
    response = client.get("/api/practice/wrong-book")
    assert response.status_code == 200, response.text[:300]
    assert response.json() == {"items": [], "total": 0}


def test_wrong_book_lists_last_wrong_and_filters_language(client: Any) -> None:
    """错题本只列「最近一次答错」的题；`language` 过滤生效；答对后移出。"""
    paper = client.post("/api/practice/paper", json={**PAPER_BODY, "language": "python"}).json()
    question = paper["questions"][0]
    client.post(
        "/api/practice/answer",
        json={"session_id": paper["session_id"], "question_id": question["id"], "answer": ["Z"]},
    )
    book = client.get("/api/practice/wrong-book", params={"language": "python"}).json()
    assert book["total"] == 1
    item = book["items"][0]
    assert set(item) == {
        "question_id",
        "prompt",
        "language",
        "direction",
        "difficulty",
        "last_wrong_at",
        "wrong_count",
    }
    assert item["question_id"] == question["id"]
    assert item["wrong_count"] == 1

    other = client.get("/api/practice/wrong-book", params={"language": "java"}).json()
    assert other == {"items": [], "total": 0}

    stored = next(row for row in repository.list_questions() if row["id"] == question["id"])
    client.post(
        "/api/practice/answer",
        json={
            "session_id": paper["session_id"] + "-fix",
            "question_id": question["id"],
            "answer": stored["answer"],
        },
    )
    assert client.get("/api/practice/wrong-book").json()["total"] == 0, "答对后必须移出错题本"


# --- B-11：零 AI -----------------------------------------------------------


def test_no_ai_without_key(monkeypatch: Any, client: Any) -> None:
    """B-11：`AI_API_KEY=` 未配置下四端点全部可用（练习链路不 import AI、不读 Key）。"""
    from app.services.assessment import practice as practice_module

    source = practice_module.__file__
    assert source is not None
    text = Path(source).read_text(encoding="utf-8")
    assert "services.ai" not in text and "AI_API_KEY" not in text, "练习服务不得 import AI 或读 Key"

    assert client.post("/api/practice/paper", json=PAPER_BODY).status_code == 200
    assert client.get("/api/practice/stats").status_code == 200
    assert client.get("/api/practice/wrong-book").status_code == 200
    question_id = client.post("/api/practice/paper", json=PAPER_BODY).json()["questions"][0]["id"]
    response = client.post(
        "/api/practice/answer",
        json={"session_id": f"ps_{uuid4().hex[:8]}", "question_id": question_id, "answer": ["A"]},
    )
    assert response.status_code == 200, response.text[:300]


def test_practice_run_prefix_constant() -> None:
    """服务层常量与事件命名空间一致（前端/文档引用同一个前缀）。"""
    assert practice.PRACTICE_RUN_PREFIX == "practice:"
    assert practice.ATTEMPT_SOURCE == "practice"


# --- r50：二级方向筛选的 HTTP 契约 ------------------------------------------


def test_paper_sub_direction_fields_and_stats_hit(client: Any) -> None:
    """r50：请求体带 `sub_direction` → 题单回传生效值与补位数，`/stats` 的 hit 同源。"""
    response = client.post(
        "/api/practice/paper", json={**PAPER_BODY, "sub_direction": "部署与推理"}
    )
    assert response.status_code == 200, response.text[:300]
    body = response.json()
    assert body["sub_direction"] == "部署与推理"
    assert isinstance(body["sub_direction_backfill"], int)
    stats = client.get(
        "/api/practice/stats",
        params={"direction": "AI 工程", "sub_direction": "部署与推理"},
    )
    assert stats.status_code == 200
    assert stats.json()["hit"] == body["hit_count"]


def test_paper_sub_direction_dirty_value_is_not_422(client: Any) -> None:
    """r50：闭集外脏值按 r46 口径静默忽略，不造第二套 422、也不落进题单事实。"""
    response = client.post(
        "/api/practice/paper", json={**PAPER_BODY, "sub_direction": "不是子方向"}
    )
    assert response.status_code == 200, response.text[:300]
    assert response.json()["sub_direction"] == ""
    assert response.json()["sub_direction_backfill"] == 0
