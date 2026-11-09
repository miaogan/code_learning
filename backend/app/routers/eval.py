"""r51 模型调用质量看板（只读聚合）：登录态 + 按 `user_id` 隔离，零 AI、零 Key 回传。

指标口径与分母写死在 `repository.ai_call_log_summary()`（见 r51 TECHNICAL §3.4）；
路由只做窗口参数校验与 pydantic 投影，不在这里另算一套指标。
"""

from fastapi import APIRouter, Depends, Query

from app.core import repository
from app.deps import current_user
from app.schemas import EvalSummary

router = APIRouter(prefix="/api/eval", tags=["eval"], dependencies=[Depends(current_user)])


@router.get("/summary", response_model=EvalSummary, summary="模型调用质量摘要（成功率和延迟分位）")
def get_summary(days: int = Query(default=7, ge=1, le=90)) -> EvalSummary:
    return EvalSummary(**repository.ai_call_log_summary(days))
