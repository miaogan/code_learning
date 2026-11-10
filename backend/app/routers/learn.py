"""学习进度与计划打卡路由（r61）：整份状态读写，两个资源各一对 GET / PUT。

写路径刻意做成「整份覆盖」而不是逐事件增量：阅读进度一次同步最多几十章、打卡最多几十条，
整份 PUT 让前端只需在本地状态变化后防抖调用一次，不必为每种事件维护一套幂等语义。
"""

from fastapi import APIRouter, Depends

from app.deps import current_user
from app.schemas import LearnProgress, PlanState, PlanStatePayload
from app.services import learn

router = APIRouter(prefix="/api", tags=["learn"], dependencies=[Depends(current_user)])


@router.get(
    "/learn/progress",
    response_model=LearnProgress,
    summary="阅读进度（章节已读小节 + 继续学习入口）",
)
def get_learn_progress() -> LearnProgress:
    return learn.read_progress()


@router.put(
    "/learn/progress",
    response_model=LearnProgress,
    summary="保存阅读进度（整份覆盖，返回落库结果）",
)
def put_learn_progress(payload: LearnProgress) -> LearnProgress:
    return learn.write_progress(payload)


@router.get(
    "/plans/{report_id}",
    response_model=PlanState,
    summary="7 天计划打卡状态（`updated_at` 为空串表示尚未同步过）",
)
def get_plan_state(report_id: str) -> PlanState:
    return learn.read_plan(report_id)


@router.put(
    "/plans/{report_id}",
    response_model=PlanState,
    summary="保存 7 天计划打卡状态（整份覆盖）",
)
def put_plan_state(report_id: str, payload: PlanStatePayload) -> PlanState:
    return learn.write_plan(report_id, payload)
