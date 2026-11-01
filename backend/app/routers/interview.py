"""模拟面试路由（r5）：开局 / 逐轮 / 会话回溯三条路由。

- 开局 `POST /api/interviews` 只返回第 1 条发言（`InterviewRun{settings, question, total}`），
  8 题计划留在 `payload.plan`（AC-4：不预先铺开题目列表）。
- 逐轮 `POST /api/interviews/{run_id}/answers` 返回 `InterviewTurn`（`ScoreResult` 超集）：
  `score` / `comment` 与下一条发言同轮返回；失败一律 envelope 错误，**前端不得清空作答**。
- 回溯 `GET /api/interviews/{run_id}` 返回整场会话镜像（AC-9 刷新 / 重进恢复）。
- 分工：本层只做参数转发与错误映射，轮次编排 / 闸门 / 回写全在 `services.interview`。
"""

from __future__ import annotations

from fastapi import APIRouter

from ..schemas import (
    AnswerRequest,
    InterviewCreateRequest,
    InterviewRun,
    InterviewSession,
    InterviewTurn,
)
from ..services.interview import create_run as create_interview_run
from ..services.interview import load_session
from ..services.interview import score_answer as score_interview_answer

router = APIRouter(prefix="/api/interviews", tags=["interview"])


@router.post("", response_model=InterviewRun, summary="补全设定并开局（只投放第 1 条发言）")
async def create_run(payload: InterviewCreateRequest) -> InterviewRun:
    return await create_interview_run(payload.profile_id, payload.settings)


@router.post(
    "/{run_id}/answers",
    response_model=InterviewTurn,
    summary="提交当前发言作答，同轮返回评分与下一条发言",
)
async def submit_answer(run_id: str, payload: AnswerRequest) -> InterviewTurn:
    return await score_interview_answer(run_id, payload.question_id, payload.answer)


@router.get(
    "/{run_id}",
    response_model=InterviewSession,
    summary="读取整场会话（刷新 / 重进恢复，不重出题）",
)
def get_run(run_id: str) -> InterviewSession:
    return load_session(run_id)
