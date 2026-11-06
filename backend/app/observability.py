"""请求级 trace id 与统一日志格式：让一次请求（含后台任务 / AI 出网）可串成一条链路。

- 入口中间件为每个请求生成 `X-Request-Id` 并写进 `ContextVar`：普通日志自动带该 id，
  `asyncio.create_task` 会复制当前上下文，后台画像任务因此能继承「发起它的那次请求」的 id。
- 日志行格式固定为「时间 级别 [request_id] logger: 事件 k=v ...」，时间线可直接按 id 过滤。
- 只记事件与元数据（状态码 / 耗时 / 错误码 / 模型名），**不记**请求体、简历正文、Prompt、API Key。
"""

from __future__ import annotations

import logging
import uuid
from contextvars import ContextVar

REQUEST_ID_HEADER = "X-Request-Id"

#: 无请求上下文（启动期 / CLI / 后台线程）时占位，保证日志格式不出现空括号。
NO_REQUEST_ID = "-"

_request_id: ContextVar[str] = ContextVar("request_id", default=NO_REQUEST_ID)


def get_request_id() -> str:
    return _request_id.get()


def new_request_id() -> str:
    return uuid.uuid4().hex


def set_request_id(request_id: str) -> object:
    """写入当前上下文，返回供 `reset_request_id` 还原的 token。"""
    return _request_id.set(request_id or NO_REQUEST_ID)


def reset_request_id(token: object) -> None:
    _request_id.reset(token)  # type: ignore[arg-type]


class _RequestIdFilter(logging.Filter):
    """把当前 trace id 注入每条日志记录（Formatter 里的 `%(request_id)s` 由此而来）。"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id()
        return True


def _level_of(raw: str) -> int:
    value = getattr(logging, str(raw or "").strip().upper(), None)
    return value if isinstance(value, int) else logging.INFO


def configure_logging(level: str = "INFO") -> None:
    """进程级日志初始化（幂等）：重复 `create_app()`（测试）不会叠加 handler。"""
    root = logging.getLogger()
    root.setLevel(_level_of(level))
    for handler in root.handlers:
        if getattr(handler, "_skill_coach_handler", False):
            return
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    handler.addFilter(_RequestIdFilter())
    handler._skill_coach_handler = True  # type: ignore[attr-defined]
    root.addHandler(handler)
