"""r67 生成任务层：后台异步生成 + 进度 + 硬超时 + 采纳 / 废弃（AC-5 / AC-6）。

与 r30/r42 的异步任务同一套纪律：
- 受理即返回 `job_id`，生成跑在 `asyncio.create_task` 里，页面轮询看进度；
- **任务级硬上限**（`2 × RADAR_GEN_TIMEOUT_S + 60`）兜住「重试 × 超时」的最坏耗时；
- 服务重启留下的未终态行由 `init_db()` 启动清扫 + 读路径惰性清扫统一判 failed，不留僵尸；
- 采纳 / 废弃是**互斥终态**，只有 `succeeded` 能被处理一次；重复采纳返回同一结果（幂等）。
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from app.core import repository
from app.core.config import get_settings
from app.core.errors import NOT_FOUND, VALIDATION_ERROR, AppError
from app.services.ai import user_ai
from app.services.radar import generate, store

logger = logging.getLogger("app.radar.jobs")

#: 后台任务的强引用集合：`create_task` 的返回值不持有引用会被 GC 回收（Python 文档明示）。
_TASKS: set[asyncio.Task[None]] = set()

PROGRESS_CHAPTER = 20
PROGRESS_QUESTIONS = 60
PROGRESS_DONE = 100
#: 硬上限的余量：模型调用本身已带「超时 + 重试一次」，再留一分钟收尾。
HARD_LIMIT_MARGIN_S = 60


def _fail(job_id: str, message: str) -> None:
    store.update_job(
        job_id, status="failed", stage="failed", error_message=(message or "生成失败")[:200]
    )


async def _run(job_id: str, tech_slug: str, user: dict[str, Any]) -> None:
    """后台生成：章节 → 题目 → 落库到任务行，任一环节异常都落 failed 中文原因。"""
    settings = get_settings()
    hard_limit = settings.radar_gen_timeout_s * 2 + HARD_LIMIT_MARGIN_S
    try:
        card = store.tech_card(tech_slug)
        if card is None:
            _fail(job_id, "该技术已不在雷达清单里，请刷新后重试")
            return
        client = user_ai.client_for(user, "light")
        store.update_job(job_id, status="running", stage="chapter", progress=PROGRESS_CHAPTER)
        chapter, questions, discarded = await asyncio.wait_for(
            generate.generate(card, str(card.get("verdict") or "watch"), job_id, client),
            timeout=hard_limit,
        )
        store.update_job(job_id, stage="questions", progress=PROGRESS_QUESTIONS)
        store.update_job(
            job_id,
            status="succeeded",
            stage="done",
            progress=PROGRESS_DONE,
            chapter_json=json.dumps(chapter, ensure_ascii=False) if chapter else "",
            questions_json=json.dumps(questions, ensure_ascii=False),
            discarded_count=discarded,
            error_message="",
        )
    except asyncio.CancelledError:
        raise
    except TimeoutError:
        _fail(job_id, "样例生成超时，请稍后重试")
    except AppError as error:
        _fail(job_id, error.message)
    except Exception:  # noqa: BLE001 — 后台任务不能把异常抛到事件循环
        logger.exception("radar.job.failed job_id=%s", job_id)
        _fail(job_id, "样例生成失败，请稍后重试")


def start(job_id: str, tech_slug: str, user: dict[str, Any]) -> None:
    """受理后立刻返回，生成在后台跑（页面离开也不中断，回来按 job_id 轮询接上）。"""
    task = asyncio.create_task(_run(job_id, tech_slug, user))
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)


def _require(job_id: str) -> dict[str, Any]:
    job = store.get_job(job_id)
    if job is None:
        raise AppError(NOT_FOUND, "样例任务不存在或不属于当前账号", status=404)
    return job


def adopt(job_id: str) -> dict[str, Any]:
    """扩充入库：通过自检的题写入练习池；章节草稿留档在任务行里（**不并入官方教程**）。

    同类题目 id 已存在时 `ON CONFLICT DO NOTHING` 不会覆盖，因此重复采纳是安全的；
    但终态只允许改一次（`succeeded → adopted`），二次调用直接回读当前任务。
    """
    job = _require(job_id)
    if job["status"] == "adopted":
        return job
    if job["status"] != "succeeded":
        raise AppError(
            VALIDATION_ERROR, "只有生成完成且尚未处理的样例可以扩充入库", status=409
        )
    inserted = repository.insert_questions(list(job.get("questions") or []))
    logger.info("radar.job.adopted job_id=%s inserted=%s", job_id, inserted)
    store.update_job(job_id, status="adopted", error_message="")
    return _require(job_id)


def discard(job_id: str) -> dict[str, Any]:
    """废弃：整份草稿作废（题目不入库、章节不留档，任务行只留「废弃」这个终态）。"""
    job = _require(job_id)
    if job["status"] == "discarded":
        return job
    if job["status"] == "adopted":
        raise AppError(VALIDATION_ERROR, "样例已扩充入库，不能废弃", status=409)
    if job["status"] not in ("succeeded", "failed"):
        raise AppError(VALIDATION_ERROR, "生成中的样例不能废弃，请等它结束", status=409)
    store.update_job(job_id, status="discarded", error_message="")
    return _require(job_id)
