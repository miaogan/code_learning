"""练习路由（r11 · TECHNICAL §5）：`/api/practice` 四端点，纯本地、零 AI。

分层与既有路由一致 —— **路由只做参数校验与错误映射**，业务全部在 `services/practice.py`：

- 请求体走 pydantic 模型（`PracticePaperRequest` / `PracticeAnswerRequest`），
  闭集越界由 FastAPI 统一映射既有 `VALIDATION_ERROR` envelope（422），不手写第二套校验；
- 服务层抛 `AppError`（400 未作答 / 非客观题、404 题目不存在），由 `main.py` 的全局处理器
  转成统一 envelope，**零新增错误码**；
- 响应模型 `Practice*` 保证题单/统计/错题本永不含 `answer`，答案只在 `/answer` 回显。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.deps import current_user
from app.schemas import (
    PracticeAnswerRequest,
    PracticeAnswerResult,
    PracticeDifficultyFilter,
    PracticeDirectionFilter,
    PracticeEssentialityFilter,
    PracticeLanguageFilter,
    PracticePaper,
    PracticePaperRequest,
    PracticeScope,
    PracticeStats,
    PracticeSubDirectionFilter,
    PracticeWrongBook,
)
from app.services.assessment import practice as practice_service

router = APIRouter(prefix="/api/practice", tags=["practice"], dependencies=[Depends(current_user)])

#: GET 端点的筛选默认值：模块级只读常量（避免把可变字面量写进函数默认值，B008/B006）。
#: 类型注解仍是 `list[...]`，FastAPI/pydantic 会在校验阶段把元组默认值归一成列表。
_ALL_CHOICES: tuple[str, ...] = ("all",)
_NO_SUB_DIRECTIONS: tuple[str, ...] = ()


@router.post("/paper", response_model=PracticePaper, summary="按筛选出一份练习题单（不含答案）")
def create_paper(payload: PracticePaperRequest) -> PracticePaper:
    return PracticePaper(
        **practice_service.build_paper(
            payload.language,
            payload.direction,
            payload.difficulty,
            payload.essentiality,
            payload.scope,
            payload.limit,
            payload.sub_direction,
        )
    )


@router.post("/answer", response_model=PracticeAnswerResult, summary="单题判分并写作答事件")
def submit_answer(payload: PracticeAnswerRequest) -> PracticeAnswerResult:
    return PracticeAnswerResult(
        **practice_service.submit_answer(
            payload.session_id, payload.question_id, payload.answer
        )
    )


@router.get("/stats", response_model=PracticeStats, summary="练习统计（命中/已练/错题）")
def get_stats(
    language: Annotated[list[PracticeLanguageFilter], Query()] = _ALL_CHOICES,
    direction: Annotated[list[PracticeDirectionFilter], Query()] = _ALL_CHOICES,
    difficulty: Annotated[list[PracticeDifficultyFilter], Query()] = _ALL_CHOICES,
    essentiality: Annotated[list[PracticeEssentialityFilter], Query()] = _ALL_CHOICES,
    scope: Annotated[list[PracticeScope], Query()] = _ALL_CHOICES,
    sub_direction: Annotated[list[PracticeSubDirectionFilter], Query()] = _NO_SUB_DIRECTIONS,
) -> PracticeStats:
    return PracticeStats(
        **practice_service.stats(language, direction, difficulty, essentiality, scope, sub_direction)
    )


@router.get("/wrong-book", response_model=PracticeWrongBook, summary="错题本（最近一次答错的题）")
def get_wrong_book(
    language: Annotated[list[PracticeLanguageFilter], Query()] = _ALL_CHOICES,
    limit: int = Query(default=20, ge=1, le=100, description="每页条数"),
    page: int = Query(default=1, ge=1, description="页码，从 1 起"),
) -> PracticeWrongBook:
    return PracticeWrongBook(**practice_service.wrong_book(language, limit, page))
