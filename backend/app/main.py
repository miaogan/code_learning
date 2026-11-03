"""FastAPI 应用入口：建库、CORS、统一错误 envelope、路由注册（ARCHITECTURE §3.2–§3.3）。"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import get_settings
from .db import init_db
from .errors import (
    FORBIDDEN,
    HTTP_ERROR,
    METHOD_NOT_ALLOWED,
    NOT_FOUND,
    VALIDATION_ERROR,
    AppError,
)
from .routers import (
    auth,
    courses,
    exam,
    history,
    interview,
    practice,
    profile,
    report,
    resume,
    timeline,
)
from .schemas import HealthResponse
from .services import question_bank

APP_VERSION = "0.1.0"


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    init_db()
    # 启动即补种子（数据不是 DDL，故不进 db.py）：r11 起**每次都跑**幂等导入 + 只补空列——
    # `ON CONFLICT DO NOTHING` 保证重复启动 0 新增，存量库（r10 卷）也能拿到新增题与解析。
    question_bank.ensure_seeded()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
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

    @app.exception_handler(AppError)
    async def handle_app_error(_request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content=exc.to_body())

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(
        _request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        # 框架级 405 默认是英文 detail；这里统一成中文 envelope，其余状态保持透传。
        if exc.status_code == 405:
            code, message = METHOD_NOT_ALLOWED, "该接口不支持此请求方法"
        elif exc.status_code == 404:
            code, message = NOT_FOUND, "请求的资源不存在"
        else:
            code, message = HTTP_ERROR, str(exc.detail)
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": code,
                    "message": message,
                    "retryable": False,
                }
            },
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _request: Request, _exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": VALIDATION_ERROR,
                    "message": "请求参数不合法，请检查后重试",
                    "retryable": False,
                }
            },
        )

    app.include_router(auth.router)
    app.include_router(resume.router)
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
