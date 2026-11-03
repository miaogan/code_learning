"""per-user AI 口径的唯一出口（r23）。

职责收在三个函数里，路由层不再自己拼端点 / Key：

- `runtime_for_user(user)`：`own` 用用户三件套，`shared` 用服务端配置；
- `capability_of(user)`：`full | light | none`（heavy 场景是否可用）；
- `client_for(user, level)`：能力闸门 + 内置 Key 配额，通过后返回已装配的 `AIClient`。

Key 加密：Fernet（`cryptography`），主密钥由 `SECRET_KEY` 经 SHA-256 派生；响应只给后 4 位。
"""

import base64
import hashlib
from datetime import UTC, datetime
from typing import Any, Literal

from cryptography.fernet import Fernet, InvalidToken

from .. import repository
from ..config import DEFAULT_JSON_MODE, JSON_MODES, AiRuntime, get_settings
from ..errors import (
    AI_KEY_REQUIRED,
    AI_KEY_STORE_UNAVAILABLE,
    AI_QUOTA_EXCEEDED,
    VALIDATION_ERROR,
    AppError,
)
from .ai import AIClient

KEY_MODE_OWN = "own"
KEY_MODE_SHARED = "shared"

CAP_FULL = "full"
CAP_LIGHT = "light"
CAP_NONE = "none"

Capability = Literal["full", "light", "none"]
Level = Literal["light", "heavy"]

_MISSING_USER_KEY = "尚未填写你自己的 API Key，请先在设置页配置"


def _fernet() -> Fernet | None:
    secret = get_settings().secret_key.strip()
    if not secret:
        return None
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())
    return Fernet(key)


def encrypt_key(raw: str) -> str:
    fernet = _fernet()
    if fernet is None:
        raise AppError(
            AI_KEY_STORE_UNAVAILABLE,
            "服务端未配置 SECRET_KEY，暂时无法保存你的 API Key，请联系管理员",
            status=503,
        )
    return fernet.encrypt(raw.strip().encode("utf-8")).decode("utf-8")


def decrypt_key(stored: str) -> str:
    """解密失败一律返回空串（视为「未配置」），绝不把密文或异常抛给上层。"""
    fernet = _fernet()
    if fernet is None or not stored:
        return ""
    try:
        return fernet.decrypt(stored.encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError):
        return ""


def masked_key(stored: str) -> str:
    """只回显后 4 位；没有 key 时返回空串（前端据此显示「未填写」）。"""
    raw = decrypt_key(stored)
    if not raw:
        return ""
    return f"****{raw[-4:]}" if len(raw) > 4 else "****"


def _user_runtime(user: dict[str, Any]) -> AiRuntime:
    settings = get_settings()
    base_url = str(user.get("ai_base_url") or "").strip()
    model = str(user.get("ai_model") or "").strip()
    api_key = decrypt_key(str(user.get("ai_api_key_enc") or ""))
    json_mode = str(user.get("ai_json_mode") or "") or DEFAULT_JSON_MODE
    if json_mode not in JSON_MODES:
        json_mode = DEFAULT_JSON_MODE
    if not (base_url and model and api_key):
        return AiRuntime(
            provider="user",
            base_url=base_url,
            model=model,
            json_mode=json_mode,
            timeout_s=settings.ai_timeout_s,
            max_retries=settings.ai_max_retries,
            ready=False,
            reason=_MISSING_USER_KEY,
        )
    return AiRuntime(
        provider="user",
        base_url=base_url,
        model=model,
        api_key=api_key,
        json_mode=json_mode,
        timeout_s=settings.ai_timeout_s,
        max_retries=settings.ai_max_retries,
        ready=True,
    )


def runtime_for_user(user: dict[str, Any]) -> AiRuntime:
    if str(user.get("key_mode") or "") == KEY_MODE_SHARED:
        return get_settings().resolve_ai()
    return _user_runtime(user)


def capability_of(user: dict[str, Any]) -> Capability:
    runtime = runtime_for_user(user)
    if not runtime.ready:
        return CAP_NONE
    return CAP_LIGHT if str(user.get("key_mode") or "") == KEY_MODE_SHARED else CAP_FULL


def _gate_message(user: dict[str, Any], capability: Capability, level: Level) -> str:
    if capability == CAP_NONE and str(user.get("key_mode") or "") == KEY_MODE_SHARED:
        return "管理员尚未配置内置 AI 服务，请先在设置页填写你自己的 API Key"
    if capability == CAP_NONE:
        return _MISSING_USER_KEY
    return "该功能消耗较大，请先在设置页填写你自己的 API Key"


def _today() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


def quota_of(user: dict[str, Any]) -> tuple[int, int]:
    """内置 Key 今日用量与上限 `(used, limit)`；非 `shared` 恒 `(0, 0)`（上限 0 = 不限）。"""
    if str(user.get("key_mode") or "") != KEY_MODE_SHARED:
        return 0, 0
    return (
        repository.count_ai_usage(str(user["id"]), _today()),
        max(0, get_settings().shared_ai_daily_limit),
    )


def consume_shared_quota(user: dict[str, Any]) -> None:
    """内置 Key 的每日配额：计数按 UTC 自然日，本版不做原子并发控制（单用户低并发）。"""
    limit = max(0, get_settings().shared_ai_daily_limit)
    day = _today()
    used = repository.count_ai_usage(str(user["id"]), day)
    if limit and used >= limit:
        raise AppError(
            AI_QUOTA_EXCEEDED,
            f"今日内置 AI 调用次数已用完（{limit} 次），请明天再试或填写自己的 API Key",
            status=429,
        )
    repository.record_ai_usage(str(user["id"]), day)


def client_for(user: dict[str, Any], level: Level) -> AIClient:
    """能力闸门：full 全开；light 只开 light；none 全禁。内置 Key 通过后计入配额。"""
    runtime = runtime_for_user(user)
    capability = capability_of(user)
    if capability == CAP_NONE or (capability == CAP_LIGHT and level == "heavy"):
        raise AppError(AI_KEY_REQUIRED, _gate_message(user, capability, level), status=403)
    if str(user.get("key_mode") or "") == KEY_MODE_SHARED:
        consume_shared_quota(user)
    return AIClient(runtime=runtime)


def normalize_ai_settings(
    *, base_url: str, model: str, api_key: str, json_mode: str
) -> tuple[str, str, str]:
    """校验并归一保存的 AI 设置；返回 `(base_url, model, json_mode)`，Key 由调用方加密。"""
    base_url = (base_url or "").strip().rstrip("/")
    model = (model or "").strip()
    json_mode = (json_mode or DEFAULT_JSON_MODE).strip()
    if not base_url.startswith(("http://", "https://")):
        raise AppError(VALIDATION_ERROR, "API 地址必须以 http:// 或 https:// 开头", status=422)
    if not model:
        raise AppError(VALIDATION_ERROR, "请填写模型名称", status=422)
    if json_mode not in JSON_MODES:
        raise AppError(VALIDATION_ERROR, "JSON 模式取值不合法", status=422)
    return base_url, model, json_mode


async def test_connection(
    *,
    base_url: str,
    model: str,
    api_key: str,
    json_mode: str,
    stored_key: str,
) -> tuple[bool, str]:
    """设置页「测试连接」：优先用表单里填的 Key，其次用已保存的 Key；失败返回中文原因。"""
    raw_key = (api_key or "").strip() or decrypt_key(stored_key)
    if not (base_url and model and raw_key):
        return False, "请先填写 API 地址、模型名称与 API Key"
    settings = get_settings()
    runtime = AiRuntime(
        provider="user",
        base_url=base_url.strip().rstrip("/"),
        model=model.strip(),
        api_key=raw_key,
        json_mode=json_mode if json_mode in JSON_MODES else DEFAULT_JSON_MODE,
        timeout_s=settings.ai_timeout_s,
        max_retries=0,
        ready=True,
    )
    try:
        await AIClient(runtime=runtime).ping()
    except AppError as exc:
        return False, exc.message
    return True, "连接成功"
