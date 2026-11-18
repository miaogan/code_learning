"""历史记录路由（AC-10）：最近测评的成绩与短板数，`created_at` 倒序。

`GET /api/history?limit=10&page=1&kind=`（默认 10 条 / 第 1 页 / 不筛选）。
`limit` 是**每页条数**，`page` 从 1 起，响应带 `total`（命中总数）供前端算总页数。
r129 起补上删除能力：`DELETE /api/history/{run_id}` 删单场测评（面试 / 笔试皆可，
级联清时间线事件与该场次作答事件）；删除逻辑在 `services/interview/history.py`，
本层只做参数校验与错误映射。
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query

from app.deps import current_user
from app.schemas import HistoryList
from app.services.interview import history
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

#: 类型多选的缺省值（模块级常量，避免 ruff B008 把 `Query()` 调用当默认值）。
_NO_KINDS: tuple[str, ...] = ()


@router.get(
    "/history",
    response_model=HistoryList,
    summary="最近测评成绩（面试均分 / 笔试总分 / 短板数，AC-10）",
)
def get_history(
    limit: Annotated[
        int,
        Query(ge=MIN_LIMIT, le=MAX_LIMIT, description="每页条数（1..200，默认 10）"),
    ] = DEFAULT_LIMIT,
    page: Annotated[int, Query(ge=1, description="页码，从 1 起")] = 1,
    kind: Annotated[
        list[Literal["interview", "exam"]],
        Query(description="按类型多选（可重复传 kind=interview&kind=exam）；不传或全选 = 全部"),
    ] = _NO_KINDS,
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


@router.delete(
    "/history/{run_id}",
    status_code=204,
    summary="删除一场测评记录（面试 / 笔试；级联清时间线与该场次作答事件，r129）",
)
def delete_history_item(run_id: str) -> None:
    history.delete_item(run_id)
