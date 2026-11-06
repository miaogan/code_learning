"""请求级当前用户上下文。

`repository.py` 是唯一 SQL 出口，但它不知道 HTTP 层；登录态由 `deps.current_user` 写入
本模块的 `ContextVar`（async 依赖，运行在事件循环上下文，写入才会传给端点任务），
仓储层据此给所有 SQL 追加 `AND user_id = ?`。默认值 `'default'` 保证未登录场景
（`/health`、管理员 CLI、存量测试）仍读写同一份旧数据。
"""

from contextvars import ContextVar

DEFAULT_USER_ID = "default"

_current_user_id: ContextVar[str] = ContextVar("current_user_id", default=DEFAULT_USER_ID)


def get_current_user_id() -> str:
    return _current_user_id.get()


def set_current_user_id(user_id: str) -> None:
    _current_user_id.set(user_id or DEFAULT_USER_ID)


def reset_current_user_id() -> None:
    _current_user_id.set(DEFAULT_USER_ID)
