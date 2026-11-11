"""SQLite 单库访问层：13 张业务表 + 1 张可选 FTS5 虚表，结构化产物以 JSON 文本列存（ARCHITECTURE §3.4）。

不做迁移框架：只用 CREATE TABLE IF NOT EXISTS，字段变更需在 memory.md 记录一次性升级说明。
r3 追加 `timeline_events`（成长时间线的事件快照，`(type, ref_id)` 唯一）——对既有 `app.core.db`
反复执行 `init_db()` 即得新表，无迁移语句。
r6 追加 `questions`（题库，`seed/questions.json` 退为唯一导入源）与 `question_attempts`
（客观题作答事件，`(question_id, run_id)` 唯一）——同样反复执行 `init_db()` 即得新表与新索引，
既有 `app.core.db` 无需迁移语句；空库由 `services/question_bank.ensure_seeded()` 幂等补 80 行。
r11 追加题库第五维 `questions.language`、逐题解析 `questions.explanation` 与作答事件来源
`question_attempts.source`（TECHNICAL §2.1）。SQLite 的 `CREATE TABLE IF NOT EXISTS` 不会给
**存量**表补列，故 `init_db()` 拆成三步定序：`SCHEMA`（新库即含新列）→ `_ensure_r11_columns()`
（`PRAGMA table_info` 判定后 `ALTER TABLE`，缺列才动，幂等）→ `SCHEMA_INDEXES`（新索引引用
`language` / `source`，必须在补列之后执行）。索引因此从 `SCHEMA` 抽出为独立脚本。
"""

import logging
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

from app.core.config import get_settings

logger = logging.getLogger("app.db")

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
R51_FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS question_search USING fts5(
    question_id UNINDEXED,
    prompt,
    explanation,
    direction UNINDEXED,
    sub_direction UNINDEXED,
    tokenize = 'trigram'
);
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
    updated_at      INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, chapter_id)
);

CREATE TABLE IF NOT EXISTS plan_states (
    user_id       TEXT NOT NULL,
    report_id     TEXT NOT NULL,
    daily_minutes INTEGER NOT NULL DEFAULT 30,
    done          TEXT NOT NULL DEFAULT '{}',
    updated_at    TEXT NOT NULL,
    PRIMARY KEY (user_id, report_id)
);
"""


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
    first_seen_at  TEXT NOT NULL,
    last_seen_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS radar_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    tech_slug       TEXT NOT NULL,
    taken_at        TEXT NOT NULL,
    stars           INTEGER NOT NULL DEFAULT 0,
    forks           INTEGER NOT NULL DEFAULT 0,
    repo_created_at TEXT NOT NULL DEFAULT '',
    pushed_at       TEXT NOT NULL DEFAULT '',
    suspect         INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS radar_assessments (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
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
    run_id         INTEGER PRIMARY KEY AUTOINCREMENT,
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


def fts5_available(conn: sqlite3.Connection) -> bool:
    """探测当前 SQLite 是否编译了 FTS5；不抛异常，缺能力即返回 False。"""
    row = conn.execute("SELECT sqlite_compileoption_used('ENABLE_FTS5') AS enabled").fetchone()
    return bool(row and row["enabled"])


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
)



#: r53 并发写锁：8 线程 × 50 次短事务基准里，无 busy_timeout 成功率仅 28.2%（287 次
#: `database is locked`），设 3000ms 后 100%、0 次失败。证据见 `docs/eval/PERF-REPORT.md`。
#: 刻意**不启用 WAL**：单进程本地库，busy_timeout 已消除写失败；WAL 会引入 -wal/-shm
#: 文件与备份复杂度，收益不成立（README 设计取舍同源判断）。
BUSY_TIMEOUT_MS = 3000


@contextmanager
def connection() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(get_settings().db_path, timeout=BUSY_TIMEOUT_MS / 1000)
    conn.row_factory = sqlite3.Row
    try:
        # 驱动参数与数据库层双保险：不同 Python 版本对 connect(timeout=) 的实现细节不同。
        conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        yield conn
        conn.commit()
    finally:
        conn.close()


def _ensure_r11_columns(conn: sqlite3.Connection) -> None:
    """存量库补列（幂等）：缺列才 `ALTER TABLE`，第二次启动执行 0 条 DDL。

    SQLite 没有 `ADD COLUMN IF NOT EXISTS`，所以只用 `PRAGMA table_info` 判定后补；
    `ADD COLUMN ... NOT NULL DEFAULT <常量>` 合法且不重建表（沿用 r3「无迁移框架」约定）。
    """
    for table, column, ddl in _ADDED_COLUMNS:
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def _ensure_r23_columns(conn: sqlite3.Connection) -> None:
    """存量 6 表补 `user_id`（幂等）：DEFAULT 'default' 让旧数据自然归到默认用户。"""
    for table, column, ddl in _R23_ADDED_COLUMNS:
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def _ensure_r67_columns(conn: sqlite3.Connection) -> None:
    """r67 存量库补列（幂等）：须在 `R67_SCHEMA` 建表之后调用。"""
    for table, column, ddl in _R67_ADDED_COLUMNS:
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def init_db() -> None:
    with connection() as conn:
        conn.executescript(SCHEMA)          # 1. 建表（新库即含新列）
        _ensure_r11_columns(conn)           # 2. 存量库补列（幂等）
        conn.executescript(R23_SCHEMA)      # 3. r23 认证 / 会话 / 配额表
        _ensure_r23_columns(conn)           # 4. 存量 6 表补 user_id（幂等）
        conn.executescript(SCHEMA_INDEXES)  # 5. 建索引（引用补出的列）
        conn.executescript(R23_INDEXES)     # 6. r23 隔离索引
        conn.executescript(R42_SCHEMA)      # 7. r42 图片识别任务表
        _dedupe_running_profile_jobs(conn)  # 8. 建部分唯一索引前先收敛历史重复 running 行
        conn.executescript(R42_INDEXES)     # 9. r42 幂等索引
        conn.executescript(R51_SCHEMA)      # 10. r51 模型调用日志表 + 索引
        if fts5_available(conn):            # 11. FTS5 虚表（可选能力，缺 tokenizer 时静默降级）
            try:
                conn.executescript(R51_FTS_SCHEMA)
            except sqlite3.OperationalError as exc:
                logger.warning("db.fts5_unavailable error=%s", type(exc).__name__)
        conn.executescript(R61_SCHEMA)      # 12. r61 学习进度 / 计划打卡表
        conn.executescript(R67_SCHEMA)      # 13. r67 技术雷达五表
        _ensure_r67_columns(conn)           # 14. 存量库补 r67 列（须在建表之后）
        _sweep_stale_radar_jobs(conn)       # 15. 建部分唯一索引前收敛重启遗留的未终态任务
        conn.executescript(R67_INDEXES)     # 16. r67 索引（含 jobs 的 active 唯一索引）


def _sweep_stale_radar_jobs(conn: sqlite3.Connection) -> None:
    """r67 生成任务在**进程重启后不续跑**：新进程里 queued/running 一定没有活的 `asyncio` 任务，
    直接按 failed + 中文原因落库（AC-4「不会永远停在生成中」的服务端兜底）。对干净库 0 行更新。
    """
    conn.execute(
        "UPDATE radar_jobs SET status = 'failed', error_message = '任务中断，请重新生成', "
        "updated_at = strftime('%Y-%m-%dT%H:%M:%f', 'now') || '+00:00' "
        "WHERE status IN ('queued', 'running')"
    )


def _dedupe_running_profile_jobs(conn: sqlite3.Connection) -> None:
    """同一 (user_id, document_id) 只保留最新一条 running 行，其余按 failed 收敛。

    r30 期间允许同一简历重复受理（每次新建 job 行），存量库里可能已有并行 running；
    r42 的幂等靠部分唯一索引保证，建索引前必须先收敛这些旧行，否则 `init_db()` 会直接失败。
    对干净库执行 0 行更新；对半升级库幂等（第二次启动已无重复行）。
    """
    conn.execute(
        "UPDATE profile_jobs SET status = 'failed', "
        "error = '旧版本重复受理的画像任务已合并，请重新生成画像', "
        "updated_at = strftime('%Y-%m-%dT%H:%M:%f', 'now') || '+00:00' "
        "WHERE status = 'running' AND rowid NOT IN ("
        "  SELECT MAX(rowid) FROM profile_jobs WHERE status = 'running' "
        "  GROUP BY user_id, document_id"
        ")"
    )
