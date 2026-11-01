"""熟练度判定：滑动窗口纯函数 + 读库聚合（TECHNICAL §3，AC-4 / AC-5）。

分工（r6 写死，两个方向都别漂）：
- 本模块只做**判定**：作答事件 + 注入的 `now` + 注入的阈值 → `Proficiency`。
  `evaluate()` 不读时钟、不读配置、不碰数据库，因此「恰好 30 天边界」「最近一次答错即回流」
  这类最容易写错的口径可以逐档单测（`tests/test_proficiency.py`）。
- **可调阈值**（窗口天数 / 窗口内答对次数 / 近卷去重卷数）只在 `config.Settings` 单一出处，
  可被环境变量覆盖；这里一个数值都不写，`proficient_ids()` 才去 `get_settings()` 取。
  **闭集与结构闸门**只在 `services/rules.py`（题量 / 占比 / 方向 / 难度 / 必备度 / 阶梯）。
- 事实层没有简答题事件（`text` 不计分、永不写 `question_attempts`），所以本模块不需要 kind
  分支，也不要引入「按题型过滤」的第二套口径。

判定式（唯一出处）::

    window 事件 = [a for a in attempts if window_start(now, days) <= a.answered_at <= now]
    proficient  =  窗口内答对次数 >= correct_threshold  且  最近一次作答（不限窗口）答对

- 边界：`answered_at == now - window_days` 恰好命中 → 算窗口内（含边界）。
- 最近一次答错 → 立即回流（即便窗口内已答对够次数）。
- 0 次作答 → `proficient=False`、`last_correct=None`。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from .. import repository
from ..config import get_settings


@dataclass(frozen=True)
class Attempt:
    """一条作答事件的服务层视图（`repository` 行 → dataclass，时间统一成 UTC aware）。"""

    question_id: str
    correct: bool
    answered_at: datetime
    run_id: str


@dataclass(frozen=True)
class Proficiency:
    """单题熟练度判定结果：`proficient` 是唯一对外结论，其余字段供报告 / 排障读取。"""

    question_id: str
    proficient: bool
    correct_in_window: int
    attempts_total: int
    last_correct: bool | None
    last_answered_at: datetime | None


def _ensure_utc(value: datetime) -> datetime:
    """统一成 UTC aware：库里存 ISO8601 UTC（带偏移），用例可能注入 naive 时间。

    naive 一律按 UTC 解释 —— 本项目所有落库时间都是 `datetime.now(UTC)`，没有本地时区语义。
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _parse_ts(value: Any) -> datetime | None:
    """`answered_at` 文本 → datetime；坏值返回 `None` 由调用方跳过（不让脏行炸整条链路）。"""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return _ensure_utc(datetime.fromisoformat(value.strip()))
    except ValueError:
        return None


def window_start(now: datetime, window_days: int) -> datetime:
    """窗口左边界（含）：`now - window_days` 天。"""
    return _ensure_utc(now) - timedelta(days=window_days)


def _attempt_of(row: Any) -> Attempt | None:
    """单行 → `Attempt`；缺字段 / 时间不可解析 / 题为空的行返回 `None`。"""
    if not isinstance(row, dict):
        return None
    question_id = str(row.get("question_id") or "").strip()
    answered_at = _parse_ts(row.get("answered_at"))
    if not question_id or answered_at is None:
        return None
    return Attempt(
        question_id=question_id,
        correct=bool(row.get("correct")),
        answered_at=answered_at,
        run_id=str(row.get("run_id") or ""),
    )


def to_attempts(rows: Sequence[dict[str, Any]]) -> list[Attempt]:
    """`repository.list_attempts()` 行 → `Attempt` 列表（坏行跳过，顺序沿用入参）。"""
    attempts: list[Attempt] = []
    for row in rows:
        attempt = _attempt_of(row)
        if attempt is not None:
            attempts.append(attempt)
    return attempts


def _ordered(attempts: Sequence[Attempt]) -> list[Attempt]:
    """按 `answered_at` 升序排序（稳定排序：同一时刻保留入参顺序）。"""
    return sorted(attempts, key=lambda item: _ensure_utc(item.answered_at))


def attempts_by_question(rows: Sequence[dict[str, Any]]) -> dict[str, list[Attempt]]:
    """按题聚合作答序列，每题的列表按 `answered_at` 升序（`evaluate()` 的唯一入参形状）。"""
    grouped: dict[str, list[Attempt]] = {}
    for attempt in to_attempts(rows):
        grouped.setdefault(attempt.question_id, []).append(attempt)
    return {question_id: _ordered(items) for question_id, items in grouped.items()}


def evaluate(
    question_id: str,
    attempts: Sequence[Attempt],
    now: datetime,
    *,
    window_days: int,
    correct_threshold: int,
) -> Proficiency:
    """单题熟练度判定（纯函数：阈值与 `now` 全部注入，不读时钟 / 配置 / 库）。"""
    moment = _ensure_utc(now)
    start = window_start(moment, window_days)
    ordered = _ordered(attempts)
    in_window = [item for item in ordered if start <= _ensure_utc(item.answered_at) <= moment]
    correct_in_window = sum(1 for item in in_window if item.correct)
    last = ordered[-1] if ordered else None
    proficient = bool(
        last is not None
        and last.correct
        and correct_in_window >= correct_threshold
    )
    return Proficiency(
        question_id=question_id,
        proficient=proficient,
        correct_in_window=correct_in_window,
        attempts_total=len(ordered),
        last_correct=None if last is None else bool(last.correct),
        last_answered_at=None if last is None else _ensure_utc(last.answered_at),
    )


def proficient_ids(now: datetime | None = None) -> set[str]:
    """全库熟练题 id 集合（组卷过滤的唯一读侧入口）。

    只读 `repository.list_attempts()`（SQL 只在 repository），阈值只来自 `config.get_settings()`。
    `now=None` 时取一次 `datetime.now(UTC)`：生产不传，测试必传以摆脱时钟依赖。
    单用户全局判定，不按画像过滤（PRD §7）。
    """
    settings = get_settings()
    moment = datetime.now(UTC) if now is None else _ensure_utc(now)
    window_days = settings.proficiency_window_days
    threshold = settings.proficiency_correct_threshold
    proficient: set[str] = set()
    for question_id, attempts in attempts_by_question(repository.list_attempts()).items():
        verdict = evaluate(
            question_id,
            attempts,
            moment,
            window_days=window_days,
            correct_threshold=threshold,
        )
        if verdict.proficient:
            proficient.add(question_id)
    return proficient
