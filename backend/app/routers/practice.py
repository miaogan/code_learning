"""练习路由（r11 · TECHNICAL §5）：`/api/practice` 四端点，纯本地、零 AI。

分层与既有路由一致 —— **路由只做参数校验与错误映射**，业务全部在 `services/practice.py`：

- 请求体走 pydantic 模型（`PracticePaperRequest` / `PracticeAnswerRequest`），
  闭集越界由 FastAPI 统一映射既有 `VALIDATION_ERROR` envelope（422），不手写第二套校验；
- 服务层抛 `AppError`（400 未作答 / 非客观题、404 题目不存在），由 `main.py` 的全局处理器
  转成统一 envelope，**零新增错误码**；
- 响应模型 `Practice*` 保证题单/统计/错题本永不含 `answer`，答案只在 `/answer` 回显。
"""

from fastapi import APIRouter

from ..schemas import (
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
    PracticeWrongBook,
)
from ..services import practice as practice_service

router = APIRouter(prefix="/api/practice", tags=["practice"])


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
    language: PracticeLanguageFilter = "all",
    direction: PracticeDirectionFilter = "all",
    difficulty: PracticeDifficultyFilter = "all",
    essentiality: PracticeEssentialityFilter = "all",
    scope: PracticeScope = "all",
) -> PracticeStats:
    return PracticeStats(
        **practice_service.stats(language, direction, difficulty, essentiality, scope)
    )


@router.get("/wrong-book", response_model=PracticeWrongBook, summary="错题本（最近一次答错的题）")
def get_wrong_book(language: PracticeLanguageFilter = "all") -> PracticeWrongBook:
    return PracticeWrongBook(**practice_service.wrong_book(language))
