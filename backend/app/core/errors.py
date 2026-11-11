"""统一错误码与错误包装：全站响应形态见 ARCHITECTURE §3.3。

message 一律中文，且不得包含文件路径、堆栈、模型端点或密钥。
"""

EMPTY_FILE = "EMPTY_FILE"
ENCRYPTED_PDF = "ENCRYPTED_PDF"
FILE_TOO_LARGE = "FILE_TOO_LARGE"
UNSUPPORTED_TYPE = "UNSUPPORTED_TYPE"
PARSE_FAILED = "PARSE_FAILED"
AI_UNAVAILABLE = "AI_UNAVAILABLE"
AI_SCHEMA_INVALID = "AI_SCHEMA_INVALID"
AI_KEY_REQUIRED = "AI_KEY_REQUIRED"
AI_QUOTA_EXCEEDED = "AI_QUOTA_EXCEEDED"
AI_KEY_STORE_UNAVAILABLE = "AI_KEY_STORE_UNAVAILABLE"
AUTH_REQUIRED = "AUTH_REQUIRED"
AUTH_INVALID = "AUTH_INVALID"
AUTH_DISABLED = "AUTH_DISABLED"
AUTH_RATE_LIMITED = "AUTH_RATE_LIMITED"
#: 按客户端 IP 的请求限流（r70）：与 `AUTH_RATE_LIMITED`（按邮箱的登录锁定）口径不同。
RATE_LIMITED = "RATE_LIMITED"
#: 熔断打开 / 在飞请求过载（r70）：快速失败，调用方可按 `Retry-After` 重试。
SERVICE_BUSY = "SERVICE_BUSY"
PASSWORD_INVALID = "PASSWORD_INVALID"
FORBIDDEN = "FORBIDDEN"
NOT_IMPLEMENTED = "NOT_IMPLEMENTED"
NOT_FOUND = "NOT_FOUND"
VALIDATION_ERROR = "VALIDATION_ERROR"
HTTP_ERROR = "HTTP_ERROR"
METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"
#: 未捕获异常的统一出口：message 只有中文兜底文案，堆栈与路径只进服务端日志。
INTERNAL_ERROR = "INTERNAL_ERROR"


class AppError(Exception):
    """携带 HTTP 状态与错误 envelope 的业务异常。"""

    def __init__(self, code: str, message: str, *, status: int = 400, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.retryable = retryable

    def to_body(self) -> dict[str, dict[str, object]]:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "retryable": self.retryable,
            }
        }


def not_implemented(feature: str) -> AppError:
    """脚手架阶段：未接通的链路返回 501，前端据 code 展示「即将接入」而非白屏。"""
    return AppError(
        NOT_IMPLEMENTED,
        f"{feature}尚未接通，本阶段仅交付脚手架",
        status=501,
        retryable=False,
    )
