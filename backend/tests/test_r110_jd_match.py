"""r110 JD 岗位对位：零 AI 关键词证据、缺口来源、召对预设与用户隔离。

fixture 自带（不建共享 helper）：画像只补本文件关心的字段；路由走 `client`（带登录 Cookie），
库是 tmp_db。断言重点不是「匹配得像不像」，而是**证据可复核、缺口来源不被混淆、没有能力分**。
"""

from __future__ import annotations

from typing import Any

from app.core import repository
from app.schemas import Evidence, JdMatchRequest, Profile, ProfileSkill
from app.services import jd_match


def _profile() -> Profile:
    return Profile(
        id="prof-jd-1",
        resume_id="res-jd-1",
        updated_at="2026-11-16T00:00:00+00:00",
        skills=[
            ProfileSkill(
                name="Python 后端服务",
                source_quote="负责 Python 服务",
                source_quotes=[
                    Evidence(
                        quote="负责 Python 服务",
                        resume_id="res-jd-1",
                        captured_at="t1",
                    ),
                    Evidence(
                        quote="优化 Python 接口",
                        resume_id="res-jd-1",
                        captured_at="t2",
                    ),
                ],
            )
        ],
        tech_stack=["Python"],
        years_experience=3.0,
        target_role="后端工程师",
    )


JD = (
    "招聘后端工程师。\n"
    "职责：设计 Python 后端服务，维护 Redis 缓存与消息队列。\n"
    "要求：熟悉 Kubernetes 运维、Docker 基础，有事务与锁经验；了解 React。"
)


def test_empty_jd_is_rejected(client: Any) -> None:
    response = client.post("/api/jd-match", json={"jd_text": "   "})
    assert response.status_code == 400
    assert "粘贴" in response.json()["error"]["message"]


def test_no_profile_still_lists_jd_evidence_with_honest_notice(client: Any) -> None:
    response = client.post("/api/jd-match", json={"jd_text": JD})
    assert response.status_code == 200
    body = response.json()
    assert body["keywords"]
    assert all(item["status"] == "missing" for item in body["keywords"])
    assert all(item["evidence_count"] == 0 for item in body["keywords"])
    assert "画像" in body["notice"]
    assert "不是能力评分" in body["notice"]
    assert body["source_chars"] == len(JD)


def test_profile_evidence_is_quoted_not_guessed(client: Any, tmp_db: Any) -> None:
    repository.insert_profile(_profile())
    body = client.post("/api/jd-match", json={"jd_text": JD}).json()
    python = next(item for item in body["keywords"] if item["name"] == "Python 后端服务")
    assert python["status"] == "evidence"
    assert python["user_level"] >= 2
    assert python["evidence_count"] == 2
    assert "负责 Python 服务" in python["evidence"]
    assert "Python" in python["source_quote"]
    assert body["matched_count"] >= 1


def test_role_is_detected_and_explicit_target_role_wins(client: Any, tmp_db: Any) -> None:
    repository.insert_profile(_profile())
    automatic = client.post("/api/jd-match", json={"jd_text": JD}).json()
    assert automatic["target_role"] == "后端工程师"
    assert automatic["role_fit"] is not None
    assert automatic["role_fit"]["model"]["direction"] == "后端"

    explicit = client.post(
        "/api/jd-match", json={"jd_text": JD, "target_role": "AI 工程师"}
    ).json()
    assert explicit["target_role"] == "AI 工程师"
    assert explicit["role_fit"]["target_role"] == "AI 工程师"


def test_gaps_keep_jd_and_role_model_sources_separate(client: Any, tmp_db: Any) -> None:
    repository.insert_profile(_profile())
    body = client.post("/api/jd-match", json={"jd_text": JD}).json()
    jd_gaps = [item for item in body["gaps"] if item["origin"] == "jd"]
    model_gaps = [item for item in body["gaps"] if item["origin"] == "role_model"]
    assert jd_gaps
    assert model_gaps
    assert all(item["source_quote"] for item in jd_gaps)
    assert all("未直接提到" in item["reason"] for item in model_gaps)
    assert all("没有可复算的证据" in item["reason"] for item in jd_gaps)


def test_preset_uses_closed_directions_and_is_interview_ready(client: Any, tmp_db: Any) -> None:
    repository.insert_profile(_profile())
    body = client.post("/api/jd-match", json={"jd_text": JD}).json()
    preset = body["preset"]
    assert preset is not None
    assert preset["target_role"] == "后端工程师"
    assert preset["direction"] in {"前端", "后端", "算法与数据结构", "计算机基础", "AI 工程", "中间件与运维", "SQL 与数据库", "研发工程实践"}
    assert preset["sub_direction"] in {"python", "java", "go", "通用后端", ""}
    gap_names = {item["name"] for item in body["gaps"]}
    assert preset["focus_gaps"]
    assert all(gap in gap_names for gap in preset["focus_gaps"])
    assert len(preset["focus_gaps"]) <= 3
    assert "召对页" in preset["reason"]


def test_short_ascii_alias_does_not_match_inside_word() -> None:
    """`go` 不能命中 `golang`，否则缺口清单会编造 JD 没写的技术。"""
    result = jd_match.match_jd(JdMatchRequest(jd_text="岗位要求 golang 开发。"))
    assert all(item.matched_alias.lower() != "go" for item in result.keywords)


def test_result_has_no_percentage_or_score_field(client: Any, tmp_db: Any) -> None:
    repository.insert_profile(_profile())
    body = client.post("/api/jd-match", json={"jd_text": JD}).json()
    assert "score" not in body
    assert "match_rate" not in body
    assert "match_percent" not in body
    assert "能力分" not in body["notice"]


def test_service_is_user_isolated(tmp_db: Any) -> None:
    from app.core import context

    repository.insert_profile(_profile())
    mine = jd_match.match_jd(JdMatchRequest(jd_text=JD))
    assert any(item.status == "evidence" for item in mine.keywords)
    try:
        context.set_current_user_id("other-user")
        other = jd_match.match_jd(JdMatchRequest(jd_text=JD))
        assert all(item.status == "missing" for item in other.keywords)
        assert "还没有画像" in str(other.notice)
    finally:
        context.reset_current_user_id()
