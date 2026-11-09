"""题目侧 FTS5 端到端召回评估（零网络、零 FastAPI 依赖，纯标准库）。

诚实边界：
- 评估对象是 SQLite FTS5 trigram 关键词检索，**不是向量检索 / RAG**；
  全程无 embedding、无向量库、无大模型生成。
- 标注 query 由题库题干关键词启发写成，存在标注泄漏风险，
  仅用于 CI 回归检测，不是能力宣传；数据全部为合成 / 题库启发标注。
- 在内存库重建与生产等价的 question_search 虚表，MATCH 表达式与
  repository.search_questions() 完全一致，短查询降级 LIKE。

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
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GOLD = ROOT / "docs" / "eval" / "question-retrieval-gold.json"
QUESTIONS = ROOT / "backend" / "app" / "seed" / "questions.json"
REPORT = ROOT / "docs" / "eval" / "QUESTION-RETRIEVAL-REPORT.md"

#: --check 门禁阈值与统计常量（顶层常量，便于调整）。
CHECK_RECALL_MIN = 0.70
WILSON_Z = 1.96
TOP_K = 5
LOGGER = logging.getLogger("eval_question_retrieval")

#: 与 backend/app/core/db.py 的 R51_FTS_SCHEMA 逐字等价。
FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS question_search USING fts5(
    question_id UNINDEXED,
    prompt,
    explanation,
    direction UNINDEXED,
    sub_direction UNINDEXED,
    tokenize = 'trigram'
);
"""


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
        WILSON_Z
        * math.sqrt(p * (1 - p) / total + z2 / (4 * total**2))
        / denom
    )
    return (
        round(max(0.0, center - margin), 4),
        round(min(1.0, center + margin), 4),
    )


def load_questions(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    return [
        (
            str(q["id"]),
            str(q.get("prompt") or ""),
            str(q.get("explanation") or ""),
            str(q.get("direction") or ""),
            str(q.get("sub_direction") or ""),
        )
        for q in data
    ]


def build_index(rows):
    """内存库重建生产等价索引；FTS5 / trigram 缺失时明确抛错，绝不静默通过。"""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    probe = conn.execute(
        "SELECT sqlite_compileoption_used('ENABLE_FTS5') AS enabled"
    ).fetchone()
    if not probe or not probe["enabled"]:
        conn.close()
        raise RuntimeError(
            "本机 SQLite 未编译 FTS5（ENABLE_FTS5 缺失），无法重建"
            " question_search 虚表，评估明确失败"
        )
    try:
        conn.execute(FTS_SCHEMA)
    except sqlite3.OperationalError as exc:
        conn.close()
        raise RuntimeError(
            "本机 SQLite 不支持 fts5 trigram tokenizer，评估明确失败：" + str(exc)
        ) from exc
    conn.execute(
        "CREATE TABLE questions ("
        "id TEXT PRIMARY KEY, prompt TEXT, explanation TEXT, "
        "direction TEXT, sub_direction TEXT)"
    )
    conn.executemany(
        "INSERT INTO questions "
        "(id, prompt, explanation, direction, sub_direction) VALUES (?, ?, ?, ?, ?)",
        rows,
    )
    conn.executemany(
        "INSERT INTO question_search "
        "(question_id, prompt, explanation, direction, sub_direction) "
        "VALUES (?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    return conn


def search(conn, needle):
    """复现 repository.search_questions()：长查询 FTS5 MATCH，短查询降级 LIKE。

    MATCH 表达式与生产一致：把 needle 用双引号包成短语，内部双引号翻倍转义。
    等价于以默认参数调用（direction/sub_direction 为空，不启用方向硬过滤）。
    """
    if len(needle) >= 3:
        match = '"' + needle.replace('"', '""') + '"'
        rows = conn.execute(
            "SELECT question_id FROM question_search "
            "WHERE question_search MATCH ? "
            "ORDER BY bm25(question_search) ASC LIMIT ?",
            (match, TOP_K),
        ).fetchall()
        return [str(r["question_id"]) for r in rows], "fts5"
    like = "%" + needle + "%"
    rows = conn.execute(
        "SELECT id FROM questions "
        "WHERE (prompt LIKE ? OR explanation LIKE ?) ORDER BY id LIMIT ?",
        (like, like, TOP_K),
    ).fetchall()
    return [str(r["id"]) for r in rows], "like"


def evaluate(gold_path, questions_path):
    gold = json.loads(gold_path.read_text(encoding="utf-8"))
    rows = load_questions(questions_path)
    known_ids = {r[0] for r in rows}
    conn = build_index(rows)
    per_case = []
    try:
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
            returned, mode = search(conn, needle)
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
        conn.close()

    n = len(per_case)
    hits = sum(1 for c in per_case if c["hit"])
    empty = sum(1 for c in per_case if not c["returned"])
    fts5_path = sum(1 for c in per_case if c["mode"] == "fts5")
    fts5_hit = sum(1 for c in per_case if c["mode"] == "fts5" and c["hit"])
    lower, upper = wilson(hits, n)
    return {
        "version": gold.get("version", "v1"),
        "created_at": gold.get("created_at", "-"),
        "n": n,
        "hits": hits,
        "recall": hits / n if n else 0.0,
        "empty": empty,
        "empty_rate": empty / n if n else 0.0,
        "fts5_path": fts5_path,
        "fts5_hit": fts5_hit,
        "fts5_hit_share": fts5_hit / n if n else 0.0,
        "like_path": n - fts5_path,
        "lower": lower,
        "upper": upper,
        "directions": len({c["direction"] for c in per_case}),
        "per_case": per_case,
    }


def build_stdout(m, check_mode):
    bar = "-" * 64
    lines = [
        bar,
        " 题目侧 FTS5 检索召回评估摘要（关键词检索，非向量检索 / RAG）",
        bar,
        " 标注数据  : docs/eval/question-retrieval-gold.json ({}, {})".format(
            m["version"], m["created_at"]
        ),
        " 样本量 n  : {}（覆盖 {} 个方向）".format(m["n"], m["directions"]),
        " recall@5  : {}（{}）".format(pct(m["recall"]), frac(m["hits"], m["n"])),
        " 无命中率  : {}（{}，top-5 返回为空）".format(
            pct(m["empty_rate"]), frac(m["empty"], m["n"])
        ),
        " FTS5 命中占比: {}（{}，走 FTS5 且命中期望）".format(
            pct(m["fts5_hit_share"]), frac(m["fts5_hit"], m["n"])
        ),
        " 路径分布  : fts5 {} / like {}".format(
            frac(m["fts5_path"], m["n"]), frac(m["like_path"], m["n"])
        ),
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
    L.append("# 题目侧 FTS5 检索召回评估报告")
    L.append("")
    L.append(
        "> 生成命令：`python -X utf8 scripts/eval_question_retrieval.py` ｜ "
        "数据：`docs/eval/question-retrieval-gold.json`（version `{}`）｜ "
        "样本量 n = {}".format(m["version"], m["n"])
    )
    L.append(">")
    L.append(
        "> 本报告由 `scripts/eval_question_retrieval.py` 真实运行输出生成，"
        "所有数字来自本次内存库 FTS5 检索的实测结果，非手写编造。"
    )
    L.append(
        "> 数据全部为合成 / 题库启发标注，仅用于回归检测，不是能力宣传。"
    )
    L.append("")
    L.append("## 口径说明")
    L.append("")
    L.append(
        "- 评估对象：SQLite `question_search` FTS5 trigram 虚表上的题目关键词召回。"
    )
    L.append(
        "- **这是关键词检索，不是向量检索 / RAG**：全程无 embedding、无向量库、"
        "无大模型生成；MATCH 是短语匹配，返回题目 id 作为引用锚点，不参与任何文本生成。"
    )
    L.append(
        "- 复现方式：在内存库从 `backend/app/seed/questions.json` 读题目，"
        "建 `questions` 表与 `question_search` FTS5 trigram 虚表，"
        "灌入 prompt / explanation / direction / sub_direction。"
    )
    L.append(
        "- 检索逻辑与 `repository.search_questions()` 完全一致："
        "把 needle 用双引号包成短语做 FTS5 MATCH（内部双引号翻倍转义），"
        "按 bm25 升序取 top-5；query 长度 < 3 时降级 LIKE。"
    )
    L.append(
        "- 不启用方向硬过滤（等价于以默认参数调用 search_questions），"
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
        "  - **FTS5 命中占比** = 走 FTS5 路径且命中期望的组数 / n。"
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
        "**存在标注泄漏风险**；recall@5 高分只能证明「FTS5 索引重建、"
        "MATCH 转义与 LIKE 降级逻辑未回归、引用 id 有效」，"
        "不能证明对真实用户自由输入的泛化能力。"
    )
    L.append(
        "- 本评估只用于 CI 回归检测，不是能力宣传；数据全部为合成 / 题库启发标注。"
    )
    L.append(
        "- 对外引用请使用 Wilson 95% 区间的下界；"
        "扩充到 >=100 组真实用户查询后再更新结论。"
    )
    L.append(
        "- 本评估只覆盖题目侧 FTS5 关键词召回，"
        "不含向量检索 / RAG / RRF 融合后的排序。"
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
        "- 默认模式：重建内存索引、跑全部标注、打印摘要并生成/覆写本报告，退出 0。"
    )
    L.append(
        "- `--check`：只读，只算指标并打印，绝不写任何文件；"
        "门禁 recall@5 >= 70%，满足退出 0，否则打印中文失败原因并退出 1。"
    )
    L.append(
        "- 仅依赖 Python 标准库（sqlite3 / json / math / pathlib / argparse），"
        "零网络、零 FastAPI 依赖；本机 SQLite 缺 FTS5 或 trigram 时明确失败退出 2。"
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
        "| FTS5 命中占比 | {}（{}） | 走 FTS5 路径且命中期望的组数 / n |".format(
            pct(m["fts5_hit_share"]), frac(m["fts5_hit"], m["n"])
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
    L.append("## 检索路径分布（FTS5 / LIKE 降级）")
    L.append("")
    L.append(
        "- FTS5 MATCH 路径：{} 组，其中命中期望 {} 组。".format(
            m["fts5_path"], m["fts5_hit"]
        )
    )
    L.append(
        "- 短查询降级 LIKE 路径：{} 组（query 长度 < 3，"
        "按 id 排序、无 bm25 相关性排序，是已知局限）。".format(m["like_path"])
    )
    L.append(
        "- 本标注集 {} 组中 {} 组走 FTS5、{} 组走 LIKE，"
        "两条路径均实测覆盖。".format(
            m["n"], m["fts5_path"], m["like_path"]
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
        "> 「是否命中」为「命中」当且仅当至少一个返回 id 属于期望集合；"
        "检索路径 `fts5` 表示走 FTS5 MATCH，`like` 表示短查询降级。"
    )
    L.append("")
    return "\n".join(L)


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(
        description="题目侧 FTS5 检索召回评估（零网络、纯标准库）"
    )
    parser.add_argument("--gold", default=str(GOLD), help="金标集 JSON 路径")
    parser.add_argument("--questions", default=str(QUESTIONS), help="题库 JSON 路径")
    parser.add_argument("--report", default=str(REPORT), help="Markdown 报告输出路径")
    parser.add_argument(
        "--check", action="store_true", help="CI 门禁：只读，不写任何文件"
    )
    args = parser.parse_args(argv)

    try:
        m = evaluate(Path(args.gold).resolve(), Path(args.questions).resolve())
    except (OSError, ValueError, KeyError, RuntimeError, sqlite3.Error) as exc:
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
