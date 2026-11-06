"""岗位能力模型加载与差距计算（AC-7/8/9/10/20）。

覆盖 TECHNICAL §7.1 的用例 11–22：seed 结构与闭集、坏文件三条异常路径、
`gap = max(0, required-user_level)` 与排序、幂等、`missing_must` 定义、空画像不抛、
`user_level` 四档规则、`resolve_target_role` 优先级与 label、无匹配降级、`first_fix` 顺序、
`years=None` 取最低级。

fixture 自带（每个新测试文件各一份，不新建共享 helper 模块）：`_profile()` 只补当前用例关心的字段，
其余走 schema 默认值——这样 schema 改了默认值，这里的用例不会因为无关字段而红。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.errors import VALIDATION_ERROR, AppError
from app.schemas import Evidence, InterviewSettings, Profile, ProfileProject, ProfileSkill
from app.services.report import role_fit, rules
from app.services.resume import coach_copy


@pytest.fixture(autouse=True)
def _clear_role_model_cache() -> None:
    """`load_role_models` 是 `lru_cache`：坏文件用例换 `SEED_PATH` 前后都要清，否则互相污染。"""
    role_fit.load_role_models.cache_clear()
    yield
    role_fit.load_role_models.cache_clear()


def _skill(name: str, *, quotes: int = 1, status: str = "active") -> ProfileSkill:
    """画像技能：`quotes` 条证据（1 = 只有 `source_quote` 回填，2+ = 真实证据链）。"""
    evidence = [Evidence(quote=f"{name} 证据 {index}") for index in range(quotes)]
    return ProfileSkill(
        name=name,
        source_quote=evidence[0].quote,
        source_quotes=evidence,
        status=status,
    )


def _project(bullets: list[str]) -> ProfileProject:
    return ProfileProject(
        name="订单系统",
        role="后端开发",
        period="2025.01-2025.09",
        bullets=bullets,
        source_quote="负责订单系统开发",
    )


def _profile(
    *,
    skills: list[ProfileSkill] | None = None,
    tech_stack: list[str] | None = None,
    projects: list[ProfileProject] | None = None,
    years: float | None = 3.0,
    target_role: str | None = "后端工程师",
) -> Profile:
    return Profile(
        id="profile-1",
        resume_id="resume-1",
        updated_at="2026-11-01T00:00:00+08:00",
        skills=skills or [],
        tech_stack=tech_stack or [],
        years_experience=years,
        projects=projects or [],
        target_role=target_role,
    )


def _bad_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, text: str) -> None:
    path = tmp_path / "role_models.json"
    path.write_text(text, encoding="utf-8")
    monkeypatch.setattr(role_fit, "SEED_PATH", path)


def _seed() -> dict[str, tuple[tuple, ...]]:
    return role_fit.load_role_models()


# --- 11/12 seed 数量与结构 ---------------------------------------------------


def test_seed_covers_four_directions_and_four_levels() -> None:
    models = _seed()
    assert len(models) >= role_fit.MIN_ROLES
    directions = set()
    for role, levels in models.items():
        assert len(levels) == role_fit.LEVELS_PER_ROLE
        assert [entry.level for entry in levels] == list(role_fit.LEVEL_ORDER)
        assert [entry.role for entry in levels] == [role] * role_fit.LEVELS_PER_ROLE
        directions.add(levels[0].direction)
    assert directions == set(rules.DIRECTIONS)


def test_seed_skills_and_must_have_obey_cardinality() -> None:
    for levels in _seed().values():
        for entry in levels:
            names = [skill.name for skill in entry.skills]
            assert role_fit.MIN_SKILLS <= len(names) <= role_fit.MAX_SKILLS
            assert len(entry.must_have) >= role_fit.MIN_MUST_HAVE
            assert set(entry.must_have) <= set(names)
            for skill in entry.skills:
                assert skill.required in role_fit.ROLE_LEVELS
            assert entry.years_min < entry.years_max


def test_seed_levels_are_sorted_by_years() -> None:
    for levels in _seed().values():
        assert [entry.years_min for entry in levels] == sorted(entry.years_min for entry in levels)


# --- 13 坏文件三条异常路径 ---------------------------------------------------


def test_missing_file_raises_validation_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(role_fit, "SEED_PATH", tmp_path / "absent.json")
    with pytest.raises(AppError) as excinfo:
        role_fit.load_role_models()
    _assert_validation_message(excinfo.value)


def test_broken_json_raises_validation_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _bad_file(tmp_path, monkeypatch, '{"models": [')
    with pytest.raises(AppError) as excinfo:
        role_fit.load_role_models()
    _assert_validation_message(excinfo.value)


def test_missing_field_raises_validation_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _bad_file(tmp_path, monkeypatch, json.dumps({"models": [{"role": "前端工程师"}]}))
    with pytest.raises(AppError) as excinfo:
        role_fit.load_role_models()
    _assert_validation_message(excinfo.value)


def test_too_few_models_raises_validation_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = json.loads(role_fit.SEED_PATH.read_text(encoding="utf-8"))
    _bad_file(tmp_path, monkeypatch, json.dumps({"models": raw["models"][:4]}))
    with pytest.raises(AppError) as excinfo:
        role_fit.load_role_models()
    _assert_validation_message(excinfo.value)


def test_must_have_not_subset_raises_validation_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = json.loads(role_fit.SEED_PATH.read_text(encoding="utf-8"))
    raw["models"][0]["must_have"] = ["不存在的技能", "JavaScript", "HTML/CSS"]
    _bad_file(tmp_path, monkeypatch, json.dumps(raw))
    with pytest.raises(AppError) as excinfo:
        role_fit.load_role_models()
    _assert_validation_message(excinfo.value)


def _assert_validation_message(error: AppError) -> None:
    """AC-7：错误码是 `VALIDATION_ERROR`，message 中文且不含路径/堆栈/文件名。"""
    assert error.code == VALIDATION_ERROR
    assert error.status == 500
    assert error.retryable is False
    assert error.message.startswith("内置岗位能力模型")
    assert "/" not in error.message
    assert "seed" not in error.message.lower()
    assert ".json" not in error.message


# --- 14 gap 与排序 -----------------------------------------------------------


def test_gap_equals_max_zero_difference() -> None:
    fit = role_fit.build_role_fit(_profile(), "后端工程师")
    assert fit.model is not None
    assert fit.items
    for item in fit.items:
        assert item.gap == max(0, item.required - item.user_level)


def test_items_sorted_must_first_then_gap_desc_then_name() -> None:
    fit = role_fit.build_role_fit(_profile(skills=[_skill("Redis 与缓存")]), "后端工程师")
    keys = [(0 if item.must else 1, -item.gap, item.name) for item in fit.items]
    assert keys == sorted(keys)


# --- 15 幂等 -----------------------------------------------------------------


def test_build_role_fit_is_idempotent() -> None:
    profile = _profile(skills=[_skill("Python", quotes=2)])
    first = role_fit.build_role_fit(profile, "后端工程师")
    second = role_fit.build_role_fit(profile, "后端工程师")
    assert first.model_dump() == second.model_dump()


# --- 16 missing_must 定义 ----------------------------------------------------


def test_missing_must_is_unmet_must_set() -> None:
    fit = role_fit.build_role_fit(_profile(skills=[_skill("Python", quotes=3)]), "后端工程师")
    assert fit.model is not None
    must_items = [item for item in fit.items if item.must]
    assert set(fit.missing_must) == {item.name for item in must_items if item.gap > 0}
    # 顺序取 items 顺序（前端与 .md 都按它渲染，不能是 set 的随机序）
    assert fit.missing_must == [item.name for item in must_items if item.gap > 0]


# --- 17 空画像不抛 -----------------------------------------------------------


def test_empty_profile_keeps_all_gaps_and_does_not_raise() -> None:
    fit = role_fit.build_role_fit(None, "后端工程师")
    assert fit.model is not None
    assert fit.items
    assert all(item.user_level == 0 for item in fit.items)
    assert all(item.gap == item.required for item in fit.items)
    assert set(fit.missing_must) == {
        item.name for item in fit.items if item.must
    }
    assert fit.conclusion


# --- 18 user_level 四档规则 --------------------------------------------------


def test_user_level_zero_when_absent() -> None:
    assert role_fit.user_level_of("Python", _profile()) == 0
    assert role_fit.user_level_of("Python", None) == 0


def test_user_level_one_for_tech_stack_only() -> None:
    assert role_fit.user_level_of("Python", _profile(tech_stack=["Python"])) == 1


def test_user_level_two_with_single_evidence() -> None:
    assert role_fit.user_level_of("Python", _profile(skills=[_skill("Python")])) == 2


def test_user_level_three_with_evidence_chain() -> None:
    profile = _profile(skills=[_skill("Python", quotes=2)])
    assert role_fit.user_level_of("Python", profile) == 3


def test_user_level_four_with_project_bullet() -> None:
    profile = _profile(
        skills=[_skill("Python", quotes=2)],
        projects=[_project(["用 Python 重写了对账服务"])],
    )
    assert role_fit.user_level_of("Python", profile) == 4


def test_historical_skill_counts_as_zero() -> None:
    """已消失的能力不算当前水平（否则换过技术栈的人会显得比实际更强）。"""
    profile = _profile(skills=[_skill("Python", quotes=2, status="historical")])
    assert role_fit.user_level_of("Python", profile) == 0


# --- 19 resolve_target_role 优先级与 label -----------------------------------


def test_resolve_target_role_prefers_interview_settings() -> None:
    resolved = role_fit.resolve_target_role(
        interview_settings=InterviewSettings(target_role="前端工程师"),
        profile=_profile(target_role="后端工程师"),
    )
    assert resolved.role == "前端工程师"
    assert resolved.source == "interview"
    assert resolved.label == coach_copy.ROLE_SOURCE_LABEL["interview"]


def test_resolve_target_role_falls_back_to_profile() -> None:
    resolved = role_fit.resolve_target_role(
        interview_settings=None, profile=_profile(target_role="算法工程师")
    )
    assert resolved.role == "算法工程师"
    assert resolved.source == "profile"
    assert resolved.label == coach_copy.ROLE_SOURCE_LABEL["profile"]


def test_resolve_target_role_is_empty_when_both_missing() -> None:
    resolved = role_fit.resolve_target_role(interview_settings=None, profile=None)
    assert (resolved.role, resolved.source, resolved.label) == (None, None, None)
    # 画像存在但岗位为空/空白也一样
    blank_profile = _profile(target_role="   ")
    blank = role_fit.resolve_target_role(interview_settings=None, profile=blank_profile)
    assert blank.role is None


def test_build_role_fit_carries_role_source_from_settings() -> None:
    resolved = role_fit.resolve_target_role(
        interview_settings=InterviewSettings(target_role="前端工程师"),
        profile=_profile(target_role="后端工程师"),
    )
    fit = role_fit.build_role_fit(_profile(target_role="后端工程师"), resolved)
    assert fit.target_role == "前端工程师"
    assert fit.role_source == "interview"
    assert fit.role_source_label == coach_copy.ROLE_SOURCE_LABEL["interview"]


# --- 20 无匹配降级 -----------------------------------------------------------


def test_unknown_role_degrades_without_raising() -> None:
    fit = role_fit.build_role_fit(_profile(), "量子计算工程师")
    assert fit.model is None
    assert fit.items == []
    assert fit.missing_must == []
    assert fit.first_fix == []
    assert fit.notice == coach_copy.ROLE_NO_MODEL
    assert fit.target_role == "量子计算工程师"


def test_no_target_role_degrades_without_raising() -> None:
    fit = role_fit.build_role_fit(_profile(target_role=None), None)
    assert fit.model is None
    assert fit.notice == coach_copy.ROLE_NO_MODEL


# --- 21 first_fix 顺序 -------------------------------------------------------


def test_first_fix_is_first_three_positive_gaps_in_items_order() -> None:
    fit = role_fit.build_role_fit(None, "前端工程师")
    expected = [item.name for item in fit.items if item.gap > 0][: role_fit.FIRST_FIX_LIMIT]
    assert fit.first_fix == expected
    assert len(fit.first_fix) <= role_fit.FIRST_FIX_LIMIT


# --- 22 years=None → 最低级 --------------------------------------------------


def test_level_for_years_none_picks_lowest() -> None:
    levels = _seed()["后端工程师"]
    assert role_fit.level_for_years(levels, None) is levels[0]


def test_level_for_years_boundaries() -> None:
    levels = _seed()["后端工程师"]
    assert role_fit.level_for_years(levels, 0.0) is levels[0]
    assert role_fit.level_for_years(levels, 2.0) is levels[1]
    assert role_fit.level_for_years(levels, 4.9) is levels[1]
    assert role_fit.level_for_years(levels, 5.0) is levels[2]
    assert role_fit.level_for_years(levels, 50.0) is levels[3]
    assert role_fit.level_for_years(levels, -1.0) is levels[0]


def test_years_experience_selects_level_in_build() -> None:
    junior = role_fit.build_role_fit(_profile(years=0.5), "后端工程师")
    senior = role_fit.build_role_fit(_profile(years=6.0), "后端工程师")
    assert junior.model is not None and senior.model is not None
    assert junior.model.level == "初级"
    assert senior.model.level == "高级"
    assert senior.model.label == "后端工程师 · 高级"
