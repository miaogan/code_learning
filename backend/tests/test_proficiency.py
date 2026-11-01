"""熟练度判定用例（TECHNICAL §3 / AC-4 / AC-5）。

三层证据：
1. `evaluate()` 纯函数逐档：0 次 / 1 次 / 2 次 / 2 次但最近答错 / 2 次都在 31 天前 /
   **恰好 30 天边界**（含），外加乱序入参与 naive/aware 混用；
2. 事实层：`to_attempts()` 跳坏行、`attempts_by_question()` 分组升序；
3. 真实链路（走库，端到端）：`repository.insert_attempts()` 写事件 → `proficient_ids()` 聚合，
   并验证 `(question_id, run_id)` 唯一约束不会把同题同卷算成两次；阈值来自 `config` 且可被
   环境变量覆盖（这里断言「阈值不在服务层写死」这一条 AC-5）。

时间一律注入，不用系统时钟；窗口与次数阈值在用例里显式传参（本文件写 30 / 2 是**断言口径**，
不是服务层字面量 —— 后者的反向门禁见 `tests/test_engineering_gates.py`）。
"""

from __future__ import annotations

import ast
import inspect
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from app import repository
from app.config import get_settings
from app.services import proficiency
from app.services.proficiency import (
    Attempt,
    attempts_by_question,
    evaluate,
    proficient_ids,
    to_attempts,
    window_start,
)

#: 注入的「现在」：固定值让边界断言与系统时钟彻底解耦。
NOW = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
#: 注入的窗口与次数（= `config.Settings` 的默认值，用例显式传入以便逐档构造）。
WINDOW_DAYS = 30
CORRECT_THRESHOLD = 2


@pytest.fixture()
def fresh_settings() -> Iterator[None]:
    """用例改过环境变量后清一次配置缓存（否则 `lru_cache` 会把设置漏给后续用例）。"""
    yield
    get_settings.cache_clear()


def _attempt(
    correct: bool,
    *,
    days_ago: float = 0.0,
    question_id: str = "q1",
    naive: bool = False,
) -> Attempt:
    """构造一条作答事件（默认：`NOW` 前 `days_ago` 天，UTC aware）。"""
    answered_at = NOW - timedelta(days=days_ago)
    if naive:
        answered_at = answered_at.replace(tzinfo=None)
    return Attempt(
        question_id=question_id,
        correct=correct,
        answered_at=answered_at,
        run_id=uuid4().hex,
    )


def _verdict(attempts: list[Attempt], *, window_days: int = WINDOW_DAYS) -> proficiency.Proficiency:
    return evaluate(
        "q1",
        attempts,
        NOW,
        window_days=window_days,
        correct_threshold=CORRECT_THRESHOLD,
    )


# --- 1. 纯函数逐档 --------------------------------------------------------


def test_no_attempt_is_not_proficient() -> None:
    """0 次作答：不熟练，`last_correct=None`（不是 False —— 无事实与答错是两件事）。"""
    verdict = _verdict([])
    assert verdict.proficient is False
    assert verdict.correct_in_window == 0
    assert verdict.attempts_total == 0
    assert verdict.last_correct is None
    assert verdict.last_answered_at is None


def test_single_correct_is_not_proficient() -> None:
    """1 次答对 < 阈值 2：仍不熟练。"""
    verdict = _verdict([_attempt(True, days_ago=1)])
    assert verdict.proficient is False
    assert verdict.correct_in_window == 1
    assert verdict.attempts_total == 1
    assert verdict.last_correct is True


def test_two_correct_in_window_is_proficient() -> None:
    """窗口内答对 2 次且最近一次答对 → 熟练。"""
    verdict = _verdict([_attempt(True, days_ago=5), _attempt(True, days_ago=1)])
    assert verdict.proficient is True
    assert verdict.correct_in_window == 2
    assert verdict.attempts_total == 2
    assert verdict.last_correct is True
    assert verdict.last_answered_at == NOW - timedelta(days=1)


def test_latest_wrong_sends_question_back_immediately() -> None:
    """窗口内已答对 2 次，但最近一次答错 → 立即回流（最近一次不限窗口）。"""
    verdict = _verdict(
        [
            _attempt(True, days_ago=9),
            _attempt(True, days_ago=4),
            _attempt(False, days_ago=1),
        ]
    )
    assert verdict.proficient is False
    assert verdict.correct_in_window == 2
    assert verdict.last_correct is False


def test_corrects_outside_window_do_not_count() -> None:
    """两次答对都在 31 天前 → 窗口内 0 次正确，不熟练。"""
    verdict = _verdict([_attempt(True, days_ago=31), _attempt(True, days_ago=40)])
    assert verdict.proficient is False
    assert verdict.correct_in_window == 0
    assert verdict.attempts_total == 2
    assert verdict.last_correct is True


def test_exactly_window_days_ago_counts_as_in_window() -> None:
    """**恰好 30 天边界**（`answered_at == now - 30d`）算窗口内 → 熟练。"""
    verdict = _verdict([_attempt(True, days_ago=WINDOW_DAYS), _attempt(True, days_ago=1)])
    assert verdict.proficient is True
    assert verdict.correct_in_window == 2


def test_one_second_outside_window_does_not_count() -> None:
    """边界外 1 秒（30 天零 1 秒前）不算 → 不熟练（`>=` 与 `>` 的分水岭）。"""
    outside = Attempt(
        question_id="q1",
        correct=True,
        answered_at=NOW - timedelta(days=WINDOW_DAYS, seconds=1),
        run_id=uuid4().hex,
    )
    verdict = _verdict([outside, _attempt(True, days_ago=1)])
    assert verdict.proficient is False
    assert verdict.correct_in_window == 1


def test_future_attempt_is_ignored() -> None:
    """`answered_at > now` 的异常事实不进窗口（`<= now` 上界也要守住）。"""
    future = Attempt(
        question_id="q1",
        correct=True,
        answered_at=NOW + timedelta(hours=1),
        run_id=uuid4().hex,
    )
    verdict = _verdict([future, _attempt(True, days_ago=1)])
    assert verdict.correct_in_window == 1
    assert verdict.proficient is False


def test_unsorted_attempts_use_latest_by_time() -> None:
    """入参乱序时按 `answered_at` 取最近一次：最新那条答对 → 熟练。"""
    verdict = _verdict(
        [
            _attempt(True, days_ago=1),  # 最新，但排在列表最前
            _attempt(False, days_ago=8),
            _attempt(True, days_ago=3),
        ]
    )
    assert verdict.proficient is True
    assert verdict.last_correct is True
    assert verdict.last_answered_at == NOW - timedelta(days=1)


def test_naive_datetimes_are_treated_as_utc() -> None:
    """naive 与 aware 混用不炸：naive 按 UTC 解释（落库时间全是 UTC）。"""
    verdict = _verdict([_attempt(True, days_ago=5, naive=True), _attempt(True, days_ago=1)])
    assert verdict.proficient is True
    assert verdict.correct_in_window == 2


def test_window_start_matches_injected_days() -> None:
    """`window_start()` 就是 `now - window_days` 天（窗口左边界唯一出处）。"""
    assert window_start(NOW, WINDOW_DAYS) == NOW - timedelta(days=WINDOW_DAYS)
    assert window_start(NOW, 0) == NOW
    naive_start = window_start(NOW.replace(tzinfo=None), WINDOW_DAYS)
    assert naive_start.tzinfo == UTC
    assert naive_start == NOW - timedelta(days=WINDOW_DAYS)


# --- 2. 事实层：行 → Attempt ---------------------------------------------


def _row(question_id: str, correct: bool, answered_at: datetime, run_id: str | None = None) -> dict:
    """`repository.list_attempts()` 行形状（ISO8601 UTC 文本）。"""
    return {
        "id": uuid4().hex,
        "question_id": question_id,
        "run_id": run_id or uuid4().hex,
        "correct": 1 if correct else 0,
        "answered_at": answered_at.isoformat(),
        "created_at": answered_at.isoformat(),
    }


def test_to_attempts_skips_bad_rows() -> None:
    """缺字段 / 时间不可解析 / 题为空 / 非 dict 的行跳过，好行保留。"""
    good = _row("q1", True, NOW - timedelta(days=1))
    rows: list[Any] = [
        good,
        {"question_id": "q2", "correct": 1, "answered_at": "not-a-time", "run_id": "r"},
        {"question_id": "q3", "correct": 1, "run_id": "r"},
        {"question_id": "", "correct": 1, "answered_at": NOW.isoformat(), "run_id": "r"},
        None,
        "garbage",
    ]
    attempts = to_attempts(rows)
    assert len(attempts) == 1
    assert attempts[0].question_id == "q1"
    assert attempts[0].correct is True
    assert attempts[0].answered_at == NOW - timedelta(days=1)


def test_attempts_by_question_groups_and_sorts() -> None:
    """按题分组，每题内部按 `answered_at` 升序（`evaluate` 的唯一入参形状）。"""
    rows = [
        _row("q2", False, NOW - timedelta(days=1)),
        _row("q1", False, NOW - timedelta(days=9)),
        _row("q1", True, NOW - timedelta(days=2)),
        _row("q2", True, NOW - timedelta(days=5)),
    ]
    grouped = attempts_by_question(rows)
    assert set(grouped) == {"q1", "q2"}
    # 升序 = 旧事实在前：q1 是 9 天前答错 → 2 天前答对；q2 是 5 天前答对 → 1 天前答错
    assert [item.correct for item in grouped["q1"]] == [False, True]
    assert [item.correct for item in grouped["q2"]] == [True, False]
    assert all(
        earlier.answered_at <= later.answered_at
        for items in grouped.values()
        for earlier, later in zip(items, items[1:])
    )
    assert attempts_by_question([]) == {}


# --- 3. 读库聚合：端到端（事件 → 熟练集合） -------------------------------


def _insert(
    question_id: str,
    correct: bool,
    answered_at: datetime,
    run_id: str | None = None,
) -> int:
    return repository.insert_attempts([_row(question_id, correct, answered_at, run_id)])


def test_proficient_ids_reads_attempts_end_to_end(tmp_db: Path) -> None:
    """走库的端到端：写事件 → `proficient_ids(now)` 只返回真正熟练的题。"""
    _insert("q-both-correct", True, NOW - timedelta(days=10))
    _insert("q-both-correct", True, NOW - timedelta(days=2))
    _insert("q-once", True, NOW - timedelta(days=3))
    _insert("q-stale", True, NOW - timedelta(days=31))
    _insert("q-stale", True, NOW - timedelta(days=40))
    _insert("q-relapsed", True, NOW - timedelta(days=6))
    _insert("q-relapsed", True, NOW - timedelta(days=5))
    _insert("q-relapsed", False, NOW - timedelta(days=1))
    _insert("q-border", True, NOW - timedelta(days=WINDOW_DAYS))
    _insert("q-border", True, NOW - timedelta(days=1))

    assert proficient_ids(now=NOW) == {"q-both-correct", "q-border"}
    # 判定的另一半事实：窗口内正确次数（报告/排障口径，不是布尔猜测）
    verdict = evaluate(
        "q-relapsed",
        attempts_by_question(repository.list_attempts())["q-relapsed"],
        NOW,
        window_days=WINDOW_DAYS,
        correct_threshold=CORRECT_THRESHOLD,
    )
    assert verdict.correct_in_window == 2
    assert verdict.last_correct is False


def test_same_question_same_run_counts_once(tmp_db: Path) -> None:
    """`UNIQUE(question_id, run_id)`：同卷同题重复写不产生第二条事实（幂等）。"""
    run_id = uuid4().hex
    assert _insert("q1", True, NOW - timedelta(days=1), run_id) == 1
    assert _insert("q1", True, NOW - timedelta(days=1), run_id) == 0
    assert len(repository.list_attempts()) == 1
    assert proficient_ids(now=NOW) == set()


def test_proficient_ids_uses_repository_rows_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """`proficient_ids()` 只消费 `repository.list_attempts()` 的行（SQL 不越界到服务层）。"""
    rows = [
        _row("q-a", True, NOW - timedelta(days=3)),
        _row("q-a", True, NOW - timedelta(days=1)),
        _row("q-b", True, NOW - timedelta(days=1)),
        _row("q-c", False, NOW - timedelta(days=1)),
    ]
    calls: list[int] = []

    def fake_list_attempts() -> list[dict[str, Any]]:
        calls.append(1)
        return rows

    monkeypatch.setattr(proficiency.repository, "list_attempts", fake_list_attempts)
    assert proficient_ids(now=NOW) == {"q-a"}
    assert len(calls) == 1


def test_thresholds_come_from_config_and_track_env(
    tmp_db: Path,
    monkeypatch: pytest.MonkeyPatch,
    fresh_settings: None,
) -> None:
    """阈值唯一出处是 `config`（可环境变量覆盖）：改环境变量，判定行为随动，服务层零改动。"""
    settings = get_settings()
    assert settings.proficiency_window_days == WINDOW_DAYS
    assert settings.proficiency_correct_threshold == CORRECT_THRESHOLD

    _insert("q-two-correct", True, NOW - timedelta(days=2))
    _insert("q-two-correct", True, NOW - timedelta(days=1))
    _insert("q-three-correct", True, NOW - timedelta(days=3))
    _insert("q-three-correct", True, NOW - timedelta(days=2))
    _insert("q-three-correct", True, NOW - timedelta(days=1))
    # 默认阈值 2：两题都算熟练
    assert proficient_ids(now=NOW) == {"q-two-correct", "q-three-correct"}

    # 次数阈值抬到 3：只有答对 3 次的题仍熟练
    monkeypatch.setenv("PROFICIENCY_CORRECT_THRESHOLD", "3")
    get_settings.cache_clear()
    assert get_settings().proficiency_correct_threshold == 3
    assert proficient_ids(now=NOW) == {"q-three-correct"}

    # 窗口压到 1 天（次数保持默认 2）：每题窗口内只剩 1 次正确 → 全部回流
    monkeypatch.setenv("PROFICIENCY_WINDOW_DAYS", "1")
    monkeypatch.delenv("PROFICIENCY_CORRECT_THRESHOLD")
    get_settings.cache_clear()
    assert get_settings().proficiency_window_days == 1
    assert get_settings().proficiency_correct_threshold == CORRECT_THRESHOLD
    assert proficient_ids(now=NOW) == set()


def test_service_module_declares_no_window_literal() -> None:
    """服务层不写窗口天数字面量（阈值只从 `config.get_settings()` 来，AC-5）。"""
    source = inspect.getsource(proficiency)
    tree = ast.parse(source)
    literal_30 = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and type(node.value) is int and node.value == 30
    ]
    assert literal_30 == [], f"proficiency.py 出现 30 字面量：{literal_30}"
    assert "correct_threshold" in source
    assert "window_days" in source
