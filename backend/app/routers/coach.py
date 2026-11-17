"""r65 AI 学习教练端点 + r100 B4 Agent 编排端点（`/api/coach/agent/*`）。

`/advice`：材料由前端组装（教程语料只在前端），服务端只做三件事：
清洗材料 → 约束提示词 → **引用白名单校验**（模型 href 必须逐字来自材料）。
业务主路径全在 `services/coach/`，路由只做空材料短路与依赖装配。

`/agent/*`（r100 B4）：服务端自己编排 —— 规划器按问题调度只读工具（薄弱点 /
教程 RAG 检索 / 题库检索 / 计划进度），执行后反思补跑，最后只基于工具结果写结论；
每次编排的完整轨迹落 `coach_runs`，可回放「它为什么这么答」。
"""

from fastapi import APIRouter, Depends

from app.core import repository
from app.core.errors import GUARDRAIL_BLOCKED, NOT_FOUND, AppError
from app.deps import CurrentUser, current_user
from app.schemas import (
    CoachAdvice,
    CoachAdviceRequest,
    CoachAgentRequest,
    CoachAgentRun,
    CoachCitation,
)
from app.services.ai import guardrails, user_ai
from app.services.coach import policy
from app.services.coach.agent import run_agent
from app.services.coach.coach import build_advice, empty_advice

router = APIRouter(prefix="/api/coach", tags=["coach"], dependencies=[Depends(current_user)])


@router.post("/advice", response_model=CoachAdvice, summary="基于站内材料生成学习建议")
async def coach_advice(payload: CoachAdviceRequest, user: CurrentUser) -> CoachAdvice:
    # 先清洗再判断：脏 / 空材料不进入 AI 链路，省一次调用与用户等待。
    materials = policy.sanitize_materials(payload.materials)
    if not materials:
        return empty_advice()
    client = user_ai.client_for(user, "light")
    return await build_advice(materials, focus=payload.focus, goal=payload.goal, client=client)


@router.post(
    "/agent/run",
    response_model=CoachAgentRun,
    summary="跑一次教练 Agent 编排（规划 → 工具 → 反思 → 有引用结论）",
)
async def coach_agent_run(payload: CoachAgentRequest, user: CurrentUser) -> CoachAgentRun:
    # r122：编排器的问句是自由文本，也是唯一能让模型“自己决定调研工具”的入口，
    # 注入拦截放在建客户端之前 —— 拦下来的一次编排就省掉规划 + 多轮工具调用。
    checked = guardrails.guard_input(payload.question, surface="coach.agent")
    if checked.blocked:
        raise AppError(GUARDRAIL_BLOCKED, checked.notice, status=422)
    client = user_ai.client_for(user, "light")
    run = await run_agent(checked.text, goal=payload.goal, client=client)
    guarded = guardrails.guard_output(run.answer, surface="coach.agent")
    if guarded.blocked or guarded.changed:
        run.answer = guarded.notice if guarded.blocked else guarded.text
    return run


@router.get(
    "/agent/runs",
    response_model=list[CoachAgentRun],
    summary="编排历史（倒序，按账号隔离）",
)
def coach_agent_runs(limit: int = 20) -> list[CoachAgentRun]:
    return [
        CoachAgentRun(
            id=row["id"],
            question=row["question"],
            goal=row["goal"],
            status=row["status"],
            steps=row["steps"],
            answer=row["answer"],
            citations=[CoachCitation(**item) for item in row["citations"] if isinstance(item, dict)],
            created_at=row["created_at"],
        )
        for row in repository.list_coach_runs(limit)
    ]


@router.get(
    "/agent/runs/{run_id}",
    response_model=CoachAgentRun,
    summary="单次编排轨迹（审计回放）",
)
def coach_agent_run_detail(run_id: str) -> CoachAgentRun:
    row = repository.coach_run_row(run_id)
    if row is None:
        raise AppError(NOT_FOUND, "编排记录不存在", status=404)
    return CoachAgentRun(
        id=row["id"],
        question=row["question"],
        goal=row["goal"],
        status=row["status"],
        steps=row["steps"],
        answer=row["answer"],
        citations=[CoachCitation(**item) for item in row["citations"] if isinstance(item, dict)],
        created_at=row["created_at"],
    )
