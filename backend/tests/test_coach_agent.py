"""r100 B4 教练 Agent 编排测试：工具层 + 图（规划/执行/反思/结论）+ 轨迹持久化 + 引用白名单。

零网络：模型调用全部经 `patch_ai`（类级补丁）按 `model_cls` 分派预置 payload。
"""

import pytest

from app.core import repository
from app.schemas import (
    CoachBriefDraft,
    CoachPlanDraft,
    CoachReflectDraft,
    Course,
    Report,
    Shortfall,
)
from app.services.coach import agent as coach_agent
from app.services.coach.agent import (
    _read_plan,
    _read_shortfalls,
    _search_questions,
    _search_tutorials,
)
from app.services.retrieval import indexer


def _report() -> Report:
    return Report(
        id="rep-agent-1",
        shortfalls=[
            Shortfall(
                name="SQL 索引与执行计划",
                severity="high",
                evidence="Q3 · 4/10",
                diagnosis="能背概念但说不出执行计划怎么看",
                actions=["读索引章节", "做 10 道索引题"],
                courses=[
                    Course(
                        id="c-1",
                        title="SQL 索引",
                        direction="SQL 与数据库",
                        level="入门",
                        url=None,
                        why="补齐执行计划基础",
                    )
                ],
            )
        ],
        generated_at="2026-11-15T00:00:00+00:00",
    )


@pytest.fixture()
def agent_db(tmp_db):
    """一道题 + 一条教程 chunk（索引已建）+ 一份带短板的报告。"""
    with repository.connection() as conn:
        conn.execute(
            "INSERT INTO questions (id, direction, sub_direction, kind, difficulty, essentiality,"
            " prompt, options, answer, source, language, explanation, created_at, updated_at)"
            " VALUES ('t-001', 'frontend', '', 'single', 'basic', 'must_know',"
            " 'React 虚拟滚动怎么实现？', '[]', '[\"A\"]', 'seed', '', '只渲染可视区',"
            " '2026-11-15T00:00:00+00:00', '2026-11-15T00:00:00+00:00')"
        )
    indexer.ingest_tutorial_chunks(
        [
            {
                "chapter_id": "ch-sql",
                "section_id": "sec-1",
                "title": "SQL · 索引与执行计划",
                "content": "索引是加速查询的物理结构；慢查询排查第一步是看执行计划，再看索引命中。",
            }
        ]
    )
    repository.insert_report(_report())


def _responder(*, plan=None, reflect=None, brief=None):
    """按目标模型分派预置 payload；反射可传列表按调用次数轮转（验证「补一轮」）。"""

    def _inner(model_cls, _user):
        if model_cls is CoachPlanDraft:
            return plan if plan is not None else {"goal": "补齐索引", "steps": []}
        if model_cls is CoachReflectDraft:
            if isinstance(reflect, list):
                return reflect[min(_inner.reflect_calls, len(reflect) - 1)]
            return reflect if reflect is not None else {
                "sufficient": True,
                "missing": [],
                "extra_steps": [],
            }
        if model_cls is CoachBriefDraft:
            return brief if brief is not None else {
                "answer": "先看执行计划，再补索引练习。",
                "citations": ["t1"],
                "actions": ["读 SQL 索引章节"],
            }
        raise AssertionError("未预期的模型契约：" + str(model_cls))

    _inner.reflect_calls = 0
    return _inner


# --- 工具层 -------------------------------------------------------------------


def test_read_shortfalls_from_latest_report(agent_db):
    """薄弱点工具：读最近报告，ref 从 w1 起，带证据与建议。"""
    outcome = _read_shortfalls({})
    assert outcome["ok"] is True
    assert outcome["items"][0]["ref"] == "w1"
    assert "SQL 索引" in outcome["items"][0]["title"]
    assert "Q3" in outcome["items"][0]["snippet"]
    assert outcome["lines"]


def test_read_shortfalls_without_report(tmp_db):
    """没有报告：ok=False + 中文说明（不拿别的数据凑数）。"""
    outcome = _read_shortfalls({})
    assert outcome["ok"] is False
    assert "报告" in outcome["summary"]


def test_search_tutorials_hits_rag_index(agent_db):
    """教程工具：走 r100 RAG 混合检索，href 指向章节锚点。"""
    outcome = _search_tutorials({"query": "索引 执行计划"})
    assert outcome["ok"] is True
    first = outcome["items"][0]
    assert first["kind"] == "tutorial"
    assert first["ref"] == "t1"
    assert first["href"] == "/learn/ch-sql#tutorial-sec-1"


def test_search_tutorials_without_index(tmp_db):
    """索引未构建：ok=False + 中文提示（考工页重建索引的指引在 notice 里）。"""
    outcome = _search_tutorials({"query": "任意"})
    assert outcome["ok"] is False
    assert "索引" in outcome["summary"]


def test_search_questions_returns_prompt_only(agent_db):
    """题库工具：只回题面与方向（答案永不入工具结果）。"""
    outcome = _search_questions({"query": "虚拟滚动"})
    assert outcome["ok"] is True
    assert outcome["items"][0]["ref"] == "q1"
    assert "虚拟滚动" in outcome["items"][0]["title"]
    assert "answer" not in outcome["items"][0]


def test_read_plan_not_started(agent_db):
    """计划工具：报告有但没打卡 → ok=False + 中文说明。"""
    outcome = _read_plan({})
    assert outcome["ok"] is False
    assert "打卡" in outcome["summary"] or "报告" in outcome["summary"]


# --- 编排图（HTTP 全链路） ------------------------------------------------------


def test_agent_run_trace_and_citations(agent_db, patch_ai, client):
    """一次完整编排：plan → tool×2 → reflect → final，轨迹与引用都落库可回放。"""
    patch_ai(
        _responder(
            plan={
                "goal": "补齐 SQL 索引",
                "steps": [
                    {"tool": "read_shortfalls", "reason": "先看短板", "args": {}},
                    {"tool": "search_tutorials", "reason": "找教程", "args": {"query": "索引 执行计划"}},
                ],
            },
            brief={
                "answer": "按执行计划→索引命中→补练习的顺序补。",
                "citations": ["t1", "t9"],
                "actions": ["读 SQL 索引章节", "做 10 道索引题"],
            },
        )
    )
    response = client.post(
        "/api/coach/agent/run", json={"question": "SQL 索引这块怎么补", "goal": "后端"}
    )
    assert response.status_code == 200
    payload = response.json()
    kinds = [step["kind"] for step in payload["steps"]]
    assert kinds == ["plan", "tool", "tool", "reflect", "final"]
    assert payload["goal"] == "补齐 SQL 索引"
    # t1 合法、t9 越界 → 丢弃并计数。
    assert [citation["ref"] for citation in payload["citations"]] == ["t1"]
    assert payload["dropped_citations"] == 1
    assert payload["citations"][0]["href"].startswith("/learn/ch-sql")

    # 轨迹落库：按 id 回放与列表都在。
    detail = client.get("/api/coach/agent/runs/" + payload["id"])
    assert detail.status_code == 200
    assert detail.json()["steps"] == payload["steps"]
    listed = client.get("/api/coach/agent/runs").json()
    assert any(item["id"] == payload["id"] for item in listed)


def test_agent_falls_back_when_planner_empty(agent_db, patch_ai, client):
    """规划器给空计划：走确定性兜底并在轨迹里如实标 fallback。"""
    patch_ai(_responder(plan={"goal": "", "steps": []}))
    payload = client.post("/api/coach/agent/run", json={"question": "怎么补索引"}).json()
    plan_step = payload["steps"][0]
    assert plan_step["kind"] == "plan" and plan_step["fallback"] is True
    tool_steps = [step for step in payload["steps"] if step["kind"] == "tool"]
    assert [step["tool"] for step in tool_steps] == [
        "read_shortfalls",
        "search_tutorials",
        "search_questions",
    ]


def test_agent_reflect_triggers_second_round(agent_db, patch_ai, client):
    """反思说「还不够」→ 补一轮执行（受 MAX_ACT_ROUNDS 约束，最多两轮）。"""
    reflector = _responder(
        plan={
            "goal": "补齐索引",
            "steps": [{"tool": "search_tutorials", "reason": "先找教程", "args": {"query": "索引"}}],
        },
        reflect=[
            {
                "sufficient": False,
                "missing": ["缺练习题"],
                "extra_steps": [
                    {"tool": "search_questions", "reason": "补题", "args": {"query": "索引"}}
                ],
            },
            {"sufficient": True, "missing": [], "extra_steps": []},
        ],
    )

    # patch_ai 只传 responder；这里包装一层，让反射调用计数推进。
    def counting(model_cls, user):
        if model_cls is CoachReflectDraft:
            payload = reflector(model_cls, user)
            reflector.reflect_calls += 1
            return payload
        return reflector(model_cls, user)

    patch_ai(counting)
    payload = client.post("/api/coach/agent/run", json={"question": "索引怎么练"}).json()
    kinds = [step["kind"] for step in payload["steps"]]
    assert kinds == ["plan", "tool", "reflect", "tool", "reflect", "final"]
    assert payload["steps"][2]["sufficient"] is False
    assert payload["steps"][-2]["sufficient"] is True


def test_agent_missing_run_is_404(client, assert_chinese):
    """不存在的轨迹：404 + 中文 message（不暴露存在性细节）。"""
    response = client.get("/api/coach/agent/runs/cr-not-exist")
    assert response.status_code == 404
    assert_chinese(response.json()["error"]["message"])


def test_agent_catalog_bounded(agent_db, patch_ai, client):
    """工具结果有界：单次编排最多 2 轮执行，每步最多 3 条材料（防止上下文被灌满）。"""
    patch_ai(_responder(plan={"goal": "g", "steps": []}))
    payload = client.post("/api/coach/agent/run", json={"question": "索引"}).json()
    tool_steps = [step for step in payload["steps"] if step["kind"] == "tool"]
    assert len(tool_steps) <= coach_agent.MAX_ACT_ROUNDS * coach_agent.MAX_STEPS_PER_ROUND
    assert all(len(step["items"]) <= coach_agent.MAX_ITEMS for step in tool_steps)


def test_read_leap_archive_tool_empty_state(tmp_db):
    """无报告 / 无画像时：跃迁档案工具给中文空结果，不编造岗位差距。"""
    from app.services.coach.agent import _read_leap_archive

    outcome = _read_leap_archive({})
    assert outcome["ok"] is False
    assert outcome["items"] == []
    assert outcome["summary"]


def test_read_leap_archive_tool_maps_report_and_projects(tmp_db):
    """有报告 + 画像时：先补项与项目都带 /leap 引用，且 ref 落在白名单形状内。"""
    from app.schemas import Profile, ProfileProject, RoleFit, RoleFitItem, RoleModelRef
    from app.services.coach.agent import _read_leap_archive

    report = _report()
    report.role_fit = RoleFit(
        target_role="后端工程师",
        role_source="profile",
        role_source_label="简历画像",
        model=RoleModelRef(level="中级", label="后端工程师 · 中级", direction="后端"),
        items=[RoleFitItem(name="Redis", required=3, user_level=1, gap=2, must=True)],
        missing_must=["Redis"],
        first_fix=["Redis"],
        conclusion="先补 Redis",
    )
    repository.insert_report(report)
    repository.insert_profile(
        Profile(
            id="prof-leap-tool",
            resume_id="res-1",
            updated_at="2026-11-16T00:00:00+00:00",
            skills=[],
            tech_stack=["Python"],
            years_experience=3.0,
            projects=[
                ProfileProject(
                    name="订单系统",
                    role="后端",
                    period="2025",
                    bullets=["拆分库存服务"],
                    source_quote="负责订单系统",
                )
            ],
            target_role="后端工程师",
        )
    )
    outcome = _read_leap_archive({})
    assert outcome["ok"] is True
    assert all(item["href"] == "/leap" for item in outcome["items"])
    assert {item["kind"] for item in outcome["items"]} == {"leap_role", "leap_project"}
    assert any("Redis" in item["title"] for item in outcome["items"])
    assert any("订单系统" in item["title"] for item in outcome["items"])
    assert len({item["ref"] for item in outcome["items"]}) == len(outcome["items"])


def test_leap_is_registered_in_tool_catalog():
    """新工具必须在闭集里，规划器才可能选到它。"""
    assert "read_leap_archive" in coach_agent.TOOL_CATALOG
    assert "read_leap_archive" in coach_agent.TOOLS
