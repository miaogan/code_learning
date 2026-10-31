"""FastAPI 应用入口：建库、CORS、统一错误 envelope、路由注册（ARCHITECTURE §3.2–§3.3）。"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import get_settings
from .db import init_db
from .errors import HTTP_ERROR, NOT_FOUND, VALIDATION_ERROR, AppError
from .routers import courses, exam, history, interview, profile, report, resume
from .schemas import HealthResponse

APP_VERSION = "0.1.0"


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    init_db()
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
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(AppError)
    async def handle_app_error(_request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content=exc.to_body())

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(
        _request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        is_missing = exc.status_code == 404
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": NOT_FOUND if is_missing else HTTP_ERROR,
                    "message": "请求的资源不存在" if is_missing else str(exc.detail),
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

    app.include_router(resume.router)
    app.include_router(profile.router)
    app.include_router(interview.router)
    app.include_router(exam.router)
    app.include_router(report.router)
    app.include_router(courses.router)
    app.include_router(history.router)

    @app.get("/health", response_model=HealthResponse, tags=["ops"], summary="探活（AC-8）")
    def health() -> HealthResponse:
        return HealthResponse(
            status="ok",
            version=APP_VERSION,
            ai_configured=settings.ai_configured,
            db="sqlite",
        )

    return app


app = create_app()
