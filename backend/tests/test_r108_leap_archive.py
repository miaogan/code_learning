"""r108 跃迁档案看板：聚合端点 + 四要素文本自检。

fixture 自带（不建共享 helper）：`_report()` / `_profile_with_project()` 只补当前用例
关心的字段，其余走 schema 默认值。路由用 `client`（带登录 Cookie），库是 tmp_db。
"""

from __future__ import annotations

from typing import Any

from app.core import repository
from app.schemas import (
    Evidence,
    Profile,
    ProfileProject,
    ProfileSkill,
    Report,
    RoleFit,
    RoleFitItem,
    RoleModelRef,
)
from app.services import leap


def _profile_with_project() -> Profile:
    """本文件私有画像：一条带 2 条证据的技能 + 一个带 1 条证据的项目。"""
    return Profile(
        id="prof-leap",
        resume_id="res-1",
        updated_at="2026-11-16T00:00:00+00:00",
        skills=[
            ProfileSkill(
                name="Python",
                source_quote="负责 Python 服务",
                source_quotes=[
                    Evidence(quote="负责 Python 服务", resume_id="res-1", captured_at="t1"),
                    Evidence(quote="优化 Python 接口", resume_id="res-1", captured_at="t2"),
                ],
            )
        ],
        tech_stack=["Python"],
        years_experience=3.0,
        projects=[
            ProfileProject(
                name="订单系统",
                role="后端",
                period="2025",
                bullets=["拆分库存服务"],
                source_quote="负责订单系统",
                source_quotes=[
                    Evidence(quote="负责订单系统", resume_id="res-1", captured_at="t1")
                ],
            )
        ],
        target_role="后端工程师",
    )


ROLE_FIT = RoleFit(
    target_role="后端工程师",
    role_source="profile",
    role_source_label="简历画像",
    model=RoleModelRef(level="中级", label="后端工程师 · 中级", direction="后端"),
    items=[
        RoleFitItem(name="Python", required=3, user_level=2, gap=1, must=True),
        RoleFitItem(name="Redis", required=2, user_level=2, gap=0, must=False),
    ],
    missing_must=["Python"],
    first_fix=["Python"],
    conclusion="先补 Python",
)


def _report(*, role_fit: RoleFit | None = ROLE_FIT) -> Report:
    return Report(
        id="rep-leap-1",
        run_ids=["run-1"],
        interview_avg=7.5,
        exam_total=80.0,
        shortfalls=[],
        generated_at="2026-11-16T00:00:00+00:00",
        role_fit=role_fit,
    )


def _answer(
    text: str,
    *,
    entry_id: str = "iq-1",
    score: float | None = 8.0,
    comment: str | None = "表达清楚",
) -> dict[str, Any]:
    return {
        "id": entry_id,
        "kind": "project",
        "prompt": "讲一个你做过的项目",
        "answer": text,
        "score": score,
        "comment": comment,
    }


# --- 四要素文本自检（纯函数） ------------------------------------------------


def test_structure_all_four_hits_and_hint_is_not_a_score() -> None:
    result = leap.check_expression_structure(
        "遇到的问题是并发下重复扣款。我采用 Redis 锁的方案，把重复率从 5% 降到 0；"
        "踩过的坑是锁过期，后来加了续期，反思是要做压测。"
    )
    assert result.hit_count == 4
    assert result.has_problem and result.has_solution and result.has_metric and result.has_pitfall
    assert "自检" in result.hint and "评分" in result.hint
    assert "生产经验" in result.hint


def test_structure_missing_parts_are_named_in_hint() -> None:
    result = leap.check_expression_structure("我做了订单系统")
    assert result.hit_count == 0
    assert "问题 / 背景" in result.hint
    assert "指标 / 数据" in result.hint


def test_structure_metric_requires_quantification() -> None:
    """趋势词没有数字不算指标；纯数字无单位也不算（避免把编号当数据）。"""
    assert not leap.check_expression_structure("性能提升了").has_metric
    assert leap.check_expression_structure("P99 从 800ms 降到 120ms").has_metric
    assert leap.check_expression_structure("吞吐量提升到 3 倍").has_metric


def test_structure_tolerates_empty_and_non_string() -> None:
    result = leap.check_expression_structure("")
    assert result.hit_count == 0
    assert result.hint


# --- 聚合读取（repository / 路由） ------------------------------------------


def test_archive_empty_state_has_chinese_notices(client: Any) -> None:
    response = client.get("/api/leap-archive")
    assert response.status_code == 200
    body = response.json()
    assert body["role_gap"]["role_fit"] is None
    assert "诊断报告" in body["role_gap"]["notice"]
    assert body["engineering"]["projects"] == []
    assert "画像里还没有项目" in body["engineering"]["notice"]
    assert body["expression"]["items"] == []
    assert "模拟面试" in body["expression"]["notice"]
    assert body["generated_at"]


def test_archive_role_gap_reuses_report_without_recompute(client: Any, tmp_db: Any) -> None:
    repository.insert_report(_report())
    body = client.get("/api/leap-archive").json()
    fit = body["role_gap"]["role_fit"]
    assert fit["target_role"] == "后端工程师"
    assert [item["gap"] for item in fit["items"]] == [1, 0]
    assert fit["first_fix"] == ["Python"]


def test_archive_role_gap_old_report_without_role_fit(client: Any, tmp_db: Any) -> None:
    repository.insert_report(_report(role_fit=None))
    body = client.get("/api/leap-archive").json()
    assert body["role_gap"]["role_fit"] is None
    assert "目标岗位" in body["role_gap"]["notice"]


def test_archive_engineering_projects_carry_real_evidence(client: Any, tmp_db: Any) -> None:
    repository.insert_profile(_profile_with_project())
    body = client.get("/api/leap-archive").json()
    projects = body["engineering"]["projects"]
    assert len(projects) == 1
    assert projects[0]["name"] == "订单系统"
    assert projects[0]["evidence_count"] == 1
    assert projects[0]["bullets"] == ["拆分库存服务"]
    assert body["engineering"]["notice"] is None
    assert isinstance(body["engineering"]["data_scale"], dict)


def test_archive_expression_uses_written_score_and_skips_unanswered(
    client: Any, tmp_db: Any, profile_factory: Any
) -> None:
    profile = profile_factory()
    repository.insert_profile(profile)
    repository.insert_run(
        "run-leap-1",
        "interview",
        profile.id,
        {
            "questions": [
                _answer("遇到重复扣款问题，采用 Redis 锁，从 5% 降到 0，踩坑是锁过期", entry_id="iq-1"),
                _answer("未作答的答案", entry_id="iq-2", score=None, comment=None),
                {"id": "iq-3", "prompt": "空白", "answer": "   ", "score": 9},
            ]
        },
    )
    body = client.get("/api/leap-archive").json()
    items = body["expression"]["items"]
    assert len(items) == 1
    assert items[0]["score"] == 8.0
    assert items[0]["comment"] == "表达清楚"
    assert items[0]["structure"]["hit_count"] == 4
    assert items[0]["structure"]["has_metric"]

    # 再写一场：读取侧按创建时间倒序取最近场次，且分数逐字沿用写入值。
    repository.insert_run(
        "run-leap-2",
        "interview",
        profile.id,
        {"questions": [_answer("方案是实现缓存", entry_id="iq-1", score=6.5, comment="偏简略")]},
    )
    body = client.get("/api/leap-archive").json()
    assert len(body["expression"]["items"]) == 2
    assert {item["score"] for item in body["expression"]["items"]} == {8.0, 6.5}


def test_archive_is_user_isolated(tmp_db: Any, profile_factory: Any) -> None:
    """直接测 service 层：切换 ContextVar 归属后，看板只读到当前账号的报告与项目。"""
    from app.core import context

    profile = profile_factory()
    repository.insert_profile(profile)
    repository.insert_report(_report())
    assert leap.build_leap_archive().role_gap.role_fit is not None

    try:
        context.set_current_user_id("other-user")
        snapshot = leap.build_leap_archive()
        assert snapshot.role_gap.role_fit is None
        assert snapshot.engineering.projects == []
    finally:
        context.reset_current_user_id()
