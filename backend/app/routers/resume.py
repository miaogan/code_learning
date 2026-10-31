"""简历上传（AC-1）：校验 → 抽取 → 入库 → 元信息。原文件不落盘，只存正文。"""

import uuid
from typing import Annotated

from fastapi import APIRouter, File, UploadFile

from .. import repository
from ..config import get_settings
from ..errors import FILE_TOO_LARGE, AppError
from ..schemas import ResumeMeta
from ..services.parser import parse_resume

router = APIRouter(prefix="/api/resumes", tags=["resume"])


@router.post("", response_model=ResumeMeta, summary="上传简历并抽取正文（PDF / DOCX / TXT）")
async def upload_resume(
    file: Annotated[UploadFile, File(description="简历文件，≤10MB")],
) -> ResumeMeta:
    settings = get_settings()
    limit_bytes = settings.max_upload_mb * 1024 * 1024
    raw = await file.read(limit_bytes + 1)
    if len(raw) > limit_bytes:
        raise AppError(
            FILE_TOO_LARGE,
            f"文件超过 {settings.max_upload_mb}MB，请压缩或分卷",
            status=413,
        )

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
