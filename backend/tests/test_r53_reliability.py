"""r53 可靠性治理：纯函数与状态机的确定性回归。"""

from __future__ import annotations

import random

from app.services.ai import reliability
from app.services.ai.ai import _extract_json_object


def test_backoff_is_deterministic_with_injected_rng() -> None:
    """注入同一 seed 的随机源，两次调用结果必须逐值一致。"""
    first = [reliability.backoff_delay(i, rng=random.Random(7)) for i in range(1, 6)]
    second = [reliability.backoff_delay(i, rng=random.Random(7)) for i in range(1, 6)]
    assert first == second
    assert first[0] > 0


def test_backoff_is_capped_and_non_negative() -> None:
    """高 attempt 必须被 cap 夹住，且抖动不会产生负延迟。"""
    for attempt in range(1, 20):
        value = reliability.backoff_delay(attempt, rng=random.Random(1))
        assert 0.0 <= value <= reliability.BACKOFF_CAP_S * (1 + reliability.BACKOFF_JITTER)
    assert reliability.backoff_delay(0, rng=random.Random(1)) == reliability.backoff_delay(
        1, rng=random.Random(1)
    )


def test_idempotency_key_stable_and_version_scoped() -> None:
    key = reliability.idempotency_key("sys", "user", "model-a")
    assert key == reliability.idempotency_key("sys", "user", "model-a")
    assert len(key) == 64
    assert key != reliability.idempotency_key("sys", "user", "model-a", version="v2")
    assert key != reliability.idempotency_key("sys", "other", "model-a")
    assert key != reliability.idempotency_key("sys", "user", "model-b")


def test_repair_recovers_trailing_comma() -> None:
    """原有解析器失败的输入，兜底能救回且值正确。"""
    raw = '{"skills": ["Python", "FastAPI",], "years": 3,}'
    assert _extract_json_object(raw) is None
    assert reliability.repair_json_object(raw) == {"skills": ["Python", "FastAPI"], "years": 3}


def test_repair_recovers_single_quotes_fence_and_prose() -> None:
    raw = "这是结果：\n```json\n{'skills': ['RAG'], 'years': 5}\n```\n以上。"
    repaired = reliability.repair_json_object(raw)
    assert repaired == {"skills": ["RAG"], "years": 5}


def test_repair_recovers_line_comments() -> None:
    raw = '{\n // 模型多写的注释\n "skills": ["SQL"]\n}'
    assert _extract_json_object(raw) is None
    assert reliability.repair_json_object(raw) == {"skills": ["SQL"]}


def test_repair_returns_none_for_hopeless_input() -> None:
    assert reliability.repair_json_object("") is None
    assert reliability.repair_json_object("完全不是 JSON") is None
    assert reliability.repair_json_object("[1, 2, 3]") is None
    assert reliability.repair_json_object(None) is None  # type: ignore[arg-type]


def test_repair_does_not_rewrite_valid_json() -> None:
    raw = '{"a": 1, "b": "中文"}'
    assert _extract_json_object(raw) == {"a": 1, "b": "中文"}
    assert reliability.repair_json_object(raw) == {"a": 1, "b": "中文"}


def test_breaker_opens_after_threshold_and_recovers() -> None:
    now = [100.0]
    breaker = reliability.CircuitBreaker(
        failure_threshold=3, recovery_timeout_s=10.0, clock=lambda: now[0]
    )
    assert breaker.state == "closed" and breaker.allow()
    for _ in range(3):
        breaker.record_failure()
    assert breaker.state == "open"
    assert breaker.allow() is False

    now[0] += 11.0
    assert breaker.allow() is True  # 转 half_open 并放行一次探测
    assert breaker.state == "half_open"
    breaker.record_success()
    assert breaker.state == "closed"
    snapshot = breaker.snapshot()
    assert snapshot["failures"] == 0
    assert snapshot["successes"] == 1


def test_breaker_half_open_failure_reopens() -> None:
    now = [0.0]
    breaker = reliability.CircuitBreaker(
        failure_threshold=2,
        recovery_timeout_s=5.0,
        half_open_max_calls=1,
        clock=lambda: now[0],
    )
    breaker.record_failure()
    breaker.record_failure()
    now[0] += 6.0
    assert breaker.allow() is True
    assert breaker.allow() is False  # 同一窗口只放行 half_open_max_calls=1 次探测
    breaker.record_failure()
    assert breaker.state == "open"
    assert breaker.allow() is False


def test_compare_shadow_reports_keys_not_values() -> None:
    primary = {"skills": ["A"], "years": 3, "only_primary": "秘密简历片段"}
    shadow = {"skills": ["A"], "years": 5, "only_shadow": "另一段正文"}
    result = reliability.compare_shadow(primary, shadow)
    assert result["compared_fields"] == 2
    assert result["matched_fields"] == 1
    assert result["agreement_rate"] == 0.5
    assert result["divergent_keys"] == ["years"]
    assert result["primary_only_keys"] == ["only_primary"]
    assert str(result) != ""
    assert "秘密简历片段" not in str(result)


def test_compare_shadow_empty_intersection() -> None:
    result = reliability.compare_shadow({"a": 1}, {"b": 2})
    assert result["agreement_rate"] == 0.0
    assert result["compared_fields"] == 0
