"""r67 技术雷达端点：先锋（清单 / 采集 / 手工录入）与国子监（生成任务 / 采纳 / 废弃）。

业务主路径全在 `services/radar/`，路由只做依赖装配与错误码映射。
`tech_slug` 含 `/` 与 `:`，**一律走 body 传参**；`job_id` 形如 `rj-<hex>` 才用路径参数。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.config import get_settings
from app.core.errors import NOT_FOUND, VALIDATION_ERROR, AppError
from app.deps import CurrentUser, current_user
from app.schemas import (
    RadarGenerateRequest,
    RadarJobAccepted,
    RadarJobItem,
    RadarJobList,
    RadarManualRequest,
    RadarRunRequest,
    RadarRunSummary,
    RadarTechItem,
    RadarTechList,
    RadarTranslateRequest,
    RadarTranslateResult,
)
from app.services import radar
from app.services.ai import user_ai
from app.services.radar import jobs, rules, sources, store

router = APIRouter(prefix="/api/radar", tags=["radar"], dependencies=[Depends(current_user)])

#: 多选筛选的缺省值（模块级常量，避免 ruff B008 把 `Query()` 调用当默认值）。
_NO_FILTER: tuple[str, ...] = ()


def _notice() -> str:
    """清单页的一句概括：离线模式 > 降级 > 空串（不编造原因）。"""
    if get_settings().radar_offline:
        return "当前为离线模式，列表只来自内置样本"
    return "最近一轮采集部分来源不可用" if store.latest_run()["degraded"] else ""


@router.get("/techs", response_model=RadarTechList, summary="技术清单（最新评估 + 快照）")
async def list_techs(
    limit: int = Query(default=50, ge=1, le=100, description="每页条数"),
    page: int = Query(default=1, ge=1, description="页码，从 1 起"),
    direction: Annotated[
        list[str],
        Query(description="按方向多选（可重复传 direction=...）；不传 = 全部"),
    ] = _NO_FILTER,
    verdict: Annotated[
        list[str],
        Query(description="按结论多选 must_learn|worth_knowing|watch|skip；不传 = 全部"),
    ] = _NO_FILTER,
) -> RadarTechList:
    directions = [item.strip() for item in direction if item.strip()]
    verdicts = [item.strip() for item in verdict if item.strip()]
    if any(item not in rules.DIRECTIONS for item in directions):
        raise AppError(VALIDATION_ERROR, "方向不在站内闭集，请从下拉框选择", status=400)
    if any(item not in rules.VERDICTS for item in verdicts):
        raise AppError(VALIDATION_ERROR, "结论不在闭集内，请从筛选器选择", status=400)
    items = store.list_techs(
        limit, directions=directions, verdicts=verdicts, offset=(page - 1) * limit
    )
    return RadarTechList(
        items=[
            RadarTechItem(**row, verdict_label=rules.label_of(row["verdict"])) for row in items
        ],
        total=store.count_techs(directions=directions, verdicts=verdicts),
        notice=_notice(),
    )


@router.post("/run", response_model=RadarRunSummary, summary="立即跑一轮采集与评估")
async def run_round(
    user: CurrentUser, payload: RadarRunRequest | None = None
) -> RadarRunSummary:
    request = payload or RadarRunRequest()
    direction = request.direction.strip()
    repo = sources.repo_full_name(request.repo)
    if direction and direction not in rules.DIRECTIONS:
        raise AppError(VALIDATION_ERROR, "方向不在站内闭集，请从下拉框选择", status=400)
    if request.repo.strip() and not repo:
        raise AppError(
            VALIDATION_ERROR, "仓库地址无法识别：请填 GitHub 仓库链接或 owner/repo", status=400
        )
    result = await radar.run_round(trigger="manual", user=user, direction=direction, repo=repo)
    return RadarRunSummary(**result)


@router.post("/translate", response_model=RadarTranslateResult, summary="英文摘要翻成中文（可重复调用）")
async def translate_summaries(
    user: CurrentUser, payload: RadarTranslateRequest | None = None
) -> RadarTranslateResult:
    """补翻历史清单里的英文摘要；已翻过的不会被重复请求（译文落库，原文变化才重翻）。"""
    request = payload or RadarTranslateRequest()
    translated, remaining = await radar.translate_summaries(user, request.limit)
    notice = f"已翻译 {translated} 条英文简介" if translated else "没有新增可翻译的摘要"
    if remaining:
        notice += f"，还有 {remaining} 条待翻译"
    return RadarTranslateResult(translated=translated, remaining=remaining, notice=notice)


@router.get("/runs/latest", response_model=RadarRunSummary, summary="最近一轮采集摘要")
async def latest_run() -> RadarRunSummary:
    return RadarRunSummary(**store.latest_run(), notice=_notice())


@router.post("/manual", response_model=RadarTechItem, summary="手工录入一条技术线索")
async def manual(payload: RadarManualRequest, user: CurrentUser) -> RadarTechItem:
    row = await radar.ingest_manual(payload.model_dump(), user)
    return RadarTechItem(**row, verdict_label=rules.label_of(row["verdict"]))


@router.post("/generate", response_model=RadarJobAccepted, summary="异步生成章节与练习题样例")
async def generate(payload: RadarGenerateRequest, user: CurrentUser) -> RadarJobAccepted:
    # 先解析账号的 AI 客户端：无 Key / 未开通立即暴露，不建任务行（AC-7 的失败面）。
    user_ai.client_for(user, "light")
    if store.tech_card(payload.tech_slug) is None:
        raise AppError(NOT_FOUND, "技术不存在，请先刷新清单", status=404)
    try:
        job_id, reused = store.create_job(payload.tech_slug, trigger="manual")
    except ValueError:
        raise AppError(
            VALIDATION_ERROR, "该技术正在为其他账号生成样例，请稍后再试", status=409, retryable=True
        ) from None
    if not reused:
        jobs.start(job_id, payload.tech_slug, user)
    return RadarJobAccepted(
        job_id=job_id,
        tech_slug=payload.tech_slug,
        status=store.get_job(job_id)["status"] if store.get_job(job_id) else "queued",
        reused=reused,
    )


@router.get("/jobs", response_model=RadarJobList, summary="本账号的样例任务列表")
async def list_jobs(
    limit: int = Query(default=20, ge=1, le=50, description="每页条数"),
    page: int = Query(default=1, ge=1, description="页码，从 1 起"),
) -> RadarJobList:
    store.sweep_stale_jobs(get_settings().radar_job_stale_minutes)
    rows = store.list_jobs(limit, offset=(page - 1) * limit)
    return RadarJobList(items=[RadarJobItem(**row) for row in rows], total=store.count_jobs())


@router.get("/jobs/{job_id}", response_model=RadarJobItem, summary="单个样例任务的进度与草稿")
async def get_job(job_id: str) -> RadarJobItem:
    store.sweep_stale_jobs(get_settings().radar_job_stale_minutes)
    # `jobs._require` 就是「不在本账号 → 404」的唯一读路径，路由不再复写一份。
    return RadarJobItem(**jobs._require(job_id))


@router.post("/jobs/{job_id}/adopt", response_model=RadarJobItem, summary="扩充入库（只进练习池）")
async def adopt(job_id: str) -> RadarJobItem:
    return RadarJobItem(**jobs.adopt(job_id))


@router.post("/jobs/{job_id}/discard", response_model=RadarJobItem, summary="废弃整份草稿")
async def discard(job_id: str) -> RadarJobItem:
    return RadarJobItem(**jobs.discard(job_id))
