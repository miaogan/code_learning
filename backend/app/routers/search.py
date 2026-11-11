"""r51 题目全文检索：FTS5 trigram 优先，环境不支持时由数据层降级为 LIKE。

- 响应**永不含 answer**（与练习 / 笔试同一答案口径）；
- 方向 / 子方向闭集外脏值静默忽略，不新增错误码、不造第二套 422；
- 方向是多选：去重后按 `IN (...)` 过滤，空列表等价于不过滤；
- 业务全在 `repository.search_questions()`，路由只做归一与模型投影。
"""

from fastapi import APIRouter, Depends

from app.core import repository
from app.deps import current_user
from app.schemas import QuestionSearchRequest, QuestionSearchResponse
from app.services.report import rules

router = APIRouter(prefix="/api/search", tags=["search"], dependencies=[Depends(current_user)])


@router.post("/questions", response_model=QuestionSearchResponse, summary="按关键词检索题库")
def search_questions(payload: QuestionSearchRequest) -> QuestionSearchResponse:
    directions = list(
        dict.fromkeys(direction for direction in payload.direction if direction in rules.DIRECTIONS)
    )
    sub_direction = (
        payload.sub_direction
        if any(
            rules.is_valid_sub_direction(direction, payload.sub_direction)
            for direction in directions
        )
        else ""
    )
    return QuestionSearchResponse(
        **repository.search_questions(
            payload.query, directions, sub_direction, payload.limit, payload.page
        )
    )
