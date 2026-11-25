"""PostgreSQL 主库 + 持久化 SQLite 完整副本的双库访问层。

正常时 PostgreSQL 是唯一权威写库，已提交事务逐笔镜像到 SQLite；PostgreSQL 故障时，
只有带 complete 标记的完整副本才能接管读写。离线业务行与重放日志原子提交，恢复时
暂停业务事务，重放并校验成功后重建副本，再回切 PostgreSQL。不存在用临时空库伪造正常
服务的路径。Redis 不在本模块处理，其进程内缓存降级见 `redis_cache.py`。

`DATABASE_URL` 由 `psycopg_pool.ConnectionPool` 统一连接，`SQLITE_PATH` 指向持久化副本。
为了让 `repository.py` 中的 `?` 占位符不必逐行改写，这里保留薄适配层
（`to_pg_sql()` / `to_sqlite_sql()` + `Connection`）。
**新写的 SQL 可以直接用 `%s`**（`to_pg_sql()` 只在出现 `?` 时才介入）
——但此时 SQL 里的 `LIKE '%kw%'` 要自己写成 `%%kw%%`，那是 psycopg 的原生语义；
用 `?` 则连这层转义都不用管。两条路都通，同一个文件里别混用。

不做迁移框架：只用 CREATE TABLE IF NOT EXISTS + ADD COLUMN IF NOT EXISTS，
字段变更需在 memory.md 记录一次性升级说明。
r3 追加 `timeline_events`（成长时间线的事件快照，`(type, ref_id)` 唯一）——对既有库
反复执行 `init_db()` 即得新表，无迁移语句。
r6 追加 `questions`（题库，`seed/questions.json` 退为唯一导入源）与 `question_attempts`
（客观题作答事件，`(question_id, run_id)` 唯一）——同样反复执行 `init_db()` 即得新表与新索引，
空库由 `services/question_bank.ensure_seeded()` 幂等补种子行。
r11 追加题库第五维 `questions.language`、逐题解析 `questions.explanation` 与作答事件来源
`question_attempts.source`（TECHNICAL §2.1）。`CREATE TABLE IF NOT EXISTS` 不会给
**存量**表补列，故 `init_db()` 用 `_ensure_columns()`（查 `information_schema.columns`
后 `ALTER TABLE ADD COLUMN IF NOT EXISTS`，缺列才动，幂等）。
"""

import atexit
import contextvars
import json
import logging
import re
import sqlite3
import threading
import time
import uuid
from collections.abc import Iterable, Iterator, Sequence
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool, PoolTimeout

from app.core.config import get_settings

logger = logging.getLogger("app.db")


class ReplicaSyncError(RuntimeError):
    """副本重建失败，且已定位到具体表。

    只记异常类型是不够的：生产真实事故里 PG 目录中的唯一索引标记 valid、实际却不拦重复，
    `IntegrityError` 本身不说是哪张表哪条约束，排查得重新写脚本跑一遍。表名必须进日志。
    """

    def __init__(self, table: str, detail: str) -> None:
        super().__init__(f"table={table} detail={detail}")
        self.table = table
        self.detail = detail

#: `_now()` 的 SQL 等价物：UTC 毫秒 + `+00:00` 后缀，与业务层写入的时间串（ISO 8601 UTC）
#: 逐字同构。PG 没有 SQLite 的 `strftime`，`to_char` 的 `MS` 恰好是 3 位毫秒。
#: 保持字符串排序＝时间排序，是既有索引（`ORDER BY created_at DESC`）成立的前提。
SQL_NOW_ISO = "to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.MS') || '+00:00'"

#: 业务层（`repository.py` 149 处 SQL）统一写 `?` 占位符，由下面这层翻译成 psycopg 的 `%s`。
#: 为什么不逐行改成 `%s`：`?` 在原文里是 SQLite 原生写法，一次性脚本替换 149 处字符串
#: 一旦漏改就变成运行期才炸；集中翻译只有一处可测。
_PLACEHOLDER = "?"
_SENTINEL = "\x00"


def to_pg_sql(sql: str) -> str:
    """把 `?` 占位符翻成 `%s`，并转义 SQL 字面量里的 `%`。

    两个动作必须一起做，且顺序不能换：

    - psycopg 用 `%` 解析参数，而检索 SQL 里有 `LIKE '%kw%'` —— 不转义会报
      `there is no parameter $kw`，这类错误只在真连 PG 时才出现（SQLite 下完全正常）；
    - 先把 `?` 换成哨兵、再转义 `%`、最后换回 `%s`。若顺序反了，`%` 转义会把刚插入的
      `%s` 变成 `%%s`（占位符变成字面量），参数个数对不上。

    **只在 SQL 含 `?` 时翻译**（判据从「含 `?` 或 `%`」收紧到此，r98 补）。原判据会把
    直接写 `%s` 的新 SQL 二次转义成 `%%s`，psycopg 报「0 placeholders but N parameters」——
    而 `db.py` 顶部与 `memory.md` 都写着「新写的 SQL 直接用 `%s`」，等于文档教人写必崩的代码。
    收紧后两条路都通：`?` 走翻译，`%s` 原样透传（此时 SQL 里的 `LIKE '%kw%'` 需自己写 `%%`，
    那是 psycopg 的原生语义）。无参 SQL 也走这条分支：simple protocol 不解析 `%`。
    """
    if _PLACEHOLDER not in sql:
        return sql
    return sql.replace(_PLACEHOLDER, _SENTINEL).replace("%", "%%").replace(_SENTINEL, "%s")


#: 活跃数据库由后台协调器切换；普通全局变量确保后台线程的切换对全部请求可见。
_active_backend = "postgresql"
#: 在线 PG 事务结束后同步 SQLite；离线事务的语句在**同一事务**追加到 replay log。
_change_log: contextvars.ContextVar[list[dict[str, Any]] | None] = contextvars.ContextVar(
    "db_change_log", default=None
)
#: 在线语句先入缓冲，PG 提交后才镜像，避免 PG 回滚而 SQLite 已写的分叉。
_pending_sqlite: contextvars.ContextVar[list[dict[str, Any]] | None] = contextvars.ContextVar(
    "pending_sqlite", default=None
)
_coordinator: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "db_coordinator", default=False
)
#: asyncio 取消不会中断 to_thread 中的同步 DB 操作。仅后台恢复任务写、lifespan 读；
#: 不能用 ContextVar：子任务里的 set 不会传播回创建它的 lifespan 上下文。
recovery_thread: threading.Thread | None = None
_recovery_depth: contextvars.ContextVar[int] = contextvars.ContextVar(
    "db_recovery_depth", default=0
)
#: 主库结构维护期间关闭镜像记录：见 `suppress_mirror()`。
_mirror_suppressed: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "db_mirror_suppressed", default=False
)


class _Transaction:
    """当前线程的外层事务；嵌套 connection() 只增加深度，不再次提交。"""

    __slots__ = ("conn", "depth", "thread_id")

    def __init__(self, conn: "Connection") -> None:
        self.conn = conn
        self.depth = 0
        self.thread_id = threading.get_ident()


_current_transaction: contextvars.ContextVar[_Transaction | None] = contextvars.ContextVar(
    "db_current_transaction", default=None
)
_SQLITE_LOCK = threading.RLock()
_STATE_LOCK = threading.RLock()
_STATE = {
    "ready": True,  # PG 尚未建表时由驱动报未初始化；副本就绪前故障不能接管。
    "replica_ready": False,
    "mode": "starting",
    "sync_pending": 0,
    "conflicts": 0,
    "last_sync_at": "",
}

#: 单机模式（r113）：SQLite 是**唯一权威库**，没有 PostgreSQL 可回放。
#: 用普通全局布尔而不是 `_STATE` 项：`connection()` 在已持 `_WRITER_LOCK` 的路径里读它，
#: 再去取 `_STATE_LOCK` 会多一层无谓的锁序约束；与 `_active_backend` 同样是「后台线程写、
#: 请求线程读」的单值标记，GIL 下读写原子。
_standalone = False

#: r113 判定「能否把空 SQLite 直接立为权威库」时要看的业务根表：任一有行就说明这个库里
#: 有过真实数据，自动接管会把它当空库覆盖掉，必须拒绝。
_STANDALONE_PROBE_TABLES: tuple[str, ...] = (
    "users", "documents", "profiles", "runs", "reports", "questions", "mirror_cards",
)

_SYNC_TABLES: tuple[str, ...] = ()
_WRITE_RE = re.compile(r"^\s*(?:INSERT|UPDATE|DELETE|REPLACE)\b", re.IGNORECASE)
_CAST_RE = re.compile(r"\?(::[a-zA-Z_][a-zA-Z0-9_]*(?:\[\])?)")
_VECTOR_SQL_RE = re.compile(
    r"SELECT id, kind, ref_id, section_id, title, content, "
    r"1 - \(embedding <=> \?::vector\) AS score "
    r"FROM rag_chunks WHERE embedder = \?(?P<filters>.*?)"
    r" ORDER BY embedding <=> \?::vector LIMIT \?"
)
_NOW_SQLITE = "strftime('%Y-%m-%dT%H:%M:%f', 'now') || '+00:00'"


def to_sqlite_sql(sql: str) -> str:
    """把业务 SQL 中的 PG 方言换成 SQLite；显式给目标库，避免镜像时误用当前后端。"""
    result = sql.replace(SQL_NOW_ISO, _NOW_SQLITE)
    if "embedding <=>" in result:
        match = _VECTOR_SQL_RE.fullmatch(result)
        if not match:
            raise RuntimeError("未识别的向量检索 SQL")
        return (
            "SELECT id, kind, ref_id, section_id, title, content, embedding "
            "FROM rag_chunks WHERE embedder = ?" + match.group("filters") + " LIMIT ?"
        )
    result = _CAST_RE.sub("?", result)
    result = result.replace("ILIKE", "LIKE")
    # PG 的 FILTER 聚合可直接换成两边同义的条件求和。
    result = re.sub(
        r"count\(\*\)\s+FILTER\s*\(WHERE\s+([^\)]+)\)",
        r"sum(CASE WHEN \1 THEN 1 ELSE 0 END)",
        result,
        flags=re.IGNORECASE,
    )
    if "to_regclass('public.questions')" in result:
        return "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'questions'"
    if "pg_tables WHERE schemaname = 'public'" in result:
        return "SELECT count(*) AS n FROM sqlite_master WHERE type = 'table'"
    if "EXTRACT(EPOCH FROM (now() - created_at::timestamptz)) / 60 > ?" in result:
        result = result.replace(
            "EXTRACT(EPOCH FROM (now() - created_at::timestamptz)) / 60 > ?",
            "(julianday('now') - julianday(created_at)) * 1440 > ?",
        )
    return result


def to_active_sql(sql: str) -> str:
    return to_pg_sql(sql) if _active_backend != "sqlite" else to_sqlite_sql(sql)


def _sqlite_params(params: Sequence[Any] | None) -> tuple[Any, ...]:
    """JSON / 向量统一存文本；不将 Python list 直接交给 sqlite3。"""
    return tuple(
        json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else value
        for value in (params or ())
    )


def _execute_raw(
    raw: Any, backend: str, sql: str, params: Sequence[Any] | None = None
) -> Any:
    if backend == "postgresql":
        return raw.execute(to_pg_sql(sql), params or ())
    return raw.execute(to_sqlite_sql(sql), _sqlite_params(params))


def _operation(sql: str, params: Sequence[Any] | None) -> dict[str, Any]:
    return {
        "op_id": uuid.uuid4().hex,
        "sql": sql,
        "params": json.dumps(list(params or ()), ensure_ascii=False, default=str),
    }


def _record_write(sql: str, params: Sequence[Any] | None) -> None:
    if _mirror_suppressed.get():
        return
    if not _WRITE_RE.match(sql):
        return
    # 内部同步表只由本层直接写，不进入离线日志，避免重放后再次制造新操作。
    if "_offline_" in sql:
        return
    for buffer in (_pending_sqlite.get(), _change_log.get()):
        if buffer is not None:
            buffer.append(_operation(sql, params))


class Connection:
    """两种数据库共用的最小连接接口；写语句同步 / 记录由连接上下文统一负责。"""

    __slots__ = ("_raw", "_backend")

    def __init__(self, raw: Any, backend: str = "postgresql") -> None:
        self._raw = raw
        self._backend = backend

    def execute(self, sql: str, params: Sequence[Any] | None = None) -> Any:
        cursor = _execute_raw(self._raw, self._backend, sql, params)
        if self._backend == _active_backend:
            _record_write(sql, params)
        return cursor

    def executemany(self, sql: str, params: Iterable[Sequence[Any]]) -> Any:
        rows = list(params)
        if self._backend == "sqlite":
            # sqlite3 已给 DML 返回正确的 rowcount，且该属性只读；total_changes 还会把
            # 同一连接上的前序语句算进去，不能用于本批次的行数。
            cursor = self._raw.executemany(to_sqlite_sql(sql), [_sqlite_params(p) for p in rows])
        else:
            cursor = self._raw.cursor()
            cursor.executemany(to_pg_sql(sql), rows)
        if self._backend == _active_backend:
            for row in rows:
                _record_write(sql, row)
        return cursor

    def executescript(self, script: str) -> None:
        if self._backend == "sqlite":
            self._raw.executescript(to_sqlite_sql(script))
        else:
            self._raw.execute(script)


#: 多继承保留旧 psycopg 捕获点的兼容，同时覆盖 SQLite 唯一约束异常。
class IntegrityError(psycopg.errors.IntegrityError, sqlite3.IntegrityError):
    """统一的唯一约束冲突，业务层不直接依赖具体驱动的异常。"""


def active_backend() -> str:
    """当前上下文的有效业务库；恢复协调器内部无论旧状态如何都固定读写 PG。"""
    return "postgresql" if _coordinator.get() else _active_backend


def is_standalone() -> bool:
    """SQLite 是否为唯一权威库（单机模式；离线重放与副本镜像在此模式下整体关闭）。"""
    return _standalone


def runtime_state() -> dict[str, Any]:
    with _STATE_LOCK:
        return {"backend": active_backend(), "standalone": _standalone, **_STATE}


#: 连接池是进程级的：`get_settings()` 被测试改写后必须 `close_pool()`，否则旧 DSN 的连接
#: 会继续被复用（表现为「测试改了库却仍读到上一轮数据」）。
_pool: ConnectionPool | None = None
_pool_lock = threading.Lock()
#: 已连上过的连接池即使后来断线，也有后台重连能力，不能因瞬时故障整个丢弃重建。
#: 只有从未成功连接的池需要在重试间隔后重建（池初始建连最终会给放弃）。
#: 已连接池断线由 psycopg_pool 自愈；main 的后台恢复循环负责重新跑幂等初始化。
_pool_ever_connected = False
_pool_retry_at = 0.0
_POOL_RETRY_S = 2.0


def get_pool() -> ConnectionPool:
    """懒建连接池（单例），构造函数立即返回，建连由池的工作线程异步完成。

    绝不在请求线程里同步 `open()`：PG 不可达时那会先等完整连接超时，再抛异常。
    后台恢复任务负责初始化；这里给请求一个有上限的等待，超时翻成中文 503。
    """
    global _pool, _pool_ever_connected, _pool_retry_at
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                settings = get_settings()
                _pool = ConnectionPool(
                    settings.database_url,
                    min_size=settings.db_pool_min_size,
                    max_size=settings.db_pool_max_size,
                    # `prepare_threshold=None` 关闭自动 prepared statement：pgbouncer 的
                    # transaction 模式（公网常见前置）不支持跨事务复用预备语句。
                    # connect_timeout 只限制单次建连，不让它沿用业务取池的长超时。
                    kwargs={
                        "row_factory": dict_row,
                        "prepare_threshold": None,
                        "connect_timeout": 2,
                    },
                    timeout=settings.db_pool_timeout_s,
                    # 首次建连不依赖 reconnect_failed 回调：给池一个正在等待的调用，
                    # 让它自然触发后台 grow；初始失败池由下面的短间隔重建接管。
                    reconnect_timeout=1.0,
                    open=False,
                )
                _pool_ever_connected = False
                _pool_retry_at = time.monotonic() + _POOL_RETRY_S
                _pool.open(wait=False)
    return _pool


def discard_failed_pool() -> None:
    """从未成功建连的池在退避后重建；成功过的断线池交给自身重连。"""
    global _pool, _pool_retry_at
    if _pool_ever_connected or time.monotonic() < _pool_retry_at:
        return
    close_pool()


def close_pool() -> None:
    """关闭并丢弃连接池（进程退出 / 测试切换数据库后调用）。"""
    global _pool, _pool_ever_connected, _pool_retry_at
    with _pool_lock:
        pool, _pool = _pool, None
        _pool_ever_connected = False
        _pool_retry_at = 0.0
    if pool is not None:
        pool.close()


# 解释器退出时兜底关闭：psycopg_pool 的工作线程不随进程退出立刻结束，不显式 close 会在
# stderr 打出 "couldn't stop thread 'pool-1-worker-0' within 5.0 seconds" —— 不影响退出码，
# 但会让每次脚本运行都带一段噪声，排查真问题时容易误判。
atexit.register(close_pool)

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT 'default',
    file_name TEXT NOT NULL,
    mime TEXT NOT NULL,
    chars INTEGER NOT NULL,
    sections INTEGER NOT NULL,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS profiles (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT 'default',
    document_id TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT 'default',
    kind TEXT NOT NULL,
    profile_id TEXT NOT NULL,
    payload TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reports (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT 'default',
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- 既有列不变，只加幂等索引：对既有 app.core.db 反复执行同样安全，无需迁移语句。
CREATE INDEX IF NOT EXISTS idx_runs_kind_created ON runs (kind, created_at);
CREATE INDEX IF NOT EXISTS idx_reports_created ON reports (created_at);

-- r30 异步画像任务：画像生成从「同步阻塞 30 秒」改为「后台任务 + 前端轮询」。
-- status ∈ running | completed | failed；result 存 ProfileWithMerge 的 JSON
-- （含一次性 merge_summary，轮询拿到即完成交付）。
CREATE TABLE IF NOT EXISTS profile_jobs (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL DEFAULT 'default',
    document_id TEXT NOT NULL,
    file_name   TEXT NOT NULL,
    chars       INTEGER NOT NULL,
    sections    INTEGER NOT NULL,
    status      TEXT NOT NULL,
    error       TEXT NOT NULL DEFAULT '',
    result      TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_profile_jobs_user ON profile_jobs (user_id, created_at);

-- r3 成长时间线：事件以 JSON 快照定格（重算报告不回写事件，分数不漂移）。
-- 唯一性写两处、语义等价：表内 `UNIQUE (type, ref_id)` 让「建表即唯一」（新库形态），
-- 显式索引让「既有库 / 半升级状态」也一定唯一（CREATE TABLE IF NOT EXISTS 不会补约束）。
CREATE TABLE IF NOT EXISTS timeline_events (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT 'default',
    type TEXT NOT NULL,
    ref_id TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (type, ref_id)
);

-- 幂等真值：同一 (type, ref_id) 只允许一条事件，`INSERT ... ON CONFLICT DO NOTHING` 依赖它。
CREATE UNIQUE INDEX IF NOT EXISTS idx_timeline_type_ref ON timeline_events (type, ref_id);
-- 读取与「上一次对比」的唯一排序口径：occurred_at DESC, created_at DESC。
CREATE INDEX IF NOT EXISTS idx_timeline_occurred ON timeline_events (occurred_at);

-- r6 题库承载：seed JSON 只做导入源。11 个业务列，answer 只服务端可见（不入任何响应模型）。
-- r11 追加两列：language（第五维；'' = 通用/算法题，闭集单一出处 rules.LANGUAGES）与
-- explanation（逐题解析，全库非空 ≥10 字）。
CREATE TABLE IF NOT EXISTS questions (
    id           TEXT PRIMARY KEY,
    direction    TEXT NOT NULL,
    sub_direction TEXT,                    -- 二级方向（如 python / react / 动态规划）；None = 通用
    kind         TEXT NOT NULL,
    difficulty   TEXT NOT NULL,   -- basic | intermediate | challenge
    essentiality TEXT NOT NULL,   -- must_know | advanced | nice_to_know
    prompt       TEXT NOT NULL,
    options      TEXT NOT NULL,   -- JSON: [{"key","text"}]
    answer       TEXT NOT NULL,   -- JSON: ["B"] / ["A","B","C"] / []（text 型恒 []）
    source       TEXT NOT NULL,   -- 'seed'（本轮唯一取值，为将来题库管理 UI 留位）
    language     TEXT NOT NULL DEFAULT '',   -- '' = 通用/算法
    explanation  TEXT NOT NULL DEFAULT '',   -- 逐题解析
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

-- r6 作答事件：熟练度判定的唯一事实源（只记客观题，简答不计分故永不写入）。
-- r11 追加 source：'exam' | 'practice'（读侧一律以列为准，`practice:<session>` 前缀只作命名空间）。
CREATE TABLE IF NOT EXISTS question_attempts (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL DEFAULT 'default',
    question_id TEXT NOT NULL,
    run_id      TEXT NOT NULL,
    correct     INTEGER NOT NULL,  -- 0/1
    answered_at TEXT NOT NULL,     -- ISO8601 UTC
    created_at  TEXT NOT NULL,
    source      TEXT NOT NULL DEFAULT 'exam',
    UNIQUE (question_id, run_id)   -- 同一卷同一题只有一条事件（重复提交再兜一层）
);
"""

#: 索引独立成脚本：`idx_questions_lang_pool` / 依赖 `source` 的口径必须在**补列之后**执行，
#: 否则存量库上会因「列不存在」直接报错。顺序即约束，只在 `init_db()` 第 3 步跑。
SCHEMA_INDEXES = """
-- 选池的唯一索引：按 (direction, difficulty) 取候选池时不必扫全表。
-- r11 组卷侧排除开关与按语言筛选都需要 language 进索引。
-- r16 二级方向过滤（sub_direction）进第三个索引，按 (direction, sub_direction) 取子池时快。
CREATE INDEX IF NOT EXISTS idx_questions_pool       ON questions (direction, difficulty);
CREATE INDEX IF NOT EXISTS idx_questions_lang_pool  ON questions (language, direction, difficulty);
CREATE INDEX IF NOT EXISTS idx_questions_subdir_pool ON questions (direction, sub_direction, difficulty);

-- 熟练度窗口读取口径：按题取该题的作答序列（`answered_at` 升序）。
-- r11 练习事件按 run 聚合（错题本 / 会话统计）需要 run_id 索引。
CREATE INDEX IF NOT EXISTS idx_attempts_question ON question_attempts (question_id, answered_at);
CREATE INDEX IF NOT EXISTS idx_attempts_run      ON question_attempts (run_id);
"""

#: r23 认证与多用户：三张新表。`users.key_mode ∈ own|shared`；`ai_api_key_enc` 只存密文。
R23_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id              TEXT PRIMARY KEY,
    email           TEXT NOT NULL UNIQUE,
    password_hash   TEXT NOT NULL,
    display_name    TEXT NOT NULL,
    role            TEXT NOT NULL DEFAULT 'member',
    key_mode        TEXT NOT NULL DEFAULT 'own',   -- own | shared
    ai_base_url     TEXT NOT NULL DEFAULT '',
    ai_model        TEXT NOT NULL DEFAULT '',
    ai_api_key_enc  TEXT NOT NULL DEFAULT '',
    ai_json_mode    TEXT NOT NULL DEFAULT 'json_object',
    ai_updated_at   TEXT NOT NULL DEFAULT '',
    disabled        INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash  TEXT PRIMARY KEY,   -- SHA-256(明文 token)，明文只在 Cookie 里
    user_id     TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    expires_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions (user_id);

CREATE TABLE IF NOT EXISTS ai_usage (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    day         TEXT NOT NULL,      -- YYYY-MM-DD（UTC）
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ai_usage_user_day ON ai_usage (user_id, day);
"""

#: r42 图片识别异步任务：图片抽取逐张调视觉模型，单批 1–3 张可达数十秒，
#: 与画像生成同属「长请求」，一并改为服务端持有任务 + 前端轮询。
#: `content_hash` 是同一批图片字节的 SHA-256：同一简历重复提交时命中同一条 running 任务
#: （幂等键），终态后不再拦新提交。`result` 存 `ResumeMeta` JSON，终态完成后可重复读。
R42_SCHEMA = """
CREATE TABLE IF NOT EXISTS resume_jobs (
    id           TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL DEFAULT 'default',
    file_name    TEXT NOT NULL,
    image_count  INTEGER NOT NULL,
    content_hash TEXT NOT NULL DEFAULT '',
    status       TEXT NOT NULL,
    error        TEXT NOT NULL DEFAULT '',
    result       TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_resume_jobs_user ON resume_jobs (user_id, created_at);
"""

#: r42 幂等索引：**部分唯一索引**只约束 running 行，终态行可无限累积（历史任务照常可查）。
#: `profile_jobs` 是存量表，建索引前先跑 `_dedupe_running_profile_jobs()` —— r30 允许重复受理，
#: 旧库里可能已有同一简历的多条 running，直接建唯一索引会失败。
R42_INDEXES = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_profile_jobs_running_doc
    ON profile_jobs (user_id, document_id) WHERE status = 'running';
CREATE UNIQUE INDEX IF NOT EXISTS idx_resume_jobs_running_hash
    ON resume_jobs (user_id, content_hash) WHERE status = 'running';
"""

#: r51 模型调用日志：结构化日志不再「打完就丢」，落库后可聚合成功率 / 延迟分位 / 失败分布。
#: 只记元数据，绝不写 Key / Prompt / 简历正文 / 图片（与 ai.py 的隐私边界一致）。
R51_SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_call_logs (
    id           TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL DEFAULT 'default',
    request_id   TEXT NOT NULL DEFAULT '-',
    provider     TEXT NOT NULL,
    model        TEXT NOT NULL,
    kind         TEXT NOT NULL,
    status_code  INTEGER,
    elapsed_ms   INTEGER NOT NULL,
    attempt      INTEGER NOT NULL DEFAULT 1,
    prompt_chars INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ai_call_logs_created ON ai_call_logs (created_at);
CREATE INDEX IF NOT EXISTS idx_ai_call_logs_user_model ON ai_call_logs (user_id, model, kind);
"""

#: r51 题目全文检索：FTS5 trigram 对中文子串友好。编译选项 / tokenizer 缺失时不建虚表，
#: 由 `repository.search_questions()` 降级为 LIKE，绝不因可选能力阻断启动。
#: r98 题库检索索引：SQLite 的 FTS5 虚表在 PostgreSQL 没有对应物，改用 `pg_trgm` + GIN
#: 支撑 `ILIKE '%kw%'` 子串检索。
#:
#: **为什么不用 tsvector**：`to_tsvector('simple', …)` 把连续中文当成一个词，检索「闭包」
#: 命中不了「闭包是什么」；`zhparser` 要额外编译扩展，部署成本与收益不匹配。trigram 对
#: 中英文子串都能命中，且与 SQLite 时代的 LIKE 降级路径**返回结果完全一致**（只是变快），
#: 检索语义零变化 —— 前端 `mode` 恒为 `like`，不再有「有 FTS / 无 FTS」两种分支。
#:
#: 索引单独建而不与 extension 同脚本：`CREATE EXTENSION` 需要超级用户，托管 PG 常见不给，
#: 失败时只应降级为「无索引扫描」而不是让整个 `init_db()` 挂掉。
R51_TRGM_SCHEMA = """
CREATE INDEX IF NOT EXISTS idx_questions_prompt_trgm
    ON questions USING gin (prompt gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_questions_explanation_trgm
    ON questions USING gin (explanation gin_trgm_ops);
"""


#: r61 学习进度与 7 天计划打卡上云：两张小表按 (user_id, 维度) 存整份状态。
#: `seen` / `done` 存 JSON 文本（与前端 localStorage 结构逐字同构，读写零转换）。
R61_SCHEMA = """
CREATE TABLE IF NOT EXISTS learn_progress (
    user_id         TEXT PRIMARY KEY,
    last_chapter_id TEXT NOT NULL DEFAULT '',
    updated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS learn_chapters (
    user_id         TEXT NOT NULL,
    chapter_id      TEXT NOT NULL,
    seen            TEXT NOT NULL DEFAULT '[]',
    last_section_id TEXT NOT NULL DEFAULT '',
    -- r98：前端传的是毫秒时间戳（13 位），SQLite 的 INTEGER 是 8 字节所以一直没暴露；
    -- PostgreSQL 的 INTEGER 只有 4 字节（上限 2147483647），存 1.7e12 直接
    -- NumericValueOutOfRange。凡是「存时间戳」的整数列一律 BIGINT。
    updated_at      BIGINT NOT NULL DEFAULT 0,
    -- r151 听模式（与前端口播稿结构同构）：`heard` 是已听完的小节 id（JSON 数组，
    -- 与 `seen` 并列、互不顶替——听过 ≠ 读过）；断点是「该章听到哪一节的哪个毫秒」。
    heard              TEXT NOT NULL DEFAULT '[]',
    listen_section_id  TEXT NOT NULL DEFAULT '',
    listen_position_ms BIGINT NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, chapter_id)
);

CREATE TABLE IF NOT EXISTS plan_states (
    user_id       TEXT NOT NULL,
    report_id     TEXT NOT NULL,
    daily_minutes INTEGER NOT NULL DEFAULT 30,
    done          TEXT NOT NULL DEFAULT '{}',
    started_on    TEXT NOT NULL DEFAULT '',
    updated_at    TEXT NOT NULL,
    PRIMARY KEY (user_id, report_id)
);
"""

#: r95 存量库补列：`plan_states` 由 `R61_SCHEMA` 建表，补列须在它之后执行。
#: `started_on` 是「计划起始日」（用户本机日历日 `YYYY-MM-DD`），空串＝还没开始计时。
#: r151 听模式三列：存量库按同一机制补（新库由 R61_SCHEMA 直接建出）。
_R61_ADDED_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("plan_states", "started_on", "TEXT NOT NULL DEFAULT ''"),
    ("learn_chapters", "heard", "TEXT NOT NULL DEFAULT '[]'"),
    ("learn_chapters", "listen_section_id", "TEXT NOT NULL DEFAULT ''"),
    ("learn_chapters", "listen_position_ms", "BIGINT NOT NULL DEFAULT 0"),
)


#: r67 技术雷达：五张表（采集 → 快照 → 评估 → 生成任务 → 采集轮次）。
#: 表名一律 `radar_*` —— `learn_chapters` 已被 r61 学习进度占用，不可复用。
R67_SCHEMA = """
CREATE TABLE IF NOT EXISTS radar_techs (
    tech_slug      TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    direction      TEXT NOT NULL,
    sub_direction  TEXT NOT NULL DEFAULT '',
    source_key     TEXT NOT NULL,
    url            TEXT NOT NULL,
    summary        TEXT NOT NULL DEFAULT '',
    summary_zh     TEXT NOT NULL DEFAULT '',
    first_seen_at  TEXT NOT NULL,
    last_seen_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS radar_snapshots (
    id              INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    tech_slug       TEXT NOT NULL,
    taken_at        TEXT NOT NULL,
    stars           INTEGER NOT NULL DEFAULT 0,
    forks           INTEGER NOT NULL DEFAULT 0,
    repo_created_at TEXT NOT NULL DEFAULT '',
    pushed_at       TEXT NOT NULL DEFAULT '',
    suspect         INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS radar_assessments (
    id             INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    tech_slug      TEXT NOT NULL,
    run_id         INTEGER NOT NULL DEFAULT 0,
    verdict        TEXT NOT NULL,
    relevance      INTEGER NOT NULL,
    adoption       INTEGER NOT NULL,
    maturity       INTEGER NOT NULL,
    effort         INTEGER NOT NULL,
    reasons_json   TEXT NOT NULL DEFAULT '[]',
    evidence_json  TEXT NOT NULL DEFAULT '[]',
    profile_digest TEXT NOT NULL DEFAULT '',
    prompt_version TEXT NOT NULL DEFAULT 'radar-r1',
    model          TEXT NOT NULL DEFAULT '',
    input_sha256   TEXT NOT NULL,
    rule_based     INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS radar_jobs (
    job_id          TEXT PRIMARY KEY,
    tech_slug       TEXT NOT NULL,
    user_id         TEXT NOT NULL DEFAULT 'default',
    status          TEXT NOT NULL DEFAULT 'queued',
    stage           TEXT NOT NULL DEFAULT 'chapter',
    progress        INTEGER NOT NULL DEFAULT 0,
    chapter_json    TEXT NOT NULL DEFAULT '',
    questions_json  TEXT NOT NULL DEFAULT '[]',
    discarded_count INTEGER NOT NULL DEFAULT 0,
    discarded_reasons_json TEXT NOT NULL DEFAULT '{}',
    error_message   TEXT NOT NULL DEFAULT '',
    trigger         TEXT NOT NULL DEFAULT 'manual',
    parent_job_id   TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS radar_runs (
    run_id         INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    trigger        TEXT NOT NULL,
    started_at     TEXT NOT NULL,
    finished_at    TEXT NOT NULL DEFAULT '',
    sources_json   TEXT NOT NULL DEFAULT '[]',
    degraded       INTEGER NOT NULL DEFAULT 0,
    techs_seen     INTEGER NOT NULL DEFAULT 0
);
"""

#: r67 索引：`idx_radar_jobs_active` 是**部分唯一索引**，保证「同一技术同时只 1 个未终态任务」
#: （AC-3 幂等的真值）。建索引前必须先收敛存量 running/queued 行（见 `init_db()` 第 14 步）。
R67_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_radar_snapshots_tech ON radar_snapshots (tech_slug, taken_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_radar_assess_unique
    ON radar_assessments (tech_slug, input_sha256);
CREATE UNIQUE INDEX IF NOT EXISTS idx_radar_jobs_active
    ON radar_jobs (tech_slug) WHERE status IN ('queued', 'running');
CREATE INDEX IF NOT EXISTS idx_radar_jobs_user ON radar_jobs (user_id, created_at);
"""

#: r77 太傅对话：**单线程**（一账号一条对话流），只存对话本身，不存任何业务数据的副本。
#: `citations` 是 JSON 数组 `[{label, href}]`，且只会是白名单校验后的站内路由。
R77_SCHEMA = """
CREATE TABLE IF NOT EXISTS taifu_messages (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL DEFAULT 'default',
    role        TEXT NOT NULL,
    content     TEXT NOT NULL,
    citations   TEXT NOT NULL DEFAULT '[]',
    created_at  TEXT NOT NULL
);
"""

#: r77 索引：读取路径恒为「本账号最近 N 条」，故按 (user_id, created_at) 建索引。
R77_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_taifu_user_created ON taifu_messages (user_id, created_at);
"""

#: r80 太傅线程摘要：一账号一行，存「被窗口挤出后压缩过的早期对话要点」。
#: 与 `taifu_messages` 分开建表而不是加一列：摘要**线程级**，
#: 塞进某条消息会被线程渲染当对话读出来，也会随消息裁剪一起被删。
#: （列名 `memory` 是 r80 的历史命名，r81 起代码里统一叫 summary —— 见 policy 注释。）
R80_SCHEMA = """
CREATE TABLE IF NOT EXISTS taifu_threads (
    user_id     TEXT PRIMARY KEY,
    memory      TEXT NOT NULL DEFAULT '',
    updated_at  TEXT NOT NULL
);
"""

#: r81 太傅长期记忆：**多条**、跨对话，记录「用户口头说过、档案里没有」的稳定事实与偏好。
#: 与 r80 的线程摘要分开：摘要是「这次聊了什么」，清空对话就该清；长期记忆是「你是谁」，
#: 清空对话不碰它，只能由用户在记忆列表里逐条「忘掉」。
R81_SCHEMA = """
CREATE TABLE IF NOT EXISTS taifu_memories (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL DEFAULT 'default',
    content     TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
"""

R81_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_taifu_memories_user ON taifu_memories (user_id, created_at);
"""


#: r100 RAG 检索域：chunk 表 + 索引状态单行表。
#: chunk 是**共享语料**（题库 + 教程正文），与 `questions` 同口径不带 `user_id`——
#: 它是从公开语料派生的索引，不含任何用户简历数据；检索结果也不分属主。
#: `(kind, ref_id, section_id)` 唯一 = 幂等摄取的锚点（同一小节重复推送只更新不翻倍）。
#: `embedding` 列**不在这段 DDL 里**：它的类型（`vector(dim)` vs `double precision[]`）
#: 取决于 pgvector 扩展是否可用，由 `_ensure_rag_embedding_column()` 在建表后单独补。
R100_SCHEMA = """
CREATE TABLE IF NOT EXISTS rag_chunks (
    id          TEXT PRIMARY KEY,
    kind        TEXT NOT NULL,
    ref_id      TEXT NOT NULL,
    section_id  TEXT NOT NULL DEFAULT '',
    title       TEXT NOT NULL DEFAULT '',
    content     TEXT NOT NULL,
    content_sha TEXT NOT NULL,
    embedder    TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    UNIQUE(kind, ref_id, section_id)
);
CREATE INDEX IF NOT EXISTS idx_rag_chunks_kind ON rag_chunks (kind);
CREATE TABLE IF NOT EXISTS rag_index_state (
    key         TEXT PRIMARY KEY,
    embedder    TEXT NOT NULL,
    dim         INTEGER NOT NULL,
    chunk_count INTEGER NOT NULL,
    built_at    TEXT NOT NULL
);
"""


#: r100 B4 教练 Agent 编排轨迹：一次「规划 → 工具 → 反思 → 结论」的完整审计记录。
#: `steps` 是 JSON 数组（每个节点的产出：plan / tool 执行 / reflect），
#: 回答与引用单独列存 —— 轨迹只追加、不改写，`user_id` 隔离与其它业务表一致。
COACH_RUNS_SCHEMA = """
CREATE TABLE IF NOT EXISTS coach_runs (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL DEFAULT 'default',
    question    TEXT NOT NULL,
    goal        TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'completed',
    steps       TEXT NOT NULL DEFAULT '[]',
    answer      TEXT NOT NULL DEFAULT '',
    citations   TEXT NOT NULL DEFAULT '[]',
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_coach_runs_user ON coach_runs (user_id, created_at);
"""


#: r125 镜试：一题一条完整复盘，结构化内容存 JSON，业务 SQL 只在 repository。
#: 与 runs / question_attempts 完全分离；不创建面试场次、不生成成绩、不写成长时间线。
MIRROR_SCHEMA = """
CREATE TABLE IF NOT EXISTS mirror_cards (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL DEFAULT 'default',
    resume_id   TEXT NOT NULL,
    file_name   TEXT NOT NULL DEFAULT '',
    question    TEXT NOT NULL,
    payload     TEXT NOT NULL,
    source      TEXT NOT NULL DEFAULT 'custom',
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mirror_cards_user_created
    ON mirror_cards (user_id, created_at);
"""


#: r103 召回反馈：用户对「某次检索结果里的某条 chunk」点赞 / 点踩。
#: 语义上这是**个人排序信号**（同一用户同一 query 的同一 chunk 只保留最新一票，
#: 换投票＝覆盖），不是全局真理——不同人对同一 chunk 的判断可以相反，
#: 所以 (user_id, query, chunk_id) 才是唯一键，全局聚合只用于看板与评测挖掘。
RAG_FEEDBACK_SCHEMA = """
CREATE TABLE IF NOT EXISTS rag_feedback (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL DEFAULT 'default',
    query       TEXT NOT NULL,
    chunk_id    TEXT NOT NULL,
    verdict     TEXT NOT NULL,
    surface     TEXT NOT NULL DEFAULT 'search',
    created_at  TEXT NOT NULL,
    UNIQUE(user_id, query, chunk_id)
);
CREATE INDEX IF NOT EXISTS idx_rag_feedback_user  ON rag_feedback (user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_rag_feedback_chunk ON rag_feedback (chunk_id, verdict);
"""


#: r129 错题本「移出」：不动作答事件（统计与熟练度口径不变），只记「用户明知这一错仍移出」。
#: 语义：dismissed_at 只掩盖**不晚于它**的错——之后再答错（新事实）会重新进错题本；
#: 主键即唯一约束，重复移出＝刷新时间戳。
WRONG_BOOK_SCHEMA = """
CREATE TABLE IF NOT EXISTS wrong_book_dismissals (
    user_id      TEXT NOT NULL DEFAULT 'default',
    question_id  TEXT NOT NULL,
    dismissed_at TEXT NOT NULL,
    PRIMARY KEY (user_id, question_id)
);
"""

#: r146 先锋学习清单：按账号收藏技术条目（与 radar_jobs 一样带 user_id，按账号隔离）。
#: `UNIQUE (user_id, tech_slug)` 让重复收藏是幂等的；删除是硬删（清单不是历史，不留痕）。
R146_SCHEMA = """
CREATE TABLE IF NOT EXISTS radar_watchlist (
    id         INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    user_id    TEXT NOT NULL,
    tech_slug  TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT '',
    UNIQUE (user_id, tech_slug)
);
CREATE INDEX IF NOT EXISTS idx_radar_watchlist_user ON radar_watchlist (user_id, created_at);
"""


#: r152 nl2sql 审计：一次问答一行，**只写不改**。它是「模型到底生成了什么 SQL」的唯一
#: 回放源，也是发现误拒 / 慢查询 / 越权尝试的事实源（没有它，事后只能靠日志猜）。
#: 两个 SQL 列刻意分开：`sql_text` 是**实际执行**的最终语句（已内联视图、已包外层 LIMIT），
#: `draft_sql` 是模型原文 —— 排查时要看真正跑的东西，看原文只是用来判断模型意图。
NL2SQL_SCHEMA = """
CREATE TABLE IF NOT EXISTS nl2sql_queries (
    id            TEXT PRIMARY KEY,
    user_id       TEXT NOT NULL DEFAULT 'default',
    question      TEXT NOT NULL,
    draft_sql     TEXT NOT NULL DEFAULT '',
    sql_text      TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL,
    reject_reason TEXT NOT NULL DEFAULT '',
    row_count     INTEGER NOT NULL DEFAULT 0,
    elapsed_ms    INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_nl2sql_user_created ON nl2sql_queries (user_id, created_at);
"""


def _try_create_vector() -> bool:
    """尽力创建 pgvector 扩展（幂等），失败只记日志——与 `_try_create_trgm` 同一模式。

    必须用独立连接：DDL 失败会让当前事务 aborted，把「少个扩展」放大成「建库全挂」。
    常见失败原因：镜像不带 pgvector（如官方 postgres:16-alpine）。降级路径是
    `double precision[]` 列 + Python 余弦（见 `rag_embedding_mode`），功能不缺失，
    只是把 top-K 从「索引内算」换成「取回后算」。
    """
    try:
        with connection(force_pg=True) as conn:
            conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        return True
    except psycopg.Error as exc:
        logger.info("db.vector_unavailable error=%s", type(exc).__name__)
        return False


def rag_embedding_mode() -> str:
    """`rag_chunks.embedding` 列的实际形态：'pgvector' | 'array' | 'missing'。

    SQLite 副本固定把向量存 JSON 文本，服务层采用 Python 余弦。
    """
    if active_backend() == "sqlite":
        with connection() as conn:
            row = conn.execute("SELECT 1 AS ok FROM pragma_table_info('rag_chunks') "
                               "WHERE name = 'embedding'").fetchone()
        return "array" if row is not None else "missing"
    """PG 形态从 information_schema 读取。

    判据是 `information_schema.columns.udt_name` 而不是扩展存在性：存量库可能
    在扩展装好之前就以降级形态建过列，`ADD COLUMN IF NOT EXISTS` 不会改已有列类型；
    只认扩展会把这种库错判成 pgvector 形态，查询时才在运行期炸。
    （踩坑实录：不能查 `data_type` —— information_schema 对用户自定义类型一律报
    `'USER-DEFINED'`，pgvector 的 vector 列也如此，判 `"vector"` 永远不成立，
    生产库会永远走 Python 余弦降级。`udt_name` 才有真实类型名：
    pgvector 列 = `'vector'`，double precision[] = `'_float8'`。）
    """
    with connection() as conn:
        row = conn.execute(
            "SELECT udt_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'rag_chunks' "
            "AND column_name = 'embedding'"
        ).fetchone()
    if row is None:
        return "missing"
    return "pgvector" if str(row["udt_name"]) == "vector" else "array"


def _rag_column_shapes(conn: Connection) -> tuple[str, int]:
    """当前连接内查 `rag_chunks.embedding` 的 (类型, 维度)：

    - `("vector", 512)` / `("array", 0)` / `("", 0)`（列不存在）；
    - 维度从 `format_type(atttypid, atttypmod)` 解析（pgvector 把维度存在 atttypmod 里，
      information_schema 的 `character_maximum_length` 对它恒为 NULL，查不到维度）。

    `rag_embedding_mode()` 开自己的连接适合运行期判型；`init_db()` 事务里必须复用当前
    连接（同事务建表后马上判型），所以单留这个内部查询。
    """
    row = conn.execute(
        "SELECT format_type(a.atttypid, a.atttypmod) AS col_type "
        "FROM pg_attribute a "
        "WHERE a.attrelid = to_regclass('public.rag_chunks') "
        "AND a.attname = 'embedding' AND NOT a.attisdropped"
    ).fetchone()
    if row is None:
        return ("", 0)
    col_type = str(row["col_type"] or "")
    if col_type.startswith("vector"):
        if "(" in col_type and ")" in col_type:
            try:
                return ("vector", int(col_type[col_type.find("(") + 1 : col_type.find(")")]))
            except ValueError:
                return ("vector", 0)
        return ("vector", 0)
    return ("array", 0)


def _ensure_rag_embedding_column(conn: Connection, vector_ok: bool) -> None:
    """按 pgvector 可用性补 `rag_chunks.embedding` 列（幂等），并在**引擎/维度变化**时自愈。

    维度取 `AI_EMBED_DIM`（默认 256）：它是索引的一部分，换 embedder 导致维度
    变化时必须改配置并重建索引；插入侧逐条校验 `len(vec) == dim`，不匹配即中文报错。

    两处自愈（都走同一条「派生索引可整体重建」的路）：

    1. **array → pgvector**（先在无扩展镜像跑过，后换 `pgvector/pgvector`）：旧列的
       `double precision[]` 与 `vector(dim)` 没有无损转换（`{...}` 与 `[...]` 格式互斥）；
    2. **维度变化**（如 256 → 512，换 bge-small 这类真语义模型的典型路径）：
       `ADD COLUMN IF NOT EXISTS` 不会改已有列的维度，旧列会让插入直接报
       `expected 256 dimensions, not 512`——提前清空派生索引并按新维度重建列，
       比等到运行期爆炸好。

    两条都清空 `rag_chunks` + `rag_index_state`：chunk 与状态本就是可整体重建的派生
    索引，status 回「未构建」，用户（或考工页）重建即恢复。
    """
    dim = get_settings().ai_embed_dim
    kind, current_dim = _rag_column_shapes(conn)
    if vector_ok:
        if kind and (kind != "vector" or (current_dim and current_dim != dim)):
            logger.info(
                "db.rag_engine_upgrade from=%s dim=%s to=vector dim=%s action=wipe_and_rebuild",
                kind,
                current_dim,
                dim,
            )
            conn.execute("DELETE FROM rag_chunks")
            conn.execute("DELETE FROM rag_index_state")
            conn.execute("ALTER TABLE rag_chunks DROP COLUMN embedding")
        conn.execute(f"ALTER TABLE rag_chunks ADD COLUMN IF NOT EXISTS embedding vector({dim})")
        # r105 修正：原用 ivfflat(lists=100)，但本库 chunk 规模只有千级 —— lists=100 把数据
        # 拆成 100 个桶、默认 probes=1 只扫 1 个桶，近似召回会丢结果（实测 top-3 只回 2 条、
        # 「只搜教程」直接空）。千级数据用 HNSW 更合适：不用调 probes、召回稳定，索引也小。
        conn.execute("DROP INDEX IF EXISTS idx_rag_chunks_embedding")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_rag_chunks_embedding_hnsw "
            "ON rag_chunks USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)"
        )
    else:
        conn.execute(
            "ALTER TABLE rag_chunks ADD COLUMN IF NOT EXISTS embedding double precision[]"
        )


def trgm_available(conn: Connection) -> bool:
    """探测库上是否已装 `pg_trgm` 扩展（缺扩展时检索退化为顺序扫描，功能不受影响）。"""
    try:
        row = conn.execute("SELECT 1 AS ok FROM pg_extension WHERE extname = 'pg_trgm'").fetchone()
    except psycopg.Error:
        return False
    return row is not None


def _try_create_trgm() -> bool:
    """尽力创建 `pg_trgm`（幂等），失败只记日志。

    **必须用独立连接**：DDL 失败会让当前事务进入 aborted 状态，之后该连接上的任何
    语句都报 `current transaction is aborted`，把一次「少个扩展」放大成「建库全挂」。
    托管 PG 常常不给超级用户，这正是要兜住的场景。
    """
    try:
        with connection(force_pg=True) as conn:
            conn.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        return True
    except psycopg.Error as exc:
        logger.warning("db.trgm_unavailable error=%s", type(exc).__name__)
        return False


#: r23 存量 6 表补 `user_id`（DEFAULT 'default' 即回填旧数据）。
_R23_ADDED_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("documents", "user_id", "TEXT NOT NULL DEFAULT 'default'"),
    ("profiles", "user_id", "TEXT NOT NULL DEFAULT 'default'"),
    ("runs", "user_id", "TEXT NOT NULL DEFAULT 'default'"),
    ("reports", "user_id", "TEXT NOT NULL DEFAULT 'default'"),
    ("timeline_events", "user_id", "TEXT NOT NULL DEFAULT 'default'"),
    ("question_attempts", "user_id", "TEXT NOT NULL DEFAULT 'default'"),
)

#: r23 隔离索引：必须在补列之后建（引用 `user_id`）。读写口径按 (user_id, 时间) 过滤。
R23_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_documents_user      ON documents (user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_profiles_user       ON profiles (user_id, updated_at);
CREATE INDEX IF NOT EXISTS idx_runs_user_kind      ON runs (user_id, kind, created_at);
CREATE INDEX IF NOT EXISTS idx_reports_user        ON reports (user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_timeline_user       ON timeline_events (user_id, occurred_at);
CREATE INDEX IF NOT EXISTS idx_attempts_user       ON question_attempts (user_id, answered_at);
"""

#: r11 追加列的唯一清单（表, 列, 列定义）：`_ensure_r11_columns()` 与单测共用同一份，
#: 加一列只改这里，不允许在其他地方再写第二份 ALTER。
_ADDED_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("questions", "language", "TEXT NOT NULL DEFAULT ''"),
    ("questions", "explanation", "TEXT NOT NULL DEFAULT ''"),
    ("questions", "sub_direction", "TEXT"),
    ("question_attempts", "source", "TEXT NOT NULL DEFAULT 'exam'"),
)

#: r67 存量库补列：`radar_jobs` 由 `R67_SCHEMA` 建表，补列必须在建表之后执行，
#: 不能并入 `_ADDED_COLUMNS`（第 2 步时该表还不存在，会对空库直接报 no such table）。
_R67_ADDED_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("radar_jobs", "discarded_reasons_json", "TEXT NOT NULL DEFAULT '{}'"),
    # r74 摘要中文化：采集到的 GitHub description 是英文，译文单独存一列（英文原文保留可追溯）。
    ("radar_techs", "summary_zh", "TEXT NOT NULL DEFAULT ''"),
)



#: r98 起并发写由 PostgreSQL 的行级锁与 MVCC 承担，不再需要 SQLite 时代的 `busy_timeout`
#: 与 WAL 取舍（r53 的 8×50 基准结论仅对单文件库成立）。池获取超时单独可配，见
#: `Settings.db_pool_timeout_s`：等连接超过该秒数即抛错，而不是无限挂住请求。
_ACTIVE_TRANSACTIONS = 0
#: 切换写锁覆盖「选库 → 提交 → 镜像」整个事务；SQLite 仍用独立锁串行写。
#: 当前单进程 uvicorn；部署多 worker 前必须将协调器和 SQLite 文件访问独立成单进程服务。
_WRITER_LOCK = threading.RLock()


def _sqlite_path() -> Path:
    return Path(get_settings().sqlite_path).expanduser().resolve()


def _open_sqlite() -> sqlite3.Connection:
    path = _sqlite_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = sqlite3.connect(path, timeout=3.0)
    try:
        raw.row_factory = sqlite3.Row
        raw.execute("PRAGMA busy_timeout = 3000")
        raw.execute("PRAGMA journal_mode = WAL")
        raw.execute("PRAGMA synchronous = FULL")
    except BaseException:
        # 文件损坏 / 磁盘满时 PRAGMA 就会失败；不关掉句柄会在 Windows 上锁住文件，
        # 后续重建与运维清理都会撞 `WinError 32`。
        raw.close()
        raise
    return raw


def has_sqlite_data() -> bool:
    """SQLite 文件里是否已有真实业务数据（决定能否安全地把它确立为单机权威库）。

    只探业务根表（`_STANDALONE_PROBE_TABLES`），不数 `_sync_state` 之类的内部表 ——
    「表建过但没数据」等于没有数据可丢，允许直接立为权威库。

    读不了（文件损坏 / 无权限）一律返回 True：宁可拒绝接管，也不要把坏文件当空库覆盖。
    """
    if not _sqlite_path().exists():
        return False
    try:
        with closing(_open_sqlite()) as raw:
            existing = {
                str(row["name"])
                for row in raw.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            }
            for table in _STANDALONE_PROBE_TABLES:
                if table not in existing:
                    continue
                if raw.execute(f'SELECT 1 FROM "{table}" LIMIT 1').fetchone() is not None:
                    return True
    except sqlite3.Error as exc:
        _note_sqlite_failure(exc)
        return True
    return False


def standalone_bootstrap_allowed() -> bool:
    """能否把当前 SQLite 直接立为权威库（单机模式的准入判据）。

    判据只有一条：**没有既有数据可丢**。这既是显式 `DB_MODE=sqlite` 的安全底线，
    也是 `auto` 模式自动降级的唯一触发条件 —— 文件不存在 / 空库意味着新建库不覆盖
    任何东西；而「有数据但缺 `complete` 标记」的库仍然是来历不明的半同步副本，
    必须拒绝接管（否则会用一份残缺数据顶替真实主库）。
    """
    return not has_sqlite_data()


def sqlite_marker(key: str) -> str | None:
    """读 SQLite 里 `_sync_state` 的一条标记；库 / 表不存在或读不了时返回 None。

    这是「这个库是什么」的唯一判据：
    - `complete=1`：由 PG 同步出来的完整副本（或已确立的单机权威库）；
    - `standalone=1`：单机权威库，没有 PG 可回放。
    """
    if not _sqlite_path().exists():
        return None
    try:
        with closing(_open_sqlite()) as raw:
            if raw.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = '_sync_state'"
            ).fetchone() is None:
                return None
            row = raw.execute(
                "SELECT value FROM _sync_state WHERE key = ?", (key,)
            ).fetchone()
    except sqlite3.Error as exc:
        _note_sqlite_failure(exc)
        return None
    return None if row is None else str(row["value"])


#: 副本故障日志节流：磁盘写满时每个请求都会失败，不能一请求一条日志。
_last_sqlite_failure_at = 0.0


def _note_sqlite_failure(exc: BaseException) -> None:
    """记录副本自身故障（30s 节流）；只记类型，不写文件路径。"""
    global _last_sqlite_failure_at
    now = time.monotonic()
    if now - _last_sqlite_failure_at < 30.0:
        return
    _last_sqlite_failure_at = now
    logger.error("db.sqlite.unavailable backend=%s error=%s", _active_backend, type(exc).__name__)


@contextmanager
def _raw_pg() -> Iterator[Any]:
    """协调器专用 PG 连接；不走活跃库，避免恢复期间重入 SQLite。"""
    global _pool_ever_connected
    try:
        with get_pool().connection(timeout=max(0.01, get_settings().db_request_timeout_s)) as raw:
            _pool_ever_connected = True
            yield raw
    except (psycopg.OperationalError, psycopg.InterfaceError, PoolTimeout) as exc:
        discard_failed_pool()
        from app.core.errors import database_unavailable

        raise database_unavailable() from exc
    except psycopg.Error as exc:
        # 连接在语句执行 / 提交途中断开同样按可重试故障处理，不泄露 DSN。
        if isinstance(exc, (psycopg.errors.AdminShutdown, psycopg.errors.ConnectionException)):
            from app.core.errors import database_unavailable

            raise database_unavailable() from exc
        raise


#: 回放失败 = 数据分叉（副本里还有未落到 PG 的操作），必须整体停写等人工对账；
#: 副本重建/切换失败只是「失去兜底」，主库健康时不能因此中断业务。写锁保证同一
#: 时刻只有一个恢复窗口，因此这个标记不需要额外加锁。
_replay_failed = False


def _mark_replay_failed() -> None:
    global _replay_failed
    _replay_failed = True


def _consume_replay_failed() -> bool:
    global _replay_failed
    value = _replay_failed
    _replay_failed = False
    return value


def _offline_log_enabled() -> bool:
    """SQLite 写入是否需要记离线重放日志。

    只有「SQLite 是 PG 的完整副本」时才有意义：那时 SQLite 上的写是 PG 不可用期间的
    临时落脚点，PG 恢复后必须按提交顺序回放。单机模式下 SQLite 就是权威库，不存在回放
    对象 —— 继续记录等于给每一笔业务写附一条永远无法消费的垃圾。
    """
    return not _standalone


@contextmanager
def suppress_mirror() -> Iterator[None]:
    """窗口内不把写语句记入副本镜像 / 离线日志。

    只给**主库结构维护**用（`init_db()` 里的建表、存量收敛、ID 游标播种）：这些语句
    不需要逐条镜像 —— 副本与主库的对齐由 `sync_sqlite_from_pg()` 整体重建完成。
    逐条镜像是错的，有两个真实原因：

    - 语句里有纯 PG 方言（`to_char(now() …)`、`to_regclass`），SQLite 解析不了；
    - `INSERT … SELECT … ON CONFLICT DO NOTHING` 这种形态 SQLite 语法上就不接受
      （upsert 不能挂在 `INSERT … SELECT` 上，报 `near "DO": syntax error`）。

    镜像失败会被记成 `db.replica_stale` 并把 `replica_ready` 打回 False —— 一次启动
    就能让 `/health` 谎报降级、并触发一整轮无谓的副本重建。维护语句不进日志即可断根。
    """
    token = _mirror_suppressed.set(True)
    try:
        yield
    finally:
        _mirror_suppressed.reset(token)


@contextmanager
def recovery() -> Iterator[None]:
    """独占恢复窗口：阻止业务事务；恢复步骤仍在同一写锁内重入数据层。"""
    global _active_backend
    with _WRITER_LOCK:
        depth = _recovery_depth.get()
        previous = _STATE["mode"]
        previous_ready = bool(_STATE["ready"])
        previous_backend = _active_backend
        if depth == 0:
            _consume_replay_failed()
            _STATE.update(ready=False, mode="recovering")
        token = _coordinator.set(True)
        depth_token = _recovery_depth.set(depth + 1)
        try:
            yield
        except Exception:
            if depth == 0:
                if _consume_replay_failed():
                    # 回放没完成就放行业务写，会在无法对账的分叉上继续累积。
                    _active_backend = "postgresql"
                    _STATE.update(ready=False, mode="starting")
                else:
                    # 副本重建 / 回切失败：回到进入前的权威库继续服务，只是暂时
                    # 失去兜底。磁盘满、副本损坏都属于这一类，不能把健康的主库拖成 503。
                    _active_backend = previous_backend
                    _STATE.update(ready=previous_ready, mode=previous)
            raise
        finally:
            _recovery_depth.reset(depth_token)
            _coordinator.reset(token)
            if depth == 0 and _STATE["mode"] == "recovering":
                _STATE.update(mode=previous, ready=previous_ready)


@contextmanager
def connection(*, force_pg: bool = False) -> Iterator[Connection]:
    """当前唯一写库的事务。SQLite 写操作和 replay log 原子提交。

    同一线程的嵌套调用复用外层连接，只有最外层提交或回滚。因此一个组合业务操作
    不会在函数边界被拆成多个事务，也不会各自覆盖离线日志缓冲。ContextVar 可能随
    `asyncio.to_thread` 复制到另一线程，所以还必须核对线程 ID，绝不跨线程共用连接。

    正常 PG 提交后才镜像 SQLite；PG 故障的短暂切换窗口仍可能收到 503，协调器
    随即切到已有副本，而不是请求线程各自建一个空库。
    """
    global _ACTIVE_TRANSACTIONS
    current = _current_transaction.get()
    if current is not None and current.thread_id == threading.get_ident():
        if current.conn._backend == active_backend() or (force_pg and _coordinator.get()):
            if force_pg and not _coordinator.get():
                raise RuntimeError("PostgreSQL 专用连接仅允许恢复协调器使用")
            current.depth += 1
            try:
                yield current.conn
            finally:
                current.depth -= 1
            return
        raise RuntimeError("同一业务事务中不能切换权威数据库")
    _WRITER_LOCK.acquire()
    try:
        backend = active_backend()
        if force_pg and not _coordinator.get():
            raise RuntimeError("PostgreSQL 专用连接仅允许恢复协调器使用")
        if force_pg or _coordinator.get():
            backend = "postgresql"
        if not _STATE["ready"] and not _coordinator.get():
            from app.core.errors import database_unavailable

            raise database_unavailable()
        _ACTIVE_TRANSACTIONS += 1
    except Exception:
        _WRITER_LOCK.release()
        raise
    try:
        if backend == "sqlite":
            with _SQLITE_LOCK:
                try:
                    with closing(_open_sqlite()) as raw:
                        raw.execute("BEGIN IMMEDIATE")
                        token = _change_log.set([])
                        transaction = _Transaction(Connection(raw, "sqlite"))
                        transaction.depth = 1
                        transaction_token = _current_transaction.set(transaction)
                        try:
                            yield transaction.conn
                            operations = _change_log.get() or []
                            # 单机模式下没有 PG 可回放：这些记录既不会被消费，也没有对账
                            # 意义，写进去只会让 `_offline_operations` 随业务写入无限增长
                            # （实测每次写都追加一条，长期运行会撑爆磁盘并拖慢提交）。
                            if _offline_log_enabled():
                                for operation in operations:
                                    raw.execute(
                                        "INSERT INTO _offline_operations "
                                        "(op_id, sql_text, params_json) VALUES (?, ?, ?)",
                                        (
                                            operation["op_id"],
                                            operation["sql"],
                                            operation["params"],
                                        ),
                                    )
                            raw.commit()
                            if operations and _offline_log_enabled():
                                with _STATE_LOCK:
                                    _STATE["sync_pending"] += len(operations)
                        except sqlite3.IntegrityError as exc:
                            raw.rollback()
                            raise IntegrityError(str(exc)) from exc
                        except Exception:
                            raw.rollback()
                            raise
                        finally:
                            _current_transaction.reset(transaction_token)
                            _change_log.reset(token)
                except IntegrityError:
                    raise
                except sqlite3.Error as exc:
                    # 副本自身故障（文件损坏 / 磁盘满 / 目录不可写）属于基础设施故障：
                    # 给可重试 503，绝不把 sqlite3 的原始异常冒成 500。
                    _note_sqlite_failure(exc)
                    from app.core.errors import database_unavailable

                    raise database_unavailable() from exc
            return
        token = _pending_sqlite.set([])
        try:
            try:
                with _raw_pg() as raw:
                    transaction = _Transaction(Connection(raw))
                    transaction.depth = 1
                    transaction_token = _current_transaction.set(transaction)
                    try:
                        yield transaction.conn
                    finally:
                        _current_transaction.reset(transaction_token)
            except psycopg.errors.IntegrityError as exc:
                raise IntegrityError(str(exc)) from exc
            operations = _pending_sqlite.get() or []
            if operations and _STATE["replica_ready"]:
                try:
                    with _SQLITE_LOCK:
                        _mirror_operations(operations)
                except (sqlite3.Error, RuntimeError) as exc:
                    # PG 是已提交的事实源；副本失效应触发重建，不能把成功写入翻成失败。
                    _STATE["replica_ready"] = False
                    logger.warning("db.replica_stale error=%s", type(exc).__name__)
            elif operations:
                # 本进程还没确认副本可用（新进程初值即 False）：写 PG 成功但没有镜像。
                # 正在服务的进程对此不可见，`/health` 仍会报 ready——所以外部写入方
                # （admin CLI / 一次性脚本）必须自己调 `refresh_replica()` 补齐。
                logger.info(
                    "db.replica.mirror_skipped count=%s hint=call db.refresh_replica()",
                    len(operations),
                )
        finally:
            _pending_sqlite.reset(token)
    finally:
        _ACTIVE_TRANSACTIONS -= 1
        _WRITER_LOCK.release()


def ping_postgresql() -> None:
    with _raw_pg() as raw:
        raw.execute("SELECT 1")


def probe_postgresql_quiet() -> bool:
    """一次性短连接探活，**不走连接池**，失败只返回 False 不抛。

    专供单机模式的低频巡检：连接池探活即使失败也会在后台留一轮建连尝试，由 psycopg
    自己打出 `error connecting in 'pool-1': connection timeout expired` —— 那正是
    「没有外部依赖」这个模式要消除的噪声。这里用 libpq 的 `connect_timeout` 直接连一次，
    失败静默返回。
    """
    try:
        with psycopg.connect(get_settings().database_url, connect_timeout=1) as raw:
            raw.execute("SELECT 1")
    except Exception:  # noqa: BLE001 - 探活失败是单机模式的正常结果
        return False
    return True


def _mirror_operations(operations: Sequence[dict[str, Any]]) -> None:
    if not operations or active_backend() != "postgresql":
        return
    with closing(_open_sqlite()) as raw:
        raw.execute("BEGIN IMMEDIATE")
        try:
            for operation in operations:
                _execute_raw(
                    raw,
                    "sqlite",
                    str(operation["sql"]),
                    json.loads(str(operation["params"])),
                )
            raw.commit()
        except Exception:
            raw.rollback()
            raise


def activate_sqlite() -> None:
    """切换与所有在途写事务互斥，PG 最后一笔镜像完成后才开放 SQLite。

    两种接管形态由库内标记区分，都要求 `complete='1'`，只是凭证来源不同：

    - `standalone='1'`：单机模式的权威库 —— 权威性不来自 PG，而来自「它被显式声明为
      唯一权威库」（见 `mark_standalone_baseline()`）。没有 PG 可回放，关闭重放日志。
    - 其余：由 PG 同步出来的完整副本，接管期间按离线语义记录重放日志。

    重启后靠持久标记恢复单机语义很关键：否则单机库会被当成「待回放的离线副本」，
    每笔写又重新开始堆 `_offline_operations`。
    """
    global _active_backend, _standalone
    with _WRITER_LOCK:
        _STATE["ready"] = False
        with _SQLITE_LOCK:
            initialize_sqlite()
            with closing(_open_sqlite()) as raw:
                complete = raw.execute(
                    "SELECT 1 FROM _sync_state WHERE key = 'complete' AND value = '1'"
                ).fetchone()
                standalone = raw.execute(
                    "SELECT 1 FROM _sync_state WHERE key = 'standalone' AND value = '1'"
                ).fetchone()
            if complete is None:
                _STATE["replica_ready"] = False
                raise RuntimeError("SQLite 副本尚未完整同步，拒绝写入")
            _active_backend = "sqlite"
            if standalone is not None:
                _standalone = True
                # replica_ready=False：单机模式下没有「副本」这个概念，`/health` 据此报 na。
                _STATE.update(
                    ready=True, replica_ready=False, mode="standalone", sync_pending=0,
                )
                logger.info("db.standalone.activated")
                return
            _standalone = False
            _STATE.update(
                ready=True, replica_ready=True, mode="online",
                sync_pending=len(pending_operations()),
            )


def mark_standalone_baseline() -> None:
    """把当前 SQLite 库确立为单机权威库：写入 `complete` + `standalone` 标记。

    `complete='1'` 在既有语义里是「这是 PG 同步出来的完整副本」的凭证，纯单机环境
    永远产生不了它。这里发一张等价凭证：这个库的权威性不来自 PG，而来自**运行模式
    的显式声明**。

    **只应在「文件不存在 / 空库」时调用**，由 `standalone_bootstrap_allowed()` 把关 ——
    对已有数据的库执行不会丢数据，但会把一个来历不明的半同步副本洗成权威库。
    """
    with _SQLITE_LOCK:
        initialize_sqlite()
        with closing(_open_sqlite()) as raw:
            for key in ("complete", "standalone"):
                raw.execute(
                    "INSERT INTO _sync_state (key, value) VALUES (?, '1') "
                    "ON CONFLICT(key) DO UPDATE SET value = '1'",
                    (key,),
                )
            raw.commit()


def activate_standalone_sqlite(*, bootstrap: bool = False) -> None:
    """进入单机模式：SQLite 成为唯一权威库，与 PostgreSQL 完全解耦。

    `bootstrap=True` 先确立权威标记（仅限空库，由 `standalone_bootstrap_allowed()` 把关），
    随后统一走 `activate_sqlite()` —— 让「接管」只有一处实现，两种形态不会各自漂移。
    """
    if bootstrap:
        mark_standalone_baseline()
    activate_sqlite()


def _report_backend(backend: str, summary: str) -> None:
    """打印「本进程最终用了哪个库」。

    格式刻意同时满足两种读者：`db.backend.selected` 是结构化 key（可 grep / 可告警），
    后半句是可直接读的中文结论。服务进程与 `admin_cli` 都调它 —— 同一种状态不允许
    有第二种说法，否则排查时要在两种措辞之间做翻译。
    """
    logger.info("[数据层] db.backend.selected backend=%s %s", backend, summary)


def _report_sqlite_path() -> str:
    return str(_sqlite_path())


def bootstrap() -> str:
    """为一个进程选定权威库、建表，并打印结论；返回 `postgresql` 或 `sqlite`。

    **这是服务进程与 `admin_cli` 共用的唯一入口。** 两条路径的判定必须逐条一致，
    否则就会出现「服务起来了、建号命令却连不上库」的割裂 —— 上一版正是只给服务加了
    单机模式、CLI 却仍在 `init_db()` 里硬连 PG，而全量测试覆盖不到独立进程。

    判定顺序（每一步都打印结论，运维一眼能看出用的是哪个库）：

    1. `DB_MODE=sqlite`：显式声明单机，**不探测 PG**，直接接管或新建；
    2. PG 连得上 → PG 是权威主库（`DB_MODE=postgres` 时连不上就直接抛错，不降级）；
    3. PG 连不上、SQLite 有 `complete=1` → 立即接管：有 `standalone=1` 是单机库，
       否则是 PG 完整副本（PG 恢复后由守护循环回切）；
    4. PG 连不上、SQLite 空库 / 不存在 → 等 `DB_STANDALONE_GRACE_S` 再确认一次
       （排除「compose 里 PG 比 backend 晚几秒就绪」），仍不通才新建单机库；
    5. PG 连不上、SQLite 有数据但**没有** `complete` 标记 → 抛错拒绝：来历不明的
       半份副本，拿它顶替主库等于静默丢数据。

    第 4 步是唯一「不可逆」的动作（新建的库不会再自动切回 PG），所以只有它需要等。
    """
    settings = get_settings()
    mode = str(settings.db_mode or "").strip().lower()

    if mode == "sqlite":
        _bootstrap_sqlite_only(trust_user=True)
        _report_backend(
            "sqlite",
            f"DB_MODE=sqlite 显式指定 → 使用 SQLite 单机库：{_report_sqlite_path()}",
        )
        return "sqlite"

    if probe_postgresql_quiet():
        init_db()
        activate_postgresql()
        _report_backend("postgresql", "PostgreSQL 可用 → 使用 PostgreSQL 作为权威主库")
        return "postgresql"

    if mode == "postgres":
        # 显式要求 PG 时不降级：让故障如实暴露，而不是悄悄换成另一个库。
        raise RuntimeError(
            "DB_MODE=postgres 但 PostgreSQL 连不上；拒绝降级到 SQLite"
        )

    marker_complete = sqlite_marker("complete")
    if marker_complete == "1":
        activate_sqlite()
        if is_standalone():
            _report_backend(
                "sqlite",
                f"PostgreSQL 不可用 → 使用 SQLite 单机库：{_report_sqlite_path()}",
            )
        else:
            _report_backend(
                "sqlite", "PostgreSQL 不可用 → 由 SQLite 完整副本接管（PG 恢复后自动回切）"
            )
        return "sqlite"

    if has_sqlite_data():
        raise RuntimeError(
            "SQLite 里有数据但缺少权威标记（complete），可能是同步中断留下的半份副本，"
            "拒绝接管。请删除该文件重新开始；若确认它就是你的单机数据，"
            "请显式设置 DB_MODE=sqlite 声明它为权威库"
        )

    # 空库 / 无库：唯一不可逆的一步，给 PG 最后一次机会。
    grace = max(0.0, float(settings.db_standalone_grace_s))
    if grace > 0:
        # 自解释的日志：只写 timeout_s 会让人以为「卡住了」，这里说清楚在等什么、等不到会怎样。
        logger.info(
            "db.bootstrap.waiting_postgres timeout_s=%s "
            "说明: 先等 PostgreSQL 就绪，超时后自动切换到 SQLite 单机库",
            grace,
        )
        deadline = time.monotonic() + grace
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(1.0, remaining))
            if probe_postgresql_quiet():
                init_db()
                activate_postgresql()
                _report_backend(
                    "postgresql", "PostgreSQL 在等待后可用 → 使用 PostgreSQL 作为权威主库"
                )
                return "postgresql"

    _bootstrap_sqlite_only()
    _report_backend(
        "sqlite",
        f"PostgreSQL 不可用且没有既有数据 → 已新建 SQLite 单机库：{_report_sqlite_path()}",
    )
    return "sqlite"


def _bootstrap_sqlite_only(*, trust_user: bool = False) -> None:
    """把 SQLite 立为权威库：空库则新建（打标记），已有权威库则沿用。

    `trust_user=True`（`DB_MODE=sqlite` 显式声明）时，即便库里有数据但缺标记也接管 ——
    用户已经明确说了「这个库就是权威库」，此时拒绝反而让升级来的老库无法使用。
    自动降级路径绝不带这个参数：那里的「无标记」意味着来历不明，必须拒绝。
    """
    if sqlite_marker("complete") == "1":
        activate_sqlite()
        return
    if not standalone_bootstrap_allowed():
        if not trust_user:
            raise RuntimeError(
                "SQLite 里有数据但缺少权威标记（complete），拒绝接管；"
                "请删除该文件重新开始，或确认数据无误后用 DB_MODE=sqlite 显式声明"
            )
        logger.warning("db.standalone.trusting_unmarked_sqlite path_kind=explicit_db_mode")
        mark_standalone_baseline()
        activate_sqlite()
        return
    activate_standalone_sqlite(bootstrap=True)


def activate_postgresql() -> None:
    global _active_backend, _standalone
    with _WRITER_LOCK:
        _standalone = False
        _STATE["ready"] = False
        with _SQLITE_LOCK:
            _active_backend = "postgresql"
            _STATE.update(ready=True, mode="online")


def pending_operations() -> list[dict[str, Any]]:
    with _SQLITE_LOCK:
        initialize_sqlite()
        with closing(_open_sqlite()) as raw:
            rows = raw.execute(
                "SELECT op_id, sql_text, params_json FROM _offline_operations ORDER BY seq"
            ).fetchall()
    return [
        {"op_id": row["op_id"], "sql": row["sql_text"], "params": row["params_json"]}
        for row in rows
    ]


def replay_pending() -> dict[str, int]:
    """在 PG 单事务内按提交顺序重放；重复 op_id 由独立回执幂等跳过。

    三种失败要区别对待：
    - 副本连读都读不了（文件损坏 / 磁盘故障）：兜底数据本身已不可用，PG 权威且健康时
      只失去兜底，不能因此把业务打成 503；
    - 重放中途失败 / 约束冲突：副本里仍有未落到 PG 的操作，必须 fail-stop 等人工对账，
      否则后续写入会在无法对账的分叉上继续累积。
    """
    try:
        operations = pending_operations()
    except sqlite3.Error as exc:
        _note_sqlite_failure(exc)
        with _STATE_LOCK:
            _STATE["replica_ready"] = False
        logger.warning("db.replay.unreadable error=%s", type(exc).__name__)
        return {"replayed": 0, "conflicts": 0}
    try:
        return _replay_pending(operations)
    except Exception:
        _mark_replay_failed()
        raise


def _replay_pending(operations: Sequence[dict[str, Any]]) -> dict[str, int]:
    conflicts = 0
    with _raw_pg() as raw:
        replayed = 0
        for operation in operations:
            exists = _execute_raw(
                raw, "postgresql",
                "SELECT 1 FROM _offline_receipts WHERE op_id = %s", (operation["op_id"],),
            ).fetchone()
            if exists:
                continue
            try:
                _execute_raw(
                    raw, "postgresql", operation["sql"], json.loads(operation["params"])
                )
            except psycopg.errors.IntegrityError as exc:
                # 约束冲突不可静默跳过：事务回滚，保持 SQLite，等待下一次人工对账。
                conflicts += 1
                raise RuntimeError("离线变更与 PostgreSQL 约束冲突，未回切") from exc
            _execute_raw(
                raw, "postgresql",
                "INSERT INTO _offline_receipts (op_id, replayed_at) VALUES (%s, %s)",
                (operation["op_id"], time.time()),
            )
            replayed += 1
    with _SQLITE_LOCK, closing(_open_sqlite()) as raw:
        raw.execute("DELETE FROM _offline_operations")
        # close() 不会提交事务；必须让日志删除与 PG 回执一起真正持久化。
        raw.commit()
    with _STATE_LOCK:
        _STATE["sync_pending"] = 0
        _STATE["conflicts"] = conflicts
        _STATE["last_sync_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return {"replayed": replayed, "conflicts": conflicts}


def ping() -> None:
    """当前活跃库的轻量探针，供 /health 使用。"""
    with connection() as conn:
        conn.execute("SELECT 1")


#: nl2sql 只读连接的取池超时：业务侧 `db_request_timeout_s`（0.25s）是「快失败」口径，
#: 分析查询多等一会儿是合理的，但也不能等满语句超时（那会让两个上限叠加）。
_READONLY_POOL_WAIT_S = 2.0
#: `statement_timeout` 只接受毫秒整数，且必须内联——`SET` 不支持参数占位符。
#: 下界防「配成 0 变成立即取消」，上界是护栏：再长就该走后台任务而不是同步问答。
_TIMEOUT_MIN_MS = 100
_TIMEOUT_MAX_MS = 30_000


@contextmanager
def readonly_connection(*, timeout_s: float = 3.0) -> Iterator[tuple[Any, str]]:
    """nl2sql 专用只读连接：**不取 `_WRITER_LOCK`**，不进镜像链路、不写离线日志。

    为什么必须另开一条路（r152 的核心理由）：`connection()` 在取连接时持进程级
    `_WRITER_LOCK`，而部署写死单进程单 worker（compose `--workers 1`）。nl2sql 生成的
    查询天然带 JOIN / GROUP BY，一条 3 秒的分析查询若走 `connection()`，这 3 秒内
    **所有业务请求都在排队**——不是变慢，是整个应用卡死。只读查询不写库，没有理由
    参与那把锁。

    三道只读约束缺一不可：

    - PG：`SET TRANSACTION READ ONLY` + `SET LOCAL statement_timeout`。两者都是
      **事务级**，事务结束自动失效。绝不能写成会话级 `SET`——连接要归还连接池，
      会话级的只读会让下一个业务事务的写操作直接失败。
    - SQLite：`PRAGMA query_only = ON`，写语句由驱动层拒绝，不依赖上层校验。
    - 两边都用**临时连接**，不复用业务连接的当前事务（`_current_transaction`）。

    SQLite 分支不持 `_SQLITE_LOCK`：副本是 WAL 模式，读读不互斥。库文件不存在时
    直接报不可用——只读路径绝不允许 `mkdir` 或建出一个空库来「假装能查」。
    """
    backend = active_backend()
    if backend == "sqlite":
        path = _sqlite_path()
        if not path.exists():
            from app.core.errors import database_unavailable

            raise database_unavailable()
        try:
            raw = _open_sqlite()
        except sqlite3.Error as exc:
            # 只读路径的失败不改全局状态：这里只把驱动异常翻成中文 503，
            # 不调 `_note_sqlite_failure()`（那会触发整体降级判定，分析查询没这个权力）。
            logger.warning("db.readonly_sqlite_failed error=%s", type(exc).__name__)
            from app.core.errors import database_unavailable

            raise database_unavailable() from exc
        try:
            raw.execute("PRAGMA query_only = ON")
            yield raw, "sqlite"
        finally:
            raw.close()
        return

    ms = max(_TIMEOUT_MIN_MS, min(_TIMEOUT_MAX_MS, int(timeout_s * 1000)))
    try:
        with get_pool().connection(timeout=_READONLY_POOL_WAIT_S) as raw, raw.transaction():
            raw.execute("SET TRANSACTION READ ONLY")
            raw.execute(f"SET LOCAL statement_timeout = {ms}")
            yield raw, "postgresql"
    except (PoolTimeout, psycopg.OperationalError, psycopg.InterfaceError) as exc:
        discard_failed_pool()
        logger.warning("db.readonly_pg_unavailable error=%s", type(exc).__name__)
        from app.core.errors import database_unavailable

        raise database_unavailable() from exc


def readonly_query(
    sql: str, params: Sequence[Any] | None = None, *, timeout_s: float = 3.0
) -> dict[str, Any]:
    """在独立只读连接上跑一条 SELECT，返回 `{"columns": [...], "rows": [...]}`。

    行统一成 `dict`：PG 池的 row_factory 已是 `dict_row`，SQLite 是 `sqlite3.Row`，
    调用方不该关心这件事。列名以 `cursor.description` 为准（`SELECT *` 的展开结果
    只有驱动知道）。
    """
    with readonly_connection(timeout_s=timeout_s) as (raw, backend):
        cursor = _execute_raw(raw, backend, sql, params)
        rows = cursor.fetchall()
        columns = [str(item[0]) for item in (cursor.description or ())]
    out: list[dict[str, Any]] = []
    for row in rows:
        if isinstance(row, dict):
            out.append({name: row.get(name) for name in columns})
        else:
            out.append({name: row[name] for name in columns})
    return {"columns": columns, "rows": out}


SYNC_SCHEMA = """
CREATE TABLE IF NOT EXISTS _offline_receipts (
    op_id TEXT PRIMARY KEY,
    replayed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS _sync_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS _id_allocations (
    kind TEXT PRIMARY KEY,
    next_id INTEGER NOT NULL
);
"""


def initialize_sqlite() -> None:
    """离线副本只补 schema；种子仅在 PG 正常初始化时写入，避免覆盖副本数据。"""
    with closing(_open_sqlite()) as raw:
        conn = Connection(raw, "sqlite")
        raw.executescript(
            "CREATE TABLE IF NOT EXISTS _offline_operations ("
            "seq INTEGER PRIMARY KEY AUTOINCREMENT, op_id TEXT NOT NULL UNIQUE, "
            "sql_text TEXT NOT NULL, params_json TEXT NOT NULL)"
        )
        radar_schema = R67_SCHEMA.replace(
            "INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY",
            "INTEGER PRIMARY KEY AUTOINCREMENT",
        )
        r146_schema = R146_SCHEMA.replace(
            "INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY",
            "INTEGER PRIMARY KEY AUTOINCREMENT",
        )
        for script in (
            SCHEMA, R23_SCHEMA, SCHEMA_INDEXES, R23_INDEXES, R42_SCHEMA, R42_INDEXES,
            R51_SCHEMA, R61_SCHEMA, radar_schema, R67_INDEXES, R77_SCHEMA, R77_INDEXES,
            R80_SCHEMA, R81_SCHEMA, R81_INDEXES, R100_SCHEMA, COACH_RUNS_SCHEMA,
            RAG_FEEDBACK_SCHEMA, MIRROR_SCHEMA, WRONG_BOOK_SCHEMA, SYNC_SCHEMA,
            r146_schema, NL2SQL_SCHEMA,
        ):
            conn.executescript(script)
        for columns in (_ADDED_COLUMNS, _R23_ADDED_COLUMNS, _R61_ADDED_COLUMNS, _R67_ADDED_COLUMNS):
            for table, column, ddl in columns:
                existing = {row["name"] for row in raw.execute(f'PRAGMA table_info("{table}")')}
                if column not in existing:
                    raw.execute(f'ALTER TABLE "{table}" ADD COLUMN "{column}" {ddl}')
        embedding_columns = {
            row["name"] for row in raw.execute("PRAGMA table_info(rag_chunks)")
        }
        if "embedding" not in embedding_columns:
            raw.execute("ALTER TABLE rag_chunks ADD COLUMN embedding TEXT")
        # 新副本的初始化去重只在真正空库执行，不能把正常的 running 任务误判为重启僵尸。
        has_data = raw.execute(
            "SELECT 1 FROM _sync_state WHERE key = 'initialized'"
        ).fetchone() is not None
        if not has_data:
            raw.execute(
                "INSERT INTO _sync_state (key, value) VALUES ('initialized', '1')"
            )


def _sync_id_allocations(pg: Any, local: sqlite3.Connection) -> None:
    rows = pg.execute(
        "SELECT kind, next_id FROM _id_allocations"
    ).fetchall() if pg.execute("SELECT to_regclass('public._id_allocations') AS name").fetchone()["name"] else []
    local.execute("DELETE FROM _id_allocations")
    local.executemany(
        "INSERT INTO _id_allocations (kind, next_id) VALUES (?, ?)",
        [(row["kind"], row["next_id"]) for row in rows],
    )


def next_id(kind: str, *, conn: Connection | None = None) -> int:
    """共享 ID 游标；提供连接时与业务行同一事务提交，防止崩溃后游标漂移。"""
    if conn is not None:
        if active_backend() == "sqlite":
            row = conn.execute(
                "SELECT next_id FROM _id_allocations WHERE kind = ?", (kind,)
            ).fetchone()
            value = int(row["next_id"]) if row else 1
            conn.execute(
                "INSERT INTO _id_allocations (kind, next_id) VALUES (?, ?) "
                "ON CONFLICT(kind) DO UPDATE SET next_id = excluded.next_id",
                (kind, value + 1),
            )
            return value
        row = conn.execute(
            "INSERT INTO _id_allocations (kind, next_id) VALUES (?, 2) "
            "ON CONFLICT(kind) DO UPDATE SET next_id = _id_allocations.next_id + 1 "
            "RETURNING next_id",
            (kind,),
        ).fetchone()
        return int(row["next_id"]) - 1
    with connection() as owned:
        return next_id(kind, conn=owned)


def _sync_table_names(raw: Any) -> list[str]:
    rows = raw.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' ORDER BY table_name"
    ).fetchall()
    return [
        str(row["table_name"])
        for row in rows
        if not str(row["table_name"]).startswith("_offline_")
    ]


def _copy_rows(
    local: Connection, table: str, columns: Sequence[str], payload: Sequence[Sequence[Any]]
) -> None:
    """把一批行写进副本；冲突时把表名带进异常。

    唯一 / 非空约束在副本侧是真实生效的，主库侧却可能因为索引损坏而不拦重复
    （生产真实事故：`radar_techs_pkey` 目录标 valid、实际缺条目）。只抛 `IntegrityError`
    类型名的话，日志看不出该去修哪张表。
    """
    if not payload:
        return
    quoted = ", ".join(f'"{name}"' for name in columns)
    marks = ", ".join("?" for _ in columns)
    try:
        local.executemany(f'INSERT INTO "{table}" ({quoted}) VALUES ({marks})', payload)
    except sqlite3.IntegrityError as exc:
        raise ReplicaSyncError(table, str(exc)) from exc


def sync_sqlite_from_pg() -> dict[str, int]:
    """首次或回切后整库重建副本；只在切库写锁内调用，不接受并发离线写。"""
    global _SYNC_TABLES
    if _standalone:
        # 单机模式下 SQLite 是权威库而不是副本：整库重建会用 PG 数据把它覆盖掉，
        # 而 PG 在这个环境里根本不该被访问。
        logger.warning("db.standalone.replica_sync_skipped")
        return {}
    with _WRITER_LOCK, _raw_pg() as pg, closing(_open_sqlite()) as local:
        initialize_sqlite()
        counts: dict[str, int] = {}
        local.execute("BEGIN IMMEDIATE")
        try:
            local.execute(
                "INSERT INTO _sync_state (key, value) VALUES ('complete', '0') "
                "ON CONFLICT(key) DO UPDATE SET value = '0'"
            )
            for table in _sync_table_names(pg):
                pg_columns = {
                    str(row["column_name"])
                    for row in pg.execute(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = 'public' AND table_name = %s", (table,)
                    ).fetchall()
                }
                columns = [
                    row["name"] for row in local.execute(f'PRAGMA table_info("{table}")')
                    if row["name"] in pg_columns
                ]
                if not columns:
                    continue
                quoted = ", ".join(f'"{name}"' for name in columns)
                rows = pg.execute(f'SELECT {quoted} FROM "{table}"').fetchall()
                local.execute(f'DELETE FROM "{table}"')
                payload = []
                for row in rows:
                    payload.append([
                        json.dumps(value) if isinstance(value, list) else value
                        for value in (row[name] for name in columns)
                    ])
                _copy_rows(local, table, columns, payload)
                counts[table] = len(payload)
            _SYNC_TABLES = tuple(counts)
            local.execute("DELETE FROM _offline_operations")
            _sync_id_allocations(pg, local)
            local.execute(
                "INSERT INTO _sync_state (key, value) VALUES ('complete', '1') "
                "ON CONFLICT(key) DO UPDATE SET value = '1'"
            )
            local.commit()
        except Exception:
            local.rollback()
            raise
    with _STATE_LOCK:
        _STATE["sync_pending"] = 0
        _STATE["replica_ready"] = True
        _STATE["last_sync_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return counts


def refresh_replica() -> dict[str, int]:
    """外部写入方（`admin_cli` / 一次性运维脚本）直接写过主库后，立刻重建副本。

    `replica_ready` 是**进程本地**状态：另一个进程写 PG 时它自己的镜像分支默认不成立，
    会静默跳过镜像；而正在服务的进程完全不知道发生过这次写入，`/health` 仍报
    `db_replica=ready`。这类「旁路写入」只能由写方自己补齐副本——生产演练时就是这样
    发现副本少了一个刚建的账号。
    """
    counts = sync_sqlite_from_pg()
    logger.info("db.replica.refreshed tables=%s rows=%s", len(counts), sum(counts.values()))
    return counts


def reset_runtime() -> None:
    """仅测试 / 进程清理使用；不会删除 SQLite 文件。"""
    global _active_backend, _standalone
    with _WRITER_LOCK:
        # 单机标记是进程本地状态，重置必须一并清掉：否则上一轮的单机语义会漏到下一轮，
        # 让本该记录重放日志的副本模式静默停止记录。
        _standalone = False
        _active_backend = "postgresql"
        _STATE.update(ready=True, mode="starting", sync_pending=0, conflicts=0, last_sync_at="")
        # 文件是持久化副本，进程重启后先验证 complete 标记再允许接管。
        # 副本损坏 / 不可读时只记「不可接管」，不能把重置运行态变成异常出口。
        try:
            with _SQLITE_LOCK, closing(_open_sqlite()) as raw:
                complete = raw.execute(
                    "SELECT value FROM _sync_state WHERE key = 'complete'"
                ).fetchone() if raw.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = '_sync_state'"
                ).fetchone() else None
        except sqlite3.Error as exc:
            _note_sqlite_failure(exc)
            _STATE["replica_ready"] = False
            return
        _STATE["replica_ready"] = bool(complete and complete["value"] == "1")


def _ensure_columns(conn: Connection, columns: Sequence[tuple[str, str, str]]) -> None:
    """存量库补列（幂等）：PostgreSQL 原生支持 `ADD COLUMN IF NOT EXISTS`。

    r98 之前这里靠 `PRAGMA table_info` 先查后补，是因为 SQLite 没有该语法；换到 PG 后
    判定交给数据库本身，少一次往返、也少一个「查到的 schema 与执行时不符」的竞态窗口。
    `ADD COLUMN ... NOT NULL DEFAULT <常量>` 在 PG 11+ 是元数据操作，不重写全表。
    """
    for table, column, ddl in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {ddl}")


#: r98 类型加宽：`CREATE TABLE IF NOT EXISTS` 只建表不改列，存量库（含从 SQLite 迁来的库）
#: 里的 `integer` 必须显式改成 `bigint`，否则写入毫秒时间戳时溢出。
#: 只放「已知会超 int4」的列 —— 无差别全改会让索引与存储无谓变大。
_WIDEN_TO_BIGINT: tuple[tuple[str, str], ...] = (("learn_chapters", "updated_at"),)


def _ensure_bigint_columns(conn: Connection) -> None:
    """把已知会超过 int4 的整数列加宽到 bigint（幂等：已是 bigint 则不发 DDL）。"""
    for table, column in _WIDEN_TO_BIGINT:
        row = conn.execute(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = ? AND column_name = ?",
            (table, column),
        ).fetchone()
        if row is not None and str(row["data_type"]) != "bigint":
            conn.execute(f"ALTER TABLE {table} ALTER COLUMN {column} TYPE BIGINT")


def _init_pg_schema() -> None:
    """建库并补齐结构（幂等）：新库全建，老库只补缺的列与索引。

    全部 DDL 都是 `IF NOT EXISTS` 形态，对已有库反复执行是安全的空操作；没有任何
    「版本号表 + 迁移脚本」机制 —— 沿用 r3 约定的同时，PG 的 `ADD COLUMN IF NOT EXISTS`
    让这套约定比 SQLite 时代更结实（不必先查 `PRAGMA` 再补）。
    """
    trgm_ok = _try_create_trgm()
    vector_ok = _try_create_vector()
    with connection(force_pg=True) as conn:
        conn.executescript(SCHEMA)                    # 1. 业务表
        _ensure_columns(conn, _ADDED_COLUMNS)         # 2. r11 追加列（幂等）
        conn.executescript(R23_SCHEMA)                # 3. 认证 / 会话 / 配额表
        _ensure_columns(conn, _R23_ADDED_COLUMNS)     # 4. 6 表补 user_id
        conn.executescript(SCHEMA_INDEXES)            # 5. 业务索引（引用补出的列，故在其后）
        conn.executescript(R23_INDEXES)               # 6. 隔离索引
        conn.executescript(R42_SCHEMA)                # 7. 图片识别任务表
        _dedupe_running_profile_jobs(conn)            # 8. 建部分唯一索引前先收敛历史重复行
        conn.executescript(R42_INDEXES)               # 9. 幂等索引
        conn.executescript(R51_SCHEMA)                # 10. 模型调用日志表
        if trgm_ok:                                   # 11. 检索 GIN 索引（无扩展则跳过）
            conn.executescript(R51_TRGM_SCHEMA)
        conn.executescript(R61_SCHEMA)                # 12. 学习进度 / 计划打卡
        _ensure_columns(conn, _R61_ADDED_COLUMNS)     # 12.1 r95 补 plan_states.started_on
        _ensure_bigint_columns(conn)                  # 12.2 毫秒时间戳列加宽到 bigint
        conn.executescript(R67_SCHEMA)                # 13. 技术雷达五表
        _ensure_columns(conn, _R67_ADDED_COLUMNS)     # 14. 雷达补列（须在建表之后）
        _sweep_stale_radar_jobs(conn)                 # 15. 建部分唯一索引前收敛未终态任务
        conn.executescript(R67_INDEXES)               # 16. 雷达索引（含 jobs 的 active 唯一索引）
        conn.executescript(R77_SCHEMA)                # 17. 太傅对话表
        conn.executescript(R77_INDEXES)               # 18. 对话索引
        conn.executescript(R80_SCHEMA)                # 19. 太傅线程摘要（单行）
        conn.executescript(R81_SCHEMA)                # 20. 太傅长期记忆（多条）
        conn.executescript(R81_INDEXES)               # 21. 长期记忆索引
        conn.executescript(R100_SCHEMA)               # 22. RAG chunk 表 + 索引状态
        _ensure_rag_embedding_column(conn, vector_ok)  # 23. 向量列（按 pgvector 可用性分支）
        if trgm_ok:                                   # 24. chunk 正文的 trigram GIN（混合检索的关键词腿）
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_rag_chunks_content_trgm "
                "ON rag_chunks USING gin (content gin_trgm_ops)"
            )
        conn.executescript(COACH_RUNS_SCHEMA)         # 25. 教练 Agent 编排轨迹
        conn.executescript(RAG_FEEDBACK_SCHEMA)       # 26. 召回反馈（点赞 / 点踩）
        conn.executescript(MIRROR_SCHEMA)             # 27. 镜试复盘卡（r125，反向面试）
        conn.executescript(WRONG_BOOK_SCHEMA)         # 28. 错题本移出标记（r129）
        conn.executescript(SYNC_SCHEMA)               # 29. SQLite 副本 / 离线重放回执
        conn.executescript(R146_SCHEMA)               # 30. 先锋学习清单（r146）
        conn.executescript(NL2SQL_SCHEMA)             # 31. nl2sql 审计（r152）
        # 28. ID 游标按现有最大 id 播种。`INSERT … SELECT … ON CONFLICT` 是 PG 形态，
        #     SQLite 语法上不接受 —— 所以这里天然不能进副本镜像日志，
        #     由 `init_db()` 的 `suppress_mirror()` 保证（副本侧靠 `_sync_id_allocations()` 对齐）。
        for table, column in (
            ("radar_snapshots", "id"), ("radar_assessments", "id"), ("radar_runs", "run_id"),
            ("radar_watchlist", "id"),
        ):
            conn.execute(
                "INSERT INTO _id_allocations (kind, next_id) "
                f"SELECT ?, COALESCE(MAX({column}), 0) + 1 FROM {table} "
                "ON CONFLICT(kind) DO NOTHING",
                (table,),
            )


def init_db() -> None:
    """明确在 PostgreSQL 上建表；不改变业务活动库或可用状态。

    结构维护整段关掉镜像（`suppress_mirror()`）：副本靠 `sync_sqlite_from_pg()` 整体
    对齐，这些 DDL / 存量收敛语句逐条镜像只会失败并把 `/health` 打成降级。
    """
    with recovery(), suppress_mirror():
        _init_pg_schema()


def _sweep_stale_radar_jobs(conn: Connection) -> None:
    """r67 生成任务在**进程重启后不续跑**：新进程里 queued/running 一定没有活的 `asyncio` 任务，
    直接按 failed + 中文原因落库（AC-4「不会永远停在生成中」的服务端兜底）。对干净库 0 行更新。

    **前提是单副本 / 单 worker**（当前部署形态：Dockerfile 无 `--workers`）。这条清扫不区分
    属主，多副本滚动升级时新副本一启动就会把旧副本正在跑的任务判死；届时要么关掉这一步、
    只留读路径的 `radar_sweep_stale_jobs`（按 `radar_job_stale_minutes` 超时清扫），
    要么给 `radar_jobs` 加属主列后按属主清扫。改部署形态前请先确认这里。
    """
    conn.execute(
        "UPDATE radar_jobs SET status = 'failed', error_message = '任务中断，请重新生成', "
        f"updated_at = {SQL_NOW_ISO} "
        "WHERE status IN ('queued', 'running')"
    )


def _dedupe_running_profile_jobs(conn: Connection) -> None:
    """同一 (user_id, document_id) 只保留最新一条 running 行，其余按 failed 收敛。

    r30 期间允许同一简历重复受理（每次新建 job 行），存量库里可能已有并行 running；
    r42 的幂等靠部分唯一索引保证，建索引前必须先收敛这些旧行，否则 `init_db()` 会直接失败。
    对干净库执行 0 行更新；对半升级库幂等（第二次启动已无重复行）。

    r98：SQLite 用 `rowid` 取「最新一行」，PG 没有 rowid 也没有 `max(ctid)` 聚合，
    改用窗口函数按 `(created_at, id)` 排序取 rn=1 —— 语义与「最后受理的那条」一致且不依赖
    物理行序（VACUUM / 并行写入后 rowid 顺序本来也不可靠）。

    **与 `_sweep_stale_radar_jobs` 同一个前提：单副本**。这条会把同 `(user_id, document_id)`
    里除最新外的 running 行判死；多副本滚动升级时新副本启动会误伤旧副本正在跑的任务。
    当前部署是单进程 uvicorn（Dockerfile 无 `--workers`），改形态前先一并处理这两处。
    """
    conn.execute(
        "WITH ranked AS ("
        "  SELECT id, row_number() OVER ("
        "    PARTITION BY user_id, document_id ORDER BY created_at DESC, id DESC"
        "  ) AS rn FROM profile_jobs WHERE status = 'running'"
        ") "
        "UPDATE profile_jobs SET status = 'failed', "
        "error = '旧版本重复受理的画像任务已合并，请重新生成画像', "
        f"updated_at = {SQL_NOW_ISO} "
        "WHERE id IN (SELECT id FROM ranked WHERE rn > 1)"
    )
