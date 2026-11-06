"""T2 回归：知识薄弱地图投影（AC-1 / AC-2 / AC-3 / AC-19 + AC-14 辅助）。

口径断言重点（这几条是 anti-goal「与历史页对不上」的唯一防线）：
- 题源必须是 `diagnosis._scored`，`sum(total) == len(_scored(run))`，简答题不拉低薄弱度；
- 排序全序且可复算，同一输入两次逐字相同（AI 成败都不影响）；
- 标签只取闭集，取不到就留空（不猜默认档）。
"""

from __future__ import annotations

from typing import Any

from app.services.assessment import question_bank
from app.services.report import diagnosis, rules, weakness
from app.services.report.markdown import format_score
from app.services.resume.coach_copy import DIFFICULTY_LABEL, ESSENTIALITY_LABEL


def _exam_run(
    *,
    run_id: str = "run-exam-1",
    questions: list[dict[str, Any]],
    scores: dict[str, float],
) -> dict[str, Any]:
    """一笔已提交笔试：`per_question` 与 `questions` 分开给，便于构造「有题无分」的简答题。"""
    return {
        "id": run_id,
        "kind": "exam",
        "created_at": "2026-10-31T10:00:00+00:00",
        "payload": {
            "questions": questions,
            "per_question": [{"id": qid, "score": score} for qid, score in scores.items()],
        },
    }


def _question(
    question_id: str,
    *,
    direction: str = "前端",
    difficulty: str = "basic",
    essentiality: str = "must_know",
    kind: str = "single",
) -> dict[str, Any]:
    return {
        "id": question_id,
        "kind": kind,
        "direction": direction,
        "difficulty": difficulty,
        "essentiality": essentiality,
        "prompt": f"题目 {question_id}",
        "options": [{"key": "A", "text": "a"}, {"key": "B", "text": "b"}],
        "answer": ["A"],
    }


QUESTIONS = [
    _question("fe-q1", difficulty="basic", essentiality="must_know"),
    _question("fe-q2", difficulty="basic", essentiality="must_know"),
    _question("fe-q3", difficulty="challenge", essentiality="nice_to_know"),
    _question("be-q1", direction="后端", difficulty="intermediate", essentiality="advanced"),
    _question("be-q2", direction="后端", difficulty="intermediate", essentiality="advanced"),
    _question("tx-q1", direction="后端", difficulty="basic", essentiality="must_know", kind="text"),
]

SCORES = {
    "fe-q1": 3.0,
    "fe-q2": 8.0,
    "fe-q3": 2.0,
    "be-q1": 9.0,
    "be-q2": 9.0,
    # `tx-q1` 是简答题：服务端判分时根本不写进 `per_question`（见 services/exam.py 的
    # `is_objective_kind` 分支），所以这里也不给分 —— 它连 `_scored` 都进不去。
}


def _items() -> list:
    return weakness.build_weakness_map([_exam_run(questions=QUESTIONS, scores=SCORES)])


def test_groups_by_point_difficulty_essentiality() -> None:
    items = _items()
    keys = [item.key for item in items]
    assert keys == [
        "前端|basic|must_know",
        "后端|intermediate|advanced",
        "前端|challenge|nice_to_know",
    ]


def test_labels_are_closed_set() -> None:
    for item in _items():
        assert set(item.difficulty) <= set(rules.DIFFICULTIES)
        assert set(item.essentiality) <= set(rules.ESSENTIALITIES)
        assert len(item.difficulty) <= 1 and len(item.essentiality) <= 1


def test_samples_point_back_to_bank_questions() -> None:
    bank = {row["id"] for row in question_bank.load_seed()}
    for item in _items():
        assert 1 <= len(item.samples) <= weakness.SAMPLE_LIMIT
        for sample in item.samples:
            assert sample.question_id in bank


def test_wrong_and_rate_and_avg() -> None:
    front_basic = next(item for item in _items() if item.key == "前端|basic|must_know")
    assert (front_basic.wrong, front_basic.total) == (1, 2)
    assert front_basic.rate == round(1 / 2, 3)
    assert front_basic.avg == round((3.0 + 8.0) / 2, 1)
    for item in _items():
        assert item.wrong <= item.total
        assert item.rate == round(item.wrong / item.total, 3)


def test_text_kind_never_scored() -> None:
    run = _exam_run(questions=QUESTIONS, scores=SCORES)
    scored = diagnosis._scored(run)
    assert all(question["kind"] != rules.TEXT_KIND for _, question, _ in scored)
    assert sum(item.total for item in _items()) == len(scored)


def test_sort_order_is_total() -> None:
    keys = [weakness._sort_key(item) for item in _items()]
    assert keys == sorted(keys)
    ranks = [key[0] for key in keys]
    assert ranks == sorted(ranks)
    assert ranks[0] == 0  # must_know 先


def test_idempotent() -> None:
    runs = [_exam_run(questions=QUESTIONS, scores=SCORES)]
    first = weakness.build_weakness_map(runs)
    second = weakness.build_weakness_map(runs)
    assert [item.model_dump() for item in first] == [item.model_dump() for item in second]


def test_ai_failure_keeps_order_and_summary(monkeypatch: Any) -> None:
    from app.services.ai.ai import AIClient

    async def boom(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("AI 不可用（测试替身）")

    monkeypatch.setattr(AIClient, "complete_model", boom)
    items = _items()
    expected = weakness.build_weakness_map([_exam_run(questions=QUESTIONS, scores=SCORES)])
    assert [item.model_dump() for item in items] == [item.model_dump() for item in expected]
    assert all(item.summary for item in items)


def test_no_scored_question_yields_empty() -> None:
    empty = _exam_run(questions=QUESTIONS, scores={})
    assert weakness.build_weakness_map([empty]) == []
    assert weakness.build_weakness_map([]) == []


def test_interview_run_without_labels() -> None:
    run = {
        "id": "run-int-1",
        "kind": "interview",
        "created_at": "2026-10-31T11:00:00+00:00",
        "payload": {
            "questions": [
                {"id": "int-1", "kind": "technical", "prompt": "说说事件循环", "score": 5.0},
                {"id": "int-2", "kind": "technical", "prompt": "说说闭包", "score": 6.0},
            ]
        },
    }
    items = weakness.build_weakness_map([run])
    assert len(items) == 1
    item = items[0]
    assert item.point == "技术基础"
    assert item.difficulty == [] and item.essentiality == []
    assert item.total == 2 and item.wrong == 2
    assert weakness._sort_key(item)[0] == weakness.UNLABELED_RANK


def test_summary_uses_server_labels() -> None:
    item = next(item for item in _items() if item.key == "前端|basic|must_know")
    assert DIFFICULTY_LABEL["basic"] in item.summary
    assert ESSENTIALITY_LABEL["must_know"] in item.summary
    assert format_score(item.avg) in item.summary
    assert f"错 {item.wrong} 题" in item.summary


def test_zero_wrong_group_never_claims_redoing_wrong_questions() -> None:
    """D-2 门禁：0 错题组（全对）的模板文案不得出现「错题」。

    「错 0 题」与「再过一遍错题」写在同一句里是自相矛盾（AC-2 要求文案与事实一致）。
    """
    run = _exam_run(questions=[_question("fe-ok-1")], scores={"fe-ok-1": 8.0})
    items = weakness.build_weakness_map([run])
    assert len(items) == 1
    item = items[0]
    assert item.wrong == 0 and item.total == 1
    assert "错题" not in item.summary, f"0 错题组不该提错题：{item.summary}"
    assert format_score(item.avg) in item.summary, "均分仍须出现在摘要里"


def test_wrong_group_still_suggests_reviewing_wrong_questions() -> None:
    """反向断言：有错题的组保留原有的「过一遍错题」指引（只看 0 错题组的话等于删功能）。"""
    run = _exam_run(questions=[_question("fe-bad-1")], scores={"fe-bad-1": 3.0})
    items = weakness.build_weakness_map([run])
    assert len(items) == 1
    assert items[0].wrong == 1
    assert "错题" in items[0].summary, f"有错题的组应保留错题复盘指引：{items[0].summary}"


def test_sample_evidence_matches_shortfall_format() -> None:
    item = next(item for item in _items() if item.key == "前端|basic|must_know")
    assert [sample.evidence for sample in item.samples] == [
        f"Q1 · {format_score(3.0)}/10",
        f"Q2 · {format_score(8.0)}/10",
    ]
