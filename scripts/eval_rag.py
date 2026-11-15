"""r100 RAG 检索评测：关键词 / 语义 / RRF 混合三态对比（直连 PostgreSQL 跑生产管线）。

评测对象与诚实边界：
- 评的是 `services/retrieval/hybrid.py::search_chunks()` 的**真实执行结果**——
  embedding 默认走离线 HashingEmbedder（char-bigram 特征哈希，零网络 / 零 Key），
  语义腿在此基座上的含义是**字符重叠相似度**（模糊关键词），不是语义模型的语义；
  配置 `AI_EMBED_MODEL` 换真实 embedding 端点后，本脚本无需改动即评真实语义路径，
  报告会按 embedder 名如实标注。
- 金标集复用 `docs/eval/question-retrieval-gold.json`（存在标注泄漏风险，只用于
  CI 回归检测，不是能力宣传）；期望命中按 chunk 的 `ref_id`（= 题目 id）对账。
- 需要可用的 PostgreSQL（`EVAL_DATABASE_URL` > `DATABASE_URL` > 本地 compose 默认），
  连不上即失败退出 2，绝不静默跳过。

门禁（--check，只读）：
1. hybrid recall@5 >= 0.70（融合路径必须能干活）；
2. hybrid recall@5 >= keyword recall@5 - 0.05（融合不许明显回退——
   RRF 的意义是「至少不比单腿差」，回退说明融合实现有 bug）。

用法：
    python -X utf8 scripts/eval_rag.py            # 离线基座评测（生成报告）
    python -X utf8 scripts/eval_rag.py --check    # CI 门禁（不写任何文件）
    AI_LIVE=1 python -X utf8 scripts/eval_rag.py --live
        # 真模型对比：先跑离线哈希基线，再把索引整体换成 AI_EMBED_MODEL 指向的真实
        # embedding 端点重跑一遍，产出「语义腿 80% → ?%」的量化对比（RAG-LIVE-REPORT.md）。
        # 会消耗真实网络调用，不进 CI。
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

import httpx
import psycopg

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend"))

from scripts_eval_shared import prepare_eval_db

from app.core.db import close_pool
from app.services.retrieval.hybrid import search_chunks

GOLD = ROOT / "docs" / "eval" / "question-retrieval-gold.json"
REPORT = ROOT / "docs" / "eval" / "RAG-RETRIEVAL-REPORT.md"
#: 真模型对比报告单独一份：不覆盖离线基线（两条轨道的口径与可复现性都不同）。
LIVE_REPORT = ROOT / "docs" / "eval" / "RAG-LIVE-REPORT.md"

CHECK_HYBRID_RECALL_MIN = 0.70
#: 融合对关键词腿的回退容忍度：hybrid 不得比 keyword 低超过 5 个百分点。
REGRESSION_TOLERANCE = 0.05
TOP_K = 5
MODES = ("keyword", "semantic", "hybrid")
LOGGER = logging.getLogger("eval_rag")


def pct(value):
    return format(value * 100, ".1f") + "%"


def frac(a, b):
    return str(a) + "/" + str(b)


def _first_hit_rank(expected, returned):
    for rank, value in enumerate(returned, start=1):
        if value in expected:
            return rank
    return 0


def _metrics(cases, mode_name):
    """单模式的 recall@K / MRR@K / hit@1（按 chunk.ref_id = 题目 id 对账）。"""
    per_case = []
    for case in cases:
        expected = set(case["expected"])
        returned = [str(item["ref_id"]) for item in case["results"][mode_name]]
        rank = _first_hit_rank(expected, returned)
        per_case.append(
            {
                "id": case["id"],
                "query": case["query"],
                "returned": returned,
                "expected": sorted(expected),
                "hit": rank > 0,
                "rank": rank,
                "mrr": 1.0 / rank if rank > 0 else 0.0,
                "hit1": bool(returned) and returned[0] in expected,
            }
        )
    n = len(per_case)
    return {
        "mode": mode_name,
        "n": n,
        "recall": sum(1 for c in per_case if c["hit"]) / n if n else 0.0,
        "mrr": sum(c["mrr"] for c in per_case) / n if n else 0.0,
        "hit1": sum(1 for c in per_case if c["hit1"]) / n if n else 0.0,
        "per_case": per_case,
    }


def evaluate(gold_path):
    gold = json.loads(gold_path.read_text(encoding="utf-8"))
    status = prepare_eval_db()
    cases = []
    try:
        for case in gold["cases"]:
            expected = [str(x) for x in case["expected_question_ids"]]
            results = {}
            for mode_name in MODES:
                payload = search_chunks(str(case["query"]).strip(), mode=mode_name, top_k=TOP_K)
                results[mode_name] = payload["items"]
            cases.append(
                {"id": case["id"], "query": str(case["query"]).strip(), "expected": expected,
                 "results": results}
            )
    finally:
        close_pool()
    metrics = {name: _metrics(cases, name) for name in MODES}
    return {
        "version": gold.get("version", "v1"),
        "created_at": gold.get("created_at", "-"),
        "n": len(cases),
        "question_count": status["question_chunks"],
        "embedder": status["embedder"],
        "engine": status["engine"],
        "dsn": status["dsn"],
        "metrics": metrics,
    }


def live_embed_config() -> tuple[str, str, str]:
    """--live 的 embedding 端点配置（缺一项就明确报错，不猜）。"""
    base = os.environ.get("AI_EMBED_BASE_URL", "").strip().rstrip("/")
    model = os.environ.get("AI_EMBED_MODEL", "").strip()
    key = os.environ.get("AI_EMBED_API_KEY", "").strip()
    missing = [
        name for name, value in (
            ("AI_EMBED_BASE_URL", base), ("AI_EMBED_MODEL", model),
        ) if not value
    ]
    if missing:
        raise RuntimeError(
            "--live 需要真实 embedding 端点：缺少 " + "、".join(missing)
            + "（本地容器写 http://embedder:8080/v1，模型写 BAAI/bge-small-zh-v1.5）"
        )
    return base, model, key


def probe_embedding_dim(base: str, model: str, api_key: str) -> int:
    """探测模型输出维度：维度要进 DDL，不能拍脑袋猜（猜错就报 expected N dimensions）。"""
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = "Bearer " + api_key
    try:
        response = httpx.post(
            base + "/embeddings",
            json={"model": model, "input": ["维度探针"]},
            headers=headers,
            timeout=30.0,
        )
    except httpx.HTTPError as exc:
        raise RuntimeError(
            "embedding 端点不可达：" + base + "（" + type(exc).__name__ + "）"
            + "；若用本地 embedder 容器，先 docker compose --profile embed up -d embedder"
        ) from exc
    if response.status_code != 200:
        raise RuntimeError(
            "embedding 端点返回 " + str(response.status_code) + "，请检查模型名与 Key"
        )
    data = response.json().get("data") or []
    if not data:
        raise RuntimeError("embedding 端点没有返回向量")
    return len(data[0]["embedding"])


def activate_live_embedder(base: str, model: str, dim: int) -> None:
    """把当前进程切到真模型：维度写进 env（init_db 据此建列），并清掉配置缓存。"""
    from app.core.config import get_settings

    os.environ["AI_EMBED_BASE_URL"] = base
    os.environ["AI_EMBED_MODEL"] = model
    os.environ["AI_EMBED_DIM"] = str(dim)
    get_settings.cache_clear()


def compare_rows(offline, live):
    """三态指标逐项对比（离线 → 真模型 + 差值）。"""
    rows = []
    for name in MODES:
        before = offline["metrics"][name]
        after = live["metrics"][name]
        rows.append(
            {
                "mode": name,
                "recall_before": before["recall"],
                "recall_after": after["recall"],
                "delta": after["recall"] - before["recall"],
                "mrr_before": before["mrr"],
                "mrr_after": after["mrr"],
                "hit1_before": before["hit1"],
                "hit1_after": after["hit1"],
            }
        )
    return rows


def render_live(offline, live):
    L = []
    L.append("# RAG 真模型 vs 离线基座 · 三态检索对比报告")
    L.append("")
    L.append(
        "> 生成命令：`AI_LIVE=1 python -X utf8 scripts/eval_rag.py --live` ｜ "
        "金标 `question-retrieval-gold.json`（{}）｜ n = {}".format(
            offline["version"], offline["n"]
        )
    )
    L.append(">")
    L.append(
        "> **两条轨道同库同金标**：先离线基座（`{}`，engine={}），再把索引整体换成"
        "真模型（`{}`，engine={}）重跑。所有数字来自直连 PostgreSQL 的真实执行。".format(
            offline["embedder"], offline["engine"], live["embedder"], live["engine"]
        )
    )
    L.append("")
    L.append("## 对比（离线基座 → 真模型）")
    L.append("")
    L.append("| 模式 | recall@5 | Δ | MRR@5 | hit@1 |")
    L.append("| --- | --- | --- | --- | --- |")
    for row in compare_rows(offline, live):
        L.append(
            "| {} | {} → {} | {:+.1f}pp | {:.4f} → {:.4f} | {} → {} |".format(
                row["mode"], pct(row["recall_before"]), pct(row["recall_after"]),
                row["delta"] * 100, row["mrr_before"], row["mrr_after"],
                pct(row["hit1_before"]), pct(row["hit1_after"]),
            )
        )
    L.append("")
    L.append("## 逐组命中名次（✗ = top-5 未命中；括号内为真模型）")
    L.append("")
    L.append("| id | query | keyword | semantic | hybrid |")
    L.append("| --- | --- | --- | --- | --- |")
    offline_cases = {c["id"]: c for c in offline["metrics"]["hybrid"]["per_case"]}
    live_keyword = {c["id"]: c for c in live["metrics"]["keyword"]["per_case"]}
    live_semantic = {c["id"]: c for c in live["metrics"]["semantic"]["per_case"]}
    live_hybrid = {c["id"]: c for c in live["metrics"]["hybrid"]["per_case"]}
    for case_id, case in offline_cases.items():
        anchor_cases = {
            "keyword": offline["metrics"]["keyword"]["per_case"],
            "semantic": offline["metrics"]["semantic"]["per_case"],
            "hybrid": offline["metrics"]["hybrid"]["per_case"],
        }
        after = {
            "keyword": live_keyword, "semantic": live_semantic, "hybrid": live_hybrid,
        }

        def cell(mode_name):
            before_rows = anchor_cases[mode_name]
            before = next((c for c in before_rows if c["id"] == case_id), None)
            after_row = after[mode_name].get(case_id)
            return "{}（{}）".format(
                "第{}位".format(before["rank"]) if before and before["hit"] else "✗",
                "第{}位".format(after_row["rank"]) if after_row and after_row["hit"] else "✗",
            )

        L.append(
            "| {} | {} | {} | {} | {} |".format(
                case_id, case["query"], cell("keyword"), cell("semantic"), cell("hybrid")
            )
        )
    L.append("")
    L.append("## 解读限制")
    L.append("")
    L.append("- 金标是题干子串式标注（存在标注泄漏），关键词腿天然占优；"
             "真模型的收益应主要看 **semantic 腿**与 **MRR**，不是只看 hybrid 的百分点。")
    L.append("- 本轮只换了 embedding 与索引，检索/融合/门禁代码零改动——"
             "对比的是「同一条管线换向量空间」的收益。")
    L.append("- 报告由脚本真实运行生成，勿手改数字。")
    L.append("")
    return "\n".join(L)


def gate(m):
    failures = []
    hybrid = m["metrics"]["hybrid"]
    keyword = m["metrics"]["keyword"]
    if hybrid["recall"] < CHECK_HYBRID_RECALL_MIN:
        failures.append(
            "hybrid recall@{} {} 低于门禁阈值 {}".format(
                TOP_K, pct(hybrid["recall"]), pct(CHECK_HYBRID_RECALL_MIN)
            )
        )
    if hybrid["recall"] < keyword["recall"] - REGRESSION_TOLERANCE:
        failures.append(
            "hybrid recall@{} {} 比 keyword {} 回退超过 {} 个百分点：融合不应明显差于单腿".format(
                TOP_K, pct(hybrid["recall"]), pct(keyword["recall"]),
                pct(REGRESSION_TOLERANCE),
            )
        )
    return failures


def build_stdout(m, check_mode, report_hint="docs/eval/RAG-RETRIEVAL-REPORT.md"):
    bar = "-" * 64
    lines = [bar, " RAG 三态检索评测摘要（chunk 级，ref_id = 题目 id）", bar,
             " 评测库    : {}（题库 chunk {} 条）".format(m["dsn"], m["question_count"]),
             " embedder  : {}（engine={}）".format(m["embedder"], m["engine"]),
             " 标注数据  : docs/eval/question-retrieval-gold.json ({}, {})".format(
                 m["version"], m["created_at"]),
             " 样本量 n  : {}".format(m["n"]),
             ""]
    for name in MODES:
        row = m["metrics"][name]
        lines.append(
            " {:<9}: recall@{} {}  MRR@{} {:.4f}  hit@1 {}".format(
                name, TOP_K, pct(row["recall"]), TOP_K, row["mrr"], pct(row["hit1"])
            )
        )
    lines.append(bar)
    lines.append("--check 只读模式：未写入任何文件" if check_mode
                 else "报告: " + report_hint)
    return "\n".join(lines)


def render(m):
    L = []
    L.append("# RAG 三态检索评测报告")
    L.append("")
    L.append(
        "> 生成命令：`python -X utf8 scripts/eval_rag.py` ｜ 金标复用 `question-retrieval-gold.json`"
        "（version `{}`）｜ embedder `{}`（engine `{}`）｜ 样本量 n = {}".format(
            m["version"], m["embedder"], m["engine"], m["n"]
        )
    )
    L.append(">")
    L.append("> 所有数字来自**直连 PostgreSQL** 真实执行 `services/retrieval/hybrid.py` 的结果，非手写。")
    L.append("> 检索对象是 `rag_chunks`（题库 chunk），命中按 `chunk.ref_id`（= 题目 id）对账。")
    L.append("")
    L.append("## 口径说明")
    L.append("")
    L.append("- 三态：keyword = chunk 正文 ILIKE；semantic = 向量余弦 top-K；"
             "hybrid = 两腿 RRF（k=60）融合。")
    L.append("- 默认 embedder 是离线 HashingEmbedder：其「语义」是字符 bigram 重叠"
             "（模糊关键词基座），**不是语义模型**；配置 `AI_EMBED_MODEL` 后本脚本零改动即评真实语义。")
    L.append("- 门禁：hybrid recall@5 ≥ 70%，且不比 keyword 回退超过 5 个百分点"
             "（融合的意义是「至少不比单腿差」）。")
    L.append("- 标注集由题干关键词启发写成，存在标注泄漏；只用于回归检测，不是能力宣传。")
    L.append("")
    L.append("## 三态指标")
    L.append("")
    L.append("| 模式 | recall@5 | MRR@5 | hit@1 |")
    L.append("| --- | --- | --- | --- |")
    for name in MODES:
        row = m["metrics"][name]
        L.append(
            "| {} | {} | {:.4f} | {} |".format(name, pct(row["recall"]), row["mrr"], pct(row["hit1"]))
        )
    L.append("")
    L.append("## 逐组明细（命中名次，✗ = top-5 未命中）")
    L.append("")
    L.append("| id | query | keyword | semantic | hybrid |")
    L.append("| --- | --- | --- | --- | --- |")
    keyword_cases = {c["id"]: c for c in m["metrics"]["keyword"]["per_case"]}
    semantic_cases = {c["id"]: c for c in m["metrics"]["semantic"]["per_case"]}
    hybrid_cases = {c["id"]: c for c in m["metrics"]["hybrid"]["per_case"]}
    for case_id in keyword_cases:
        def cell(row):
            if row is None:
                return "—"
            return "第{}位".format(row["rank"]) if row["hit"] else "✗"
        L.append(
            "| {} | {} | {} | {} | {} |".format(
                case_id, keyword_cases[case_id]["query"],
                cell(keyword_cases.get(case_id)), cell(semantic_cases.get(case_id)),
                cell(hybrid_cases.get(case_id)),
            )
        )
    L.append("")
    return "\n".join(L)


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description="RAG 三态检索评测（关键词 / 语义 / 混合）")
    parser.add_argument("--gold", default=str(GOLD), help="金标集 JSON 路径")
    parser.add_argument("--report", default=str(REPORT), help="Markdown 报告输出路径")
    parser.add_argument("--check", action="store_true", help="CI 门禁：只读，不写任何文件")
    parser.add_argument(
        "--live", action="store_true",
        help="真模型对比（需 AI_LIVE=1 与 AI_EMBED_BASE_URL/AI_EMBED_MODEL；不进 CI）",
    )
    args = parser.parse_args(argv)
    if args.live and args.check:
        LOGGER.error("--check 与 --live 互斥：门禁只跑离线基座")
        return 2
    if args.live and os.environ.get("AI_LIVE") != "1":
        LOGGER.error("--live 需要 AI_LIVE=1 显式确认（会真实调用 embedding 端点）")
        return 2

    gold_path = Path(args.gold).resolve()
    try:
        # 真模型对比：先跑离线基座（此时 AI_EMBED_MODEL 必须为空），再切真模型重跑。
        if args.live:
            # 先把端点配置读进来，再临时摘掉 embedding 环境变量跑离线基线
            # （否则基线会被当成真模型，两条轨道就变成同一条了）。
            base, model, api_key = live_embed_config()
            for name in ("AI_EMBED_BASE_URL", "AI_EMBED_MODEL", "AI_EMBED_API_KEY", "AI_EMBED_DIM"):
                os.environ.pop(name, None)
            LOGGER.info("第一段：离线哈希基线…")
            offline = evaluate(gold_path)
            dim = probe_embedding_dim(base, model, api_key)
            LOGGER.info("第二段：真模型 %s（%s，%d 维），重建索引并重跑…", model, base, dim)
            activate_live_embedder(base, model, dim)
            live = evaluate(gold_path)
        else:
            m = evaluate(gold_path)
    except (OSError, ValueError, KeyError, RuntimeError, psycopg.Error) as exc:
        LOGGER.error("RAG 检索评测运行失败：%s", exc)
        return 2

    if args.check:
        print(build_stdout(m, check_mode=True))
        failures = gate(m)
        if failures:
            LOGGER.error("RAG 检索门禁未通过（--check 只读，未写入任何文件）：")
            for line in failures:
                LOGGER.error("  - %s", line)
            return 1
        print("RAG 检索门禁通过（--check 只读，未写入任何文件）")
        return 0

    if args.live:
        print("=== 第一段：离线基座（零网络，CI 对照面）===")
        print(build_stdout(offline, check_mode=False, report_hint="本段不单独出报告"))
        print("=== 第二段：真模型 " + live["embedder"] + " ===")
        print(build_stdout(live, check_mode=False, report_hint="docs/eval/RAG-LIVE-REPORT.md"))
        for row in compare_rows(offline, live):
            print(
                " Δ {:<9}: recall {:+5.1f}pp  MRR {:+.4f}  hit@1 {:+5.1f}pp".format(
                    row["mode"], row["delta"] * 100,
                    row["mrr_after"] - row["mrr_before"],
                    (row["hit1_after"] - row["hit1_before"]) * 100,
                )
            )
        report_path = LIVE_REPORT
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(render_live(offline, live), encoding="utf-8")
        print("报告已生成：" + str(report_path))
        failures = gate(live)
        if failures:
            LOGGER.error("真模型门禁未通过：")
            for line in failures:
                LOGGER.error("  - %s", line)
            return 1
        return 0

    report_path = Path(args.report).resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render(m), encoding="utf-8")
    print(build_stdout(m, check_mode=False))
    print("报告已生成：" + str(report_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
