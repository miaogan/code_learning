"""per-user AI 口径的唯一出口（r23）。

职责收在三个函数里，路由层不再自己拼端点 / Key：

- `runtime_for_user(user)`：`own` 用用户三件套，`shared` 用服务端配置；
- `capability_of(user)`：`full | light | none`（heavy 场景是否可用）；
- `client_for(user, level)`：能力闸门 + 内置 Key 配额，通过后返回已装配的 `AIClient`。

Key 加密：Fernet（`cryptography`），主密钥由 `SECRET_KEY` 经 SHA-256 派生；响应只给后 4 位。
"""

import base64
import hashlib
import ipaddress
import socket
from datetime import UTC, datetime
from typing import Any, Literal
from urllib.parse import urlparse

from cryptography.fernet import Fernet, InvalidToken

from app.core import repository
from app.core.config import DEFAULT_JSON_MODE, JSON_MODES, AiRuntime, get_settings
from app.core.errors import (
    AI_KEY_REQUIRED,
    AI_KEY_STORE_UNAVAILABLE,
    AI_QUOTA_EXCEEDED,
    VALIDATION_ERROR,
    AppError,
)
from app.services.ai.ai import AIClient

KEY_MODE_OWN = "own"
KEY_MODE_SHARED = "shared"

CAP_FULL = "full"
CAP_LIGHT = "light"
CAP_NONE = "none"

Capability = Literal["full", "light", "none"]
Level = Literal["light", "heavy"]

_MISSING_USER_KEY = "尚未填写你自己的 API Key，请先在设置页配置"
#: 公网档（默认）的拒绝文案。前端与用例都在断言这句，改动要连带同步。
_SSRF_MESSAGE = "API 地址不允许指向本机、内网或云元数据地址"
#: 内网放行档仍然拒绝的那一类：文案必须解释「为什么放行了内网还拒」。
_SSRF_METADATA_MESSAGE = "API 地址不允许指向云元数据或链路本地地址（内网放行模式也不例外）"

#: 本机别名：公网档拒绝；内网部署里模型常与后端同机（ollama / vLLM / LM Studio），必须允许。
_LOOPBACK_HOST_HINTS = frozenset({"localhost"})
#: 元数据服务常用别名：任何档位都拒绝。
_METADATA_HOST_HINTS = frozenset({"metadata", "metadata.google.internal", "instance-data"})

#: 已知云元数据地址：`ipaddress` 会把它们归进 private / link-local 段，光靠段判断挡不住。
#: 内网部署也常跑在云主机上，这一层不能因为「内网」两个字就丢。
_METADATA_ADDRESSES = frozenset(
    {"169.254.169.254", "169.254.0.23", "100.100.100.200", "fd00:ec2::254"}
)


def _allow_private_endpoints() -> bool:
    """内网放行开关的唯一判据（不要在别处重复读配置）。"""
    return bool(get_settings().ai_allow_private_endpoints)


def _is_blocked_address(address: str, *, allow_private: bool) -> bool:
    """判定解析结果是否落在禁止出网的地址段。

    `allow_private=True`（内网部署）只保留三类拒绝：云元数据、链路本地、组播 / 未指定。
    私网、环回、CGNAT、IPv6 ULA 全部放行 —— 那正是内网模型的形态。

    顺序有讲究：环回必须**先于**「保留段」判断 —— Python 的 `ipaddress` 把 `::1` 同时
    标成 `is_reserved`，而 `localhost` 在这台机器上优先解析成 `::1`；先判 reserved 会把
    「模型跑在本机」这个最常见的单机形态挡在门外。
    """
    addr = ipaddress.ip_address(address.split("%", 1)[0])
    if str(addr) in _METADATA_ADDRESSES:
        return True
    if addr.is_link_local or addr.is_multicast or addr.is_unspecified:
        return True
    if allow_private:
        return False
    return addr.is_reserved or not addr.is_global or addr.is_loopback or addr.is_private


def validate_ai_base_url(base_url: str) -> str:
    """校验用户自带的 AI 端点；`AI_ALLOW_PRIVATE_ENDPOINTS=true` 时放行内网地址。

    r99：实测 `/api/me/ai/test` 会拿表单里的 `base_url` 直接发 POST，可探测内网端口；
    而该端点**不经过** `normalize_ai_settings`，所以两个入口都必须调用本函数：
    保存设置（`PUT /api/me/ai`）与测试连接（`POST /api/me/ai/test`）。

    两档语义：

    - **公网档（默认，`AI_ALLOW_PRIVATE_ENDPOINTS=false`）**：只能指向公网地址，沿用 r99 口径；
    - **内网档（`=true`）**：放行私网 / 环回 —— 内网部署的模型就在
      `http://10.x.x.x:8000/v1` 或 `http://localhost:11434/v1` 上，不放行等于功能不可用 ——
      但仍拒绝云元数据地址与链路本地段。这是刻意保留的：内网机器常常就是云主机，
      元数据服务（`169.254.169.254` / `100.100.100.200` 等）是这层防护里最不能丢的一条。

    校验在 DNS 解析**之后**做，能挡住 localhost、十进制/简写 IP、`*.nip.io` 一类
    把域名解析回 127.0.0.1 的绕过。解析失败时放行：连 DNS 都解析不了，后续请求同样
    发不出去，不构成 SSRF；同时也让 `api.example.test` 这类离线测试桩保持可用。

    残留风险：DNS rebinding（校验时返回公网 IP、真正请求时换成内网 IP）。彻底消除需要
    在 httpx 层把已校验的 IP 钉进连接，本部署是单副本演示机，暂不引入该复杂度；
    配合 `ai_test_timeout_s` 与按 IP 限流，可把探测速度与收益压到很低。
    """
    allow_private = _allow_private_endpoints()
    parsed = urlparse(base_url)
    if parsed.scheme not in ("http", "https"):
        raise AppError(VALIDATION_ERROR, "API 地址必须以 http:// 或 https:// 开头", status=422)
    host = (parsed.hostname or "").strip().rstrip(".").lower()
    if not host:
        raise AppError(VALIDATION_ERROR, "API 地址缺少主机名", status=422)
    if host in _METADATA_HOST_HINTS:
        raise AppError(VALIDATION_ERROR, _SSRF_METADATA_MESSAGE, status=422)
    if host in _LOOPBACK_HOST_HINTS and not allow_private:
        raise AppError(VALIDATION_ERROR, _SSRF_MESSAGE, status=422)
    try:
        port = parsed.port
    except ValueError:
        port = None
    try:
        infos = socket.getaddrinfo(
            host, port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM
        )
    except (socket.gaierror, OSError, ValueError):
        return base_url
    for info in infos:
        try:
            blocked = _is_blocked_address(info[4][0], allow_private=allow_private)
        except ValueError:
            continue
        if blocked:
            raise AppError(
                VALIDATION_ERROR,
                _SSRF_METADATA_MESSAGE if allow_private else _SSRF_MESSAGE,
                status=422,
            )
    return base_url


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
    base_url = validate_ai_base_url((base_url or "").strip().rstrip("/"))
    model = (model or "").strip()
    json_mode = (json_mode or DEFAULT_JSON_MODE).strip()
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
    # 本端点不经过 normalize_ai_settings，必须在这里独立校验，否则「保存被挡、测试照打」。
    # 这里吞掉 AppError 转成 ok=false，保持 AiTestResult 的响应契约不变。
    try:
        base_url = validate_ai_base_url((base_url or "").strip().rstrip("/"))
    except AppError as exc:
        return False, exc.message
    raw_key = (api_key or "").strip() or decrypt_key(stored_key)
    if not (base_url and model and raw_key):
        return False, "请先填写 API 地址、模型名称与 API Key"
    settings = get_settings()
    runtime = AiRuntime(
        provider="user",
        base_url=base_url,
        model=model.strip(),
        api_key=raw_key,
        json_mode=json_mode if json_mode in JSON_MODES else DEFAULT_JSON_MODE,
        timeout_s=min(settings.ai_timeout_s, settings.ai_test_timeout_s),
        max_retries=0,
        ready=True,
    )
    try:
        await AIClient(runtime=runtime).ping()
    except AppError as exc:
        return False, exc.message
    return True, "连接成功"
