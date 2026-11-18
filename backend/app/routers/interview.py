"""模拟面试路由（r5）：开局 / 逐轮 / 提前结束 / 会话回溯四条路由。

- 开局 `POST /api/interviews` 只返回第 1 条发言（`InterviewRun{settings, question, total}`），
  8 题计划留在 `payload.plan`（AC-4：不预先铺开题目列表）。
- 逐轮 `POST /api/interviews/{run_id}/answers` 返回 `InterviewTurn`（`ScoreResult` 超集）：
  `score` / `comment` 与下一条发言同轮返回；失败一律 envelope 错误，**前端不得清空作答**。
- 提前结束 `POST /api/interviews/{run_id}/finish` 返回会话镜像：**不调用 AI**，因此不走
  heavy 能力闸门 —— 轻能力用户也能随时退出，未答题目不再计分。
- 回溯 `GET /api/interviews/{run_id}` 返回整场会话镜像（AC-9 刷新 / 重进恢复）。
- 分工：本层只做参数转发与错误映射，轮次编排 / 闸门 / 回写全在 `services.interview`。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.core.errors import GUARDRAIL_BLOCKED, AppError
from app.core.sse import SSE_HEADERS, sse_event
from app.deps import CurrentUser, current_user
from app.schemas import (
    AnswerRequest,
    InterviewCreateRequest,
    InterviewRun,
    InterviewSession,
    InterviewSessionSummary,
    InterviewTurn,
)
from app.services.ai import guardrails, user_ai
from app.services.interview.interview import (
    create_run as create_interview_run,
    finish_run as finish_interview_run,
    list_sessions as list_interview_sessions,
    load_session,
    score_answer as score_interview_answer,
    skip_question as skip_interview_question,
)

router = APIRouter(
    prefix="/api/interviews", tags=["interview"], dependencies=[Depends(current_user)]
)

#: r122：作答正文上限。面试作答通常几百字，6000 已远超实际需求 ——
#: `AnswerRequest.answer` 的 schema 不限长度，这里补一道兜底，避免单次请求把提示词撑爆。
_ANSWER_MAX_CHARS = 6000


def _guard_answer(raw: str) -> str:
    """作答正文过输入护栏：放行时返回归一化后的文本，命中则抛 422。"""
    checked = guardrails.guard_input(
        raw, surface="interview.answer", max_chars=_ANSWER_MAX_CHARS
    )
    if checked.blocked:
        raise AppError(GUARDRAIL_BLOCKED, checked.notice, status=422)
    return checked.text


def _guard_turn(turn: InterviewTurn) -> InterviewTurn:
    """回合输出过护栏：评语与下一条发言都是模型写的，可能复述作答里的手机号。"""
    guarded = guardrails.guard_output(turn.comment, surface="interview.answer")
    if guarded.blocked or guarded.changed:
        turn.comment = guarded.notice if guarded.blocked else guarded.text
    if turn.next_question is not None:
        prompt = guardrails.guard_output(turn.next_question.prompt, surface="interview.answer")
        if prompt.blocked or prompt.changed:
            turn.next_question.prompt = prompt.notice if prompt.blocked else prompt.text
    return turn


@router.get("", response_model=list[InterviewSessionSummary], summary="历史面试列表（含在途场次）")
def get_runs(limit: int = 10) -> list[InterviewSessionSummary]:
    return list_interview_sessions(limit)


@router.post("", response_model=InterviewRun, summary="补全设定并开局（只投放第 1 条发言）")
async def create_run(payload: InterviewCreateRequest, user: CurrentUser) -> InterviewRun:
    client = user_ai.client_for(user, "heavy")
    return await create_interview_run(payload.profile_id, payload.settings, client=client)


@router.post(
    "/{run_id}/answers",
    response_model=InterviewTurn,
    summary="提交当前发言作答，同轮返回评分与下一条发言",
)
async def submit_answer(
    run_id: str, payload: AnswerRequest, user: CurrentUser
) -> InterviewTurn:
    # r122：作答正文会原样进评分提示词，是注入的入口之一（且 schema 不限长度）。
    checked = _guard_answer(payload.answer)
    client = user_ai.client_for(user, "heavy")
    turn = await score_interview_answer(run_id, payload.question_id, checked, client=client)
    return _guard_turn(turn)


@router.post(
    "/{run_id}/answers/stream",
    summary="提交作答并以 SSE 推送回合（phase → turn → done；错误走 error 事件）",
)
async def submit_answer_stream(
    run_id: str, payload: AnswerRequest, user: CurrentUser
) -> StreamingResponse:
    """回合流（r102）：评分 + 出题是一次结构化补全，结果本就是 JSON，**不做逐字文本流**
    ——把契约拆成两跳模型调用只会让成本翻倍、结果还可能不一致。这里流的是**阶段事实**：
    评分开始 → 结果就绪 → 结束；前端据此把按钮态与 60s 等待变成有反馈的进度。

    业务口径与同步端点完全一致（同一条 `score_answer`，同一套错误映射）：
    失败在帧内以 `error` 事件返回，前端不得清空已写作答。
    """
    # r122：护栏在 `client_for` 之前 —— 被拦的请求不该扣掉一次内置 Key 配额。
    # 帧内报错而不是 HTTP 4xx：本端点的契约是「业务失败走 error 事件」，前端据此保留作答。
    checked = guardrails.guard_input(
        payload.answer, surface="interview.answer", max_chars=_ANSWER_MAX_CHARS
    )
    if checked.blocked:

        async def _blocked() -> AsyncIterator[str]:
            yield sse_event(
                "error",
                {
                    "code": GUARDRAIL_BLOCKED,
                    "message": checked.notice,
                    "retryable": False,
                },
            )

        return StreamingResponse(
            _blocked(), media_type="text/event-stream", headers=SSE_HEADERS
        )
    client = user_ai.client_for(user, "heavy")

    async def _gen():
        yield sse_event("phase", {"phase": "scoring", "message": "正在评分并生成下一条发言"})
        try:
            turn = _guard_turn(
                await score_interview_answer(
                    run_id, payload.question_id, checked.text, client=client
                )
            )
        except AppError as exc:
            yield sse_event(
                "error",
                {"code": exc.code, "message": exc.message, "retryable": exc.retryable},
            )
            return
        yield sse_event("phase", {"phase": "ready", "message": "评分完成"})
        yield sse_event("turn", turn.model_dump(mode="json"))
        yield sse_event(
            "done", {"run_id": run_id, "run_status": turn.run_status}
        )

    return StreamingResponse(_gen(), media_type="text/event-stream", headers=SSE_HEADERS)


@router.post(
    "/{run_id}/finish",
    response_model=InterviewSession,
    summary="提前结束本场面试（不调用 AI，未答题目不再计分）",
)
def finish_run(run_id: str) -> InterviewSession:
    return finish_interview_run(run_id)


@router.post(
    "/{run_id}/skip",
    response_model=InterviewSession,
    summary="跳过当前题目（不计分不调 AI，直接换下一道正题）",
)
def skip_run(run_id: str) -> InterviewSession:
    return skip_interview_question(run_id)


@router.get(
    "/{run_id}",
    response_model=InterviewSession,
    summary="读取整场会话（刷新 / 重进恢复，不重出题）",
)
def get_run(run_id: str) -> InterviewSession:
    return load_session(run_id)
