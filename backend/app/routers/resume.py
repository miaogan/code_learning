"""简历上传（AC-1）+ 简历润色两端点（r3 AC-8/9/11/12）：校验 → 抽取 → 入库 → 元信息。

润色端点只做三件事：取正文 → 解析 `target_role`（body 优先、缺省取画像，**只用于本次调用**）→
调 `services/resume_polish` 组装响应。提示词、模型名、反幻觉校验、成稿拼装全部在 service，
本层零提示词、零出网客户端，也不写任何 SQL（`repository` 是唯一出口）。
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile

from app.core import repository
from app.core.errors import NOT_FOUND, VALIDATION_ERROR, AppError
from app.deps import CurrentUser, current_user
from app.schemas import (
    PolishFullRequest,
    PolishFullResponse,
    PolishRequest,
    PolishResponse,
    Profile,
    ResumeMeta,
)
from app.services.ai import user_ai
from app.services.resume import resume_polish
from app.services.resume.parser import max_upload_bytes, parse_resume

router = APIRouter(prefix="/api/resumes", tags=["resume"], dependencies=[Depends(current_user)])

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
    meta = ResumeMeta(
        resume_id=resume_id,
        file_name=file_name,
        chars=parsed.chars,
        sections=parsed.sections,
    )
    repository.insert_document(
        meta,
        parsed.text,
        mime=file.content_type or "application/octet-stream",
    )
    return meta


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
