"""成长时间线路由（r3 AC-1）：`GET /api/timeline?limit=N`，`occurred_at` 倒序。

只有一条读路径 —— 时间线是 `timeline_events` 的投影：组装与对比在 `services/timeline.py`，
排序在 `repository.list_timeline_events`（唯一排序点），本层只做参数校验，不写 SQL、不排序。
"""

from typing import Annotated

from fastapi import APIRouter, Query

from ..schemas import TimelineEvent
from ..services.timeline import DEFAULT_LIMIT, MAX_LIMIT, MIN_LIMIT, list_timeline

router = APIRouter(prefix="/api", tags=["timeline"])


@router.get(
    "/timeline",
    response_model=list[TimelineEvent],
    summary="成长时间线（事件 + 指标快照 + 本次/上次对比，r3 AC-1/AC-2/AC-5）",
)
def get_timeline(
    limit: Annotated[
        int,
        Query(ge=MIN_LIMIT, le=MAX_LIMIT, description="返回条数（1..50，默认 20）"),
    ] = DEFAULT_LIMIT,
) -> list[TimelineEvent]:
    """`limit` 越界由 `Query(ge=1, le=50)` 拦下（422 → 统一错误 envelope）。"""
    return list_timeline(limit)
