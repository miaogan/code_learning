"""r23 认证基础设施：密码哈希 / 会话 token / Cookie 口径（标准库实现，零新依赖）。

- 密码：`hashlib.scrypt`（n=2^14, r=8, p=1, dklen=32），存储格式 `scrypt$<salt>$<hash>`。
- 会话：`secrets.token_urlsafe(32)` 明文只进 HttpOnly Cookie，库里只存 SHA-256 摘要。
"""

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

from .config import get_settings

#: 会话 Cookie 名（前端不需要知道，靠 HttpOnly 自动携带）。
COOKIE_NAME = "sc_session"

_PREFIX = "scrypt"
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_DK_LEN = 32
#: 密码长度闭集（前后端都按这个口径提示）。
MIN_PASSWORD_LEN = 8
MAX_PASSWORD_LEN = 72


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt.encode("utf-8"),
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_DK_LEN,
    )
    return f"{_PREFIX}${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """常数时间比较；格式不认识 / 字段缺失一律 `False`（不抛异常）。"""
    try:
        prefix, salt, digest_hex = stored.split("$", 2)
    except ValueError:
        return False
    if prefix != _PREFIX or not salt or not digest_hex:
        return False
    try:
        digest = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt.encode("utf-8"),
            n=_SCRYPT_N,
            r=_SCRYPT_R,
            p=_SCRYPT_P,
            dklen=_DK_LEN,
        )
    except ValueError:
        return False
    return hmac.compare_digest(digest.hex(), digest_hex)


def password_error(password: str) -> str | None:
    """返回中文错误说明；`None` 表示通过。"""
    length = len(password or "")
    if length < MIN_PASSWORD_LEN:
        return f"密码至少 {MIN_PASSWORD_LEN} 位"
    if length > MAX_PASSWORD_LEN:
        return f"密码最多 {MAX_PASSWORD_LEN} 位"
    return None


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def new_session_token() -> tuple[str, str]:
    """返回 `(明文 token, 库里存的 SHA-256 摘要)`。"""
    raw = secrets.token_urlsafe(32)
    return raw, token_digest(raw)


def token_digest(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def session_expiry() -> str:
    days = get_settings().session_days
    return (datetime.now(UTC) + timedelta(days=days)).isoformat()


def set_session_cookie(response: object, raw_token: str) -> None:
    """统一 Cookie 属性：HttpOnly 防 XSS 读取，SameSite=Lax 防跨站 POST 携带。"""
    settings = get_settings()
    response.set_cookie(  # type: ignore[attr-defined]
        key=COOKIE_NAME,
        value=raw_token,
        max_age=settings.session_days * 86400,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )


def clear_session_cookie(response: object) -> None:
    response.delete_cookie(  # type: ignore[attr-defined]
        key=COOKIE_NAME,
        path="/",
        httponly=True,
        samesite="lax",
        secure=get_settings().cookie_secure,
    )
