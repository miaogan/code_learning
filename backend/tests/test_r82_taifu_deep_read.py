"""r82 太傅深读：焦点闭集 / 三类明细取料 / 预算 / 白名单只扩到本次读到的那一条。

重点口径：
- 焦点不合法、越界、数据不存在 → 一律等同「没传」，走原有摘要问答，不报错；
- 明细是**服务端重新取的真值**，与档案同等有效，进白名单；
- 没读到明细时，`/polish` 这类只存在于明细里的页面不可被引用（丢弃并计数）。
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core import repository
from app.schemas import (
    Report,
    ResumeMeta,
    ResumePointer,
    TaifuFocus,
    WeaknessItem,
    WeaknessSample,
)
from app.services.taifu import deep_read, policy

RESUME_TEXT = "个人简介\n五年外包交付经验。\n项目经历\n负责接口开发与维护，日均处理三十万请求。\n"


def _question(question_id: str = "q-1", **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": question_id,
        "direction": "前端",
        "sub_direction": "浏览器",
        "kind": "single",
        "difficulty": "intermediate",
        "essentiality": "must_know",
        "prompt": "以下哪个操作不会阻塞事件循环？",
        "options": [{"key": "A", "text": "同步 IO"}, {"key": "B", "text": "Promise 回调"}],
        "answer": ["B"],
        "source": "seed",
        "language": "js",
        "explanation": "Promise 回调进入微任务队列，在本轮同步代码之后执行。",
    }
    base.update(overrides)
    return base


def _report(*, with_samples: bool = True) -> Report:
    samples = (
        [WeaknessSample(question_id="q-1", score=2.0, evidence="Q1 · 2/10")]
        if with_samples
        else []
    )
    return Report(
        id="rep-r82",
        run_ids=["run-1"],
        interview_avg=6.0,
        exam_total=60.0,
        shortfalls=[],
        generated_at="2026-11-12T01:00:00+00:00",
        weakness_map=[
            WeaknessItem(
                key="前端|intermediate,|must_know,",
                point="事件循环",
                direction="前端",
                sub_direction="浏览器",
                wrong=3,
                total=4,
                rate=0.75,
                avg=3.0,
                difficulty=["intermediate"],
                essentiality=["must_know"],
                summary="微任务顺序没吃透",
                samples=samples,
            )
        ],
        resume_pointers=[
            ResumePointer(
                section="project",
                location="项目经历 · 第 2 行",
                anchor_text="负责接口开发",
                issue="缺少量化结果",
                focus_key="负责接口开发",
            )
        ],
    )


def _loader(*questions: dict[str, Any]) -> Any:
    table = {item["id"]: item for item in questions}
    return lambda question_id: table.get(question_id)


def _attempt(question_id: str = "q-1", correct: int = 0) -> dict[str, Any]:
    return {
        "id": f"att-{question_id}",
        "question_id": question_id,
        "run_id": "run-1",
        "correct": correct,
        "answered_at": "2026-11-10T08:00:00+00:00",
        "created_at": "2026-11-10T08:00:00+00:00",
        "source": "practice",
    }


# --- 焦点闭集 -----------------------------------------------------------------


def test_sanitize_focus_accepts_only_closed_shapes() -> None:
    assert policy.sanitize_focus(None) is None
    assert policy.sanitize_focus({"kind": "team", "index": 1}) is None
    assert policy.sanitize_focus({"kind": "", "index": 1}) is None
    assert policy.sanitize_focus({"kind": "weakness", "index": 0}) is None
    assert policy.sanitize_focus({"kind": "weakness", "index": -2}) is None
    # bool 是 int 的子类：True 不能被当成「第 1 组」。
    assert policy.sanitize_focus({"kind": "weakness", "index": True}) is None
    assert policy.sanitize_focus({"kind": "weakness", "index": "2"}) is None
    assert policy.sanitize_focus({"kind": "attempt", "question_id": "   "}) is None
    assert policy.sanitize_focus({"kind": "attempt", "question_id": "q 1"}) is None
    assert policy.sanitize_focus({"kind": "attempt", "question_id": "q" * 65}) is None
    assert policy.sanitize_focus({"kind": "resume", "anchor": ""}) is None
    assert policy.sanitize_focus({"kind": "resume", "anchor": "字" * 81}) is None


def test_sanitize_focus_normalizes_valid_values() -> None:
    assert policy.sanitize_focus({"kind": "weakness", "index": 2}) == {
        "kind": "weakness",
        "index": 2,
    }
    assert policy.sanitize_focus({"kind": "attempt", "question_id": "q-1"}) == {
        "kind": "attempt",
        "question_id": "q-1",
    }
    # 原句要压平空白：简历正文是单行文本，多行原句永远匹配不上。
    assert policy.sanitize_focus({"kind": "resume", "anchor": " 负责\n接口开发 "}) == {
        "kind": "resume",
        "anchor": "负责 接口开发",
    }
    # 前端传 pydantic 模型（路由层转 dict 之前）也要能用。
    model = TaifuFocus(kind="weakness", index=3)
    assert policy.sanitize_focus(model) == {"kind": "weakness", "index": 3}


# --- 明细取料 -----------------------------------------------------------------


def test_weakness_detail_carries_question_answer_and_result() -> None:
    detail = deep_read.build_detail(
        {"kind": "weakness", "index": 1},
        profile=None,
        report=_report(),
        attempts=[_attempt()],
        document_text=None,
        load_question=_loader(_question()),
    )

    assert detail is not None
    assert detail["href"] == "/report#weakness-1"
    text = "\n".join(detail["lines"])
    assert "错误率 75%（3/4）" in text
    assert "诊断：微任务顺序没吃透" in text
    assert "正确答案：B" in text
    assert "你的结果：答错" in text
    assert "Promise 回调进入微任务队列" in text


def test_weakness_detail_is_none_when_focus_does_not_resolve() -> None:
    loader = _loader(_question())
    assert (
        deep_read.build_detail(
            {"kind": "weakness", "index": 2},
            profile=None,
            report=_report(),
            attempts=[],
            document_text=None,
            load_question=loader,
        )
        is None
    )
    assert (
        deep_read.build_detail(
            {"kind": "weakness", "index": 1},
            profile=None,
            report=_report(with_samples=False),
            attempts=[],
            document_text=None,
            load_question=loader,
        )
        is None
    )
    assert (
        deep_read.build_detail(
            {"kind": "weakness", "index": 1},
            profile=None,
            report=None,
            attempts=[],
            document_text=None,
            load_question=loader,
        )
        is None
    )


def test_weakness_detail_does_not_invent_a_deleted_question() -> None:
    detail = deep_read.build_detail(
        {"kind": "weakness", "index": 1},
        profile=None,
        report=_report(),
        attempts=[],
        document_text=None,
        load_question=_loader(),
    )

    assert detail is not None
    text = "\n".join(detail["lines"])
    assert "已不在题库" in text
    assert "Q1 · 2/10" in text


def test_attempt_detail_requires_a_recorded_answer() -> None:
    loader = _loader(_question())
    assert (
        deep_read.build_detail(
            {"kind": "attempt", "question_id": "q-1"},
            profile=None,
            report=None,
            attempts=[],
            document_text=None,
            load_question=loader,
        )
        is None
    )
    assert (
        deep_read.build_detail(
            {"kind": "attempt", "question_id": "q-9"},
            profile=None,
            report=None,
            attempts=[_attempt()],
            document_text=None,
            load_question=loader,
        )
        is None
    )

    detail = deep_read.build_detail(
        {"kind": "attempt", "question_id": "q-1"},
        profile=None,
        report=None,
        attempts=[_attempt()],
        document_text=None,
        load_question=loader,
    )
    assert detail is not None
    assert detail["href"] == "/practice"
    assert "作答时间：2026-11-10" in "\n".join(detail["lines"])


def test_resume_detail_needs_an_exact_quote_in_the_document(profile_factory: Any) -> None:
    profile = profile_factory()
    detail = deep_read.build_detail(
        {"kind": "resume", "anchor": "负责接口开发"},
        profile=profile,
        report=_report(),
        attempts=[],
        document_text=RESUME_TEXT,
        load_question=_loader(),
    )

    assert detail is not None
    assert detail["href"] == "/polish"
    text = "\n".join(detail["lines"])
    assert "位置：项目经历 · 第 2 行" in text
    assert "报告指出的问题：缺少量化结果" in text
    assert "后文：与维护" in text

    # 原句不在正文（正文换代 / 前端传错）→ 当没传，不拿相似句硬凑。
    assert (
        deep_read.build_detail(
            {"kind": "resume", "anchor": "负责算法开发"},
            profile=profile,
            report=_report(),
            attempts=[],
            document_text=RESUME_TEXT,
            load_question=_loader(),
        )
        is None
    )
    # 没有画像就没有简历正文可读。
    assert (
        deep_read.build_detail(
            {"kind": "resume", "anchor": "负责接口开发"},
            profile=None,
            report=_report(),
            attempts=[],
            document_text=RESUME_TEXT,
            load_question=_loader(),
        )
        is None
    )


def test_detail_respects_line_and_row_budget() -> None:
    long_question = _question(
        prompt="长" * 400,
        explanation="析" * 400,
        options=[{"key": "A", "text": "选" * 120}],
    )
    detail = deep_read.build_detail(
        {"kind": "weakness", "index": 1},
        profile=None,
        report=_report(),
        attempts=[_attempt()],
        document_text=None,
        load_question=_loader(long_question),
    )

    assert detail is not None
    assert len(detail["lines"]) <= deep_read.MAX_DETAIL_LINES
    assert all(len(line) <= deep_read.DETAIL_LINE_MAX for line in detail["lines"])


# --- 编排与白名单 --------------------------------------------------------------


def test_chat_with_weakness_focus_lets_the_model_read_that_group(
    client: TestClient, patch_ai: Any, profile_factory: Any
) -> None:
    """r83：焦点只告诉模型「该调哪个工具」，明细必须由它自己读回来。"""
    repository.insert_profile(profile_factory())
    repository.insert_report(_report())
    repository.insert_question(_question())
    seen: dict[str, str] = {}

    def _responder(_model_cls: type[Any], user_prompt: str) -> dict[str, Any]:
        seen["prompt"] = user_prompt
        return {
            "reply": "错在微任务顺序。",
            "tool_calls": [
                {"name": "read_weakness_detail", "arguments": {"point": "事件循环"}}
            ],
        }

    patch_ai(_responder)
    response = client.post(
        "/api/taifu/chat",
        json={"question": "这条怎么补", "page": "/report", "focus": {"kind": "weakness", "index": 1}},
    )

    assert response.status_code == 200
    body = response.json()
    # 第一轮提示词里只有「去调哪个工具」的指引，明细本身不在里面 —— 这是 r83 与 r82 的分界。
    assert "read_weakness_detail" in seen["prompt"]
    assert "题面：以下哪个操作不会阻塞事件循环？" not in seen["prompt"]
    assert body["materials_used"] == 2
    assert [item["href"] for item in body["citations"]] == ["/report#weakness-1"]
    assert "薄弱明细" in body["citations"][0]["label"]
    assert body["reply"] == "错在微任务顺序。"


def test_chat_without_focus_is_unchanged(
    client: TestClient, patch_ai: Any, profile_factory: Any
) -> None:
    repository.insert_profile(profile_factory())
    repository.insert_report(_report())
    seen: dict[str, str] = {}

    def _responder(_model_cls: type[Any], user_prompt: str) -> dict[str, Any]:
        seen["prompt"] = user_prompt
        return {"reply": "先补部署。", "citations": ["/report"]}

    patch_ai(_responder)
    body = client.post("/api/taifu/chat", json={"question": "我先补什么"}).json()

    assert body["detail"] is None
    assert body["materials_used"] == 2
    assert policy.NO_FOCUS in seen["prompt"]
    assert "【重点明细】" not in seen["prompt"]


@pytest.mark.parametrize(
    "focus",
    [
        {"kind": "weakness", "index": 9},
        {"kind": "attempt", "question_id": "q-404"},
        {"kind": "resume", "anchor": "正文里没有这句"},
        {"kind": "team", "index": 1},
        {},
    ],
)
def test_unresolvable_focus_falls_back_instead_of_failing(
    client: TestClient, patch_ai: Any, profile_factory: Any, focus: dict[str, Any]
) -> None:
    repository.insert_profile(profile_factory())
    repository.insert_report(_report())
    patch_ai(lambda _model_cls, _user: {"reply": "按档案说。", "citations": ["/report"]})

    response = client.post("/api/taifu/chat", json={"question": "这条怎么补", "focus": focus})

    assert response.status_code == 200
    body = response.json()
    assert body["detail"] is None
    assert body["reply"] == "按档案说。"


def test_resume_anchor_is_only_citable_when_the_tool_read_it(
    client: TestClient, patch_ai: Any, profile_factory: Any
) -> None:
    repository.insert_document(
        ResumeMeta(resume_id="res-1", file_name="简历.txt", chars=len(RESUME_TEXT), sections=2),
        RESUME_TEXT,
    )
    repository.insert_profile(profile_factory())
    repository.insert_report(_report())
    patch_ai(
        lambda _model_cls, _user: {
            "reply": "改成量化结果。",
            "tool_calls": [
                {"name": "read_resume_anchor", "arguments": {"anchor_text": "负责接口开发"}}
            ],
        }
    )

    with_detail = client.post(
        "/api/taifu/chat",
        json={"question": "这句怎么写", "focus": {"kind": "resume", "anchor": "负责接口开发"}},
    ).json()
    assert [item["href"] for item in with_detail["citations"]] == ["/polish"]

    # 模型自己写了 href 但没调工具：不进引用，也不计「丢弃」（根本没通道）。
    patch_ai(lambda _model_cls, _user: {"reply": "改成量化结果。", "citations": ["/polish"]})
    without_detail = client.post("/api/taifu/chat", json={"question": "这句怎么写"}).json()
    assert without_detail["detail"] is None
    assert without_detail["citations"] == []
    assert without_detail["dropped_citations"] == 0


def test_attempt_focus_reads_the_wrong_answer(
    client: TestClient, patch_ai: Any, profile_factory: Any
) -> None:
    repository.insert_profile(profile_factory())
    repository.insert_question(_question())
    repository.insert_attempts([_attempt()])

    patch_ai(
        lambda _model_cls, _user: {
            "reply": "微任务顺序记反了。",
            "tool_calls": [
                {"name": "read_question_detail", "arguments": {"question_id": "q-1"}}
            ],
        }
    )
    body = client.post(
        "/api/taifu/chat",
        json={"question": "这题为什么错", "focus": {"kind": "attempt", "question_id": "q-1"}},
    ).json()

    # 引用成立即证明工具真的读到了：没读到就没有 /practice 这一条。
    assert [item["href"] for item in body["citations"]] == ["/practice"]
    assert "错题明细" in body["citations"][0]["label"]
    assert body["reply"] == "微任务顺序记反了。"
