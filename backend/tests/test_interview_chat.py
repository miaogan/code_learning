"""r5 对话化面试 + 四项面试配置：零网络用例集（TECHNICAL §6.1，逐条标注 AC）。

断言口径尽量落在「下游能复算的东西」上：payload 形状、提示词里的原文、错误 envelope 的
status/retryable、以及「失败这一轮什么都没写」。渲染细节交给前端 vitest，不在这里断言。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from app.core import repository
from app.core.errors import AI_SCHEMA_INVALID, AI_UNAVAILABLE, NOT_FOUND, VALIDATION_ERROR, AppError
from app.schemas import InterviewSettings, InterviewSettingsPatch
from app.services.interview import history, interview as interview_service
from app.services.report import diagnosis, rules

#: 结构合格的计划：5 技术 + 3 项目（8 题、0 挑战），与 rules 下限逐项贴合。
VALID_KINDS = ["technical"] * rules.MIN_TECHNICAL_QUESTIONS + ["project"] * (
    rules.MIN_INTERVIEW_QUESTIONS - rules.MIN_TECHNICAL_QUESTIONS
)

#: 首位即挑战题的计划（用于「challenge 父题不给追问」：挑战 1 道 ≤ ceil(9×20%)=2）。
CHALLENGE_FIRST_KINDS = ["challenge"] + ["technical"] * 5 + ["project"] * 3

#: 四项设定 + 方向聚焦的一组非默认值（同时验证「不写回画像」与「每轮进提示词」）。
SETTINGS_VALUES = {
    "target_role": "后端工程师",
    "years_experience": "3-5年",
    "market": "北美",
    "company_size": "初创",
    "direction": "后端",
    "sub_direction": "python",
}


# --- 零网络基座 -------------------------------------------------------------


def _plan_items(kinds: list[str]) -> list[dict[str, str]]:
    """AI 计划响应：题干互不相同（`_squash` 后也不重复），配比由用例决定。"""
    return [
        {
            "kind": kind,
            "prompt": f"第 {index} 题（{kind}）：请结合简历里的经历说明做法、取舍与结果",
            "hint": "结合具体经历",
        }
        for index, kind in enumerate(kinds, start=1)
    ]


def _follow_up(round_no: int) -> dict[str, str]:
    """追问草稿：每轮文案不同，否则会被「题干去重」静默降级成计划正题。"""
    return {
        "mode": "follow_up",
        "prompt": f"追问 {round_no}：请补充第 {round_no} 个细节与结果",
        "hint": "",
    }


def _responder(
    *,
    kinds: list[str] | None = None,
    next_of: Any = None,
    score_of: Any = None,
) -> Any:
    """零网络 responder：出题模型给计划，轮次模型给「评分 + 下一条发言」，报告模型给空文案。"""
    plan = _plan_items(kinds if kinds is not None else VALID_KINDS)
    state = {"round": 0}

    def _respond(model_cls: type[Any], user: str) -> dict[str, Any]:
        fields = getattr(model_cls, "model_fields", {})
        if "shortfalls" in fields:  # 报告文案模型：空集 ⇒ 服务端退回模板文案（降级路径）
            return {"shortfalls": []}
        if "questions" in fields:  # 开局计划模型
            return {"questions": plan}
        state["round"] += 1
        round_no = state["round"]
        context = json.loads(user)
        return {
            "score": score_of(round_no, context) if score_of else 6.0,
            "comment": f"第 {round_no} 轮点评：思路清楚，但缺少量化结果",
            "next": next_of(round_no, context) if next_of else {"mode": "advance"},
        }

    return _respond


class _DownAI:
    """AI 出网口整体不可用（AC-10 的反面用例）：本轮必须什么都不写。"""

    async def complete_model(self, *_args: Any, **_kwargs: Any) -> Any:
        raise AppError(AI_UNAVAILABLE, "模型服务暂时不可用，请稍后再试", status=503, retryable=True)


def _seed_profile(profile_factory: Any) -> Any:
    profile = profile_factory()
    repository.insert_profile(profile)
    return profile


def _create(fake_ai: Any, profile_id: str, settings: InterviewSettingsPatch | None) -> Any:
    return asyncio.run(interview_service.create_run(profile_id, settings, client=fake_ai))


def _payload_of(run_id: str) -> dict[str, Any]:
    run = repository.get_run(run_id)
    assert run is not None
    return run["payload"]


def _drive(run_id: str, fake_ai: Any, *, rounds: int = 20) -> list[Any]:
    """从当前发言起连续作答直到会话结束，返回每轮的 `InterviewTurn`。"""
    session = interview_service.load_session(run_id)
    question_id = session.current_id
    turns: list[Any] = []
    while question_id is not None and len(turns) < rounds:
        turn = asyncio.run(
            interview_service.score_answer(
                run_id,
                question_id,
                f"第 {len(turns) + 1} 轮作答：先讲背景，再讲做法、取舍与结果",
                client=fake_ai,
            )
        )
        turns.append(turn)
        question_id = turn.next_question.id if turn.next_question is not None else None
    return turns


def _entry(
    question_id: str, kind: str, prompt: str, *, score: float | None = None
) -> dict[str, Any]:
    """payload 里的一篇发言（与 `_entry_of` 同形状，额外允许预置分数）。"""
    return {
        "id": question_id,
        "kind": kind,
        "prompt": prompt,
        "hint": "结合具体经历",
        "parent_id": None,
        "answer": None if score is None else "既有作答",
        "score": score,
        "comment": None if score is None else "既有点评",
        "answered_at": None,
        "elapsed_s": None,
    }


# --- AC-2②/AC-4：开局只投放第 1 条发言，settings 一并落库 ---------------------


def test_create_returns_single_question_and_settings(
    tmp_db: Any, profile_factory: Any, fake_ai: Any
) -> None:
    profile = _seed_profile(profile_factory)
    fake_ai.responder = _responder()

    run = _create(fake_ai, profile.id, InterviewSettingsPatch(**SETTINGS_VALUES))

    payload = _payload_of(run.run_id)
    assert payload["version"] == 2
    assert payload["settings"] == SETTINGS_VALUES
    assert run.settings.model_dump() == SETTINGS_VALUES
    assert run.question.id == "iq-1"
    assert payload["current_id"] == "iq-1"
    assert len(payload["questions"]) == 1, "开局只投放第 1 条发言（AC-4）"
    assert len(payload["plan"]) == len(VALID_KINDS), "整场计划留在 payload.plan，不回给前端"
    assert payload["plan_index"] == 0
    assert payload["answered_count"] == 0
    assert run.total == len(VALID_KINDS)


def test_create_fills_defaults_when_settings_omitted(
    tmp_db: Any, profile_factory: Any, fake_ai: Any
) -> None:
    blank = profile_factory().model_copy(
        update={"target_role": None, "years_experience": None}
    )
    repository.insert_profile(blank)
    fake_ai.responder = _responder()

    run = _create(fake_ai, blank.id, None)

    expected = {
        "target_role": rules.DEFAULT_TARGET_ROLE,
        "years_experience": rules.DEFAULT_EXPERIENCE_BAND,
        "market": rules.DEFAULT_MARKET,
        "company_size": rules.DEFAULT_COMPANY_SIZE,
        # 未指定方向 = 不限（空串，不占位、不进 focus 的「已聚焦」分支）。
        "direction": "",
        "sub_direction": "",
    }
    assert run.settings.model_dump() == expected
    assert _payload_of(run.run_id)["settings"] == expected


def test_create_does_not_write_back_profile(
    tmp_db: Any, profile_factory: Any, fake_ai: Any
) -> None:
    profile = _seed_profile(profile_factory)  # 画像岗位 = 前端开发工程师
    before = repository.get_profile(profile.id)
    assert before is not None
    fake_ai.responder = _responder()

    run = _create(fake_ai, profile.id, InterviewSettingsPatch(**SETTINGS_VALUES))

    after = repository.get_profile(profile.id)
    assert after is not None
    assert after.model_dump() == before.model_dump(), "临时设定绝不写回画像（AC-3）"
    assert after.target_role == "前端开发工程师"
    latest = repository.latest_profile()
    assert latest is not None
    assert latest.target_role == "前端开发工程师"
    assert run.settings.target_role == SETTINGS_VALUES["target_role"]


# --- AC-2③/AC-2④：设定进每一轮提示词，口径逐档可测 --------------------------


def test_every_round_prompt_carries_settings(
    tmp_db: Any, profile_factory: Any, fake_ai: Any
) -> None:
    profile = _seed_profile(profile_factory)
    fake_ai.responder = _responder()

    run = _create(fake_ai, profile.id, InterviewSettingsPatch(**SETTINGS_VALUES))
    _drive(run.run_id, fake_ai, rounds=3)

    assert len(fake_ai.calls) >= 3, "开局 1 次 + 每轮 1 次（同一轮产出评分与下一条发言）"
    for _system, user, timeout_s in fake_ai.calls[:3]:
        for value in SETTINGS_VALUES.values():
            assert value in user, f"设定值 {value} 未进入本轮提示词"
        assert timeout_s is None or timeout_s <= 15.0


def test_calibration_bands_are_distinct() -> None:
    base = {
        "target_role": "后端工程师",
        "years_experience": rules.DEFAULT_EXPERIENCE_BAND,
        "market": rules.DEFAULT_MARKET,
        "company_size": rules.DEFAULT_COMPANY_SIZE,
    }
    cases: list[tuple[str, tuple[str, ...], str]] = [
        ("years_experience", rules.EXPERIENCE_BANDS, "experience"),
        ("market", rules.MARKETS, "market"),
        ("company_size", rules.COMPANY_SIZES, "company"),
    ]
    for field, values, key in cases:
        texts = [
            interview_service.calibration_of(
                InterviewSettings.model_validate({**base, field: value})
            )[key]
            for value in values
        ]
        assert all(text.strip() for text in texts), f"{field} 存在空口径"
        assert len(set(texts)) == len(texts), f"{field} 档间口径重复，改了配置题目也不会变"

    role_text = interview_service.calibration_of(InterviewSettings.model_validate(base))["role"]
    assert "后端工程师" in role_text


def test_focus_calibration_covers_three_levels() -> None:
    """方向聚焦三档（不限 / 只到方向 / 到子方向）口径互不相同，且越界组合被清空。"""
    base = {
        "target_role": "后端工程师",
        "years_experience": rules.DEFAULT_EXPERIENCE_BAND,
        "market": rules.DEFAULT_MARKET,
        "company_size": rules.DEFAULT_COMPANY_SIZE,
    }
    unset = interview_service.calibration_of(InterviewSettings.model_validate(base))["focus"]
    direction_only = interview_service.calibration_of(
        InterviewSettings.model_validate({**base, "direction": "后端"})
    )["focus"]
    with_sub = interview_service.calibration_of(
        InterviewSettings.model_validate({**base, "direction": "前端", "sub_direction": "react"})
    )["focus"]
    assert len({unset, direction_only, with_sub}) == 3, "三档 focus 口径必须互不相同"
    assert "前端" in with_sub and "react" in with_sub

    # 越界方向清空方向；子方向不属于该方向只清子方向（方向本身合法就保留）；
    # 子方向脱离方向一并清空 —— 任何非法组合都不落进提示词。
    cases = [
        (InterviewSettingsPatch(direction="不存在的方向"), "", ""),
        (InterviewSettingsPatch(direction="前端", sub_direction="python"), "前端", ""),
        (InterviewSettingsPatch(sub_direction="python"), "", ""),
    ]
    for patch, direction, sub_direction in cases:
        settings = interview_service.fill_settings(patch, None)
        assert settings.direction == direction, f"{patch!r} 方向归一化不符"
        assert settings.sub_direction == sub_direction, f"{patch!r} 子方向归一化不符"


def test_settings_or_none_rejects_out_of_closure_direction() -> None:
    """历史 / 报告读路径：越界方向视为脏 payload（None），不得补默认值装成合法。"""
    base = {
        "target_role": "后端工程师",
        "years_experience": "3-5年",
        "market": "北美",
        "company_size": "初创",
    }
    assert rules.settings_or_none({"settings": {**base, "direction": "不存在的方向"}}) is None
    assert rules.settings_or_none({"settings": {**base, "direction": "前端", "sub_direction": "python"}}) is None
    assert rules.settings_or_none({"settings": {**base, "sub_direction": "python"}}) is None
    assert rules.settings_or_none({"settings": {**base, "direction": "前端", "sub_direction": "react"}}) is not None


# --- AC-6：历史窗口带上一答原文；追问继承 kind 与 parent ----------------------


def test_round_prompt_contains_recent_answers(
    tmp_db: Any, profile_factory: Any, fake_ai: Any
) -> None:
    profile = _seed_profile(profile_factory)
    fake_ai.responder = _responder()
    run = _create(fake_ai, profile.id, None)
    session = interview_service.load_session(run.run_id)
    first_id = session.current_id
    assert first_id is not None
    first_answer = "第一轮作答：React 虚拟滚动把首屏从 1.8s 降到 0.9s"
    second_answer = "第二轮作答：SQLite 用复合索引把慢查询降到 12ms"

    first = asyncio.run(
        interview_service.score_answer(run.run_id, first_id, first_answer, client=fake_ai)
    )
    assert first.next_question is not None
    second = asyncio.run(
        interview_service.score_answer(
            run.run_id, first.next_question.id, second_answer, client=fake_ai
        )
    )
    assert second.next_question is not None

    third_user = fake_ai.calls[-1][1]
    assert first_answer in third_user, "第 3 轮必须逐字带第 1 轮作答原文"
    assert second_answer in third_user, "第 3 轮必须逐字带第 2 轮作答原文"


def test_follow_up_inherits_kind_and_parent(
    tmp_db: Any, profile_factory: Any, fake_ai: Any
) -> None:
    profile = _seed_profile(profile_factory)
    fake_ai.responder = _responder(next_of=lambda round_no, _ctx: _follow_up(round_no))
    run = _create(fake_ai, profile.id, None)

    turn = asyncio.run(interview_service.score_answer(run.run_id, "iq-1", "作答", client=fake_ai))

    nxt = turn.next_question
    assert nxt is not None
    assert nxt.parent_id == "iq-1"
    assert nxt.kind == "technical", "追问继承父题 kind"
    assert nxt.id == "iq-2", "id 单调递增（服务端重编号）"
    payload = _payload_of(run.run_id)
    assert payload["follow_up_count"] == 1
    assert payload["current_id"] == "iq-2"
    assert [entry["id"] for entry in payload["questions"]] == ["iq-1", "iq-2"]


# --- AC-7：追问守门（challenge 父题 / 配额用尽）+ 双闸门 ---------------------


def test_follow_up_gated_by_challenge_parent(
    tmp_db: Any, profile_factory: Any, fake_ai: Any
) -> None:
    profile = _seed_profile(profile_factory)
    fake_ai.responder = _responder(
        kinds=CHALLENGE_FIRST_KINDS, next_of=lambda round_no, _ctx: _follow_up(round_no)
    )
    run = _create(fake_ai, profile.id, None)
    assert run.question.kind == "challenge"

    turn = asyncio.run(interview_service.score_answer(run.run_id, "iq-1", "作答", client=fake_ai))

    nxt = turn.next_question
    assert nxt is not None
    assert nxt.parent_id is None, "challenge 父题不给追问，静默降级为计划下一正题"
    assert nxt.id == "iq-2"
    assert _payload_of(run.run_id)["follow_up_count"] == 0


def test_follow_up_gated_by_low_score(
    tmp_db: Any, profile_factory: Any, fake_ai: Any
) -> None:
    """低分 (< FOLLOW_UP_MIN_SCORE) 时不得追问：AI 即使返回 follow_up 也静默降级为 advance（服务端硬门禁）。

    边界场景：提示词本应引导 AI 在追低分答时选 advance，但万一模型没遵守，服务端兜底拦截。
    这与 challenge 守门、配额守门并列，构成追问决策的三重保障。
    """
    profile = _seed_profile(profile_factory)
    # AI 同时返回「追问」模式和「低分」——模拟提示词没说服 AI 的边界情况
    fake_ai.responder = _responder(
        next_of=lambda round_no, _ctx: _follow_up(round_no),
        score_of=lambda _round_no, _ctx: interview_service.FOLLOW_UP_MIN_SCORE - 2,  # 低于阈值 2 分
    )
    run = _create(fake_ai, profile.id, None)

    turn = asyncio.run(interview_service.score_answer(run.run_id, "iq-1", "作答", client=fake_ai))

    nxt = turn.next_question
    assert nxt is not None
    assert nxt.parent_id is None, "低分禁追问：静默降级为计划下一正题，无 parent_id"
    assert nxt.id == "iq-2"
    assert _payload_of(run.run_id)["follow_up_count"] == 0
    assert turn.score == interview_service.FOLLOW_UP_MIN_SCORE - 2, "分数本身不受门禁影响，如实记录"


def test_follow_up_allowed_at_threshold_score(
    tmp_db: Any, profile_factory: Any, fake_ai: Any
) -> None:
    """恰在阈值（= FOLLOW_UP_MIN_SCORE）时允许追问：分数够了，且 allow_follow_up 也为 true。"""
    profile = _seed_profile(profile_factory)
    fake_ai.responder = _responder(
        next_of=lambda round_no, _ctx: _follow_up(round_no),
        score_of=lambda _round_no, _ctx: interview_service.FOLLOW_UP_MIN_SCORE,
    )
    run = _create(fake_ai, profile.id, None)

    turn = asyncio.run(interview_service.score_answer(run.run_id, "iq-1", "作答", client=fake_ai))

    nxt = turn.next_question
    assert nxt is not None
    assert nxt.parent_id == "iq-1", "阈值分数恰好允许追问"
    assert _payload_of(run.run_id)["follow_up_count"] == 1


def test_follow_up_gated_by_quota(tmp_db: Any, profile_factory: Any, fake_ai: Any) -> None:
    profile = _seed_profile(profile_factory)
    fake_ai.responder = _responder(next_of=lambda round_no, _ctx: _follow_up(round_no))
    run = _create(fake_ai, profile.id, None)

    turns = _drive(run.run_id, fake_ai)

    payload = _payload_of(run.run_id)
    expected_total = len(VALID_KINDS) + rules.MAX_FOLLOW_UPS
    assert len(turns) == expected_total
    assert payload["follow_up_count"] == rules.MAX_FOLLOW_UPS, "追问配额用尽后只走计划正题"
    assert len(payload["questions"]) == expected_total
    assert sum(1 for entry in payload["questions"] if entry["parent_id"]) == rules.MAX_FOLLOW_UPS
    assert payload["current_id"] is None
    assert turns[-1].run_status == repository.RUN_COMPLETED


#: r8 D-4 的题量梯子：最小合规卷 8 题 / 提示词声明的 9 题 / 比标准预算(12)还长的 13 题。
PAPER_SIZE_LADDER = {
    "8题": ["technical"] * 5 + ["project"] * 3,
    "9题": ["technical"] * 5 + ["project"] * 3 + ["challenge"],
    "13题": ["technical"] * 7 + ["project"] * 5 + ["challenge"],
}


@pytest.mark.parametrize("kinds", list(PAPER_SIZE_LADDER.values()), ids=list(PAPER_SIZE_LADDER))
def test_turn_cap_derives_from_paper_size(
    tmp_db: Any, profile_factory: Any, fake_ai: Any, kinds: list[str]
) -> None:
    """r8 D-4/D-5：轮次上限必须由**实际计划题量**派生，且每场追问配额用满。

    每轮都要求追问，把追问配额与轮次预算同时压到极限：一场会的发言数必须恰为
    `计划题量 + MAX_FOLLOW_UPS`，且**计划正题一题不落**。9 题卷因此是 13 条
    （9 正题 + 4 追问）；r8 D-5 之前上限只取 `max(12, 9) = 12`，追问被压到 3 次，本用例即红。
    """
    profile = _seed_profile(profile_factory)
    fake_ai.responder = _responder(
        kinds=kinds, next_of=lambda round_no, _ctx: _follow_up(round_no)
    )
    run = _create(fake_ai, profile.id, None)
    plan_total = len(kinds)
    turns = _drive(run.run_id, fake_ai)

    payload = _payload_of(run.run_id)
    entries = payload["questions"]
    planned_prompts = {item["prompt"] for item in _plan_items(kinds)}
    assert {entry["prompt"] for entry in entries} >= planned_prompts, "计划正题必须全部问到"
    assert len(turns) == plan_total + rules.MAX_FOLLOW_UPS, (
        f"{plan_total} 题卷必须用满 {rules.MAX_FOLLOW_UPS} 次追问"
        "（r8 D-5：9 题卷曾只给 3 次）"
    )
    assert len(turns) <= rules.max_turns(plan_total), "发言数越过由题量派生的轮次上限"
    assert len(entries) <= rules.max_turns(plan_total)
    assert rules.max_turns(plan_total) >= plan_total, "上限不得把计划正题挤出去"
    follow_ups = sum(1 for entry in entries if entry["parent_id"])
    assert follow_ups == rules.MAX_FOLLOW_UPS
    assert payload["follow_up_count"] == follow_ups
    assert payload["current_id"] is None
    assert turns[-1].run_status == repository.RUN_COMPLETED


def test_bad_plan_502_and_no_run_inserted(
    tmp_db: Any, profile_factory: Any, fake_ai: Any
) -> None:
    profile = _seed_profile(profile_factory)
    before = len(repository.list_runs(history.INTERVIEW_KIND))
    fake_ai.responder = _responder(kinds=["technical"] * 4 + ["project"] * 3)  # 7 题 < 下限

    with pytest.raises(AppError) as excinfo:
        _create(fake_ai, profile.id, None)

    assert excinfo.value.status == 502
    assert excinfo.value.retryable is True
    assert excinfo.value.code == AI_SCHEMA_INVALID
    assert len(repository.list_runs(history.INTERVIEW_KIND)) == before, "开局闸门失败不落库"


def test_session_structure_guard_blocks_completion(
    tmp_db: Any, profile_factory: Any, fake_ai: Any
) -> None:
    profile = _seed_profile(profile_factory)
    kinds = ["challenge"] * 5 + ["technical"] * 2 + ["project"] * 1  # 挑战 5 道 > ceil(8×20%)
    entries = [
        _entry(f"iq-{index}", kind, f"被构造的第 {index} 题（{kind}）", score=None if index == 8 else 6.0)
        for index, kind in enumerate(kinds, start=1)
    ]
    payload: dict[str, Any] = {
        "version": 2,
        "plan": [],
        "plan_index": 0,
        "questions": entries,
        "answered_count": len(entries) - 1,
        "total": len(entries),
        "follow_up_count": 0,
        "turn": len(entries) - 1,
        "current_id": "iq-8",
    }
    run_id = "run-guard"
    repository.insert_run(run_id, history.INTERVIEW_KIND, profile.id, payload)
    before = repository.get_run(run_id)
    assert before is not None
    fake_ai.responder = _responder()

    with pytest.raises(AppError) as excinfo:
        asyncio.run(interview_service.score_answer(run_id, "iq-8", "作答", client=fake_ai))

    assert excinfo.value.status == 502
    assert excinfo.value.retryable is True
    assert excinfo.value.code == AI_SCHEMA_INVALID
    after = repository.get_run(run_id)
    assert after is not None
    assert after["payload"] == before["payload"], "结束闸门拦下时本轮分数也不落库"
    assert after["status"] == repository.RUN_RUNNING


# --- AC-9：会话恢复与已结束只读 ---------------------------------------------


def test_load_session_restores_all(tmp_db: Any, profile_factory: Any, fake_ai: Any) -> None:
    profile = _seed_profile(profile_factory)
    fake_ai.responder = _responder(next_of=lambda round_no, _ctx: _follow_up(round_no))
    run = _create(fake_ai, profile.id, InterviewSettingsPatch(**SETTINGS_VALUES))
    first = asyncio.run(interview_service.score_answer(run.run_id, "iq-1", "第一轮作答", client=fake_ai))
    assert first.next_question is not None
    second = asyncio.run(
        interview_service.score_answer(
            run.run_id, first.next_question.id, "第二轮作答", client=fake_ai
        )
    )
    calls_before = len(fake_ai.calls)

    session = interview_service.load_session(run.run_id)

    assert len(fake_ai.calls) == calls_before, "恢复会话不得再调用 AI（不重出题、不重计分）"
    assert session.settings is not None
    assert session.settings.model_dump() == SETTINGS_VALUES
    assert len(session.questions) == 3, "2 条已答 + 1 条当前待答"
    assert session.answered_count == 2
    assert session.current_id == second.next_question.id  # type: ignore[union-attr]
    assert session.questions[0].answer == "第一轮作答"
    assert session.questions[0].score == 6.0
    assert session.questions[0].comment is not None
    assert session.questions[0].comment.startswith("第 1 轮点评")
    assert session.questions[-1].answer is None
    assert session.questions[-1].score is None
    assert session.total == len(VALID_KINDS)
    assert session.status == repository.RUN_RUNNING
    assert session.interview_avg == pytest.approx(6.0)


def test_completed_session_is_readonly(tmp_db: Any, profile_factory: Any, fake_ai: Any) -> None:
    profile = _seed_profile(profile_factory)
    fake_ai.responder = _responder()
    run = _create(fake_ai, profile.id, None)
    _drive(run.run_id, fake_ai)

    session = interview_service.load_session(run.run_id)
    assert session.status == repository.RUN_COMPLETED
    assert session.current_id is None, "已结束 ≠ 还有待答发言"
    assert session.answered_count == len(VALID_KINDS)

    with pytest.raises(AppError) as excinfo:
        asyncio.run(
            interview_service.score_answer(
                run.run_id, session.questions[-1].id, "再来一次", client=fake_ai
            )
        )
    assert excinfo.value.status == 400
    assert excinfo.value.code == VALIDATION_ERROR
    assert "结束" in excinfo.value.message


# --- AC-10：零副作用与幂等 --------------------------------------------------


def test_ai_timeout_leaves_no_trace(tmp_db: Any, profile_factory: Any, fake_ai: Any) -> None:
    profile = _seed_profile(profile_factory)
    fake_ai.responder = _responder()
    run = _create(fake_ai, profile.id, None)
    before = _payload_of(run.run_id)

    with pytest.raises(AppError) as excinfo:
        asyncio.run(interview_service.score_answer(run.run_id, "iq-1", "作答", client=_DownAI()))

    assert excinfo.value.status == 503
    after_run = repository.get_run(run.run_id)
    assert after_run is not None
    assert after_run["payload"] == before, "AI 失败整轮无痕迹（无新分数 / 无新发言）"
    assert after_run["status"] == repository.RUN_RUNNING
    assert after_run["payload"]["answered_count"] == 0


def test_replay_answered_question_rejected_without_side_effect(
    tmp_db: Any, profile_factory: Any, fake_ai: Any
) -> None:
    """重放**已答**旧题（网络重试 / 旧标签页 / 双击）：400 中文 + 既成事实一字不改（QA D-2）。"""
    profile = _seed_profile(profile_factory)
    fake_ai.responder = _responder(score_of=lambda round_no, _ctx: 4.0 if round_no == 1 else 8.0)
    run = _create(fake_ai, profile.id, None)

    first = asyncio.run(
        interview_service.score_answer(run.run_id, "iq-1", "第一次作答", client=fake_ai)
    )
    before = _payload_of(run.run_id)

    with pytest.raises(AppError) as excinfo:
        asyncio.run(interview_service.score_answer(run.run_id, "iq-1", "再答一次", client=fake_ai))

    assert excinfo.value.status == 400
    assert excinfo.value.code == VALIDATION_ERROR
    assert "答过" in excinfo.value.message
    payload = _payload_of(run.run_id)
    assert payload == before, "重放不得产生任何副作用（分数 / 点评 / 答案 / 进度全不变）"
    assert first.score == 4.0
    assert payload["questions"][0]["score"] == 4.0
    assert payload["questions"][0]["answer"] == "第一次作答"
    assert payload["answered_count"] == 1
    assert payload["current_id"] == "iq-2"


def test_retry_current_question_after_failure_is_accepted(
    tmp_db: Any, profile_factory: Any, fake_ai: Any
) -> None:
    """反面：AI 失败没写成绩 ⇒ 当前发言没推进，重试同一题仍须被接受且只计一次分（AC-10）。"""
    profile = _seed_profile(profile_factory)
    fake_ai.responder = _responder()
    run = _create(fake_ai, profile.id, None)

    with pytest.raises(AppError):
        asyncio.run(interview_service.score_answer(run.run_id, "iq-1", "作答", client=_DownAI()))
    assert _payload_of(run.run_id)["current_id"] == "iq-1", "失败这一轮不得推进当前发言"

    turn = asyncio.run(interview_service.score_answer(run.run_id, "iq-1", "作答", client=fake_ai))

    payload = _payload_of(run.run_id)
    assert turn.score == 6.0
    assert payload["questions"][0]["answer"] == "作答"
    assert payload["questions"][0]["score"] == 6.0
    assert payload["answered_count"] == 1, "重试只计一次分"
    assert payload["current_id"] == "iq-2"


# --- AC-11/AC-12/AC-14：旧 payload 只读、投影可回溯 --------------------------


def test_settings_readers_agree_on_partial_payload() -> None:
    """会话读路径与历史/报告读路径必须给同一答案（QA D-5：两套解析器严格度不同）。

    缺一个键的脏 payload 曾经在会话页是 `None`（未记录设定）、在历史/报告却被 schema
    默认值补成「中型」—— 同一场面试两个页面互相矛盾。解析口径已收敛到
    `rules.settings_or_none`，这里钉死三方一致。
    """
    partial = {"settings": {"target_role": "后端工程师", "years_experience": "3-5年", "market": "北美"}}
    assert interview_service._settings_or_none(partial) is None
    assert history._interviews_settings_of(partial) is None
    assert diagnosis.interview_settings_of([{"kind": "interview", "payload": partial}]) is None

    full = {"settings": dict(SETTINGS_VALUES)}
    session_settings = interview_service._settings_or_none(full)
    assert session_settings is not None
    assert history._interviews_settings_of(full) == session_settings
    assert diagnosis.interview_settings_of([{"kind": "interview", "payload": full}]) == session_settings


def test_legacy_payload_reads_with_null_settings(tmp_db: Any, profile_factory: Any) -> None:
    profile = _seed_profile(profile_factory)
    entries = [
        _entry(f"iq-{index}", "technical", f"存量第 {index} 题")
        for index in range(1, rules.MIN_INTERVIEW_QUESTIONS + 1)
    ]
    legacy: dict[str, Any] = {
        "questions": entries,
        "answered_count": 0,
        "total": len(entries),
    }
    run_id = "run-legacy"
    repository.insert_run(run_id, history.INTERVIEW_KIND, profile.id, legacy)

    session = interview_service.load_session(run_id)

    assert session.settings is None, "v1 payload 没记设定 → null，不伪造默认值"
    assert len(session.questions) == len(entries)
    assert session.current_id == entries[0]["id"]
    assert session.status == repository.RUN_RUNNING
    legacy_run = {
        "id": run_id,
        "kind": "interview",
        "created_at": "2026-10-30T00:00:00+00:00",
        "payload": legacy,
    }
    assert diagnosis.interview_settings_of([legacy_run]) is None


def test_history_row_carries_interview_settings(
    tmp_db: Any, profile_factory: Any, fake_ai: Any
) -> None:
    profile = _seed_profile(profile_factory)
    fake_ai.responder = _responder()
    run = _create(fake_ai, profile.id, InterviewSettingsPatch(**SETTINGS_VALUES))
    _drive(run.run_id, fake_ai)

    rows, total = history.list_history()

    assert total == 1
    assert len(rows) == 1
    assert rows[0].kind == history.INTERVIEW_KIND
    assert rows[0].interview_settings is not None
    assert rows[0].interview_settings.model_dump() == SETTINGS_VALUES
    assert rows[0].score == pytest.approx(6.0)


def test_report_carries_interview_settings(
    tmp_db: Any, profile_factory: Any, fake_ai: Any
) -> None:
    profile = _seed_profile(profile_factory)
    fake_ai.responder = _responder(score_of=lambda _round_no, _ctx: 2.0)  # 低分 → 必有短板
    run = _create(fake_ai, profile.id, InterviewSettingsPatch(**SETTINGS_VALUES))
    _drive(run.run_id, fake_ai)

    report = asyncio.run(diagnosis.build_report([run.run_id], client=fake_ai))

    assert report.run_ids == [run.run_id]
    assert report.interview_settings is not None
    assert report.interview_settings.model_dump() == SETTINGS_VALUES
    exam_like = {
        "id": "exam-1",
        "kind": "exam",
        "created_at": "2026-11-01T00:00:00+00:00",
        "payload": {"questions": []},
    }
    assert diagnosis.interview_settings_of([exam_like]) is None, "无面试 run → 报告不记设定"


# --- 提前结束（用户主动放弃本场：零 AI 调用、不跑结束闸门） -------------------


def test_finish_run_early_completes_without_ai(
    tmp_db: Any, profile_factory: Any, fake_ai: Any
) -> None:
    """刚开局就放弃：未答一题也能结束，且结束动作不花一次 AI 调用。"""
    profile = _seed_profile(profile_factory)
    fake_ai.responder = _responder()
    run = _create(fake_ai, profile.id, None)
    calls_before = len(fake_ai.calls)

    session = interview_service.finish_run(run.run_id)

    assert len(fake_ai.calls) == calls_before, "结束不需要评分，不得调用 AI"
    assert session.status == repository.RUN_COMPLETED
    assert session.current_id is None
    assert session.answered_count == 0
    assert session.total == run.total, "分母仍是计划题量，不因提前结束缩水"
    payload = _payload_of(run.run_id)
    assert payload["current_id"] is None
    assert len(payload["questions"]) == 1, "未答的题不铺开"
    assert len(repository.list_timeline_events()) == 1, "结束态写 1 条时间线事件"


def test_finish_run_keeps_answered_scores_and_is_idempotent(
    tmp_db: Any, profile_factory: Any, fake_ai: Any
) -> None:
    """答了一题再放弃：分数保留、未答题目不计分；重复结束幂等（不重复写时间线）。"""
    profile = _seed_profile(profile_factory)
    fake_ai.responder = _responder()
    run = _create(fake_ai, profile.id, None)
    turn = asyncio.run(interview_service.score_answer(run.run_id, "iq-1", "作答", client=fake_ai))
    assert turn.next_question is not None

    session = interview_service.finish_run(run.run_id)

    assert session.status == repository.RUN_COMPLETED
    assert session.answered_count == 1
    assert len(session.questions) == 2, "已答 1 条 + 已投放未答 1 条"
    assert session.questions[0].score == turn.score
    assert session.questions[1].score is None

    calls_before = len(fake_ai.calls)
    again = interview_service.finish_run(run.run_id)
    assert again.status == repository.RUN_COMPLETED
    assert again.answered_count == 1
    assert len(fake_ai.calls) == calls_before
    assert len(repository.list_timeline_events()) == 1, "幂等：不重复写时间线"


def test_finish_run_unknown_404(tmp_db: Any) -> None:
    with pytest.raises(AppError) as excinfo:
        interview_service.finish_run("no-such-run")
    assert excinfo.value.code == NOT_FOUND
    assert excinfo.value.status == 404


# --- r92：每题追问上限 + 跳过换题 ---------------------------------------------


def test_follow_up_capped_per_question(
    tmp_db: Any, profile_factory: Any, fake_ai: Any
) -> None:
    """r92：同一道题最多追问一次——追问的追问必须被拦下，静默降级为计划正题。

    模型每轮都要求 follow_up（分数 6 分、配额充足）：旧逻辑会在一道题上连续追问
    （全局 4 次配额可以全烧在同一题上）；新逻辑每条追问链深度 ≤ 1。
    """
    profile = _seed_profile(profile_factory)
    fake_ai.responder = _responder(next_of=lambda round_no, _ctx: _follow_up(round_no))
    run = _create(fake_ai, profile.id, None)
    _drive(run.run_id, fake_ai)

    payload = _payload_of(run.run_id)
    entries = payload["questions"]
    # 每条追问的父题必须是计划正题（parent_id 为空），不得出现「追问的追问」。
    by_id = {str(entry["id"]): entry for entry in entries}
    for entry in entries:
        if entry.get("parent_id"):
            parent = by_id.get(str(entry["parent_id"]))
            assert parent is not None
            assert not parent.get("parent_id"), "追问链深度超过 1：还在同一技术点上问到底"
    follow_ups = sum(1 for entry in entries if entry.get("parent_id"))
    assert follow_ups >= 1, "每题一次的追问额度没有被用上（用例失效）"
    assert payload["follow_up_count"] == follow_ups


def test_skip_question_advances_without_scoring(
    tmp_db: Any, profile_factory: Any, fake_ai: Any
) -> None:
    """r92 跳过：不计分、不调 AI，直接换下一道计划正题；跳过标记落库。"""
    profile = _seed_profile(profile_factory)
    fake_ai.responder = _responder(next_of=lambda _round_no, _ctx: {"mode": "advance"})
    run = _create(fake_ai, profile.id, None)
    calls_before = len(fake_ai.calls)

    session = interview_service.skip_question(run.run_id)
    assert len(fake_ai.calls) == calls_before, "跳过不得调用 AI"
    assert session.current_id == "iq-2", "跳过 iq-1 后应直接投放计划第 2 题"
    payload = _payload_of(run.run_id)
    first = payload["questions"][0]
    assert first["skipped"] is True
    assert first["answer"] is None and first["score"] is None
    assert payload["answered_count"] == 0
    assert payload["current_id"] == "iq-2"

    # 跳过后再作答推进不受影响（守门 / 计划投放照常）。
    fake_ai.responder = _responder(next_of=lambda _round_no, _ctx: {"mode": "advance"})
    turn = asyncio.run(
        interview_service.score_answer(
            run.run_id, "iq-2", "第 2 题作答：先讲背景，再讲做法与结果", client=fake_ai
        )
    )
    assert turn.score == 6.0
    assert turn.next_question is not None and turn.next_question.id == "iq-3"


def test_skip_last_question_completes_run(
    tmp_db: Any, profile_factory: Any, fake_ai: Any
) -> None:
    """r92：把最后一题也跳过 → 本场直接结束，与答满共用同一结束形状。"""
    profile = _seed_profile(profile_factory)
    fake_ai.responder = _responder(next_of=lambda _round_no, _ctx: {"mode": "advance"})
    run = _create(fake_ai, profile.id, None)
    payload = _payload_of(run.run_id)
    last_id = f"iq-{len(payload['plan'])}"

    # 连续跳到最后一题再跳过它：每一跳都不调 AI（calls 计数不变）。
    session = interview_service.load_session(run.run_id)
    while session.current_id is not None and session.current_id != last_id:
        session = interview_service.skip_question(run.run_id)
    session = interview_service.skip_question(run.run_id)
    assert session.status == "completed"
    assert session.current_id is None
    skipped = {str(entry["id"]) for entry in _payload_of(run.run_id)["questions"] if entry.get("skipped")}
    assert last_id in skipped


def test_skip_rejects_completed_and_unknown_run(tmp_db: Any, profile_factory: Any, fake_ai: Any) -> None:
    """r92：已结束的场与不存在的 run 跳过必须拒绝，零副作用。"""
    profile = _seed_profile(profile_factory)
    fake_ai.responder = _responder(next_of=lambda _round_no, _ctx: {"mode": "advance"})
    run = _create(fake_ai, profile.id, None)
    interview_service.finish_run(run.run_id)
    with pytest.raises(AppError) as finished:
        interview_service.skip_question(run.run_id)
    assert finished.value.status == 400
    with pytest.raises(AppError) as missing:
        interview_service.skip_question("no-such-run")
    assert missing.value.status == 404
