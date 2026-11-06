"""r23 认证与用户设置路由：登录 / 登出 / 当前用户 / AI Key / 改密。"""

from datetime import UTC, datetime

from fastapi import APIRouter, Request, Response

from app.core import repository
from app.core.auth import (
    COOKIE_NAME,
    clear_session_cookie,
    hash_password,
    new_session_token,
    normalize_email,
    password_error,
    session_expiry,
    set_session_cookie,
    token_digest,
    verify_password,
)
from app.core.errors import (
    AUTH_DISABLED,
    AUTH_INVALID,
    AUTH_RATE_LIMITED,
    PASSWORD_INVALID,
    VALIDATION_ERROR,
    AppError,
)
from app.deps import CurrentUser
from app.schemas import (
    AiSettingsRequest,
    AiTestRequest,
    AiTestResult,
    LoginRequest,
    MeResponse,
    PasswordChangeRequest,
)
from app.services import login_guard
from app.services.ai import user_ai

router = APIRouter(prefix="/api", tags=["auth"])


def _me(user: dict[str, object]) -> MeResponse:
    used, limit = user_ai.quota_of(user)
    return MeResponse(
        id=str(user["id"]),
        email=str(user["email"]),
        display_name=str(user["display_name"]),
        role=str(user["role"]),
        key_mode=str(user["key_mode"]),  # type: ignore[arg-type]
        ai_capability=user_ai.capability_of(user),
        ai_base_url=str(user.get("ai_base_url") or ""),
        ai_model=str(user.get("ai_model") or ""),
        ai_json_mode=str(user.get("ai_json_mode") or "json_object"),
        ai_masked_key=user_ai.masked_key(str(user.get("ai_api_key_enc") or "")),
        ai_updated_at=str(user.get("ai_updated_at") or ""),
        ai_quota_used=used,
        ai_quota_limit=limit,
    )


@router.post("/auth/login", response_model=MeResponse, summary="登录")
def login(payload: LoginRequest, response: Response) -> MeResponse:
    email = normalize_email(payload.email)
    wait_seconds = login_guard.retry_after(email)
    if wait_seconds > 0:
        minutes = (wait_seconds + 59) // 60
        raise AppError(
            AUTH_RATE_LIMITED,
            f"登录尝试过于频繁，请约 {minutes} 分钟后再试",
            status=429,
            retryable=True,
        )
    user = repository.get_user_by_email(email)
    if user is None or not verify_password(payload.password, str(user["password_hash"])):
        login_guard.register_failure(email)
        raise AppError(AUTH_INVALID, "邮箱或密码不正确", status=401)
    if user["disabled"]:
        raise AppError(AUTH_DISABLED, "账号已被停用，请联系管理员", status=403)
    login_guard.clear(email)
    raw, digest = new_session_token()
    repository.create_session(
        token_hash=digest, user_id=str(user["id"]), expires_at=session_expiry()
    )
    set_session_cookie(response, raw)
    return _me(user)


@router.post("/auth/logout", status_code=204, summary="退出登录")
def logout(request: Request, response: Response) -> Response:
    raw = request.cookies.get(COOKIE_NAME, "")
    if raw:
        repository.delete_session(token_digest(raw))
    clear_session_cookie(response)
    response.status_code = 204
    return response


@router.get("/me", response_model=MeResponse, summary="当前用户")
def me(user: CurrentUser) -> MeResponse:
    return _me(user)


@router.put("/me/ai", response_model=MeResponse, summary="保存自带 AI Key")
def save_ai_settings(payload: AiSettingsRequest, user: CurrentUser) -> MeResponse:
    base_url, model, json_mode = user_ai.normalize_ai_settings(
        base_url=payload.base_url,
        model=payload.model,
        api_key=payload.api_key,
        json_mode=payload.json_mode,
    )
    api_key = payload.api_key.strip()
    if api_key:
        encrypted = user_ai.encrypt_key(api_key)
        #: 填了自己的 Key 即自动切到 `own`：自己的 Key 不受内置 Key 的能力分级限制。
        repository.update_user_key_mode(str(user["id"]), user_ai.KEY_MODE_OWN)
    else:
        encrypted = str(user.get("ai_api_key_enc") or "")
        if not encrypted:
            raise AppError(VALIDATION_ERROR, "请填写 API Key", status=422)
    repository.update_user_ai(
        str(user["id"]),
        base_url=base_url,
        model=model,
        api_key_enc=encrypted,
        json_mode=json_mode,
        updated_at=datetime.now(UTC).isoformat(),
    )
    refreshed = repository.get_user_by_id(str(user["id"]))
    if refreshed is None:
        raise AppError(AUTH_INVALID, "用户不存在，请重新登录", status=401)
    return _me(refreshed)


@router.delete("/me/ai", response_model=MeResponse, summary="清除自带 AI Key")
def clear_ai_settings(user: CurrentUser) -> MeResponse:
    """清除已保存的 Key（保留 Base URL / 模型）：能力降为 `none`，高消耗场景随即不可用。"""
    repository.clear_user_ai_key(str(user["id"]))
    refreshed = repository.get_user_by_id(str(user["id"]))
    if refreshed is None:
        raise AppError(AUTH_INVALID, "用户不存在，请重新登录", status=401)
    return _me(refreshed)


@router.post("/me/ai/test", response_model=AiTestResult, summary="测试 AI 连接")
async def test_ai(payload: AiTestRequest, user: CurrentUser) -> AiTestResult:
    base_url = payload.base_url.strip() or str(user.get("ai_base_url") or "")
    model = payload.model.strip() or str(user.get("ai_model") or "")
    json_mode = payload.json_mode or str(user.get("ai_json_mode") or "json_object")
    ok, message = await user_ai.test_connection(
        base_url=base_url,
        model=model,
        api_key=payload.api_key,
        json_mode=json_mode,
        stored_key=str(user.get("ai_api_key_enc") or ""),
    )
    return AiTestResult(ok=ok, message=message)


@router.patch("/me/password", status_code=204, summary="修改密码")
def change_password(
    payload: PasswordChangeRequest,
    request: Request,
    response: Response,
    user: CurrentUser,
) -> Response:
    if not verify_password(payload.old_password, str(user["password_hash"])):
        raise AppError(PASSWORD_INVALID, "当前密码不正确", status=400)
    reason = password_error(payload.new_password)
    if reason:
        raise AppError(VALIDATION_ERROR, reason, status=422)
    repository.update_user_password(str(user["id"]), hash_password(payload.new_password))
    # 当前这台设备保持登录，其他设备上已发出的会话立即失效。
    raw = request.cookies.get(COOKIE_NAME, "")
    if raw:
        repository.delete_other_sessions(str(user["id"]), token_digest(raw))
    response.status_code = 204
    return response
