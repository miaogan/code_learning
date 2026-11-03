"""r23 认证 / 多用户隔离 / 用户自带 Key 的接口级证据。

覆盖：
- 未登录一律 401 AUTH_REQUIRED（`/api/me` 与业务路由）；
- 登录 / 登出 / 错误密码 / 停用账号；
- Key 加密落库、响应只回显后 4 位、`SECRET_KEY` 缺失时拒存（503）；
- 跨用户越权按「不存在」处理（404，不泄露他人资源存在性）；
- `own` 未配置 Key 时高消耗场景不可用（403 AI_KEY_REQUIRED，用户明确要求）；
- `shared` 模式只开 light，并按日配额拦截（429 AI_QUOTA_EXCEEDED）。
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from app import repository
from app.auth import COOKIE_NAME, hash_password, new_session_token, session_expiry
from app.config import get_settings
from app.context import reset_current_user_id, set_current_user_id
from app.errors import AI_KEY_REQUIRED, AI_QUOTA_EXCEEDED
from app.main import app
from app.services import login_guard, user_ai
from fastapi.testclient import TestClient
from tests.conftest import (
    TEST_SECRET_KEY,
    TEST_USER_EMAIL,
    TEST_USER_ID,
    TEST_USER_KEY,
    TEST_USER_PASSWORD,
)

RESUME_TEXT = (
    "教育经历\n2019-2023 计算机科学与技术\n"
    "工作经历\n2023-2026 前端开发工程师\n"
    "技能\nReact TypeScript Python SQLite"
)


@pytest.fixture()
def anonymous(tmp_db: Path, auth_user: dict[str, Any]) -> Iterator[TestClient]:
    """同一个 app，但**不带**登录 Cookie。"""
    with TestClient(app) as test_client:
        yield test_client


def _as_user(client: TestClient, user_id: str) -> None:
    """直接建会话并换 Cookie：用于「切到另一个用户」的越权用例。"""
    raw, digest = new_session_token()
    repository.create_session(token_hash=digest, user_id=user_id, expires_at=session_expiry())
    client.cookies.set(COOKIE_NAME, raw)


def _second_user() -> dict[str, Any]:
    repository.create_user(
        user_id="user-b",
        email="other@example.com",
        password_hash=hash_password("other-password-123"),
        display_name="另一个用户",
        role="member",
        key_mode="own",
    )
    user = repository.get_user_by_id("user-b")
    assert user is not None
    return user


def test_anonymous_is_rejected_everywhere(anonymous: TestClient) -> None:
    for method, path in (
        ("GET", "/api/me"),
        ("GET", "/api/profiles/latest"),
        ("GET", "/api/reports/latest"),
        ("GET", "/api/practice/stats"),
        ("POST", "/api/interviews"),
    ):
        response = anonymous.request(method, path, json={})
        assert response.status_code == 401, f"{method} {path}: {response.text}"
        assert response.json()["error"]["code"] == "AUTH_REQUIRED"


def test_login_sets_http_only_cookie(anonymous: TestClient) -> None:
    response = anonymous.post(
        "/api/auth/login",
        json={"email": TEST_USER_EMAIL, "password": TEST_USER_PASSWORD},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["email"] == TEST_USER_EMAIL
    assert body["key_mode"] == "own"
    assert body["ai_capability"] == "full"
    assert body["ai_masked_key"].startswith("****")

    cookie = response.headers["set-cookie"].lower()
    assert "sc_session=" in cookie
    assert "httponly" in cookie
    assert "samesite=lax" in cookie

    me = anonymous.get("/api/me")
    assert me.status_code == 200 and me.json()["id"] == TEST_USER_ID


def test_login_wrong_password_and_disabled(anonymous: TestClient) -> None:
    bad = anonymous.post(
        "/api/auth/login", json={"email": TEST_USER_EMAIL, "password": "wrong-password"}
    )
    assert bad.status_code == 401
    assert bad.json()["error"]["code"] == "AUTH_INVALID"

    repository.set_user_disabled(TEST_USER_ID, True)
    disabled = anonymous.post(
        "/api/auth/login",
        json={"email": TEST_USER_EMAIL, "password": TEST_USER_PASSWORD},
    )
    assert disabled.status_code == 403
    assert disabled.json()["error"]["code"] == "AUTH_DISABLED"


def test_logout_invalidates_session(client: TestClient) -> None:
    assert client.get("/api/me").status_code == 200
    assert client.post("/api/auth/logout").status_code == 204
    after = client.get("/api/me")
    assert after.status_code == 401
    assert after.json()["error"]["code"] == "AUTH_REQUIRED"


def test_saving_key_never_echoes_plaintext(client: TestClient, tmp_db: Path) -> None:
    plain = "sk-user-own-9876"
    saved = client.put(
        "/api/me/ai",
        json={
            "base_url": "https://api.example.test/v1",
            "model": "user-model",
            "api_key": plain,
            "json_mode": "json_object",
        },
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["key_mode"] == "own"
    assert body["ai_capability"] == "full"
    assert body["ai_masked_key"] == "****9876"
    # 响应体里绝不放明文 / 密文原文。
    assert plain not in saved.text

    with repository.connection() as conn:
        row = conn.execute(
            "SELECT ai_api_key_enc FROM users WHERE id = ?", (TEST_USER_ID,)
        ).fetchone()
    assert row is not None
    stored = str(row["ai_api_key_enc"])
    assert stored and plain not in stored  # 库里是密文
    assert user_ai.decrypt_key(stored) == plain


def test_secret_key_missing_blocks_key_storage(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SECRET_KEY", "")
    get_settings.cache_clear()
    response = client.put(
        "/api/me/ai",
        json={
            "base_url": "https://api.example.test/v1",
            "model": "user-model",
            "api_key": "sk-new",
            "json_mode": "json_object",
        },
    )
    assert response.status_code == 503, response.text
    assert response.json()["error"]["code"] == "AI_KEY_STORE_UNAVAILABLE"
    # 清理：后续用例（同一进程）仍需要 SECRET_KEY 解密夹具里的 Key。
    monkeypatch.setenv("SECRET_KEY", TEST_SECRET_KEY)
    get_settings.cache_clear()


def test_cross_user_resources_are_404(client: TestClient) -> None:
    uploaded = client.post(
        "/api/resumes",
        files={"file": ("resume.txt", RESUME_TEXT.encode("utf-8"), "text/plain")},
    )
    assert uploaded.status_code == 200, uploaded.text
    resume_id = uploaded.json()["resume_id"]

    _second_user()
    _as_user(client, "user-b")

    # B 读 A 的简历 → 404（不是 403：不暴露资源存在性）。
    refused = client.post(f"/api/resumes/{resume_id}/polish", json={})
    assert refused.status_code == 404, refused.text
    assert refused.json()["error"]["code"] == "NOT_FOUND"

    # 画像 / 报告列表同样按用户隔离。
    assert client.get("/api/profiles/latest").status_code == 404
    assert client.get("/api/reports/latest").status_code == 404


def test_own_user_without_key_cannot_use_ai(tmp_db: Path) -> None:
    repository.create_user(
        user_id="user-nokey",
        email="nokey@example.com",
        password_hash=hash_password("nokey-password-123"),
        display_name="未配置 Key 的用户",
        role="member",
        key_mode="own",
    )
    user = repository.get_user_by_id("user-nokey")
    assert user is not None
    assert user_ai.capability_of(user) == "none"

    with TestClient(app) as test_client:
        _as_user(test_client, "user-nokey")
        heavy = test_client.post(
            "/api/interviews",
            json={"profile_id": "anything", "settings": None},
        )
        assert heavy.status_code == 403, heavy.text
        assert heavy.json()["error"]["code"] == AI_KEY_REQUIRED

        uploaded = test_client.post(
            "/api/resumes",
            files={"file": ("resume.txt", RESUME_TEXT.encode("utf-8"), "text/plain")},
        )
        light = test_client.post(f"/api/resumes/{uploaded.json()['resume_id']}/polish", json={})
        assert light.status_code == 403, light.text
        assert a_chinese(light.json()["error"]["message"])


def test_shared_mode_is_light_only_and_quota_limited(
    tmp_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AI_PROVIDER", "")
    monkeypatch.setenv("AI_BASE_URL", "https://api.example.test/v1")
    monkeypatch.setenv("AI_MODEL", "shared-model")
    monkeypatch.setenv("AI_API_KEY", "sk-shared-builtin")
    monkeypatch.setenv("SHARED_AI_DAILY_LIMIT", "2")
    get_settings.cache_clear()

    repository.create_user(
        user_id="user-shared",
        email="shared@example.com",
        password_hash=hash_password("shared-password-123"),
        display_name="内置 Key 用户",
        role="member",
        key_mode="shared",
    )
    user = repository.get_user_by_id("user-shared")
    assert user is not None
    assert user_ai.capability_of(user) == "light"

    # light 可用两次，第三次撞配额。
    user_ai.client_for(user, "light")
    user_ai.client_for(user, "light")
    with pytest.raises(Exception) as limited:
        user_ai.client_for(user, "light")
    assert getattr(limited.value, "code", "") == AI_QUOTA_EXCEEDED

    # heavy 永远不对 shared 开放（消耗大，须自带 Key）。
    with pytest.raises(Exception) as gated:
        user_ai.client_for(user, "heavy")
    assert getattr(gated.value, "code", "") == AI_KEY_REQUIRED


def a_chinese(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text)


def test_second_user_key_isolation(tmp_db: Path, auth_user: dict[str, Any]) -> None:
    """两个用户的 Key 各自加密，互不串用。"""
    user = _second_user()
    assert user["key_mode"] == "own"
    assert user_ai.masked_key(str(user.get("ai_api_key_enc") or "")) == ""
    assert user_ai.decrypt_key(str(user.get("ai_api_key_enc") or "")) == ""

    repository.update_user_ai(
        "user-b",
        base_url="https://api.example.test/v1",
        model="b-model",
        api_key_enc=user_ai.encrypt_key("sk-b-1234"),
        json_mode="json_object",
        updated_at="2026-11-03T00:00:00+00:00",
    )
    refreshed = repository.get_user_by_id("user-b")
    assert refreshed is not None
    assert user_ai.masked_key(str(refreshed["ai_api_key_enc"])) == "****1234"
    # 默认用户（夹具）仍是自己的 Key，没被覆盖。
    default_user = repository.get_user_by_id(TEST_USER_ID)
    assert default_user is not None
    assert user_ai.decrypt_key(str(default_user["ai_api_key_enc"])) == TEST_USER_KEY


def test_password_change_revokes_other_sessions(
    client: TestClient, anonymous: TestClient, auth_user: dict[str, Any]
) -> None:
    """自助改密：当前设备保持登录，其他设备上的旧会话立即失效。"""
    raw, digest = new_session_token()
    repository.create_session(token_hash=digest, user_id=TEST_USER_ID, expires_at=session_expiry())
    anonymous.cookies.set(COOKIE_NAME, raw)
    assert anonymous.get("/api/me").status_code == 200

    changed = client.patch(
        "/api/me/password",
        json={"old_password": TEST_USER_PASSWORD, "new_password": "new-password-123"},
    )
    assert changed.status_code == 204, changed.text

    assert client.get("/api/me").status_code == 200
    assert anonymous.get("/api/me").status_code == 401


def test_me_exposes_shared_quota(tmp_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """设置页要展示内置 Key 今日余量，故 `/api/me` 必须回传已用 / 上限。"""
    monkeypatch.setenv("AI_PROVIDER", "")
    monkeypatch.setenv("AI_BASE_URL", "https://api.example.test/v1")
    monkeypatch.setenv("AI_MODEL", "shared-model")
    monkeypatch.setenv("AI_API_KEY", "sk-shared-builtin")
    monkeypatch.setenv("SHARED_AI_DAILY_LIMIT", "3")
    get_settings.cache_clear()
    try:
        repository.create_user(
            user_id="user-quota",
            email="quota@example.com",
            password_hash=hash_password("quota-password-123"),
            display_name="配额用户",
            role="member",
            key_mode="shared",
        )
        user = repository.get_user_by_id("user-quota")
        assert user is not None
        with TestClient(app) as test_client:
            _as_user(test_client, "user-quota")
            user_ai.client_for(user, "light")
            user_ai.client_for(user, "light")
            body = test_client.get("/api/me").json()
            assert body["key_mode"] == "shared"
            assert body["ai_capability"] == "light"
            assert body["ai_quota_used"] == 2
            assert body["ai_quota_limit"] == 3
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()


def test_clear_own_key_disables_heavy_ai(client: TestClient) -> None:
    """清除自带 Key：能力降为 none，高消耗场景 403；重新填写后恢复 full。"""
    assert client.get("/api/me").json()["ai_capability"] == "full"

    cleared = client.delete("/api/me/ai")
    assert cleared.status_code == 200, cleared.text
    body = cleared.json()
    assert body["ai_capability"] == "none"
    assert body["ai_masked_key"] == ""

    heavy = client.post("/api/interviews", json={"profile_id": "anything", "settings": None})
    assert heavy.status_code == 403, heavy.text
    assert heavy.json()["error"]["code"] == AI_KEY_REQUIRED

    restored = client.put(
        "/api/me/ai",
        json={
            "base_url": "https://api.example.test/v1",
            "model": "user-model",
            "api_key": TEST_USER_KEY,
            "json_mode": "json_object",
        },
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["ai_capability"] == "full"


def test_cross_user_timeline_history_practice_interview_are_isolated(
    client: TestClient,
) -> None:
    """补全隔离证据：面试回溯 / 历史 / 时间线 / 练习统计统统只看得到自己的数据。"""
    repository.insert_run("run-a", "interview", "profile-a", {"plan": []})

    _second_user()
    _as_user(client, "user-b")

    interview = client.get("/api/interviews/run-a")
    assert interview.status_code == 404, interview.text

    history = client.get("/api/history")
    assert history.status_code == 200
    assert "run-a" not in history.text

    timeline = client.get("/api/timeline")
    assert timeline.status_code == 200
    assert timeline.json() == []

    # `hit` 是共享题库的筛选命中数（与用户无关），只看用户维度的两个计数。
    stats = client.get("/api/practice/stats").json()
    assert stats["practiced"] == 0
    assert stats["wrong_total"] == 0


def test_adopt_default_data_moves_legacy_rows(tmp_db: Path) -> None:
    """升级到 r23 后，管理员可通过 adopt-default 把旧数据改挂到自己的账号。"""
    repository.create_user(
        user_id="user-adopt",
        email="adopt@example.com",
        password_hash=hash_password("adopt-password-123"),
        display_name="管理员",
        role="admin",
        key_mode="own",
    )
    repository.insert_run("legacy-run", "interview", "profile-x", {"plan": []})

    migrated = repository.adopt_default_data("user-adopt")
    assert migrated["runs"] == 1

    set_current_user_id("user-adopt")
    try:
        assert repository.get_run("legacy-run") is not None
    finally:
        reset_current_user_id()


def test_login_is_rate_limited_after_repeated_failures(
    anonymous: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """连续输错达到阈值后先锁一段时间，正确密码也不能立刻登录（防口令爆破）。"""
    monkeypatch.setenv("LOGIN_MAX_FAILURES", "3")
    monkeypatch.setenv("LOGIN_LOCKOUT_MINUTES", "1")
    get_settings.cache_clear()
    login_guard.reset_all()
    try:
        for _ in range(3):
            bad = anonymous.post(
                "/api/auth/login",
                json={"email": TEST_USER_EMAIL, "password": "wrong-password"},
            )
            assert bad.status_code == 401
            assert bad.json()["error"]["code"] == "AUTH_INVALID"

        locked = anonymous.post(
            "/api/auth/login",
            json={"email": TEST_USER_EMAIL, "password": TEST_USER_PASSWORD},
        )
        assert locked.status_code == 429, locked.text
        error = locked.json()["error"]
        assert error["code"] == "AUTH_RATE_LIMITED"
        assert error["retryable"] is True
        assert a_chinese(error["message"])
    finally:
        login_guard.reset_all()
        monkeypatch.undo()
        get_settings.cache_clear()


def test_expired_sessions_are_purged_on_login(auth_user: dict[str, Any]) -> None:
    """过期会话在读时不可用，登录时批量清掉，避免 sessions 表无限累积。"""
    user_id = str(auth_user["id"])
    with repository.connection() as conn:
        conn.execute(
            "INSERT INTO sessions (token_hash, user_id, created_at, expires_at) "
            "VALUES (?, ?, ?, ?)",
            ("stale-hash", user_id, "2020-01-01T00:00:00+00:00", "2020-01-02T00:00:00+00:00"),
        )
    # 行确实存在（过期判定在 deps.current_user 层，get_session 只负责读）。
    assert repository.get_session("stale-hash") is not None

    _, digest = new_session_token()
    repository.create_session(token_hash=digest, user_id=user_id, expires_at=session_expiry())
    assert repository.get_session(digest) is not None

    with repository.connection() as conn:
        stale = conn.execute(
            "SELECT 1 FROM sessions WHERE token_hash = ?", ("stale-hash",)
        ).fetchone()
    assert stale is None, "登录后应已批量清理过期会话行"
