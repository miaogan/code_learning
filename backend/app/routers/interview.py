"""模拟面试路由（r5）：开局 / 逐轮 / 提前结束 / 会话回溯四条路由。

- 开局 `POST /api/interviews` 只返回第 1 条发言（`InterviewRun{settings, question, total}`），
  8 题计划留在 `payload.plan`（AC-4：不预先铺开题目列表）。
- 逐轮 `POST /api/interviews/{run_id}/answers` 返回 `InterviewTurn`（`ScoreResult` 超集）：
  `score` / `comment` 与下一条发言同轮返回；失败一律 envelope 错误，**前端不得清空作答**。
- 提前结束 `POST /api/interviews/{run_id}/finish` 返回会话镜像：**不调用 AI**，因此不走
  heavy 能力闸门 —— 轻能力用户也能随时退出，未答题目不再计分。
- 回溯 `GET /api/interviews/{run_id}` 返回整场会话镜像（AC-9 刷新 / 重进恢复）。
- 分工：本层只做参数转发与错误映射，轮次编排 / 闸门 / 回写全在 `services.interview`。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.deps import CurrentUser, current_user
from app.schemas import (
    AnswerRequest,
    InterviewCreateRequest,
    InterviewRun,
    InterviewSession,
    InterviewSessionSummary,
    InterviewTurn,
)
from app.services.ai import user_ai
from app.services.interview.interview import (
    create_run as create_interview_run,
    finish_run as finish_interview_run,
    list_sessions as list_interview_sessions,
    load_session,
    score_answer as score_interview_answer,
    skip_question as skip_interview_question,
)

router = APIRouter(
    prefix="/api/interviews", tags=["interview"], dependencies=[Depends(current_user)]
)


@router.get("", response_model=list[InterviewSessionSummary], summary="历史面试列表（含在途场次）")
def get_runs(limit: int = 10) -> list[InterviewSessionSummary]:
    return list_interview_sessions(limit)


@router.post("", response_model=InterviewRun, summary="补全设定并开局（只投放第 1 条发言）")
async def create_run(payload: InterviewCreateRequest, user: CurrentUser) -> InterviewRun:
    client = user_ai.client_for(user, "heavy")
    return await create_interview_run(payload.profile_id, payload.settings, client=client)


@router.post(
    "/{run_id}/answers",
    response_model=InterviewTurn,
    summary="提交当前发言作答，同轮返回评分与下一条发言",
)
async def submit_answer(
    run_id: str, payload: AnswerRequest, user: CurrentUser
) -> InterviewTurn:
    client = user_ai.client_for(user, "heavy")
    return await score_interview_answer(run_id, payload.question_id, payload.answer, client=client)


@router.post(
    "/{run_id}/finish",
    response_model=InterviewSession,
    summary="提前结束本场面试（不调用 AI，未答题目不再计分）",
)
def finish_run(run_id: str) -> InterviewSession:
    return finish_interview_run(run_id)


@router.post(
    "/{run_id}/skip",
    response_model=InterviewSession,
    summary="跳过当前题目（不计分不调 AI，直接换下一道正题）",
)
def skip_run(run_id: str) -> InterviewSession:
    return skip_interview_question(run_id)


@router.get(
    "/{run_id}",
    response_model=InterviewSession,
    summary="读取整场会话（刷新 / 重进恢复，不重出题）",
)
def get_run(run_id: str) -> InterviewSession:
    return load_session(run_id)
