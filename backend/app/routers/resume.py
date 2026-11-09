"""简历上传（AC-1）+ 简历润色两端点（r3 AC-8/9/11/12）：校验 → 抽取 → 入库 → 元信息。

润色端点只做三件事：取正文 → 解析 `target_role`（body 优先、缺省取画像，**只用于本次调用**）→
调 `services/resume_polish` 组装响应。提示词、模型名、反幻觉校验、成稿拼装全部在 service，
本层零提示词、零出网客户端，也不写任何 SQL（`repository` 是唯一出口）。
"""

import asyncio
import hashlib
import logging
import time
import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, File, UploadFile

from app.core import repository
from app.core.config import get_settings
from app.core.context import get_current_user_id, set_current_user_id
from app.core.errors import (
    AI_UNAVAILABLE,
    EMPTY_FILE,
    INTERNAL_ERROR,
    NOT_FOUND,
    VALIDATION_ERROR,
    AppError,
)
from app.deps import CurrentUser, current_user
from app.schemas import (
    PolishFullRequest,
    PolishFullResponse,
    PolishRequest,
    PolishResponse,
    Profile,
    ResumeJobStarted,
    ResumeJobStatus,
    ResumeMeta,
)
from app.services.ai import user_ai
from app.services.ai.ai import AIClient
from app.services.resume import image_resume, resume_polish
from app.services.resume.parser import ensure_upload_size, max_upload_bytes, parse_resume

router = APIRouter(prefix="/api/resumes", tags=["resume"], dependencies=[Depends(current_user)])
#: r42 任务查询端点独立前缀：读写都在本文件，但不属于「上传简历」这组资源路径。
jobs_router = APIRouter(
    prefix="/api/resume-jobs", tags=["resume"], dependencies=[Depends(current_user)]
)

logger = logging.getLogger("app.resume_job")

#: 临时目标岗位的长度上限（超过按参数不合法拒绝，避免把超长串带进提示词）。
MAX_TARGET_ROLE_CHARS = 40


@router.post("", response_model=ResumeMeta, summary="上传简历并抽取正文（PDF / DOCX / TXT）")
async def upload_resume(
    file: Annotated[UploadFile, File(description="简历文件（PDF / DOCX / TXT，体积上限可配置）")],
) -> ResumeMeta:
    # 只多读 1 字节用于「是否超限」判断；体积校验的唯一出口在 services.parser。
    raw = await file.read(max_upload_bytes() + 1)
    parsed = parse_resume(file.filename or "", raw)
    resume_id = uuid.uuid4().hex
    file_name = file.filename or "resume"
    suffix = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
    source_type: Literal["pdf", "docx", "txt"] = (
        "docx" if suffix == "docx" else "txt" if suffix == "txt" else "pdf"
    )
    meta = ResumeMeta(
        resume_id=resume_id,
        file_name=file_name,
        chars=parsed.chars,
        sections=parsed.sections,
        source_type=source_type,
    )
    repository.insert_document(
        meta,
        parsed.text,
        mime=file.content_type or "application/octet-stream",
    )
    return meta


async def _read_images(files: list[UploadFile]) -> tuple[list[bytes], list[str]]:
    """数量 / 体积 / 格式三件校验的唯一出口（同步与异步图片入口共用）。"""
    if not files:
        raise AppError(VALIDATION_ERROR, "请至少上传 1 张图片", status=400)
    if len(files) > image_resume.MAX_IMAGE_COUNT:
        raise AppError(
            VALIDATION_ERROR,
            f"一次最多上传 {image_resume.MAX_IMAGE_COUNT} 张图片",
            status=400,
        )
    limit = max_upload_bytes()
    images: list[bytes] = []
    mimes: list[str] = []
    total = 0
    for upload in files:
        raw = await upload.read(limit + 1)
        if not raw:
            raise AppError(EMPTY_FILE, "图片内容为空，请重新选择", status=400)
        # 单张与合计的体积阈值统一由 services.parser 判断（r43，文案各自不同）。
        ensure_upload_size(len(raw), message="单张图片超过 {mb}MB，请压缩后重试")
        total += len(raw)
        ensure_upload_size(total, message="图片总大小超过 {mb}MB，请减少张数或压缩后重试")
        # HEIC 在这里给专用中文提示（复用 UNSUPPORTED_TYPE，不新增错误码）。
        mimes.append(image_resume.sniff_or_raise(raw))
        images.append(raw)
    return images, mimes


def _image_file_name(files: list[UploadFile]) -> str:
    if len(files) == 1:
        return files[0].filename or "resume.jpg"
    return f"照片简历（{len(files)} 张）"


def _image_meta(file_name: str, parsed_chars: int, parsed_sections: int, count: int) -> ResumeMeta:
    return ResumeMeta(
        resume_id=uuid.uuid4().hex,
        file_name=file_name,
        chars=parsed_chars,
        sections=parsed_sections,
        source_type="image",
        image_count=count,
    )


@router.post(
    "/images",
    response_model=ResumeMeta,
    summary="上传简历照片 / 截图并抽取正文（1–3 张，JPG / PNG / WebP）",
)
async def upload_resume_images(
    files: Annotated[list[UploadFile], File(description="简历图片，按顺序拼成一份简历（最多 3 张）")],
) -> ResumeMeta:
    """同步版（r41 既有契约，保留不动）：手机接口弱网时长等待仍可能断，新客户端应走 `/images/async`。

    多图共用同一个 `resume_id`；图片字节只在内存里流转，`repository` 只收到抽取正文。
    """
    images, mimes = await _read_images(files)
    parsed = await image_resume.extract_resume_text(images)
    file_name = _image_file_name(files)
    meta = _image_meta(file_name, parsed.chars, parsed.sections, len(images))
    repository.insert_document(meta, parsed.text, mime=mimes[0])
    return meta


# --- 图片识别异步任务（r42）---------------------------------------------------

#: 运行中的后台任务引用（原因同 profile.py：不保存引用可能被 GC 回收）。
_RESUME_PENDING_JOBS: set[asyncio.Task[None]] = set()

#: 无进展阈值：任务每识别完一页写一次心跳，10 分钟没有任何进展才判死
#: （3 张图合法总耗时可达数十分钟，不能用总耗时衡量）。
_RESUME_JOB_STALE_SECONDS = 10 * 60

#: 单任务硬上限：3 张 × 单页 AI 超时（统一 600s）+ 余量；超时由任务体落 failed。
_RESUME_JOB_DEADLINE_S = image_resume.MAX_IMAGE_COUNT * 600 + 300


def _resume_job_error_message(exc: Exception) -> str:
    if isinstance(exc, AppError):
        return exc.message
    return "图片识别失败，请稍后重试"


async def _run_resume_job(
    job_id: str,
    file_name: str,
    image_count: int,
    images: list[bytes],
    mime_first: str,
    client: AIClient,
    user_id: str,
) -> None:
    """后台识别：逐页抽取（每页落心跳）→ 入库 → 写终态；任何失败都落中文原因。"""
    set_current_user_id(user_id)
    started = time.perf_counter()
    logger.info("resume_job.start job_id=%s images=%s user_id=%s", job_id, image_count, user_id)
    try:
        parsed = await asyncio.wait_for(
            image_resume.extract_resume_text(
                images,
                client,
                on_page_done=lambda _index: repository.touch_resume_job(
                    job_id, user_id=user_id
                ),
            ),
            timeout=_RESUME_JOB_DEADLINE_S,
        )
        meta = _image_meta(file_name, parsed.chars, parsed.sections, image_count)
        repository.insert_document(meta, parsed.text, mime=mime_first)
        repository.finish_resume_job(job_id, meta.model_dump_json(), user_id=user_id)
        logger.info(
            "resume_job.finish job_id=%s elapsed_ms=%s chars=%s",
            job_id,
            int((time.perf_counter() - started) * 1000),
            parsed.chars,
        )
    except TimeoutError:
        repository.fail_resume_job(job_id, "图片识别超时，请稍后重试", user_id=user_id)
        logger.warning("resume_job.timeout job_id=%s", job_id)
    except Exception as exc:  # noqa: BLE001 - 任何失败都要落库可见
        repository.fail_resume_job(job_id, _resume_job_error_message(exc), user_id=user_id)
        if isinstance(exc, AppError):
            logger.warning(
                "resume_job.failed job_id=%s code=%s elapsed_ms=%s message=%s",
                job_id,
                exc.code,
                int((time.perf_counter() - started) * 1000),
                exc.message,
            )
        else:
            logger.exception(
                "resume_job.failed job_id=%s elapsed_ms=%s",
                job_id,
                int((time.perf_counter() - started) * 1000),
            )


@router.post(
    "/images/async",
    response_model=ResumeJobStarted,
    summary="上传简历照片并后台识别（幂等：同一批图片在途时复用同一任务）",
)
async def upload_resume_images_async(
    files: Annotated[list[UploadFile], File(description="简历图片，按顺序拼成一份简历（最多 3 张）")],
) -> ResumeJobStarted:
    images, mimes = await _read_images(files)
    runtime = get_settings().resolve_vision()
    if not runtime.ready:
        raise AppError(AI_UNAVAILABLE, runtime.reason, status=503)

    content_hash = hashlib.sha256(b"".join(images)).hexdigest()
    repository.expire_stale_resume_jobs(_RESUME_JOB_STALE_SECONDS)
    existing = repository.find_running_resume_job(content_hash)
    if existing is not None:
        return ResumeJobStarted(job_id=str(existing["job_id"]))

    file_name = _image_file_name(files)
    for _attempt in range(2):
        job_id = uuid.uuid4().hex
        if repository.insert_resume_job(job_id, file_name, len(images), content_hash):
            task = asyncio.create_task(
                _run_resume_job(
                    job_id,
                    file_name,
                    len(images),
                    images,
                    mimes[0],
                    AIClient(runtime=runtime),
                    get_current_user_id(),
                )
            )
            _RESUME_PENDING_JOBS.add(task)
            task.add_done_callback(_RESUME_PENDING_JOBS.discard)
            logger.info("resume_job.accepted job_id=%s images=%s", job_id, len(images))
            return ResumeJobStarted(job_id=job_id)
        # 撞唯一约束：要么是并发受理（复用同一任务），要么是旧任务刚进终态（重试一次）。
        existing = repository.find_running_resume_job(content_hash)
        if existing is not None:
            return ResumeJobStarted(job_id=str(existing["job_id"]))
    raise AppError(INTERNAL_ERROR, "识别任务受理冲突，请稍后重试", status=500, retryable=True)


def _resume_job_status(row: dict[str, Any]) -> ResumeJobStatus:
    result_json = str(row.get("result") or "")
    result = ResumeMeta.model_validate_json(result_json) if result_json.strip() else None
    return ResumeJobStatus(
        job_id=str(row["job_id"]),
        file_name=str(row["file_name"]),
        image_count=int(row["image_count"]),
        status=str(row["status"]),
        error=str(row["error"]),
        result=result,
        created_at=str(row["created_at"]),
    )


@jobs_router.get(
    "/latest",
    response_model=ResumeJobStatus,
    summary="最近一次图片识别任务（回上传页自动接上进度用）",
)
def read_latest_resume_job() -> ResumeJobStatus:
    repository.expire_stale_resume_jobs(_RESUME_JOB_STALE_SECONDS)
    row = repository.latest_resume_job()
    if row is None:
        raise AppError(NOT_FOUND, "还没有图片识别任务", status=404)
    return _resume_job_status(row)


@jobs_router.get("/{job_id}", response_model=ResumeJobStatus, summary="查询图片识别任务状态")
def read_resume_job(job_id: str) -> ResumeJobStatus:
    repository.expire_stale_resume_jobs(_RESUME_JOB_STALE_SECONDS)
    row = repository.get_resume_job(job_id)
    if row is None:
        raise AppError(NOT_FOUND, "没有找到这个图片识别任务", status=404)
    return _resume_job_status(row)


# --- 润色（r3 AC-8 ~ AC-13）---------------------------------------------------


def _load_resume(resume_id: str) -> tuple[str, str]:
    """取简历正文与源文件名；不存在 / 正文为空按既有错误码拒绝（不新增错误码）。

    一次 `repository.get_document` 同时拿到 `text` 与 `file_name`，润色响应与前端导出命名
    共用同一条读路径，不重复查库。
    """
    document = repository.get_document(resume_id)
    if document is None:
        raise AppError(NOT_FOUND, "没有找到这份简历，请重新上传后再润色", status=404)
    text = str(document.get("text") or "")
    file_name = str(document.get("file_name") or "")
    if not text.strip():
        raise AppError(
            VALIDATION_ERROR,
            "这份简历没有可润色的正文，请换一份可复制文本的文件重试",
            status=400,
        )
    return text, file_name


def _resolve_target_role(payload_role: str | None, profile: Profile | None) -> str | None:
    """body 优先、缺省取画像；**只用于本次调用，不写库**（AC-12）。"""
    role = (payload_role or "").strip()
    if role:
        if len(role) > MAX_TARGET_ROLE_CHARS:
            raise AppError(
                VALIDATION_ERROR,
                f"目标岗位最多 {MAX_TARGET_ROLE_CHARS} 字，请缩短后重试",
                status=400,
            )
        return role
    inherited = (profile.target_role or "").strip() if profile is not None else ""
    return inherited or None


@router.post(
    "/{resume_id}/polish",
    response_model=PolishResponse,
    summary="按简历正文生成逐条润色建议（不落库）",
)
async def polish_resume(
    resume_id: str,
    user: CurrentUser,
    payload: PolishRequest | None = None,
) -> PolishResponse:
    text, file_name = _load_resume(resume_id)
    profile = repository.latest_profile()
    target_role = _resolve_target_role(
        payload.target_role if payload is not None else None, profile
    )

    client = user_ai.client_for(user, "light")
    suggestions = await resume_polish.build_suggestions(
        text, profile, target_role, client=client
    )
    kept, dropped = resume_polish.validate_suggestions(
        suggestions, text, profile, target_role=target_role
    )
    polish_id = resume_polish.remember_suggestions(resume_id, target_role, kept, dropped)
    return PolishResponse(
        polish_id=polish_id,
        resume_id=resume_id,
        target_role=target_role,
        resume_text=text,
        file_name=file_name,
        suggestions=kept,
        dropped_count=dropped,
        insufficient_reason=resume_polish.insufficient_reason(kept),
    )


@router.post(
    "/{resume_id}/polish/full",
    response_model=PolishFullResponse,
    summary="组装润色成稿（同一份建议集只调一次模型）",
)
async def polish_full(
    resume_id: str,
    user: CurrentUser,
    payload: PolishFullRequest | None = None,
) -> PolishFullResponse:
    text, _ = _load_resume(resume_id)
    profile = repository.latest_profile()
    request = payload or PolishFullRequest()
    requested_role = (request.target_role or "").strip() or None

    cached = resume_polish.recall_suggestions(request.polish_id) if request.polish_id else None
    # 命中缓存的前提是同一次简历 + 同一个目标岗位；换岗位是「临时重跑」，如实标 `regenerated`。
    reused = cached is not None and cached.resume_id == resume_id and (
        requested_role is None or requested_role == cached.target_role
    )
    if reused and cached is not None:
        suggestions = cached.suggestions
        dropped = cached.dropped_count
        target_role = cached.target_role
        polish_id = cached.polish_id
        regenerated = False
    else:
        target_role = _resolve_target_role(requested_role, profile)
        # 只有真正调模型时才过重活闸门：命中缓存复用建议集不需要 AI，也不消耗配额。
        client = user_ai.client_for(user, "heavy")
        built = await resume_polish.build_suggestions(
            text, profile, target_role, client=client
        )
        suggestions, dropped = resume_polish.validate_suggestions(
            built, text, profile, target_role=target_role
        )
        polish_id = resume_polish.remember_suggestions(
            resume_id, target_role, suggestions, dropped
        )
        regenerated = True

    markdown = resume_polish.compose_full(
        text,
        suggestions,
        request.suggestion_ids,
        target_role=target_role,
        dropped_count=dropped,
    )
    return PolishFullResponse(
        id=polish_id,
        markdown=markdown,
        dropped_count=dropped,
        regenerated=regenerated,
    )
