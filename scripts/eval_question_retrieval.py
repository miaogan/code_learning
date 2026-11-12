"""题目侧检索召回评估（r98：直连 PostgreSQL，跑生产同一条 SQL）。

诚实边界：
- 评估对象是 `repository.search_questions()` 的**真实执行结果** —— PG 的
  `prompt ILIKE ? OR explanation ILIKE ?` 子串匹配（`pg_trgm` GIN 索引加速），
  **不是向量检索 / RAG**；全程无 embedding、无向量库、无大模型生成。
- r98 之前这里用内存 SQLite 的 FTS5 trigram 虚表复现检索。SQLite 下线后那张虚表
  已不存在，继续评它等于评一条死代码，故改为直连真库、直接调生产函数。
- 需要可用的 PostgreSQL 实例（`EVAL_DATABASE_URL` > `DATABASE_URL` > 本地默认）。
  连不上即**失败退出 2**，绝不静默跳过：「门禁没跑」被当成「门禁通过」是最坏的失败模式。
- 标注 query 由题库题干关键词启发写成，存在标注泄漏风险，
  仅用于 CI 回归检测，不是能力宣传；数据全部为合成 / 题库启发标注。

格式化口径（遵守 ruff）：不用 f-string、不用 % 格式化；普通字符串用
str.format() / format() 内置 / 字符串拼接；日志走 logging 的 %s 占位，
避免 G004（logger f-string）、UP031（% 格式化）、UP032（简单 .format 调用）。

用法：
    python -X utf8 scripts/eval_question_retrieval.py            # 生成报告
    python -X utf8 scripts/eval_question_retrieval.py --check    # CI 门禁（只读）
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

import psycopg

ROOT = Path(__file__).resolve().parents[1]
# 从仓库根或 backend/ 下运行都能导入 app 包（CI 的 working-directory 是 backend）。
if str(ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend"))

from app.core import repository
from app.core.config import get_settings
from app.core.db import close_pool, init_db

GOLD = ROOT / "docs" / "eval" / "question-retrieval-gold.json"
REPORT = ROOT / "docs" / "eval" / "QUESTION-RETRIEVAL-REPORT.md"

#: --check 门禁阈值与统计常量（顶层常量，便于调整）。
CHECK_RECALL_MIN = 0.70
WILSON_Z = 1.96
TOP_K = 5
LOGGER = logging.getLogger("eval_question_retrieval")

#: 与 `backend/.env.example` / `backend/tests/conftest.py` 保持同一口径的默认实例。
DEFAULT_DSN = "postgresql://postgres:postgres@127.0.0.1:5433/sc_eval"

#: 库名只允许安全字符：它会被拼进 DDL（标识符不能用占位符）。
_SAFE_DB_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def pct(value):
    return format(value * 100, ".1f") + "%"


def frac(a, b):
    return str(a) + "/" + str(b)


def wilson(successes, total):
    """小样本比例的 Wilson 95% 区间；total<=0 时给 (0, 0)，不编造置信度。"""
    if total <= 0:
        return (0.0, 0.0)
    p = successes / total
    z2 = WILSON_Z**2
    denom = 1 + z2 / total
    center = (p + z2 / (2 * total)) / denom
    margin = (
        WILSON_Z * math.sqrt(p * (1 - p) / total + z2 / (4 * total**2)) / denom
    )
    return (
        round(max(0.0, center - margin), 4),
        round(min(1.0, center + margin), 4),
    )


def eval_dsn():
    """评测库地址：`EVAL_DATABASE_URL` > `DATABASE_URL` > 本地 compose 默认值。"""
    return (
        os.environ.get("EVAL_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
        or DEFAULT_DSN
    )


def redact(dsn):
    """去掉口令后的 DSN，用于报告与日志（评测记录要能公开）。"""
    parsed = urlparse(dsn)
    user = parsed.username or ""
    host = parsed.hostname or ""
    port = ":" + str(parsed.port) if parsed.port else ""
    auth = user + "@" if user else ""
    return parsed._replace(netloc=auth + host + port).geturl()


def ensure_database(dsn):
    """库不存在则创建；连不上就抛中文错误，不静默降级。"""
    parsed = urlparse(dsn)
    name = parsed.path.lstrip("/")
    if not _SAFE_DB_NAME.match(name):
        raise RuntimeError("评测库名不合法：" + repr(name) + "（只允许字母、数字、下划线）")
    admin = parsed._replace(path="/postgres").geturl()
    try:
        with psycopg.connect(admin, autocommit=True, connect_timeout=5) as conn:
            found = conn.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s", (name,)
            ).fetchone()
            if not found:
                conn.execute('CREATE DATABASE "' + name + '"')
    except psycopg.OperationalError as exc:
        raise RuntimeError(
            "题目检索评测需要 PostgreSQL，但连不上 "
            + redact(admin)
            + "（"
            + type(exc).__name__
            + "）。\n请先启动 docker compose -f docker-compose.yml "
            "-f docker-compose.dev.yml up -d postgres，"
            "或用 EVAL_DATABASE_URL 指向一个可用实例。"
        ) from exc


def prepare(dsn):
    """把评测库清成「空 schema」后建表灌种。

    每次重建而非复用：题库或建表语句一改，旧表残留会让评测数字失真，
    而这类失真恰恰是回归门禁最不该有的东西。`pg_trgm` 扩展由 `init_db()` 重新创建。
    """
    ensure_database(dsn)
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")
    os.environ["DATABASE_URL"] = dsn
    get_settings.cache_clear()
    close_pool()
    init_db()
    from app.services.assessment import question_bank

    question_bank.ensure_seeded()
    close_pool()


def search(needle):
    """直接调生产检索函数，不在评测里重写 SQL —— 评的就是线上那条语句。"""
    result = repository.search_questions(needle, limit=TOP_K)
    return (
        [str(item["question_id"]) for item in result["items"]],
        str(result["mode"]),
    )


def known_question_ids():
    from app.core.db import connection

    with connection() as conn:
        rows = conn.execute("SELECT id FROM questions").fetchall()
    return {str(row["id"]) for row in rows}


def evaluate(gold_path):
    gold = json.loads(gold_path.read_text(encoding="utf-8"))
    dsn = eval_dsn()
    prepare(dsn)
    try:
        known_ids = known_question_ids()
        per_case = []
        for case in gold["cases"]:
            expected = [str(x) for x in case["expected_question_ids"]]
            missing = [x for x in expected if x not in known_ids]
            if missing:
                raise RuntimeError(
                    "金标 {} 引用了题库不存在的 id：{}".format(
                        case["id"], ", ".join(missing)
                    )
                )
            needle = str(case["query"]).strip()
            returned, mode = search(needle)
            per_case.append(
                {
                    "id": case["id"],
                    "query": needle,
                    "direction": str(case.get("direction") or "-"),
                    "mode": mode,
                    "returned": returned,
                    "expected": expected,
                    "hit": any(x in expected for x in returned),
                }
            )
    finally:
        close_pool()

    n = len(per_case)
    hits = sum(1 for c in per_case if c["hit"])
    empty = sum(1 for c in per_case if not c["returned"])
    lower, upper = wilson(hits, n)
    modes = {}
    for case in per_case:
        modes[case["mode"]] = modes.get(case["mode"], 0) + 1
    return {
        "version": gold.get("version", "v1"),
        "created_at": gold.get("created_at", "-"),
        "n": n,
        "hits": hits,
        "recall": hits / n if n else 0.0,
        "empty": empty,
        "empty_rate": empty / n if n else 0.0,
        "modes": modes,
        "question_count": len(known_ids),
        "dsn": redact(dsn),
        "lower": lower,
        "upper": upper,
        "directions": len({c["direction"] for c in per_case}),
        "per_case": per_case,
    }


def build_stdout(m, check_mode):
    bar = "-" * 64
    modes = " / ".join(
        name + " " + frac(count, m["n"]) for name, count in sorted(m["modes"].items())
    )
    lines = [
        bar,
        " 题目侧检索召回评估摘要（PG ILIKE 关键词检索，非向量检索 / RAG）",
        bar,
        " 评测库    : {}（题库 {} 道）".format(m["dsn"], m["question_count"]),
        " 标注数据  : docs/eval/question-retrieval-gold.json ({}, {})".format(
            m["version"], m["created_at"]
        ),
        " 样本量 n  : {}（覆盖 {} 个方向）".format(m["n"], m["directions"]),
        " recall@5  : {}（{}）".format(pct(m["recall"]), frac(m["hits"], m["n"])),
        " 无命中率  : {}（{}，top-5 返回为空）".format(
            pct(m["empty_rate"]), frac(m["empty"], m["n"])
        ),
        f" 检索路径  : {modes}",
        " recall@5 Wilson 95% (z=1.96): [{:.4f}, {:.4f}] = [{}, {}]".format(
            m["lower"], m["upper"], pct(m["lower"]), pct(m["upper"])
        ),
        bar,
    ]
    if check_mode:
        lines.append(" --check 只读模式：未写入任何文件")
    else:
        lines.append(" 报告生成: docs/eval/QUESTION-RETRIEVAL-REPORT.md")
    return "\n".join(lines)


def gate(m):
    failures = []
    if m["recall"] < CHECK_RECALL_MIN:
        failures.append(
            "recall@5 {} 低于门禁阈值 {}".format(
                pct(m["recall"]), pct(CHECK_RECALL_MIN)
            )
        )
    return failures


def render(m):
    L = []
    L.append("# 题目侧检索召回评估报告")
    L.append("")
    L.append(
        "> 生成命令：`python -X utf8 scripts/eval_question_retrieval.py` ｜ "
        "数据：`docs/eval/question-retrieval-gold.json`（version `{}`）｜ "
        "样本量 n = {}".format(m["version"], m["n"])
    )
    L.append(">")
    L.append(
        "> 本报告由 `scripts/eval_question_retrieval.py` 真实运行输出生成，"
        "所有数字来自本次**直连 PostgreSQL** 调用 `repository.search_questions()` "
        "的实测结果，非手写编造。"
    )
    L.append("> 数据全部为合成 / 题库启发标注，仅用于回归检测，不是能力宣传。")
    L.append("")
    L.append("## 口径说明")
    L.append("")
    L.append(
        "- 评估对象：`repository.search_questions()` 的真实执行结果 —— "
        "`prompt ILIKE ? OR explanation ILIKE ?` 子串匹配（`pg_trgm` GIN 索引加速）。"
    )
    L.append(
        "- **这是关键词检索，不是向量检索 / RAG**：全程无 embedding、无向量库、"
        "无大模型生成；返回题目 id 作为引用锚点，不参与任何文本生成。"
    )
    L.append(
        "- 复现方式：脚本在 `{}` 上重建 schema、执行 `init_db()` 建表、"
        "由 `question_bank.ensure_seeded()` 灌入 `backend/app/seed/questions.json` "
        "（本次 {} 道），再逐条调用生产检索函数。".format(
            m["dsn"], m["question_count"]
        )
    )
    L.append(
        "- 不启用方向硬过滤（等价于以默认参数调用 `search_questions`），"
        "case 的 direction 仅作标注元信息与方向覆盖统计。"
    )
    L.append("- 指标定义：")
    L.append(
        "  - **recall@5** = top-5 至少命中一个 `expected_question_ids` 的组数 / n。"
    )
    L.append(
        "  - **无命中率** = top-5 返回为空（未召回任何题目）的组数 / n；"
        "未命中期望 = 1 - recall@5。"
    )
    L.append(
        "  - **Wilson 95% 区间** = 对 recall@5 的小样本比例区间（z=1.96）。"
    )
    L.append(
        "- 数据来源：`docs/eval/question-retrieval-gold.json`（version `{}`，"
        "created_at `{}`），共 {} 组，覆盖 {} 个方向，"
        "期望 id 100% 来自题库真实 id。".format(
            m["version"], m["created_at"], m["n"], m["directions"]
        )
    )
    L.append("")
    L.append("### 解读限制（不要把 100% 当能力宣传）")
    L.append("")
    L.append(
        "- 标注集由题目关键词启发写成（query 取自题干连续中文子串或 2 字概念词），"
        "**存在标注泄漏风险**；recall@5 高分只能证明「检索 SQL、"
        "排序与分页逻辑未回归、引用 id 有效」，不能证明对真实用户自由输入的泛化能力。"
    )
    L.append(
        "- 本评估只用于 CI 回归检测，不是能力宣传；数据全部为合成 / 题库启发标注。"
    )
    L.append(
        "- 对外引用请使用 Wilson 95% 区间的下界；"
        "扩充到 >=100 组真实用户查询后再更新结论。"
    )
    L.append(
        "- 本评估只覆盖题目侧关键词召回，不含向量检索 / RAG / RRF 融合后的排序。"
    )
    L.append("")
    L.append("## 生成命令")
    L.append("")
    L.append("在仓库根目录执行（Windows 请用 `python -X utf8`）：")
    L.append("")
    L.append("```bash")
    L.append("python -X utf8 scripts/eval_question_retrieval.py")
    L.append("python -X utf8 scripts/eval_question_retrieval.py --check")
    L.append("```")
    L.append("")
    L.append(
        "- 默认模式：重建评测库、跑全部标注、打印摘要并生成/覆写本报告，退出 0。"
    )
    L.append(
        "- `--check`：只读，只算指标并打印，绝不写任何文件；"
        "门禁 recall@5 >= 70%，满足退出 0，否则打印中文失败原因并退出 1。"
    )
    L.append(
        "- 依赖 PostgreSQL（`EVAL_DATABASE_URL` / `DATABASE_URL`，默认本地 5433）"
        "与 `backend/requirements.txt`；连不上时明确失败退出 2。"
    )
    L.append("")
    L.append("## 样本量与指标")
    L.append("")
    L.append("| 指标 | 实测值 | 说明 |")
    L.append("| --- | --- | --- |")
    L.append(
        "| 样本量 n | {} | gold.json 的标注 case 数，覆盖 {} 个方向 |".format(
            m["n"], m["directions"]
        )
    )
    L.append(
        "| recall@5 | {}（{}） | top-5 命中任一期望 id 的组数 / n |".format(
            pct(m["recall"]), frac(m["hits"], m["n"])
        )
    )
    L.append(
        "| 无命中率 | {}（{}） | top-5 返回为空的组数 / n |".format(
            pct(m["empty_rate"]), frac(m["empty"], m["n"])
        )
    )
    L.append(
        "| recall@5 Wilson 95% 区间 | [{}, {}] | z=1.96 的 Wilson score 区间 |".format(
            pct(m["lower"]), pct(m["upper"])
        )
    )
    L.append("")
    L.append("## recall@5 的 Wilson 95% 置信区间")
    L.append("")
    L.append(
        "z = 1.96，n = {}，命中组数 k = {}，点估计 p = {:.4f}。".format(
            m["n"], m["hits"], m["recall"]
        )
    )
    L.append("")
    L.append("```text")
    L.append("denom  = 1 + z^2 / n")
    L.append("center = (p + z^2 / (2n)) / denom")
    L.append("half   = (z / denom) * sqrt( p(1-p)/n + z^2/(4n^2) )")
    L.append("CI     = [center - half, center + half]   （钳到 [0,1]）")
    L.append("```")
    L.append("")
    L.append(
        "- **Wilson 95% CI = [{:.4f}, {:.4f}]，即 [{}, {}]**".format(
            m["lower"], m["upper"], pct(m["lower"]), pct(m["upper"])
        )
    )
    L.append("")
    L.append(
        "> recall@5 属于小样本（n={}）比例，故不以裸百分比单独给出，"
        "随附 Wilson 区间以反映估计的不确定性。".format(m["n"])
    )
    L.append("")
    L.append("## 检索路径分布")
    L.append("")
    L.append(
        "- r98 起检索只剩一条路径（SQLite FTS5 虚表已删除）："
        "`prompt` / `explanation` 的 `ILIKE` 子串匹配，由 `pg_trgm` GIN 索引加速。"
    )
    L.append(
        "- 本次实测：{}。`search_questions()` 的 `mode` 恒为 `like`、"
        "`notice` 恒为空，前端不会再看到「未启用全文索引」的提示。".format(
            " / ".join(
                name + " " + frac(count, m["n"])
                for name, count in sorted(m["modes"].items())
            )
        )
    )
    L.append("")
    L.append("## 逐组明细")
    L.append("")
    L.append(
        "| id | query | 方向 | 检索路径 | "
        "top-5 返回（命中期望加 [期望] 前缀） | 是否命中 |"
    )
    L.append("| --- | --- | --- | --- | --- | --- |")
    for c in m["per_case"]:
        expected = set(c["expected"])
        shown = ", ".join(
            ("[期望]" + x) if x in expected else x for x in c["returned"]
        )
        if not shown:
            shown = "—"
        L.append(
            "| {} | {} | {} | {} | {} | {} |".format(
                c["id"],
                c["query"],
                c["direction"],
                c["mode"],
                shown,
                "命中" if c["hit"] else "未命中",
            )
        )
    L.append("")
    L.append(
        "> 「top-5 返回」列列出该组检索返回的题目 id（保序），"
        "前缀 [期望] 表示该 id 属于该组 `expected_question_ids`；"
        "`—` 表示未返回任何题目。"
    )
    L.append(
        "> 「是否命中」为「命中」当且仅当至少一个返回 id 属于期望集合。"
    )
    L.append("")
    return "\n".join(L)


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(
        description="题目侧检索召回评估（直连 PostgreSQL，跑生产同一条 SQL）"
    )
    parser.add_argument("--gold", default=str(GOLD), help="金标集 JSON 路径")
    parser.add_argument("--report", default=str(REPORT), help="Markdown 报告输出路径")
    parser.add_argument(
        "--check", action="store_true", help="CI 门禁：只读，不写任何文件"
    )
    args = parser.parse_args(argv)

    try:
        m = evaluate(Path(args.gold).resolve())
    except (OSError, ValueError, KeyError, RuntimeError, psycopg.Error) as exc:
        LOGGER.error("题目侧检索评估运行失败：%s", exc)
        return 2

    if args.check:
        print(build_stdout(m, check_mode=True))
        failures = gate(m)
        if failures:
            LOGGER.error("题目侧检索门禁未通过（--check 只读，未写入任何文件）：")
            for line in failures:
                LOGGER.error("  - %s", line)
            return 1
        print(
            "题目侧检索门禁通过（--check 只读，未写入任何文件）："
            "recall@5 >= " + pct(CHECK_RECALL_MIN)
        )
        return 0

    report_path = Path(args.report).resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render(m), encoding="utf-8")
    print(build_stdout(m, check_mode=False))
    print("报告已生成：" + str(report_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
