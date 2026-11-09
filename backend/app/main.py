"""FastAPI 应用入口：建库、CORS、统一错误 envelope、路由注册（ARCHITECTURE §3.2–§3.3）。

所有请求带 `X-Request-Id`：同一条链路（HTTP → 业务 → AI 出网 → 后台画像任务）的日志
都带该 id，排查时按 id 过滤即可拿到完整时间线（见 `observability.py`）。
"""

import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core import repository
from app.core.config import get_settings
from app.core.db import init_db
from app.core.errors import (
    FORBIDDEN,
    HTTP_ERROR,
    INTERNAL_ERROR,
    METHOD_NOT_ALLOWED,
    NOT_FOUND,
    VALIDATION_ERROR,
    AppError,
)
from app.core.observability import (
    REQUEST_ID_HEADER,
    configure_logging,
    get_request_id,
    new_request_id,
    reset_request_id,
    set_request_id,
)
from app.routers import (
    auth,
    courses,
    eval as eval_router,
    exam,
    history,
    interview,
    practice,
    profile,
    report,
    resume,
    search,
    timeline,
)
from app.schemas import HealthResponse
from app.services.ai.ai import close_ai_pool
from app.services.assessment import question_bank

APP_VERSION = "0.1.0"

logger = logging.getLogger("app.http")


def _log_access(method: str, path: str, status: int, elapsed_ms: int, request_id: str) -> None:
    """访问日志：只记元数据（方法 / 路径 / 状态 / 耗时），不记请求体与查询参数。"""
    line = "http.request request_id=%s method=%s path=%s status=%s duration_ms=%s"
    args = (request_id, method, path, status, elapsed_ms)
    if status >= 500:
        logger.error(line, *args)
    elif status >= 400:
        logger.warning(line, *args)
    else:
        logger.info(line, *args)


def _request_id_of(request: Request) -> str:
    """异常处理器里的 trace id：优先取 `request.state`（上下文可能已随中间件退出被重置）。"""
    return str(getattr(request.state, "request_id", "") or get_request_id())


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    init_db()
    # 启动即补种子（数据不是 DDL，故不进 db.py）：r11 起**每次都跑**幂等导入 + 只补空列——
    # `ON CONFLICT DO NOTHING` 保证重复启动 0 新增，存量库（r10 卷）也能拿到新增题与解析。
    question_bank.ensure_seeded()
    # r51：题库导入后重建 FTS 索引（无 FTS5 能力时数据层自行降级为 LIKE，不影响启动）。
    repository.rebuild_question_search()
    yield
    # 关停时释放 AI 连接池（进程内共享客户端，keep-alive 连接不能留给下一次启动）。
    await close_ai_pool()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(
        title="Skill Coach API",
        version=APP_VERSION,
        description="简历读画像 → 模拟面试/笔试 → 短板报告 → 精选课程",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        # 让浏览器侧也能读到 trace id（前端报错时可直接报给后端按 id 查日志）。
        expose_headers=[REQUEST_ID_HEADER],
    )

    @app.middleware("http")
    async def origin_guard(request: Request, call_next):
        """非安全方法做同源校验：有 Origin 且既不同源、又不在白名单 → 403。

        Cookie 认证已带 `SameSite=Lax`，这一层是纵深防御（也覆盖未来放开跨站 CORS 的场景）。
        """
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            if origin:
                host = request.headers.get("host", "")
                same_host = urlparse(origin).netloc == host
                if not same_host and origin not in settings.cors_origin_list:
                    return JSONResponse(
                        status_code=403,
                        content=AppError(
                            FORBIDDEN, "请求来源不被允许", status=403
                        ).to_body(),
                    )
        return await call_next(request)

    @app.middleware("http")
    async def trace_requests(request: Request, call_next):
        """全链路 trace：生成 request id → 注入日志上下文 → 回写响应头。

        注册顺序在 `origin_guard` 之后 ⇒ 本中间件在外层，403 等提前返回的响应同样带 id。
        `request.state` 里也留一份：未捕获异常由更外层的 ServerErrorMiddleware 处理，
        那时上下文变量已随本中间件退出被重置。
        """
        request_id = new_request_id()
        request.state.request_id = request_id
        token = set_request_id(request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            _log_access(
                request.method, request.url.path, response.status_code, elapsed_ms, request_id
            )
        finally:
            reset_request_id(token)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        request_id = _request_id_of(request)
        log = logger.error if exc.status >= 500 else logger.warning
        log(
            "http.app_error request_id=%s code=%s status=%s path=%s message=%s",
            request_id,
            exc.code,
            exc.status,
            request.url.path,
            exc.message,
        )
        return JSONResponse(
            status_code=exc.status,
            content=exc.to_body(),
            headers={REQUEST_ID_HEADER: request_id},
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        # 框架级 405 默认是英文 detail；这里统一成中文 envelope，其余状态保持透传。
        if exc.status_code == 405:
            code, message = METHOD_NOT_ALLOWED, "该接口不支持此请求方法"
        elif exc.status_code == 404:
            code, message = NOT_FOUND, "请求的资源不存在"
        else:
            code, message = HTTP_ERROR, str(exc.detail)
        request_id = _request_id_of(request)
        if exc.status_code >= 500:
            logger.error(
                "http.framework_error request_id=%s code=%s status=%s path=%s",
                request_id,
                code,
                exc.status_code,
                request.url.path,
            )
        else:
            logger.warning(
                "http.framework_error request_id=%s code=%s status=%s path=%s",
                request_id,
                code,
                exc.status_code,
                request.url.path,
            )
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": code,
                    "message": message,
                    "retryable": False,
                }
            },
            headers={REQUEST_ID_HEADER: request_id},
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        request_id = _request_id_of(request)
        # 只记条数与位置，不记请求体（简历 / 画像草稿全文不进日志）。
        logger.warning(
            "http.validation_error request_id=%s path=%s errors=%s",
            request_id,
            request.url.path,
            len(exc.errors()),
        )
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": VALIDATION_ERROR,
                    "message": "请求参数不合法，请检查后重试",
                    "retryable": False,
                }
            },
            headers={REQUEST_ID_HEADER: request_id},
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, _exc: Exception) -> JSONResponse:
        """未捕获异常兜底：堆栈只进服务端日志，响应给中文 envelope + 同一个 trace id。"""
        request_id = _request_id_of(request)
        logger.exception(
            "http.unhandled request_id=%s path=%s", request_id, request.url.path
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": INTERNAL_ERROR,
                    "message": "服务内部错误，请稍后重试",
                    "retryable": True,
                }
            },
            headers={REQUEST_ID_HEADER: request_id},
        )

    app.include_router(auth.router)
    app.include_router(resume.router)
    # r42：图片识别任务查询端点（与上传端点同文件、独立前缀）。
    app.include_router(resume.jobs_router)
    app.include_router(profile.router)
    app.include_router(interview.router)
    app.include_router(exam.router)
    # r11：练习四端点（/api/practice/paper|answer|stats|wrong-book）纯本地、零 AI，
    # 与笔试共用 `exam.grade_objective()` 与同一张 `question_attempts`。
    app.include_router(practice.router)
    app.include_router(report.router)
    app.include_router(courses.router)
    app.include_router(history.router)
    app.include_router(timeline.router)
    # r51：模型调用质量看板与题目全文检索（只读 / 登录态 / 按用户隔离）。
    app.include_router(eval_router.router)
    app.include_router(search.router)

    @app.get("/health", response_model=HealthResponse, tags=["ops"], summary="探活（AC-8）")
    def health() -> HealthResponse:
        # r9：请求内 live 读取（不是 create_app 的 import 期快照），切供应商后无需重启即可被探活观测。
        # 只透传 `resolve_ai()` 的结果，不在这里做任何就绪判定 / 文案拼接（唯一出口在 config）。
        runtime = get_settings().resolve_ai()
        return HealthResponse(
            status="ok",
            version=APP_VERSION,
            ai_configured=runtime.ready,
            db="sqlite",
            ai_provider=runtime.provider,
            ai_model=runtime.model,
            ai_json_mode=runtime.json_mode,
        )

    return app


app = create_app()
