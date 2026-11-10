"""学习进度与 7 天计划打卡（r61 上云）。

本地 localStorage 退化为缓存，服务端才是权威副本：这里只做「边界净化 + 读写投影」，
不做业务判断（「读过」与「掌握」的分界仍归前端展示口径，本层不产出任何成绩）。

净化一律静默夹取而不是报错：这两个接口由后台自动同步调用，用户没有重试入口，
抛错只会把「这次没同步上」变成用户看不见、也修不了的故障。
"""

import re
from typing import Any

from app.core import repository
from app.core.errors import NOT_FOUND, AppError
from app.schemas import LearnChapterProgress, LearnProgress, PlanState, PlanStatePayload

#: 章节 / 小节 / 任务 id 都是程序生成的短标识，超出闭集形态一律视为脏值丢弃。
_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
MAX_CHAPTERS = 200
MAX_SEEN = 200
MAX_TASKS = 200


def clean_id(value: Any) -> str:
    """把外部传入的 id 收敛到安全形态；不合格返回空串（调用方据此跳过该条）。"""
    if not isinstance(value, str):
        return ""
    text = value.strip()
    return text if _ID_PATTERN.match(text) else ""


def normalize_progress(payload: LearnProgress) -> LearnProgress:
    """章节上限 / 已读去重 / 脏 id 丢弃；`last_chapter_id` 指向不存在的章节时置空。"""
    chapters: dict[str, LearnChapterProgress] = {}
    for chapter_id, item in list(payload.chapters.items())[:MAX_CHAPTERS]:
        cid = clean_id(chapter_id)
        if not cid or cid in chapters:
            continue
        seen: list[str] = []
        for section in list(item.seen or [])[:MAX_SEEN]:
            sid = clean_id(section)
            if sid and sid not in seen:
                seen.append(sid)
        chapters[cid] = LearnChapterProgress(
            seen=seen,
            last_section_id=clean_id(item.last_section_id) or None,
            updated_at=max(0, int(item.updated_at or 0)),
        )
    last = clean_id(payload.last_chapter_id)
    return LearnProgress(
        last_chapter_id=last if last in chapters else None,
        chapters=chapters,
    )


def read_progress() -> LearnProgress:
    """读整份阅读进度；该账号还没同步过时返回空状态（前端据此把本地进度回推）。"""
    return LearnProgress(**repository.get_learn_progress())


def write_progress(payload: LearnProgress) -> LearnProgress:
    """整份覆盖写，返回落库后的状态（前端以服务端返回值作为合并结果）。"""
    cleaned = normalize_progress(payload)
    repository.save_learn_progress(
        cleaned.last_chapter_id,
        {chapter_id: item.model_dump() for chapter_id, item in cleaned.chapters.items()},
    )
    return cleaned


def _ensure_report(report_id: str) -> None:
    """计划打卡只允许挂在自己真实生成的报告上，避免任意 id 写进库。"""
    if repository.get_report(report_id) is None:
        raise AppError(NOT_FOUND, "没有找到这份报告，请先完成一次测评后重试", status=404)


def read_plan(report_id: str) -> PlanState:
    _ensure_report(report_id)
    return PlanState(**repository.get_plan_state(report_id))


def write_plan(report_id: str, payload: PlanStatePayload) -> PlanState:
    """只保留「已打卡」（`True`）的条目：取消打卡等价于从 map 里删掉。"""
    _ensure_report(report_id)
    done: dict[str, bool] = {}
    for task_id, flag in list(payload.done.items())[:MAX_TASKS]:
        tid = clean_id(task_id)
        if tid and flag:
            done[tid] = True
    repository.save_plan_state(report_id, payload.daily_minutes, done)
    return read_plan(report_id)
