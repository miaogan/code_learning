"""历史记录路由（AC-10）：最近测评的成绩与短板数，`created_at` 倒序。

只有一条读路径：`GET /api/history?limit=10`（默认 10，1..50）。无新建、无删除 ——
历史是 `runs` / `reports` 的投影，投影逻辑在 `services/history.py`，本层只做参数校验。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from ..deps import current_user
from ..schemas import RunSummary
from ..services.history import DEFAULT_LIMIT, MAX_LIMIT, MIN_LIMIT, list_history

router = APIRouter(prefix="/api", tags=["history"], dependencies=[Depends(current_user)])


@router.get(
    "/history",
    response_model=list[RunSummary],
    summary="最近测评成绩（面试均分 / 笔试总分 / 短板数，AC-10）",
)
def get_history(
    limit: Annotated[
        int,
        Query(ge=MIN_LIMIT, le=MAX_LIMIT, description="返回条数（1..50，默认 10）"),
    ] = DEFAULT_LIMIT,
) -> list[RunSummary]:
    """`limit` 由 `Query(ge=1, le=50)` 校验，越界即 422 → 统一错误 envelope（路由内不写 SQL）。"""
    return list_history(limit)
