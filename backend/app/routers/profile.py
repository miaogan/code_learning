"""画像路由（AC-2）：AI 生成 → 读取最新 → 行内编辑（PATCH 响应即唯一真值）。

- 生成走 body-less POST（`/api/resumes/{resume_id}/profile`），不接收任何 query 参数。
- 编辑走 PATCH：只覆盖请求体里**出现过且非 null**的字段，其余维度原样保留。
- r3 起 POST 是合并入口：响应 `ProfileWithMerge`（`merge_summary` 只此一次）；
  读取接口 `GET /api/profiles/latest` 的**持久契约不扩**——没有 `merge_summary`，
  但 `source_quotes` / `status` 属于 r3 的 `Profile` 本体扩展，读回同样带出（DESIGN §7-1）。
- SQL 一律走 `repository`（唯一 SQL 出口），本层只做参数与错误映射。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter

from .. import repository
from ..errors import NOT_FOUND, AppError
from ..schemas import Profile, ProfilePatch, ProfileWithMerge
from ..services.profile import generate_profile
from ..services.profile_merge import backfill_evidence

router = APIRouter(prefix="/api", tags=["profile"])


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
async def create_profile(resume_id: str) -> ProfileWithMerge:
    text = repository.get_document_text(resume_id)
    if text is None:
        raise AppError(NOT_FOUND, "没有找到这份简历，请重新上传后再生成画像", status=404)
    meta = _document_meta(resume_id)
    return await generate_profile(
        resume_id,
        text,
        file_name=str(meta.get("file_name") or ""),
        captured_at=str(meta.get("created_at") or ""),
    )


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
