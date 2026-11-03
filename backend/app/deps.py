"""FastAPI 依赖：登录态解析与当前用户注入。

`current_user` **必须是 async**：sync 依赖跑在线程池，`ContextVar` 的写入不会回传到端点
所在的上下文，仓储层就拿不到当前用户 id 了。
"""

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import Depends, Request

from . import repository
from .auth import COOKIE_NAME, token_digest
from .context import set_current_user_id
from .errors import AUTH_DISABLED, AUTH_REQUIRED, AppError


async def current_user(request: Request) -> dict[str, Any]:
    raw = request.cookies.get(COOKIE_NAME, "")
    if not raw:
        raise AppError(AUTH_REQUIRED, "请先登录后再使用", status=401)
    session = repository.get_session(token_digest(raw))
    if session is None:
        raise AppError(AUTH_REQUIRED, "登录已失效，请重新登录", status=401)
    if session["expires_at"] <= datetime.now(UTC).isoformat():
        repository.delete_session(session["token_hash"])
        raise AppError(AUTH_REQUIRED, "登录已过期，请重新登录", status=401)
    user = repository.get_user_by_id(session["user_id"])
    if user is None:
        repository.delete_session(session["token_hash"])
        raise AppError(AUTH_REQUIRED, "登录已失效，请重新登录", status=401)
    if user["disabled"]:
        raise AppError(AUTH_DISABLED, "账号已被停用，请联系管理员", status=403)
    set_current_user_id(user["id"])
    return user


#: 路由签名统一写法：`user: CurrentUser`（避免 `Depends(...)` 出现在参数默认值里，ruff B008）。
CurrentUser = Annotated[dict[str, Any], Depends(current_user)]
