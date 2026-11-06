"""练习服务口径（r11 · §7 B-1..B-10）：筛选 / scope / limit / 错题本 / 熟练度零回归。

为什么必须构造数据而不是读真库：`all/unseen/wrong` 三口径、`answer⊆options`、
「最近一次答错才进错题本」这些**只能靠构造数据断言**，读代码无法证伪；
`proficiency` / `exam_selector` 的零改动也只有在「练习事件真的进了那张表」之后才有意义。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from app.core import repository
from app.services.assessment import exam as exam_service, practice, proficiency, question_bank
from app.services.report import rules

#: 造数用的固定「现在」：同一 `minutes_ago` 得到**同一时刻**，排序断言才可复现
#: （每次调用 `datetime.now()` 会差几微秒，同刻次序的用例会变成掷骰子）。
_BASE = datetime.now(UTC)


# --- 造数 ------------------------------------------------------------------


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
) -> dict[str, Any]:
    """一道可入库的题（字段与 `seed/questions.json` 同形，`_usable()` 判为可用）。"""
    options = (
        [_option("A", "正确"), _option("B", "错误")]
        if kind == "judge"
        else [_option("A", "选项 A"), _option("B", "选项 B"), _option("C", "选项 C")]
    )
    return {
        "id": question_id,
        "direction": direction,
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
    """把题库写进临时库（用例自行决定题池，不依赖真种子文件）。"""
    for question in questions:
        assert repository.insert_question(question) is True, f"入库失败：{question['id']}"


def _attempt(question_id: str, *, correct: bool, minutes_ago: int, source: str = "practice") -> dict[str, Any]:
    stamp = (_BASE - timedelta(minutes=minutes_ago)).isoformat()
    return {
        "id": uuid4().hex,
        "question_id": question_id,
        "run_id": f"{source}:{uuid4().hex[:8]}",
        "correct": 1 if correct else 0,
        "answered_at": stamp,
        "created_at": stamp,
        "source": source,
    }


def _ids(paper: dict[str, Any]) -> set[str]:
    return {str(question["id"]) for question in paper["questions"]}


def _by(prefix: str, count: int, **kwargs: Any) -> list[dict[str, Any]]:
    return [_question(f"{prefix}-{index}", **kwargs) for index in range(count)]


# --- B-1 / B-2 / B-3：scope 三口径 -----------------------------------------


def test_scope_unseen_means_no_attempt(tmp_db: Any) -> None:
    """B-1：`unseen` = 该题在 `question_attempts` **无任何事件**（笔试做过也算做过）。"""
    _seed(_by("q", 3))
    repository.insert_attempts([_attempt("q-0", correct=True, minutes_ago=5, source="exam")])
    repository.insert_attempts([_attempt("q-1", correct=False, minutes_ago=5)])

    paper = practice.build_paper(scope="unseen", limit=0)
    assert _ids(paper) == {"q-2"}, f"unseen 应为「一次都没做过」的题（笔试做过也算做过）：{_ids(paper)}"
    assert paper["hit_count"] == 1


def test_scope_wrong_is_last_attempt(tmp_db: Any) -> None:
    """B-2：`wrong` = **最近一次**作答为错误；曾经答错但后来答对 → 不算错题。"""
    _seed(_by("q", 3))
    # q-0：先错后对 → 不是错题；q-1：先对后错 → 是错题；q-2：从未作答 → 不进 wrong。
    repository.insert_attempts(
        [
            _attempt("q-0", correct=False, minutes_ago=30),
            _attempt("q-0", correct=True, minutes_ago=10),
            _attempt("q-1", correct=True, minutes_ago=30),
            _attempt("q-1", correct=False, minutes_ago=10),
        ]
    )
    paper = practice.build_paper(scope="wrong", limit=0)
    assert _ids(paper) == {"q-1"}, f"wrong 只看最近一次作答：{_ids(paper)}"


def test_scopes_are_disjoint_and_stackable(tmp_db: Any) -> None:
    """B-3：三口径互斥可叠加 —— `unseen ∩ wrong = ∅`，且可与其他筛选同时生效。"""
    _seed(_by("q", 4))
    _seed([_question("qt-0", language="js", direction="前端")])
    repository.insert_attempts([_attempt("q-0", correct=False, minutes_ago=5)])

    unseen = _ids(practice.build_paper(scope="unseen", limit=0))
    wrong = _ids(practice.build_paper(scope="wrong", limit=0))
    everything = _ids(practice.build_paper(scope="all", limit=0))
    assert unseen & wrong == set(), f"unseen 与 wrong 必须互斥：{unseen & wrong}"
    assert unseen | wrong == everything, "all 必须等于 unseen ∪ wrong（同一张事件表）"
    assert "qt-0" in unseen, "从未作答的题进 unseen（不因方向/语言而消失）"

    stacked = practice.build_paper(language="js", direction="前端", scope="unseen", limit=0)
    assert _ids(stacked) == {"qt-0"}, "语言 + 方向 + scope 必须同时生效"


# --- B-4 / B-5 / B-6：命中与取样 -------------------------------------------


def test_paper_rows_match_all_filters(tmp_db: Any) -> None:
    """B-4：返回的每道题逐字段满足全部筛选（语言 / 方向 / 难度 / 必备度）。"""
    _seed(_by("py", 4, language="python", direction="后端", difficulty="basic"))
    _seed(_by("js", 4, language="js", direction="前端", difficulty="challenge"))
    _seed(_by("go", 4, language="go", direction="后端", difficulty="basic", essentiality="advanced"))

    paper = practice.build_paper(
        language="python",
        direction="后端",
        difficulty="basic",
        essentiality="must_know",
        limit=0,
    )
    assert paper["hit_count"] == 4
    for question in paper["questions"]:
        assert question["language"] == "python"
        assert question["direction"] == "后端"
        assert question["difficulty"] == "basic"
        assert question["essentiality"] == "must_know"
        assert "answer" not in question, "题单绝不含答案（题智隔离）"
        assert question["options"], "客观题必须带选项"


def test_paper_limit_10_20_all(tmp_db: Any) -> None:
    """B-5：`10` / `20` → `min(limit, hit)`；`0` → 全部命中；`hit_count` 不受截断影响。"""
    _seed(_by("q", 25))
    assert len(practice.build_paper(limit=10)["questions"]) == 10
    assert len(practice.build_paper(limit=20)["questions"]) == 20
    assert len(practice.build_paper(limit=0)["questions"]) == 25

    _seed(_by("r", 5))
    # 30 题池：limit 20 只能取 20 道，`hit_count` 仍是全部命中数（不受截断影响）。
    paper = practice.build_paper(limit=20)
    assert paper["hit_count"] == 30
    assert len(paper["questions"]) == 20


def test_paper_questions_unique(tmp_db: Any) -> None:
    """B-6：一次组卷内题 id 唯一（sample 天然去重，AC-8「同一会话不重复出现」）。"""
    _seed(_by("q", 30))
    paper = practice.build_paper(limit=0)
    ids = [question["id"] for question in paper["questions"]]
    assert len(ids) == len(set(ids)) == 30


def test_notice_five_states(tmp_db: Any) -> None:
    """AC-12：notice 五态 —— 满额空串 / 命中 0 放宽建议 / 不足说明 / 题库空未就绪。"""
    _seed(_by("q", 3))
    assert practice.build_paper(limit=0)["notice"] == ""
    assert practice.build_paper(limit=10)["notice"] == "该组合下只有 3 道，已全部给出"
    empty = practice.build_paper(language="js")
    assert empty["questions"] == [] and empty["hit_count"] == 0
    assert empty["notice"] == practice.NOTICE_EMPTY


def test_empty_bank_notice(tmp_db: Any, monkeypatch: Any) -> None:
    """题库不可用（练习题池为空）→ 空题单 + 「题库未就绪」，绝不是 500。"""
    monkeypatch.setattr(question_bank, "practice_pool", lambda: [])
    paper = practice.build_paper()
    assert paper["questions"] == [] and paper["hit_count"] == 0
    assert paper["notice"] == practice.NOTICE_BANK_EMPTY
    assert practice.stats()["total"] == 0


# --- B-7：会话命名空间与事件 -----------------------------------------------


def test_answer_writes_attempt_with_source(tmp_db: Any) -> None:
    """B-7：事件 `run_id = "practice:<session>"`、`source="practice"`；同会话同题只一条。"""
    _seed([_question("q-0", kind="judge", answer=["A"])])
    result = practice.submit_answer("ps_abc123", "q-0", ["A"])
    assert result["correct"] is True
    assert result["correct_answer"] == ["A"]
    assert result["explanation"] == "解析 q-0"

    rows = repository.list_attempts()
    assert len(rows) == 1, f"一次判定应只写一条事件：{rows}"
    assert rows[0]["run_id"] == "practice:ps_abc123"
    assert rows[0]["source"] == "practice"
    assert rows[0]["correct"] == 1

    repeat = practice.submit_answer("ps_abc123", "q-0", ["B"])
    assert repeat["correct"] is False, "重复提交照常返回判定结果（前端重试友好）"
    assert len(repository.list_attempts()) == 1, "同会话同题不得写出第二条事件（UNIQUE 兜底）"


def test_answer_error_matrix(tmp_db: Any) -> None:
    """错误矩阵：未作答 400 / 不存在 404 / 非客观题 400（零新增错误码）。"""
    _seed([_question("q-0"), _question("t-0", kind="text", answer=[])])
    for blank in (None, "", [], ["  "]):
        try:
            practice.submit_answer("ps_1", "q-0", blank)
        except Exception as exc:  # noqa: BLE001 - 断言 code/status 而非异常类型文本
            assert getattr(exc, "status", None) == 400, f"未作答必须 400：{exc}"
            assert getattr(exc, "code", "") == "VALIDATION_ERROR"
            assert "先选一个答案" in str(exc)
        else:
            raise AssertionError(f"未作答应被拒：{blank!r}")

    try:
        practice.submit_answer("ps_1", "missing", ["A"])
    except Exception as exc:  # noqa: BLE001
        assert getattr(exc, "status", None) == 404
        assert getattr(exc, "code", "") == "NOT_FOUND"
        assert "题目不存在" in str(exc)
    else:
        raise AssertionError("不存在的题必须 404")

    try:
        practice.submit_answer("ps_1", "t-0", ["A"])
    except Exception as exc:  # noqa: BLE001
        assert getattr(exc, "status", None) == 400
        assert "不支持练习判分" in str(exc)
    else:
        raise AssertionError("简答题不得进入判分链路")


def test_answer_grades_multiple_and_judge(tmp_db: Any) -> None:
    """多选必须完全匹配（少选算错）；判断题走同一判分函数（集合相等）。"""
    _seed(
        [
            _question("m-0", kind="multiple", answer=["A", "B"]),
            _question("j-0", kind="judge", answer=["B"], language="js", direction="前端"),
        ]
    )
    assert practice.submit_answer("ps_m", "m-0", ["A", "B"])["correct"] is True
    assert practice.submit_answer("ps_m", "m-0", ["A"])["correct"] is False, "少选不给部分分"
    assert practice.submit_answer("ps_j", "j-0", "B")["correct"] is True, "字符串作答同样可判"


# --- B-8 / B-9：熟练度与组卷零回归 -----------------------------------------


def test_practice_attempts_count_as_proficiency(tmp_db: Any, profile_factory: Any) -> None:
    """B-8：练习事件按**原阈值**参与熟练度判定（实测 2 次答对 + 最近正确 → 题被过滤）。

    `proficiency` 公式与 `config` 阈值零改动，事件只是写进了笔试也在读的那张表。
    """
    profile = profile_factory()
    repository.insert_profile(profile)
    # L1 要求方向覆盖 ≥2，故题库必须跨两个方向；否则卷子会退回 L2 把熟练题放回卷面，
    # 净过滤数也就变 0（口径见 exam_selector._filtered_count）。
    _seed(_by("q", 10, language="python", direction="后端"))
    _seed(_by("f", 10, language="js", direction="前端"))
    target = "q-0"
    repository.insert_attempts(
        [
            _attempt(target, correct=True, minutes_ago=30),
            _attempt(target, correct=True, minutes_ago=20),
        ]
    )
    assert target in proficiency.proficient_ids(), "练习事件必须参与熟练度判定"

    before = exam_service.create_run(profile.id)
    payload = repository.get_run(before.run_id)["payload"]
    assert payload["filtered_count"] == 1, f"净过滤数应为 1（熟练题被过滤）：{payload['filtered_count']}"
    assert target not in {question.id for question in before.questions}


def test_exam_still_ok_when_all_proficient(tmp_db: Any, profile_factory: Any) -> None:
    """B-9：全库熟练（含练习事件）→ 出卷仍成功且结构达标（r6 六级阶梯不回退）。"""
    profile = profile_factory()
    repository.insert_profile(profile)
    questions = question_bank.load_questions()
    assert len(questions) >= rules.MIN_EXAM_QUESTIONS
    rows: list[dict[str, Any]] = []
    for question in questions:
        for index in range(2):
            stamp = (datetime.now(UTC) - timedelta(days=1, minutes=index)).isoformat()
            rows.append(
                {
                    "id": uuid4().hex,
                    "question_id": question["id"],
                    "run_id": f"{practice.PRACTICE_RUN_PREFIX}seed-{index}",
                    "correct": 1,
                    "answered_at": stamp,
                    "created_at": stamp,
                    "source": "practice",
                }
            )
    repository.insert_attempts(rows)
    assert proficiency.proficient_ids(), "前置：全库应判为熟练"

    run = exam_service.create_run(profile.id)
    payload = repository.get_run(run.run_id)["payload"]
    total = len(run.questions)
    assert rules.MIN_EXAM_QUESTIONS <= total <= rules.MAX_EXAM_QUESTIONS, f"题量 {total} 越界"
    objective = [
        question for question in run.questions if rules.is_objective_kind(question.kind)
    ]
    assert len(objective) >= rules.MIN_OBJECTIVE_QUESTIONS, "客观题不得少于下限"
    challenge = [
        question
        for question in payload["questions"]
        if rules.is_challenge_difficulty(str(question.get("difficulty")))
    ]
    assert len(challenge) <= rules.max_challenge_count(total), "挑战题不得超 20%"


# --- B-10：text 永不进练习 --------------------------------------------------


def test_text_questions_never_in_practice(tmp_db: Any) -> None:
    """B-10：存量简答题恒不出现在练习池（`kind` 非客观题判分 400）。"""
    _seed(_by("text", 5, kind="text", answer=[]))
    _seed(_by("py", 3))
    pool = question_bank.practice_pool()
    assert {question["id"] for question in pool} == {"py-0", "py-1", "py-2"}
    paper = practice.build_paper(limit=0)
    assert all(question["kind"] != "text" for question in paper["questions"])
    assert practice.stats()["total"] == 3


# --- 统计与错题本 ----------------------------------------------------------


def test_stats_hit_matches_paper_hit_count(tmp_db: Any) -> None:
    """`/stats.hit` 与 `/paper.hit_count` 同源同值；`total` / `practiced` 不带筛选。"""
    _seed(_by("py", 4, language="python"))
    _seed(_by("js", 6, language="js", direction="前端"))
    repository.insert_attempts([_attempt("py-0", correct=True, minutes_ago=5)])

    stats = practice.stats(language="python")
    assert stats["total"] == 10, "total 是全库可用练习题数（不带筛选）"
    assert stats["practiced"] == 1
    assert stats["hit"] == 4
    assert practice.build_paper(language="python")["hit_count"] == stats["hit"]

    unseen = practice.stats(scope="unseen")
    assert unseen["hit"] == 9
    assert practice.build_paper(scope="unseen", limit=0)["hit_count"] == unseen["hit"]


def test_wrong_book_removed_after_correct(tmp_db: Any) -> None:
    """错题本：最近一次答对即移出；时间倒序 + 同刻按 id 升序；`language` 过滤生效。"""
    _seed(_by("q", 3))
    _seed([_question("js-0", language="js", direction="前端")])
    repository.insert_attempts(
        [
            _attempt("q-0", correct=False, minutes_ago=60),
            _attempt("q-1", correct=False, minutes_ago=10),
            _attempt("q-2", correct=False, minutes_ago=10),
            _attempt("js-0", correct=False, minutes_ago=120),
        ]
    )
    book = practice.wrong_book()
    assert [item["question_id"] for item in book["items"]] == ["q-1", "q-2", "q-0", "js-0"]
    assert book["total"] == 4
    assert book["items"][0]["wrong_count"] == 1
    assert book["items"][0]["last_wrong_at"]
    assert {item["question_id"] for item in practice.wrong_book("js")["items"]} == {"js-0"}

    repository.insert_attempts([_attempt("q-0", correct=True, minutes_ago=1)])
    remaining = {item["question_id"] for item in practice.wrong_book()["items"]}
    assert "q-0" not in remaining, "答对后必须移出错题本"
    assert remaining == {"q-1", "q-2", "js-0"}


def test_wrong_book_empty_is_zero(tmp_db: Any) -> None:
    """空错题本：`items: []` / `total: 0`（前端中文空态，不是错误）。"""
    _seed(_by("q", 2))
    assert practice.wrong_book() == {"items": [], "total": 0}


def test_wrong_book_skips_unavailable_questions(tmp_db: Any) -> None:
    """题被下线（不可用）→ 错题本静默跳过，不抛错、不出现幽灵行。"""
    _seed(_by("q", 2))
    repository.insert_attempts([_attempt("gone-0", correct=False, minutes_ago=5)])
    assert practice.wrong_book()["total"] == 0


def test_build_paper_is_deterministic_in_content(tmp_db: Any) -> None:
    """`limit=0` 的题单内容确定（排序稳定：难度档 → 语言 → id），随机性只体现在取样截断。"""
    _seed(_by("b", 2, difficulty="basic"))
    _seed(_by("c", 2, difficulty="challenge"))
    paper = practice.build_paper(limit=0)
    assert [question["id"] for question in paper["questions"]][:2] == ["b-0", "b-1"]
    assert [question["id"] for question in paper["questions"]][-2:] == ["c-0", "c-1"]


def test_session_id_prefix(tmp_db: Any) -> None:
    """会话 id `ps_` + 8 位十六进制；两次组卷不共用会话（各自命名空间）。"""
    _seed(_by("q", 2))
    first = practice.build_paper()["session_id"]
    second = practice.build_paper()["session_id"]
    assert first.startswith("ps_") and len(first) == len("ps_") + 8
    assert first != second
