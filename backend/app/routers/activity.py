"""r138 活跃日路由：`GET /api/activity/days?tz_offset=-480&limit=400`。

零 AI、零出网，只读本地三张表；按浏览器当前时区偏移折算日键，
供顶栏「连续学习」徽章使用（不替代 `/api/history` 的战绩列表）。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.deps import current_user
from app.schemas import ActivityDays
from app.services.activity import DEFAULT_DAY_LIMIT, MAX_DAY_LIMIT, activity_days

router = APIRouter(prefix="/api", tags=["activity"], dependencies=[Depends(current_user)])


@router.get(
    "/activity/days",
    response_model=ActivityDays,
    summary="活跃日（测评完成 / 演武作答 / 学堂阅读，按本机时区去重）",
)
def get_activity_days(
    tz_offset: Annotated[
        int,
        Query(
            ge=-840,
            le=840,
            description="浏览器 getTimezoneOffset()：UTC+8 传 -480；缺省 0 = UTC",
        ),
    ] = 0,
    limit: Annotated[
        int,
        Query(ge=1, le=MAX_DAY_LIMIT, description="返回最近几天的日键"),
    ] = DEFAULT_DAY_LIMIT,
) -> ActivityDays:
    """时区与条数都由 Query 校验；业务归一在 service，路由只做投影。"""
    return ActivityDays(**activity_days(tz_offset=tz_offset, limit=limit))
