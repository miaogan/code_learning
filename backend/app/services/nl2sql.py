"""nl2sql：把「我最近三场面试里 Redis 题对了几个」翻成一条只读 SELECT（r152）。

**这不是一个 SQL 编辑器。** 用户永远看不到、也写不了 SQL；模型生成的那条语句在
执行前必须过五道闸门，任何一道不过就整条作废，不给「差不多能跑」的余地。

为什么不复用 `core.db.connection()`（这是本模块最重要的一条约束）：

    那把进程级 `_WRITER_LOCK` 是给写路径串行化用的，而部署是单进程单 worker。
    分析查询天然带 JOIN / GROUP BY，一条 3 秒的查询若走 `connection()`，
    这 3 秒内所有业务请求都在排队 —— 不是变慢，是整个应用卡住。
    所以执行一律走 `db.readonly_query()`（独立连接、不持写锁、事务级只读）。

五道闸门（顺序固定，前一道不通过就不进下一道）：

1. **形状**：去尾分号后必须只剩单条语句、必须以 `SELECT` 开头、长度有上限；
2. **标识符**：禁止注释（`--` / `/*`）、禁止占位符 `?`、禁止引号包裹的标识符
   —— 后两条是为了让第 3 道的正则在结构上不会漏检，不是为了限制能力；
3. **表名**：`FROM` / `JOIN` 后面的每个标识符都必须在 `LOGICAL_VIEWS` 里。
   模型写 `users`、`ai_call_logs`、`documents` 一律拒绝 —— 白名单是**穷举**的，
   没有「其余默认放行」；
4. **函数与关键字**：函数只允许 `count/sum/avg/min/max/round/coalesce/abs/cast/nullif`；
   写操作、DDL、`pg_*` 元数据函数在形状检查里就已经不可能出现（不是 SELECT），
   这里是第二道冗余；
5. **行级隔离**：每个逻辑视图内联时都带上 `WHERE user_id = ?`，参数由服务端会话填，
   **绝不从模型参数取**。模型看不到裸表，越权在物理上不成立。

执行层再补两道：外层强制包一层带 LIMIT 的查询（模型写多大都不算数）、
语句超时由 `readonly_connection` 的事务级 `statement_timeout` 兜住。

产品口径（与 AGENTS.md 的 JD 闭环一致）：**只返回可回溯的事实计数，不产出匹配分 /
百分比 / 掌握度评分。** 说「9 答 6 对」是事实，说「Redis 掌握度 67%」就是编造。
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any

from pydantic import BaseModel

from app.core import db, repository
from app.core.config import get_settings
from app.core.context import get_current_user_id
from app.core.errors import AppError
from app.services.ai.ai import AIClient

logger = logging.getLogger("app.nl2sql")

#: 一次生成的 SQL 文本上限。正常查询 300–800 字符，2000 已经宽到不可能误伤，
#: 但足以挡住「模型把整段提示词或一堆 UNION 吐出来」这类失控输出。
MAX_SQL_CHARS = 2000
#: 问题文本上限：与太傅入口的输入上限同量级，超出的部分对生成没有帮助。
MAX_QUESTION_CHARS = 500
#: 函数白名单。刻意不含日期函数（`date_trunc` / `strftime` 两库语义不同），
#: 时间过滤走字符串比较 —— 本项目的所有时间列都是 ISO-8601 UTC 文本，
#: 字典序就是时间序（`db.SQL_NOW_ISO` 的注释里已经把这个前提钉死了）。
ALLOWED_FUNCTIONS = frozenset(
    {"count", "sum", "avg", "min", "max", "round", "coalesce", "abs", "cast", "nullif"}
)
#: 会被 `名字(` 正则误认成函数的关键字。少一个就会把正常查询误拒，
#: 多一个也不会放过危险函数（真正的函数仍要过白名单）。
SQL_WORDS = frozenset(
    {
        "in", "exists", "case", "when", "then", "else", "end", "not", "and", "or",
        "select", "from", "where", "group", "order", "having", "limit", "as", "on",
        "join", "left", "right", "inner", "outer", "full", "cross", "union", "all",
        "distinct", "like", "between", "is", "null", "asc", "desc", "values",
    }
)
#: 即使形状校验已经拦住了，仍显式拒绝一遍的关键词（防御性冗余，成本为零）。
FORBIDDEN_WORDS = (
    "insert", "update", "delete", "drop", "alter", "create", "truncate", "grant",
    "revoke", "copy", "attach", "detach", "pragma", "vacuum", "reindex", "begin",
    "commit", "rollback", "savepoint", "call", "do", "execute", "prepare",
    "pg_", "dblink", "lo_import", "lo_export", "current_setting", "set_config",
)


#: 逻辑视图规格的唯一出处是 `repository.py` —— SQL 只能写在唯一出口，工程门禁
#: `test_sql_only_through_repository` 会拦住散落在服务层的查询字面量（连注释也算）。
#: 这里只取个别名，让下面的引用读起来短一些。
LOGICAL_VIEWS = repository.NL2SQL_VIEWS


#: `FROM x` / `JOIN x` 的引用点。**只在这里做视图内联**，不在全文替换 ——
#: 全文替换会把字符串字面量里的同名词（`LIKE '%my_attempts%'`）一起换掉。
_TABLE_REF_RE = re.compile(
    r"\b(from|join)\s+(" + "|".join(re.escape(name) for name in LOGICAL_VIEWS) + r")\b",
    re.IGNORECASE,
)
_FROM_JOIN_RE = re.compile(r"\b(?:from|join)\s+([A-Za-z_][A-Za-z0-9_]*)", re.IGNORECASE)
_FUNC_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*\(")


class Nl2SqlDraft(BaseModel):
    """模型的结构化输出。字段给默认空串：模型偶尔只给 sql 不给解释，不该整体作废。"""

    sql: str = ""
    explain: str = ""


SYSTEM_PROMPT = """你是数据分析助手，把用户的问题翻译成**一条**只读 SELECT。

## 可用的表（只有这些，其他一律不存在）
{schema}

## 硬规则
1. 只输出一条 SQL，以 `SELECT` 开头，不要写分号，不要写注释。
2. 表名直接写（如 my_attempts），不要加引号、反引号或库名前缀。
3. 不要写问号占位符 ?，所有条件值直接写字面量。
4. 时间列都是 ISO-8601 UTC 文本（如 2026-11-20T03:14:00.000+00:00），
   比较用字符串：answered_at >= '2026-11-01'。不要用 date_trunc / strftime / now()。
5. 只能用这些函数：count / sum / avg / min / max / round / coalesce / abs / cast / nullif。
6. 要取前 N 条时，必须同时写 ORDER BY 和 LIMIT，否则顺序不确定。
7. 不要写 WITH / 子查询套子查询 / UNION 以外的复杂结构；能 JOIN 就 JOIN。
8. 用户问「最近几场」时，用 created_at 或 answered_at 倒序配合 LIMIT。
9. 拿不准的问题也要给一条最接近的查询，不要回「无法回答」。

## 关于口径（必须遵守）
你只输出**事实计数**，不输出评分、百分比、掌握度、匹配度这类派生结论。
「9 题答对 6 题」是事实；「掌握度 67%」是编造，禁止出现在任何字段里。

## 输出
只输出一个 JSON 对象：sql 放一条只读查询，explain 放一句话说明。示例：
{example}
"""


def _schema_text() -> str:
    """把 `LOGICAL_VIEWS` 拼成提示词里的表清单（定义一处，两处使用）。"""
    blocks = []
    for spec in LOGICAL_VIEWS.values():
        blocks.append(f"### {spec.name}\n{spec.summary}\n列：{spec.columns}")
    return "\n\n".join(blocks)


def _normalize_sql(raw: str) -> str:
    """去首尾空白与尾随分号；中间还残留分号由调用方按「多语句」拒绝。"""
    text = (raw or "").strip()
    while text.endswith(";"):
        text = text[:-1].rstrip()
    return text


def check_sql(sql: str) -> str | None:
    """形状 + 标识符 + 表名 + 函数四道闸门。返回拒绝原因（中文），`None` 表示通过。

    纯函数、零 IO、零网络：它必须能被单测逐条钉住，也是整条链路里唯一不依赖
    模型「听话」的一环。
    """
    if not sql:
        return "模型没有给出查询语句"
    if len(sql) > MAX_SQL_CHARS:
        return "查询语句过长"
    lower = sql.lower()
    if not lower.startswith("select"):
        return "只支持查询语句"
    if ";" in sql:
        return "一次只能查一条语句"
    if "?" in sql:
        return "查询里不能有占位符"
    if "--" in sql or "/*" in sql:
        return "查询里不能有注释"
    if '"' in sql or "`" in sql or "[" in sql:
        return "表名和列名不要加引号"
    for word in FORBIDDEN_WORDS:
        # `pg_` 是前缀（`pg_read_file` / `pg_sleep`），右边界会把它们全漏掉；
        # 其余词必须两侧都有词边界，否则 `do` 会误伤 `domain`、`call` 误伤 `called`。
        pattern = rf"\b{re.escape(word)}" if word.endswith("_") else rf"\b{re.escape(word)}\b"
        if re.search(pattern, lower):
            return "查询里包含不被允许的关键字"

    # 表名白名单：穷举检查，没有「其余放行」的分支。
    # `FROM (` 不匹配该正则，所以子查询会继续往内层找 —— 藏在子查询里的裸表同样拦得住。
    for name in _FROM_JOIN_RE.findall(sql):
        if name.lower() not in LOGICAL_VIEWS:
            return f"没有名为 {name} 的数据表"

    for name in _FUNC_RE.findall(sql):
        low = name.lower()
        if low in SQL_WORDS:
            continue
        if low not in ALLOWED_FUNCTIONS:
            return f"不支持函数 {name}"
    return None


def inline_views(sql: str, user_id: str) -> tuple[str, list[str]]:
    """把逻辑视图名内联成带 `WHERE user_id = ?` 的子查询，返回 (SQL, 参数)。

    参数顺序 = 替换发生的顺序 = SQL 文本中 `?` 出现的顺序，所以两库的占位符
    翻译（`to_pg_sql` / `to_sqlite_sql`）都能直接吃。

    `user_id` 来自 `core.context` 的服务端会话值，不是模型输出、也不是用户输入；
    它在这里仍然只作为**参数**传，不做字符串拼接。
    """
    params: list[str] = []

    def replace(match: re.Match[str]) -> str:
        keyword = match.group(1)
        spec = LOGICAL_VIEWS[match.group(2).lower()]
        params.extend([user_id] * spec.sql.count("?"))
        return f"{keyword} ({spec.sql})"

    return _TABLE_REF_RE.sub(replace, sql), params


def _cell(value: Any) -> str:
    """单元格文本：`None` 显示成 `-`，避免模型把「空值」读成「零」。"""
    if value is None:
        return "-"
    text = str(value)
    return text if len(text) <= 60 else text[:59] + "…"


def _format_rows(columns: list[str], rows: list[dict[str, Any]], limit: int) -> list[str]:
    """把结果压成回灌模型的文本行：表头一行 + 最多 `limit` 行明细。"""
    if not rows:
        return ["查询没有返回任何行"]
    lines = [" · ".join(columns)]
    for row in rows[:limit]:
        lines.append(" | ".join(f"{name}={_cell(row.get(name))}" for name in columns))
    return lines


def _friendly_error(exc: BaseException) -> str:
    """把驱动的原始异常翻成中文：不泄露 SQL 片段、表名、列名与堆栈。"""
    name = type(exc).__name__
    if "QueryCanceled" in name or "timeout" in str(exc).lower():
        return "查询超时了，把时间范围或条件缩小一点再问"
    if "OperationalError" in name or "InterfaceError" in name:
        return "数据库暂时不可用，稍后再试"
    logger.info("nl2sql.query_failed error=%s", name)
    return "这条查询没有跑通，换个问法再试一次"


async def query(question: str, *, client: AIClient | None = None) -> dict[str, Any]:
    """生成并执行一条只读查询。永不抛业务异常之外的东西，失败以 `ok=False` 返回。

    返回字段与 `taifu.tools.ToolResult` 对齐，工具层只做搬运。
    """
    settings = get_settings()
    if not settings.nl2sql_enabled:
        return _fail("数据问答当前未开启")
    text = (question or "").strip()
    if not text:
        return _fail("没有收到问题")
    if len(text) > MAX_QUESTION_CHARS:
        text = text[:MAX_QUESTION_CHARS]

    started = time.monotonic()
    draft_sql = ""
    executed_sql = ""
    status = "failed"
    reason = ""

    try:
        model = client or AIClient()
        draft = await model.complete_model(
            SYSTEM_PROMPT.format(schema=_schema_text(), example=repository.NL2SQL_FEW_SHOT),
            f"问题：{text}",
            Nl2SqlDraft,
            timeout_s=settings.nl2sql_timeout_s * 4,
        )
        draft_sql = draft.sql or ""
        sql = _normalize_sql(draft_sql)
        reason = check_sql(sql) or ""
        if reason:
            status = "rejected"
            _audit(text, draft_sql, "", status, reason, 0, started)
            return _fail(reason, label="数据查询被拦下", draft_sql=draft_sql)

        executed_sql, params = inline_views(sql, get_current_user_id())
        # 外层强制截断：模型自己写 `LIMIT 100000` 也只拿到 N 行。
        wrapped = repository.NL2SQL_WRAP.format(
            sql=executed_sql, limit=max(1, int(settings.nl2sql_max_rows))
        )
        # `to_thread`：同步驱动的查询最长 3 秒，直接在事件循环里跑会把整个进程卡住
        # —— 与「不持写锁」是同一个理由的两个面。
        data = await asyncio.to_thread(
            db.readonly_query, wrapped, params, timeout_s=settings.nl2sql_timeout_s
        )
    except AppError as exc:
        _audit(text, draft_sql, executed_sql, status, exc.message, 0, started)
        return _fail(exc.message, label="数据查询失败", draft_sql=draft_sql)
    except Exception as exc:  # noqa: BLE001 - 这里是查询链路的唯一兜底出口
        reason = _friendly_error(exc)
        _audit(text, draft_sql, executed_sql, status, reason, 0, started)
        return _fail(reason, label="数据查询失败", draft_sql=draft_sql)

    rows = data.get("rows") or []
    columns = [str(name) for name in (data.get("columns") or [])]
    elapsed_ms = int((time.monotonic() - started) * 1000)
    explain = (draft.explain or "").strip()
    label = f"数据查询 · {explain[:24]}" if explain else "数据查询"
    summary = (
        f"共 {len(rows)} 行" + (f"：{'、'.join(columns[:4])}" if columns else "")
        if rows
        else "查询没有返回任何行"
    )
    _audit(text, draft_sql, wrapped, "ok", "", len(rows), started)
    logger.info("nl2sql.ok rows=%s elapsed_ms=%s", len(rows), elapsed_ms)
    return {
        "ok": True,
        "reason": "",
        "label": label,
        "summary": summary,
        "content": _format_rows(columns, rows, max(1, int(settings.nl2sql_feed_lines))),
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "sql": executed_sql,
        "explain": explain,
    }


def _fail(reason: str, *, label: str = "数据查询", draft_sql: str = "") -> dict[str, Any]:
    """失败形状与成功一致（只是 `ok=False`），调用方不必分支判断字段是否存在。"""
    return {
        "ok": False,
        "reason": reason,
        "label": label,
        "summary": reason[:60],
        "content": [f"未读到：{reason}"],
        "columns": [],
        "rows": [],
        "row_count": 0,
        "sql": "",
        "explain": "",
        "draft_sql": draft_sql,
    }


def _audit(
    question: str,
    draft_sql: str,
    executed_sql: str,
    status: str,
    reason: str,
    row_count: int,
    started: float,
) -> None:
    """写审计。审计自身失败绝不影响主流程 —— 它是观测手段，不是业务前置条件。"""
    try:
        repository.insert_nl2sql_query(
            question=question,
            draft_sql=draft_sql,
            sql_text=executed_sql,
            status=status,
            reject_reason=reason[:200],
            row_count=row_count,
            elapsed_ms=int((time.monotonic() - started) * 1000),
        )
    except Exception as exc:  # noqa: BLE001 - 见上
        logger.warning("nl2sql.audit_failed error=%s", type(exc).__name__)
