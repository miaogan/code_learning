"""r102 任务进度 SSE：把上传页的「2 秒轮询」升级为服务端推送。

分工刻意清晰：
- **流只送事实**（`status` / `updated_at` / `error`）——**不送结果正文**。完成态的大对象
  （画像 payload、识别结果）仍走既有的单查端点，序列化口径只有一处，不因流式化多出第二份；
- 前端拿不到流（旧后端、代理缓冲、断网）时自动回落原轮询，功能不缺失；
- 流有界：心跳保活、客户端断连即退出、超过 `jobs_stream_max_s` 发 `timeout` 关闭。

用户隔离沿用仓储层：`get_*_job` 都带 `user_id` 条件，跨用户 job_id 一律视为不存在。
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Callable
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.core import repository
from app.core.config import get_settings
from app.core.errors import NOT_FOUND, VALIDATION_ERROR, AppError
from app.core.sse import SSE_HEADERS, client_gone, sse_event, sse_heartbeat
from app.deps import current_user

#: 画像任务的惰性清扫阈值：与 `routers/profile.py` 共用同一个常量（单源），
#: 流的读路径也要清扫——否则僵尸 running 任务会让流一直挂着等一个永远不会来的终态。
from app.routers.profile import _PROFILE_JOB_STALE_SECONDS

logger = logging.getLogger("app.jobs")

router = APIRouter(prefix="/api/jobs", tags=["jobs"], dependencies=[Depends(current_user)])

#: 终态：流推完这一帧就关闭。
TERMINAL_STATUSES = frozenset({"completed", "failed"})


def _profile_row(job_id: str) -> dict[str, Any] | None:
    repository.expire_stale_profile_jobs(_PROFILE_JOB_STALE_SECONDS)
    return repository.get_profile_job(job_id)


def _resume_row(job_id: str) -> dict[str, Any] | None:
    return repository.get_resume_job(job_id)


#: kind → 取行函数（闭集；新增任务类型只加一行）。
_GETTERS: dict[str, Callable[[str], dict[str, Any] | None]] = {
    "profile": _profile_row,
    "resume": _resume_row,
}


def _frame(row: dict[str, Any], job_id: str) -> dict[str, Any]:
    """流事件只送状态事实（结果正文仍走单查端点，序列化口径只有一处）。"""
    return {
        "job_id": job_id,
        "status": str(row.get("status") or ""),
        "updated_at": str(row.get("updated_at") or row.get("created_at") or ""),
        "error": str(row.get("error") or ""),
    }


async def _pump(kind: str, job_id: str, request: Request) -> AsyncIterator[str]:
    settings = get_settings()
    getter = _GETTERS[kind]
    poll_s = max(0.05, float(settings.jobs_stream_poll_s))
    beat_s = max(1, int(settings.jobs_stream_heartbeat_s))
    max_s = max(10, int(settings.jobs_stream_max_s))
    started = time.monotonic()
    next_beat = started + beat_s
    last: tuple[str, str] | None = None
    while True:
        row = getter(job_id)
        if row is None:
            yield sse_event("error", {"code": NOT_FOUND, "message": "后台任务已不存在"})
            return
        frame = _frame(row, job_id)
        marker = (frame["status"], frame["updated_at"])
        if marker != last:
            last = marker
            yield sse_event("status", frame)
            if frame["status"] in TERMINAL_STATUSES:
                yield sse_event("done", frame)
                return
        now = time.monotonic()
        if now >= next_beat:
            # 断连检测只在心跳节拍上做：`is_disconnected()` 在 TestClient 下会误报
            # （请求体读完后即报断开），逐帧查会让流在第一条帧之后就被掐断；
            # 生产环境真断开时 uvicorn 会取消任务，这里的检查是保底而非唯一手段。
            if await client_gone(request):
                logger.info("jobs.stream.client_gone kind=%s job_id=%s", kind, job_id)
                return
            yield sse_heartbeat()
            next_beat = now + beat_s
        if now - started >= max_s:
            yield sse_event("timeout", {"job_id": job_id, "message": "进度流超过时长上限，请改用轮询"})
            return
        await asyncio.sleep(poll_s)


@router.get(
    "/{kind}/{job_id}/stream",
    summary="后台任务进度流（SSE：status / done / error / timeout）",
)
async def stream_job(kind: str, job_id: str, request: Request) -> StreamingResponse:
    if kind not in _GETTERS:
        raise AppError(VALIDATION_ERROR, "不支持的任务类型：" + kind, retryable=False)
    row = _GETTERS[kind](job_id)
    if row is None:
        raise AppError(NOT_FOUND, "没有找到这个后台任务", status=404)
    return StreamingResponse(
        _pump(kind, job_id, request), media_type="text/event-stream", headers=SSE_HEADERS
    )
