"""PostgreSQL 单库访问层：24 张业务表，结构化产物以 JSON 文本列存（ARCHITECTURE §3.4）。

r98 起 SQLite 已下线，**没有本地文件库、也没有降级路径**：`DATABASE_URL` 是唯一数据源，
连接由 `psycopg_pool.ConnectionPool` 统一给出。为了让 2261 行 `repository.py` 的 149 处 `?`
占位符不必逐行改写，这里保留一个薄适配层（`to_pg_sql()` + `Connection`），
**新写的 SQL 请直接用 `%s`**，不要让适配层继续扩散。

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
import logging
import threading
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.core.config import get_settings

logger = logging.getLogger("app.db")

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

    只在**带参数**时调用：psycopg 无参数 `execute()` 走 simple protocol，不做 `%` 解析，
    此时转义反而会把 `%%` 原样写进 SQL。
    """
    if _PLACEHOLDER not in sql and "%" not in sql:
        return sql
    return sql.replace(_PLACEHOLDER, _SENTINEL).replace("%", "%%").replace(_SENTINEL, "%s")


class Connection:
    """`sqlite3.Connection` 的最小替身：只实现业务层真正用到的三个方法。

    刻意不实现 `commit()` —— 事务边界统一由 `connection()` 上下文管理（psycopg 连接池
    在退出时先 commit、异常时 rollback 并归还连接），业务层自己 commit 会绕开这套语义。
    """

    __slots__ = ("_raw",)

    def __init__(self, raw: psycopg.Connection) -> None:
        self._raw = raw

    def execute(self, sql: str, params: Sequence[Any] | None = None) -> psycopg.Cursor:
        if params is None:
            return self._raw.execute(sql)
        return self._raw.execute(to_pg_sql(sql), params)

    def executemany(self, sql: str, params: Iterable[Sequence[Any]]) -> psycopg.Cursor:
        """批量执行。psycopg3 的批量接口在 **cursor** 上，Connection 没有同名方法。"""
        cursor = self._raw.cursor()
        cursor.executemany(to_pg_sql(sql), params)
        return cursor

    def executescript(self, script: str) -> None:
        """执行 `;` 分隔的建表脚本：psycopg 无参数 execute 用 simple query，原生支持多语句。"""
        self._raw.execute(script)


#: 连接池是进程级的：`get_settings()` 被测试改写后必须 `close_pool()`，否则旧 DSN 的连接
#: 会继续被复用（表现为「测试改了库却仍读到上一轮数据」）。
_pool: ConnectionPool | None = None
_pool_lock = threading.Lock()


def get_pool() -> ConnectionPool:
    """懒建连接池（单例）。首次访问才连库，导入本模块不产生任何网络行为。"""
    global _pool
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
                    kwargs={"row_factory": dict_row, "prepare_threshold": None},
                    timeout=settings.db_pool_timeout_s,
                    open=True,
                )
    return _pool


def close_pool() -> None:
    """关闭并丢弃连接池（进程退出 / 测试切换数据库后调用）。"""
    global _pool
    with _pool_lock:
        pool, _pool = _pool, None
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
_R61_ADDED_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("plan_states", "started_on", "TEXT NOT NULL DEFAULT ''"),
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
        with connection() as conn:
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
@contextmanager
def connection() -> Iterator[Connection]:
    """从池里取一个连接执行一段事务；正常结束 commit，异常 rollback 并归还。

    `ConnectionPool.connection()` 自带这个语义（含归还），业务层无需也不应手动提交。
    """
    with get_pool().connection() as raw:
        yield Connection(raw)


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


def init_db() -> None:
    """建库并补齐结构（幂等）：新库全建，老库只补缺的列与索引。

    全部 DDL 都是 `IF NOT EXISTS` 形态，对已有库反复执行是安全的空操作；没有任何
    「版本号表 + 迁移脚本」机制 —— 沿用 r3 约定的同时，PG 的 `ADD COLUMN IF NOT EXISTS`
    让这套约定比 SQLite 时代更结实（不必先查 `PRAGMA` 再补）。
    """
    trgm_ok = _try_create_trgm()
    with connection() as conn:
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


def _sweep_stale_radar_jobs(conn: Connection) -> None:
    """r67 生成任务在**进程重启后不续跑**：新进程里 queued/running 一定没有活的 `asyncio` 任务，
    直接按 failed + 中文原因落库（AC-4「不会永远停在生成中」的服务端兜底）。对干净库 0 行更新。
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
