"""r70：按客户端 IP 限流 + 熔断（应用层，JSON envelope + `Retry-After`）。

`conftest` 的 `_isolate_protection` 默认把两项防护关掉（整套用例共用同一个来源 IP），
这里显式开启后验证行为；需要假时钟的用例替换 `rate_limit._now`，不碰标准库 `time`。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app
from app.services import rate_limit

IP_HEADER = "X-Real-IP"


def _enable(monkeypatch: pytest.MonkeyPatch, **env: str) -> None:
    """开启防护并按用例覆盖阈值（`get_settings` 是 lru_cache，改完必须清缓存）。"""
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("BREAKER_ENABLED", "true")
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()
    rate_limit.reset_all()


def test_client_ip_prefers_real_ip() -> None:
    assert rate_limit.client_ip(" 203.0.113.5 ", "10.0.0.1") == "203.0.113.5"
    assert rate_limit.client_ip("", "10.0.0.1") == "10.0.0.1"
    assert rate_limit.client_ip(None, None) == "unknown"


def test_sliding_window_expires(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable(monkeypatch, RATE_LIMIT_API_PER_WINDOW="3", RATE_LIMIT_WINDOW_S="60")
    clock = {"now": 100.0}
    monkeypatch.setattr(rate_limit, "_now", lambda: clock["now"])
    for _ in range(3):
        assert rate_limit.hit("198.51.100.1", rate_limit.BUCKET_API) == 0
    assert rate_limit.hit("198.51.100.1", rate_limit.BUCKET_API) == 60
    # 另一来源 IP 不受影响：桶按 (分档, IP) 隔离。
    assert rate_limit.hit("198.51.100.2", rate_limit.BUCKET_API) == 0
    clock["now"] += 60
    assert rate_limit.hit("198.51.100.1", rate_limit.BUCKET_API) == 0


def test_login_bucket_limited_per_ip(tmp_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _enable(monkeypatch, RATE_LIMIT_AUTH_PER_WINDOW="2")
    with TestClient(app) as client:
        first = client.post(
            "/api/auth/login",
            json={"email": "a@example.com", "password": "wrong-password"},
            headers={IP_HEADER: "203.0.113.7"},
        )
        second = client.post(
            "/api/auth/login",
            json={"email": "b@example.com", "password": "wrong-password"},
            headers={IP_HEADER: "203.0.113.7"},
        )
        third = client.post(
            "/api/auth/login",
            json={"email": "c@example.com", "password": "wrong-password"},
            headers={IP_HEADER: "203.0.113.7"},
        )
        other_ip = client.post(
            "/api/auth/login",
            json={"email": "d@example.com", "password": "wrong-password"},
            headers={IP_HEADER: "203.0.113.8"},
        )
    assert first.status_code == 401 and second.status_code == 401
    assert third.status_code == 429
    body = third.json()["error"]
    assert body["code"] == "RATE_LIMITED"
    assert body["retryable"] is True
    assert int(third.headers["Retry-After"]) >= 1
    assert third.headers.get("X-Request-Id")
    # 换个 IP 依旧走正常业务（401 而非 429）。
    assert other_ip.status_code == 401


def test_health_and_preflight_bypass(tmp_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _enable(monkeypatch, RATE_LIMIT_API_PER_WINDOW="1")
    with TestClient(app) as client:
        assert [client.get("/health").status_code for _ in range(3)] == [200, 200, 200]
        preflight = client.options(
            "/api/auth/login",
            headers={
                "Origin": "http://127.0.0.1:5173",
                "Access-Control-Request-Method": "POST",
            },
        )
    assert preflight.status_code == 200


def test_breaker_denies_with_503_envelope(
    tmp_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable(monkeypatch)
    monkeypatch.setattr(
        rate_limit, "acquire", lambda: rate_limit.Passage(allowed=False, retry_after=2)
    )
    with TestClient(app) as client:
        response = client.get("/api/me", headers={IP_HEADER: "203.0.113.9"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SERVICE_BUSY"
    assert response.json()["error"]["retryable"] is True
    assert response.headers["Retry-After"] == "2"


def test_breaker_inflight_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable(monkeypatch, BREAKER_MAX_INFLIGHT="1")
    first = rate_limit.acquire()
    assert first.allowed
    second = rate_limit.acquire()
    assert not second.allowed and second.retry_after == 1
    rate_limit.release(first, 200)
    third = rate_limit.acquire()
    assert third.allowed
    rate_limit.release(third, 200)


def test_breaker_opens_on_error_ratio_and_recovers(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable(
        monkeypatch,
        BREAKER_MIN_REQUESTS="10",
        BREAKER_ERROR_RATIO="0.5",
        BREAKER_OPEN_S="30",
        BREAKER_WINDOW_S="60",
        BREAKER_MAX_INFLIGHT="64",
    )
    clock = {"now": 500.0}
    monkeypatch.setattr(rate_limit, "_now", lambda: clock["now"])

    for _ in range(10):
        passage = rate_limit.acquire()
        assert passage.allowed
        rate_limit.release(passage, 500)

    opened = rate_limit.acquire()
    assert not opened.allowed and opened.retry_after == 30

    # 冷却结束 → 只放一个探针，其余继续快速失败。
    clock["now"] += 31
    probe = rate_limit.acquire()
    assert probe.allowed and probe.probe
    assert not rate_limit.acquire().allowed
    rate_limit.release(probe, 200)
    assert rate_limit.acquire().allowed


def test_breaker_ignores_4xx(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable(monkeypatch, BREAKER_MIN_REQUESTS="5", BREAKER_ERROR_RATIO="0.5")
    for _ in range(10):
        passage = rate_limit.acquire()
        assert passage.allowed
        rate_limit.release(passage, 401)
    # 4xx 是正常业务反馈，不应打开熔断。
    assert rate_limit.acquire().allowed
