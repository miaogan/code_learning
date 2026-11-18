"""镜试路由（r125）：推荐题 / 一次自问复盘 / 复盘列表三条路由。

- `POST /api/mirror/suggestions`：依据简历推荐自查问题（quote 必须能在原文命中）。
- `POST /api/mirror/ask`：一次完整复盘（参考答案 / 答题理由 / 题目水准 / 追问 +
  简历证据 + 缺失信息），结果落库可刷新恢复。
- `GET /api/mirror/cards`：当前账号最近的复盘列表。
- 分工：本层只做护栏、鉴权与参数转发；编排、证据闸门、数字闸门全在 `services.mirror`。
- 与 `/api/interviews` 的边界：不创建场次、不评分、不写成长时间线。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.errors import GUARDRAIL_BLOCKED, AppError
from app.deps import CurrentUser, current_user
from app.schemas import (
    ClearResult,
    MirrorAskRequest,
    MirrorCard,
    MirrorCardList,
    MirrorSuggestions,
    MirrorSuggestionsRequest,
)
from app.services.ai import guardrails, user_ai
from app.services.mirror import mirror as mirror_service

router = APIRouter(prefix="/api/mirror", tags=["mirror"], dependencies=[Depends(current_user)])

#: 自拟问题会进复盘提示词，是注入入口之一；schema 已限 1000，这里再统一护栏口径。
_QUESTION_MAX_CHARS = 1000


@router.post("/suggestions", response_model=MirrorSuggestions, summary="依据简历推荐自查问题")
async def suggest(payload: MirrorSuggestionsRequest, user: CurrentUser) -> MirrorSuggestions:
    client = user_ai.client_for(user, "heavy")
    return await mirror_service.suggest_questions(payload.resume_id, payload.count, client=client)


@router.post("/ask", response_model=MirrorCard, summary="一次自问复盘（自定义问题或 AI 推荐题）")
async def ask(payload: MirrorAskRequest, user: CurrentUser) -> MirrorCard:
    # r122 口径：护栏在 `client_for` 之前 —— 被拦的请求不扣内置 Key 配额。
    asked = (payload.question or "").strip()
    if asked:
        checked = guardrails.guard_input(
            asked, surface="mirror.question", max_chars=_QUESTION_MAX_CHARS
        )
        if checked.blocked:
            raise AppError(GUARDRAIL_BLOCKED, checked.notice, status=422)
    client = user_ai.client_for(user, "heavy")
    source = "custom" if asked else "recommended"
    return await mirror_service.ask(payload.resume_id, asked, source, client=client)


@router.get("/cards", response_model=MirrorCardList, summary="当前账号最近的复盘列表（刷新恢复）")
def cards(limit: int = 50) -> MirrorCardList:
    rows = mirror_service.list_cards(limit)
    return MirrorCardList(
        items=[mirror_service.card_from_row(row) for row in rows]
    )


@router.delete("/cards/{card_id}", status_code=204, summary="删除一条复盘（r129）")
def delete_card(card_id: str) -> None:
    mirror_service.delete_card(card_id)


@router.delete("/cards", response_model=ClearResult, summary="清空全部复盘（r129）")
def clear_cards() -> ClearResult:
    return ClearResult(deleted=mirror_service.clear_cards())
