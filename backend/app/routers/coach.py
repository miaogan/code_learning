"""r65 AI 学习教练端点：`POST /api/coach/advice`。

材料由前端组装（教程语料只在前端），服务端只做三件事：
清洗材料 → 约束提示词 → **引用白名单校验**（模型 href 必须逐字来自材料）。
业务主路径全在 `services/coach/`，路由只做空材料短路与依赖装配。
"""

from fastapi import APIRouter, Depends

from app.deps import CurrentUser, current_user
from app.schemas import CoachAdvice, CoachAdviceRequest
from app.services.ai import user_ai
from app.services.coach import policy
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
