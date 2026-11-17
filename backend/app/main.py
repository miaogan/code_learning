"""FastAPI 应用入口：建库、CORS、统一错误 envelope、路由注册（ARCHITECTURE §3.2–§3.3）。

所有请求带 `X-Request-Id`：同一条链路（HTTP → 业务 → AI 出网 → 后台画像任务）的日志
都带该 id，排查时按 id 过滤即可拿到完整时间线（见 `observability.py`）。
"""

import asyncio
import logging
import threading
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core import db, redis_cache, repository
from app.core.config import get_settings
from app.core.db import close_pool, init_db
from app.core.errors import (
    FORBIDDEN,
    HTTP_ERROR,
    INTERNAL_ERROR,
    METHOD_NOT_ALLOWED,
    NOT_FOUND,
    RATE_LIMITED,
    SERVICE_BUSY,
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
    coach,
    courses,
    eval as eval_router,
    evidence,
    exam,
    history,
    interview,
    jd,
    jobs,
    leap,
    learn,
    practice,
    profile,
    radar,
    rag,
    report,
    resume,
    search,
    taifu,
    timeline,
)
from app.schemas import HealthResponse
from app.services import radar as radar_service, rate_limit
from app.services.ai.ai import close_ai_pool
from app.services.assessment import question_bank
from app.services.retrieval import indexer as rag_indexer

APP_VERSION = "0.4.0"

logger = logging.getLogger("app.http")
db_logger = logging.getLogger("app.db")
cache_logger = logging.getLogger("app.cache")


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


def _error_response(code: str, message: str, status: int, retry_after: int) -> JSONResponse:
    """限流 / 熔断的快速失败响应：保持 JSON envelope，并带 `Retry-After`（秒）。"""
    return JSONResponse(
        status_code=status,
        content=AppError(code, message, status=status, retryable=True).to_body(),
        headers={"Retry-After": str(max(1, retry_after))},
    )


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    # r97：生产档先做安全校验再碰数据库 —— 配置不安全时宁可按启动失败暴露出来，
    # 也不要「带病上线后被访问到」。开发档 blockers / warnings 恒为空，行为零变化。
    settings = get_settings()
    blockers = settings.production_blockers()
    if blockers:
        raise RuntimeError("生产环境配置不安全，已拒绝启动：" + "；".join(blockers))
    for warning in settings.production_warnings():
        logging.getLogger(__name__).warning("production.config_warning=%s", warning)

    # PG / Redis 都是可恢复的**运行时**依赖：不在 Web 启动路径上同步连库。
    db.reset_runtime()
    # 先启动后台恢复，马上 yield 让 uvicorn 接流量；首次连得上时通常毫秒级初始化，
    # 连不上则优先由完整 SQLite 副本接管；没有副本时才返回可重试的 503。
    # Event 绑定当前 lifespan 的 loop，不能模块级复用（TestClient 每次新建 loop）。
    ready = asyncio.Event()
    _DB_STATE.update(
        state="starting", initialized=False, checked_at=0.0, probe_state="starting",
        ready_event=ready,
    )
    # 无论哪个档位都走同一条启动链：`db.bootstrap()` 内部按 DB_MODE 决定是否探测 PG。
    # 这样「服务启动」和「admin_cli 建号」用的是同一份判定代码，不会各写一套。
    recovery_task = asyncio.create_task(_recover_database(ready))
    # 启动时要先探一次 PostgreSQL（connect_timeout=2s）才能打印「用了哪个库」，
    # 所以给首个就绪窗口留足一次探测的时间；连得上时通常是毫秒级，不受影响。
    try:
        await asyncio.wait_for(ready.wait(), timeout=2.5)
    except TimeoutError:
        db_logger.warning("db.recovery.startup_degraded")
    try:
        radar_service.start_scheduler()
        yield
    finally:
        # 先停恢复 / 调度器，避免连接池关闭后仍在写；DDL / 种子幂等，取消后下次可重试。
        recovery_task.cancel()
        with suppress(asyncio.CancelledError):
            await recovery_task
        # asyncio 取消只取消 await，不会杀掉 to_thread 里的同步恢复；必须等它真实退出
        # 才能关闭连接池，否则后台线程会在 lifespan 结束后继续拿库 / 留下 recovering。
        worker = db.recovery_thread
        if worker is not None:
            await asyncio.to_thread(worker.join)
        await radar_service.stop_scheduler()
        await close_ai_pool()
        close_pool()
        redis_cache.reset_client()


def _run_recovery_thread(worker: threading.Thread, failures: list[Exception]) -> None:
    """等待真实恢复线程收尾，并把同步 DB 异常交还 asyncio 恢复循环处理。"""
    worker.start()
    worker.join()
    if failures:
        raise failures[0]


#: 恢复失败后的退避上限（秒）。确定性失败（例如主库数据撞副本唯一约束）重试多少次都一样，
#: 每 2s 全量重拷一遍只会刷日志、给 PG 加压；退到 30s 仍能在一分钟内自愈。
_RECOVERY_BACKOFF_CAP_S = 30.0


def _exc_brief(exc: BaseException) -> str:
    """异常的单行摘要：带上消息本体，去掉换行，避免把堆栈灌进日志。"""
    text = " ".join(str(exc).split())
    head = f"{type(exc).__name__}: {text}" if text else type(exc).__name__
    return head[:300]


def _backoff_delay(base: float, failures: int) -> float:
    """连续失败后的重试间隔：指数退避，封顶 `_RECOVERY_BACKOFF_CAP_S`。"""
    if failures <= 0:
        return base
    return min(_RECOVERY_BACKOFF_CAP_S, base * 2 ** (failures - 1))


#: 数据库初始化状态：只记状态，不保存异常文本 / DSN（它们绝不能进公开探活响应）。
_DB_STATE: dict[str, object] = {
    "state": "starting",
    "initialized": False,
    "checked_at": 0.0,
    "probe_state": "starting",
}


#: 单机模式下巡检 PostgreSQL 的间隔（秒）。巡检本身不是启动/运行依赖，只用来在
#: 「用户后来把 PG 配好了」时给一次明确告警 —— 单机库里的数据只有它自己一份，
#: 自动切到 PG 等于把它丢掉，所以这里只告警、绝不切换。
_STANDALONE_SUPERVISE_S = 300.0


async def _supervise_standalone() -> None:
    """单机模式的低频巡检：PG 可达时提示「不会自动切换」。

    用 `probe_postgresql_quiet()` 而不是 `ping_postgresql()`：后者走连接池，失败会在
    后台留一轮建连并让 psycopg 打出 `error connecting in 'pool-1'` —— 在「没有 PG」的
    环境里，这条噪声每 5 分钟来一次，正好抵消单机模式的意义。
    """
    if not await asyncio.to_thread(db.probe_postgresql_quiet):
        return
    now = time.monotonic()
    if now - float(_DB_STATE.get("standalone_warn_at", 0.0)) < _STANDALONE_SUPERVISE_S:
        return
    _DB_STATE["standalone_warn_at"] = now
    db_logger.warning(
        "db.standalone.postgres_reachable "
        "hint=不会自动切换；请先迁移数据，或改用 DB_MODE=auto 并换一个空数据目录"
    )


async def _report_cache() -> None:
    """打印缓存层结论：优先 Redis，连不上则进程内缓存（功能不中断，只是不跨进程共享）。

    和数据库一样，用户需要**看得出实际用了谁**：`memory` 与 `degraded` 在业务上都还能跑，
    但前者是「本来就没配」、后者是「配了但连不上」，运维处理方式完全不同。
    """
    try:
        state = await asyncio.to_thread(redis_cache.status)
    except Exception as exc:  # noqa: BLE001 - 探活失败只影响这行日志
        cache_logger.warning("cache.probe.failed error=%s", type(exc).__name__)
        return
    if state == "up":
        cache_logger.info("[缓存层] Redis 可用 → 使用 Redis（限流 / 会话 / 读缓存跨进程共享）")
    elif state == "memory":
        cache_logger.info("[缓存层] 未配置 Redis → 使用进程内缓存（仅单进程有效）")
    else:
        cache_logger.warning("[缓存层] Redis 不可用 → 已降级为进程内缓存（恢复后自动切回）")


async def _recover_database(ready: asyncio.Event | None = None) -> None:
    """启动时选库 + 建表 + 写种子；之后转入守护：PG 回切 / 单机巡检。

    选库这件事只有 `db.bootstrap()` 一个实现（`admin_cli` 也用同一份），这里只负责
    把它放到线程里跑、把结果反映到 `/health`，以及启动之后的长期守护。
    """
    base_interval = max(0.1, get_settings().db_recovery_interval_s)
    delay = base_interval
    consecutive_failures = 0

    # —— 启动决策：只做一次，结果直接决定这个进程用哪个库 ——
    # 失败不重试：典型失败是「SQLite 里有数据却缺权威标记」，那是确定性的配置问题，
    # 重试只会把同一条错误刷满日志。把状态标成 degraded，让 /health 与请求如实反映。
    try:
        backend = await asyncio.to_thread(db.bootstrap)
        await asyncio.to_thread(_seed_business_data, rag_strict=backend != "sqlite")
        _DB_STATE.update(
            state="up", initialized=True, checked_at=time.monotonic(), probe_state="up"
        )
        db_logger.info("db.bootstrap.ready backend=%s", backend)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 - 启动失败必须如实暴露，不能让进程崩
        _DB_STATE.update(state="degraded", initialized=False, probe_state="degraded")
        db_logger.error("db.bootstrap.failed error=%s", _exc_brief(exc))
    finally:
        if ready is not None:
            ready.set()

    # 缓存层结论紧跟着数据库结论打印：两件事都是「实际用了谁」，放在一起读最省事。
    await _report_cache()

    while True:
        # 本轮预探活是否真的拿到 PG 应答：except 分支据此区分「主库健康、只是副本坏了」
        # 与「PG 本身不可达」。仅凭 ready 判断会在首次故障时把未就绪误报成 up。
        pg_answered = False
        if db.is_standalone():
            # auto 模式已经降级到单机：不再跑 PG 恢复（那会一直刷重试告警），
            # 只做低频巡检，PG 变得可达时提示一次「不会自动切换」。
            # **先睡再探**：刚进入单机就立刻探测会让连接池在后台拉起一轮注定超时的建连
            # （psycopg 自己会打 `error connecting in 'pool-1'`），恰好是单机模式要避免的噪声。
            await asyncio.sleep(_STANDALONE_SUPERVISE_S)
            await _supervise_standalone()
            continue
        try:
            runtime = db.runtime_state()
            if (
                db.active_backend() != "postgresql"
                or runtime["mode"] != "online"
                or not runtime["replica_ready"]
            ):
                # 先分清「缺的是什么」，再决定 `/health` 说什么 —— 这两件事的严重程度不同：
                #   · 主库还在、只是兜底副本没建 / 过期：业务一条都没受影响，只该体现在
                #     `db_replica=stale` 上；把 initialized 打回 False 会让探活谎报降级。
                #   · 主库真的不可达：业务只能靠已存在的副本接管，这时才该报 recovering。
                # 判据只能是探活本身，所以在动 `_DB_STATE` 之前先探。
                #
                # PG 不可达时不能进入独占恢复窗口：恢复要拿写锁，失败一次就会把
                # SQLite 模式下本该毫秒级的业务写入挡到请求超时（实测 4s 后 503）。
                # 先做无锁轻量探活，只有 PG 真的应答才值得暂停业务事务去重放/重建。
                try:
                    await asyncio.to_thread(db.ping_postgresql)
                except Exception:
                    _DB_STATE.update(state="recovering", initialized=False)
                    raise
                pg_answered = True
                if db.active_backend() != "postgresql":
                    # 副本已经在服务、PG 也回来了：业务可用但还没回切。
                    _DB_STATE.update(
                        state="degraded", initialized=True,
                        checked_at=time.monotonic(), probe_state="up",
                    )
                failures: list[Exception] = []

                def recover(failures: list[Exception]) -> None:
                    try:
                        with db.recovery():
                            _initialize_pg_database()
                            result = db.replay_pending()
                            db.sync_sqlite_from_pg()
                            db.activate_postgresql()
                            if result["replayed"]:
                                db_logger.info("db.recovery.replayed count=%s", result["replayed"])
                    except Exception as exc:  # noqa: BLE001 - 由 _run_recovery_thread 交还
                        failures.append(exc)

                # 先登记真实线程再启动：取消若恰好落在 to_thread 调度前，退出路径
                # 仍然能等到它结束，不会提前关闭 PG 连接池。
                worker = threading.Thread(target=recover, args=(failures,), name="db-recovery")
                db.recovery_thread = worker
                try:
                    await asyncio.to_thread(_run_recovery_thread, worker, failures)
                finally:
                    # 被取消后 to_thread 仍在运行；再 join 一次是幂等的，确保引用
                    # 指向已结束的线程，lifespan 随后可以安全关闭连接池。
                    worker.join()
                _DB_STATE.update(
                    state="up", initialized=True, checked_at=time.monotonic(), probe_state="up"
                )
                if ready is not None:
                    ready.set()
                db_logger.info("db.recovery.ready backend=%s", db.active_backend())
            else:
                # 在线只做探活，不在每次探活里建 DDL / 重拷整库。
                await asyncio.to_thread(db.ping_postgresql)
            # 本轮没抛异常：清掉退避，回到常规节拍。
            consecutive_failures = 0
            delay = base_interval
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - 恢复失败仍可尝试完整副本
            consecutive_failures += 1
            delay = _backoff_delay(base_interval, consecutive_failures)
            reason = _exc_brief(exc)
            runtime = db.runtime_state()
            primary_ok = (
                pg_answered and bool(runtime["ready"]) and runtime["backend"] == "postgresql"
            )
            if primary_ok:
                # 主库健康、只是副本重建失败（磁盘满 / 副本文件损坏 / 主库数据撞唯一约束）：
                # 业务继续在 PG 上跑，只是暂时失去兜底。把坏掉的兜底当故障扩散到健康主库
                # 是得不偿失的。
                _DB_STATE.update(
                    state="up", initialized=True,
                    checked_at=time.monotonic(), probe_state="up",
                )
                db_logger.warning(
                    "db.replica.rebuild_failed error=%s retry_in=%.0fs", reason, delay
                )
            else:
                # 运行中 PG 故障：只能按**已存在的副本**接管。绝不在这里新建单机库 ——
                # 启动时 `db.bootstrap()` 已经做过一次决策，那时没有 PG 就已经选了单机；
                # 运行中再建一个新单机库，等于把正在服务的 PG 数据换成另一份，必然分叉。
                try:
                    if db.active_backend() != "sqlite" or not db.is_standalone():
                        await asyncio.to_thread(db.activate_sqlite)
                    _DB_STATE.update(
                        state="degraded", initialized=True,
                        checked_at=time.monotonic(), probe_state="up",
                    )
                    db_logger.warning("db.sqlite_fallback.ready error=%s", reason)
                except Exception as fallback_exc:  # noqa: BLE001 - 无完整副本时明确拒绝业务写
                    _DB_STATE.update(state="degraded", initialized=False, probe_state="degraded")
                    db_logger.warning(
                        "db.sqlite_fallback.unavailable error=%s", _exc_brief(fallback_exc)
                    )
            if ready is not None:
                ready.set()
            now = time.monotonic()
            if now - float(_DB_STATE.get("last_log_at", 0.0)) >= 30.0:
                db_logger.warning(
                    "db.recovery.retry backend=%s replica_ready=%s attempts=%s error=%s",
                    runtime["backend"], runtime["replica_ready"],
                    consecutive_failures, reason,
                )
                _DB_STATE["last_log_at"] = now
        await asyncio.sleep(delay)


def _initialize_pg_database() -> None:
    """PostgreSQL 确认可用后的初始化（仅在恢复窗口内调用）：建表 + 写种子。

    与启动决策分离：`db.bootstrap()` 负责「选哪个库」，这里只负责「PG 已选定后补齐结构」。
    两者分开，恢复循环重试时不会重新走一遍探测与降级判定。
    """
    init_db()
    _seed_business_data(rag_strict=True)


def _seed_business_data(*, rag_strict: bool) -> None:
    """业务种子（题库 + 检索索引）：PG 与单机两种形态共用同一份实现。

    `rag_strict` 区分失败语义，刻意不统一：
    - `True`（PG 档，沿用既有行为）：教程索引失败即算初始化失败，交给恢复循环重试；
    - `False`（单机档）：教程索引依赖 embedding 供应商，缺 AI Key 时必然失败，而它是
      **可选增强**，不该把整个服务拖成不可用 —— 降级为跳过并留一条日志。
    """
    question_bank.ensure_seeded()
    # r98：题库检索由 `pg_trgm` GIN 索引支撑，重建入口保留为空操作（索引随写入自动维护）。
    repository.rebuild_question_search()
    # DB 初始化完成前先不让业务报 ready；教程索引在同一线程补。
    if not get_settings().rag_seed_tutorials:
        return
    if rag_strict:
        summary = rag_indexer.ensure_tutorials_indexed()
    else:
        try:
            summary = rag_indexer.ensure_tutorials_indexed()
        except Exception as exc:  # noqa: BLE001 - 可选增强，失败不阻断启动
            logger.warning("rag.tutorial_seed.skipped error=%s", _exc_brief(exc))
            return
    if summary is not None:
        logger.info(
            "rag.tutorial_seed.done skipped=%s tutorial_chunks=%s",
            summary.get("skipped"),
            summary.get("tutorial_chunks"),
        )


def _db_probe_state() -> str:
    """初始化状态 + 短 TTL 的真实轻量查询；故障只降级，绝不让探活抛 503。"""
    if not bool(_DB_STATE["initialized"]):
        return str(_DB_STATE["state"])
    now = time.monotonic()
    if now - float(_DB_STATE.get("checked_at", 0.0)) < 15.0:
        return str(_DB_STATE.get("probe_state", "up"))
    try:
        db.ping()
        state = "up"
    except Exception as exc:  # noqa: BLE001 - /health 必须反映故障而非自己故障
        db_logger.warning("db.health.unavailable error=%s", type(exc).__name__)
        state = "degraded"
    _DB_STATE.update(probe_state=state, checked_at=now)
    return state


#: embedder 探活缓存：/health 被 docker healthcheck 高频调用，探活必须带 TTL。
_EMBEDDER_PROBE: dict[str, object] = {"state": "na", "checked_at": 0.0}


def _embedder_probe_state() -> str:
    """本地 embedder 探活（up / down / na）：60s 缓存 + 1.5s 超时，失败只降级。"""
    settings = get_settings()
    if not settings.ai_embed_model:
        return "na"
    now = time.monotonic()
    if now - float(_EMBEDDER_PROBE["checked_at"]) < 60.0:
        return str(_EMBEDDER_PROBE["state"])
    state = "down"
    base = (settings.ai_embed_base_url or "").rstrip("/")
    # OpenAI 兼容端点的 base 以 /v1 结尾，而 TEI 的健康端点在**根路径** /health ——
    # 直接拼会探到 /v1/health（404）而误报 down（生产实测过）。
    if base.endswith("/v1"):
        base = base[: -len("/v1")]
    if base:
        try:
            resp = httpx.get(base + "/health", timeout=1.5)
            state = "up" if resp.status_code == 200 else "down"
        except Exception:  # noqa: BLE001 - 探活永不抛错：/health 必须始终可用
            state = "down"
    _EMBEDDER_PROBE["state"] = state
    _EMBEDDER_PROBE["checked_at"] = now
    return state


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(
        title="逃跑计划 API",
        version=APP_VERSION,
        description="外包工程师的 AI 应用 / Agent 后端跃迁工作台：简历证据 → 能力验证 → 项目补强",
        # r97：生产档不暴露 /docs、/redoc、/openapi.json —— 接口清单对公网没有使用价值，
        # 只降低扫描与爬取成本。开发 / 测试档保持默认路径，联调零变化。
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None if settings.is_production else "/redoc",
        openapi_url=None if settings.is_production else "/openapi.json",
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
    async def limit_requests(request: Request, call_next):
        """r70：按客户端 IP 限流 + 全局熔断，快速失败且保持 JSON envelope。

        注册顺序在 `trace_requests` 之前 ⇒ 本中间件在内层，提前返回的 429/503 同样带
        `X-Request-Id` 并进访问日志。`/health` 与 CORS 预检完全放行：前者是探活（熔断期间
        也必须能探，否则容器会被误判不健康而重启）；后者由浏览器高频发起且不触达业务。
        """
        if request.method == "OPTIONS" or request.url.path == "/health":
            return await call_next(request)
        cfg = get_settings()
        if cfg.rate_limit_enabled:
            ip = rate_limit.client_ip(
                request.headers.get("x-real-ip"),
                request.client.host if request.client else None,
            )
            wait = rate_limit.hit(ip, rate_limit.bucket_of(request.url.path))
            if wait > 0:
                return _error_response(RATE_LIMITED, "请求过于频繁，请稍后再试", 429, wait)
        passage = rate_limit.acquire()
        if not passage.allowed:
            return _error_response(SERVICE_BUSY, "服务繁忙，请稍后重试", 503, passage.retry_after)
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            # 未捕获异常按 5xx 记：熔断要能观测到「请求直接炸了」。
            rate_limit.release(passage, status)

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
    # r61：学习进度与 7 天计划打卡上云（整份状态读写，按账号隔离）。
    app.include_router(learn.router)
    # r108：跃迁档案看板（岗位差距 / 工程证据 / 面试表达，只读聚合零 AI）。
    app.include_router(leap.router)
    # r110：JD 岗位对位（零 AI 关键词证据 / 缺口清单 / 召对预设，登录态按账号隔离）。
    app.include_router(jd.router)
    # r65：AI 学习教练（检索增强 + 引用白名单校验，材料由前端组装后随请求上传）。
    app.include_router(coach.router)
    # r67：技术雷达（先锋清单 / 采集 / 国子监生成任务，任务按账号隔离）。
    app.include_router(radar.router)
    app.include_router(taifu.router)
    app.include_router(rag.router)
    app.include_router(evidence.router)
    app.include_router(jobs.router)

    @app.get("/health", response_model=HealthResponse, tags=["ops"], summary="探活（AC-8）")
    def health() -> HealthResponse:
        # r9：请求内 live 读取（不是 create_app 的 import 期快照），切供应商后无需重启即可被探活观测。
        # 只透传 `resolve_ai()` 的结果，不在这里做任何就绪判定 / 文案拼接（唯一出口在 config）。
        runtime = get_settings().resolve_ai()
        db_state = _db_probe_state()
        redis_state = redis_cache.status()
        runtime_db = db.runtime_state()
        return HealthResponse(
            # 200 = Web 进程可服务，不等于全部依赖就绪；真正状态看下方分项。
            status="ok" if db_state == "up" and redis_state in ("up", "memory") else "degraded",
            version=APP_VERSION,
            ai_configured=runtime.ready,
            # 当前实际业务读写在哪个库：`postgresql`（正常）/ `sqlite`。
            # `sqlite` 有两种情形，靠 `db_replica` 与 `status` 区分：离线副本正在服务
            # （degraded + ready/stale），或单机模式下的权威库（ok + na）。
            db=db.active_backend(),
            db_status=db_state,
            redis_status=redis_state,
            # ready / stale / na：stale 表示主库在服务、但副本坏了或需要重建（失去兜底）；
            # na 表示**没有副本这个概念** —— 单机模式下 SQLite 就是权威库本身，
            # 报 ready 会假装有兜底、报 stale 会假装兜底坏了，两者都是误导。
            db_replica=(
                "na" if runtime_db["standalone"]
                else ("ready" if runtime_db["replica_ready"] else "stale")
            ),
            # r105：本地 embedder 探活（哈希档恒为 na；远程档 60s 缓存探活一次）。
            rag_embedder=_embedder_probe_state(),
            ai_provider=runtime.provider,
            ai_model=runtime.model,
            ai_json_mode=runtime.json_mode,
        )

    return app


app = create_app()
