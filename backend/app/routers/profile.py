"""画像路由（AC-2）：AI 生成 → 读取最新 → 行内编辑（PATCH 响应即唯一真值）。

- 生成走 body-less POST（`/api/resumes/{resume_id}/profile`），不接收任何 query 参数。
- 编辑走 PATCH：只覆盖请求体里**出现过且非 null**的字段，其余维度原样保留。
- SQL 一律走 `repository`（唯一 SQL 出口），本层只做参数与错误映射。
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter

from .. import repository
from ..errors import NOT_FOUND, AppError
from ..schemas import Profile, ProfilePatch
from ..services.profile import generate_profile

router = APIRouter(prefix="/api", tags=["profile"])


@router.get("/profiles/latest", response_model=Profile, summary="读取最近一次画像")
def read_latest_profile() -> Profile:
    profile = repository.latest_profile()
    if profile is None:
        raise AppError(NOT_FOUND, "还没有画像，请先上传简历", status=404)
    return profile


@router.post("/resumes/{resume_id}/profile", response_model=Profile, summary="依据简历生成画像")
async def create_profile(resume_id: str) -> Profile:
    text = repository.get_document_text(resume_id)
    if text is None:
        raise AppError(NOT_FOUND, "没有找到这份简历，请重新上传后再生成画像", status=404)
    return await generate_profile(resume_id, text)


@router.patch("/profiles/{profile_id}", response_model=Profile, summary="编辑画像条目")
def update_profile(profile_id: str, patch: ProfilePatch) -> Profile:
    profile = repository.get_profile(profile_id)
    if profile is None:
        raise AppError(NOT_FOUND, "没有找到这份画像，请先生成画像", status=404)

    # 显式传 null 视为「不改这一维」，避免前端把整份草稿回传时抹掉其它维度。
    fields = patch.model_dump(exclude_unset=True)
    changes = {name: value for name, value in fields.items() if value is not None}
    updated = Profile.model_validate(
        {
            **profile.model_dump(),
            **changes,
            "updated_at": datetime.now(UTC).isoformat(),
        }
    )
    repository.save_profile(updated)
    return updated
