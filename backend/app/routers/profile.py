"""画像路由（AC-2）：AI 生成 → 读取最新 → 行内编辑（PATCH 响应即唯一真值）。

- 生成走 body-less POST（`/api/resumes/{resume_id}/profile`），不接收任何 query 参数。
- 编辑走 PATCH：只覆盖请求体里**出现过且非 null**的字段，其余维度原样保留。
- r3 起 POST 是合并入口：响应 `ProfileWithMerge`（`merge_summary` 只此一次）；
  读取接口 `GET /api/profiles/latest` 的**持久契约不扩**——没有 `merge_summary`，
  但 `source_quotes` / `status` 属于 r3 的 `Profile` 本体扩展，读回同样带出（DESIGN §7-1）。
- SQL 一律走 `repository`（唯一 SQL 出口），本层只做参数与错误映射。
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends

from app.core import repository
from app.core.context import set_current_user_id
from app.core.errors import INTERNAL_ERROR, NOT_FOUND, AppError
from app.deps import CurrentUser, current_user
from app.schemas import (
    Profile,
    ProfileJobStarted,
    ProfileJobStatus,
    ProfilePatch,
    ProfileWithMerge,
)
from app.services.ai import user_ai
from app.services.ai.ai import AIClient
from app.services.profile.profile import generate_profile
from app.services.profile.profile_merge import backfill_evidence

router = APIRouter(prefix="/api", tags=["profile"], dependencies=[Depends(current_user)])

logger = logging.getLogger("app.profile_job")


def _document_meta(document_id: str) -> dict[str, Any]:
    """读来源简历的元信息（文件名 / 抓取时间），供合并摘要与证据链的「来源 · 日期」使用。

    `repository.get_document` 尚未落地时返回空表：元信息缺失只影响展示措辞，
    不影响合并语义与证据的逐字命中口径，因此不阻断画像生成。
    """
    reader = getattr(repository, "get_document", None)
    if not callable(reader):
        return {}
    document = reader(document_id)
    return document if isinstance(document, dict) else {}


@router.get("/profiles/latest", response_model=Profile, summary="读取最近一次画像")
def read_latest_profile() -> Profile:
    profile = repository.latest_profile()
    if profile is None:
        raise AppError(NOT_FOUND, "还没有画像，请先上传简历", status=404)
    # 兼容读取：让读回条目的形状与 POST 合并结果一致（证据折叠 / 历史分组要用到）。
    return backfill_evidence(profile)


@router.post(
    "/resumes/{resume_id}/profile",
    response_model=ProfileWithMerge,
    summary="依据简历生成或合并画像",
)
async def create_profile(resume_id: str, user: CurrentUser) -> ProfileWithMerge:
    text = repository.get_document_text(resume_id)
    if text is None:
        raise AppError(NOT_FOUND, "没有找到这份简历，请重新上传后再生成画像", status=404)
    meta = _document_meta(resume_id)
    client = user_ai.client_for(user, "light")
    return await generate_profile(
        resume_id,
        text,
        file_name=str(meta.get("file_name") or ""),
        captured_at=str(meta.get("created_at") or ""),
        client=client,
    )


# --- 异步画像任务（r30）-------------------------------------------------------

#: 运行中的后台任务引用：asyncio 文档要求任务创建后必须保存引用，
#: 否则任务可能被垃圾回收中途回收（终态不落库、轮询永远 running）。
_PENDING_JOBS: set[asyncio.Task[None]] = set()

#: running 任务行的停滞阈值（秒）：生成常态数十秒，但统一 AI 超时 600s 且允许重试一次，
#: 合法耗时上限约 20 分钟 —— r30 的 10 分钟会把合法长任务误判死（r42 调整为 30 分钟）。
#: 进程中断（服务重启 / 任务被回收）的行在读路径上惰性标记 failed，前端不会无限轮询。
_PROFILE_JOB_STALE_SECONDS = 30 * 60

#: 单任务硬上限（秒）：用 `asyncio.wait_for` 兜住「AI 客户端自身超时没生效」的挂死场景，
#: 超时由任务体落 failed + 中文原因，绝不留永远「进行中」的行。
_PROFILE_JOB_DEADLINE_S = 25 * 60


def _job_error_message(exc: Exception) -> str:
    """后台任务的失败原因：业务异常直接用中文 message，其余一律收敛成通用提示。

    任务在事件循环里独立跑，异常不会再经过全局错误处理器 —— 不在这里兜住，
    任务就会无声消失，前端轮询永远停在 running。
    """
    if isinstance(exc, AppError):
        return exc.message
    return "画像生成失败，请稍后重试"


async def _run_profile_job(
    job_id: str,
    resume_id: str,
    text: str,
    meta: dict[str, Any],
    client: AIClient,
    user_id: str,
) -> None:
    """后台任务体：成功落 `ProfileWithMerge` JSON，失败落中文原因 —— 两种终态都必须可见。"""
    set_current_user_id(user_id)
    started = time.perf_counter()
    # 任务继承了发起请求的 trace id（asyncio.create_task 复制上下文），日志里的 request_id 可回连到那次 POST。
    logger.info(
        "profile_job.start job_id=%s resume_id=%s chars=%s user_id=%s",
        job_id,
        resume_id,
        len(text),
        user_id,
    )
    try:
        result = await asyncio.wait_for(
            generate_profile(
                resume_id,
                text,
                file_name=str(meta.get("file_name") or ""),
                captured_at=str(meta.get("created_at") or ""),
                client=client,
            ),
            timeout=_PROFILE_JOB_DEADLINE_S,
        )
        repository.finish_profile_job(job_id, result.model_dump_json(), user_id=user_id)
        logger.info(
            "profile_job.finish job_id=%s resume_id=%s elapsed_ms=%s",
            job_id,
            resume_id,
            int((time.perf_counter() - started) * 1000),
        )
    except TimeoutError:
        repository.fail_profile_job(
            job_id, "画像生成超时，请重新生成（稍后重试通常即可）", user_id=user_id
        )
        logger.warning("profile_job.timeout job_id=%s resume_id=%s", job_id, resume_id)
    except Exception as exc:  # noqa: BLE001 - 任何失败都要落库可见，见 _job_error_message
        repository.fail_profile_job(job_id, _job_error_message(exc), user_id=user_id)
        if isinstance(exc, AppError):
            logger.warning(
                "profile_job.failed job_id=%s resume_id=%s code=%s elapsed_ms=%s message=%s",
                job_id,
                resume_id,
                exc.code,
                int((time.perf_counter() - started) * 1000),
                exc.message,
            )
        else:
            # 非业务异常才带堆栈（业务异常的 message 是给用户看的中文，堆栈无意义）。
            logger.exception(
                "profile_job.failed job_id=%s resume_id=%s elapsed_ms=%s",
                job_id,
                resume_id,
                int((time.perf_counter() - started) * 1000),
            )


@router.post(
    "/resumes/{resume_id}/profile/async",
    response_model=ProfileJobStarted,
    summary="依据简历生成或合并画像（后台任务，凭 job_id 轮询）",
)
async def create_profile_async(resume_id: str, user: CurrentUser) -> ProfileJobStarted:
    text = repository.get_document_text(resume_id)
    if text is None:
        raise AppError(NOT_FOUND, "没有找到这份简历，请重新上传后再生成画像", status=404)
    meta = _document_meta(resume_id)
    stats = repository.get_document_stats(resume_id) or {}
    client = user_ai.client_for(user, "light")

    # r42 幂等：同一简历已有在途任务时直接复用，不产生重复任务（部分唯一索引兜并发）。
    repository.expire_stale_profile_jobs(_PROFILE_JOB_STALE_SECONDS)
    existing = repository.find_running_profile_job(resume_id)
    if existing is not None:
        return ProfileJobStarted(job_id=str(existing["job_id"]))

    file_name = str(stats.get("file_name") or meta.get("file_name") or "")
    chars = int(stats.get("chars") or 0)
    sections = int(stats.get("sections") or 0)
    for _attempt in range(2):
        job_id = uuid.uuid4().hex
        if repository.insert_profile_job(job_id, resume_id, file_name=file_name,
                                         chars=chars, sections=sections):
            # Task 会拷贝请求上下文，但任务体里仍显式 set_current_user_id 兜底（仓储层写状态用）。
            task = asyncio.create_task(
                _run_profile_job(job_id, resume_id, text, meta, client, user["id"])
            )
            _PENDING_JOBS.add(task)
            task.add_done_callback(_PENDING_JOBS.discard)
            logger.info("profile_job.accepted job_id=%s resume_id=%s", job_id, resume_id)
            return ProfileJobStarted(job_id=job_id)
        # 撞唯一约束：并发受理复用同一任务；旧任务刚终态则换 id 再试一次。
        existing = repository.find_running_profile_job(resume_id)
        if existing is not None:
            return ProfileJobStarted(job_id=str(existing["job_id"]))
    raise AppError(INTERNAL_ERROR, "画像任务受理冲突，请稍后重试", status=500, retryable=True)


def _job_status_of(row: dict[str, Any]) -> ProfileJobStatus:
    result_json = str(row.get("result") or "")
    result = (
        ProfileWithMerge.model_validate_json(result_json) if result_json.strip() else None
    )
    return ProfileJobStatus(
        job_id=str(row["job_id"]),
        document_id=str(row["document_id"]),
        file_name=str(row["file_name"]),
        chars=int(row["chars"]),
        sections=int(row["sections"]),
        status=str(row["status"]),
        error=str(row["error"]),
        result=result,
        created_at=str(row["created_at"]),
    )


@router.get(
    "/profile-jobs/latest",
    response_model=ProfileJobStatus,
    summary="最近一次画像生成任务（回上传页自动接上进度用）",
)
def read_latest_profile_job() -> ProfileJobStatus:
    repository.expire_stale_profile_jobs(_PROFILE_JOB_STALE_SECONDS)
    row = repository.latest_profile_job()
    if row is None:
        raise AppError(NOT_FOUND, "还没有画像生成任务", status=404)
    return _job_status_of(row)


@router.get(
    "/profile-jobs/{job_id}",
    response_model=ProfileJobStatus,
    summary="查询画像生成任务状态",
)
def read_profile_job(job_id: str) -> ProfileJobStatus:
    repository.expire_stale_profile_jobs(_PROFILE_JOB_STALE_SECONDS)
    row = repository.get_profile_job(job_id)
    if row is None:
        raise AppError(NOT_FOUND, "没有找到这个画像生成任务", status=404)
    return _job_status_of(row)


@router.patch("/profiles/{profile_id}", response_model=Profile, summary="编辑画像条目")
def update_profile(profile_id: str, patch: ProfilePatch) -> Profile:
    profile = repository.get_profile(profile_id)
    if profile is None:
        raise AppError(NOT_FOUND, "没有找到这份画像，请先生成画像", status=404)

    # 显式传 null 视为「不改这一维」，避免前端把整份草稿回传时抹掉其它维度。
    fields = patch.model_dump(exclude_unset=True)
    changes = {name: value for name, value in fields.items() if value is not None}
    # 基底走兼容读取：未改动的条目带着证据链/历史标记一起回写，PATCH 不会把它抹平。
    base = backfill_evidence(profile)
    updated = Profile.model_validate(
        {
            **base.model_dump(),
            **changes,
            "updated_at": datetime.now(UTC).isoformat(),
        }
    )
    repository.save_profile(updated)
    return updated
