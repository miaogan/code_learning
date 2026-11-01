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
from .routers import (
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
