"""模拟笔试路由（AC-4）：`POST /api/exams` 出卷、`POST /api/exams/{run_id}/submit` 判分。

路由只做参数校验与错误映射，判定规则全部在 `services/exam.py`：
- `profile_id` 走请求体（`ExamCreateRequest`），裸函数参数会被 FastAPI 当 query，前端对不上；
- 响应模型 `ExamRun` / `ExamResult` 而非 `-> None`，答案与判定细节由服务层负责；
- 错误一律经 `AppError` → 统一 envelope（404 画像/试卷不存在、400 题库不足或重复提交）。
"""

from fastapi import APIRouter, Depends

from app.deps import current_user
from app.schemas import ExamAnswers, ExamCreateRequest, ExamResult, ExamRun
from app.services.assessment import exam as exam_service

router = APIRouter(prefix="/api/exams", tags=["exam"], dependencies=[Depends(current_user)])


@router.post("", response_model=ExamRun, summary="依据画像出笔试题（可选指定方向/难度/题量）")
def create_run(payload: ExamCreateRequest) -> ExamRun:
    return exam_service.create_run(
        payload.profile_id,
        direction=payload.direction,
        difficulty=payload.difficulty,
        question_count=payload.question_count,
    )


@router.post(
    "/{run_id}/submit",
    response_model=ExamResult,
    summary="提交试卷并返回总分、客观题数与服务端用时",
)
def submit_run(run_id: str, payload: ExamAnswers) -> ExamResult:
    return exam_service.submit_run(run_id, payload.answers)
