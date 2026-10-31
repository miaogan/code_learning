"""模拟面试路由（AC-3）：出题与逐题评分。

- 出题 `POST /api/interviews` 走 body（`profile_id` 裸签名会被 FastAPI 当 query，前端必然对不上）。
- 评分 `POST /api/interviews/{run_id}/answers` 只返回 `ScoreResult{score, comment}`；
  超时/失败一律 envelope 错误，**前端不得清空作答**（AC-3）。
- 分工：本层只做参数转发与错误映射，题目配比 / 回写 / status 全在 `services.interview`。
"""

from __future__ import annotations

from fastapi import APIRouter

from ..schemas import AnswerRequest, InterviewCreateRequest, InterviewRun, ScoreResult
from ..services.interview import create_run as create_interview_run
from ..services.interview import score_answer as score_interview_answer

router = APIRouter(prefix="/api/interviews", tags=["interview"])


@router.post("", response_model=InterviewRun, summary="依据画像出 8 道面试题")
async def create_run(payload: InterviewCreateRequest) -> InterviewRun:
    return await create_interview_run(payload.profile_id)


@router.post(
    "/{run_id}/answers",
    response_model=ScoreResult,
    summary="提交单题作答并返回 0–10 分",
)
async def submit_answer(run_id: str, payload: AnswerRequest) -> ScoreResult:
    return await score_interview_answer(run_id, payload.question_id, payload.answer)
