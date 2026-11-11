"""历史记录路由（AC-10）：最近测评的成绩与短板数，`created_at` 倒序。

只有一条读路径：`GET /api/history?limit=10&page=1&kind=`（默认 10 条 / 第 1 页 / 不筛选）。
`limit` 是**每页条数**，`page` 从 1 起，响应带 `total`（命中总数）供前端算总页数。
无新建、无删除 —— 历史是 `runs` / `reports` 的投影，投影逻辑在 `services/interview/history.py`，
本层只做参数校验。
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query

from app.deps import current_user
from app.schemas import HistoryList
from app.services.interview.history import (
    DEFAULT_LIMIT,
    EXAM_KIND,
    INTERVIEW_KIND,
    MAX_LIMIT,
    MIN_LIMIT,
    kind_counts,
    list_history,
)

router = APIRouter(prefix="/api", tags=["history"], dependencies=[Depends(current_user)])


@router.get(
    "/history",
    response_model=HistoryList,
    summary="最近测评成绩（面试均分 / 笔试总分 / 短板数，AC-10）",
)
def get_history(
    limit: Annotated[
        int,
        Query(ge=MIN_LIMIT, le=MAX_LIMIT, description="每页条数（1..50，默认 10）"),
    ] = DEFAULT_LIMIT,
    page: Annotated[int, Query(ge=1, description="页码，从 1 起")] = 1,
    kind: Annotated[
        Literal["interview", "exam"] | None,
        Query(description="按类型筛选：interview / exam；省略则全部"),
    ] = None,
) -> HistoryList:
    """参数由 `Query` 校验，越界即 422 → 统一错误 envelope（路由内不写 SQL）。"""
    items, total = list_history(limit, page, kind)
    counts = kind_counts()
    return HistoryList(
        items=items,
        total=total,
        interview_total=counts[INTERVIEW_KIND],
        exam_total=counts[EXAM_KIND],
    )
