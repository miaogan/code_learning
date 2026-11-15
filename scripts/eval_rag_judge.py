"""r100 RAG 生成质量评测（LLM-as-judge 轨）：检索增强回答的忠实度 / 相关性自动评审。

两态口径（与 `eval_live.py` 同一诚实边界）：
- 默认 / `--check`（进 CI）：**DRY-RUN**——生成与评审都走「规则替身」：答案取首条
  检索 chunk 的正文，评审按「答案是否被引用材料支撑 / 期望题是否被召回」打分。
  它验证的是**管线**（检索 → 引用白名单 → 评分 → 聚合 → 报告），零网络、零 Key、
  确定性复跑；**不证明模型质量**。
- `--live`（`AI_LIVE=1`，不进 CI、消耗配额）：真实模型两跳——先按材料生成带引用的
  答案（`generate_answer`），再用 `judge_answer` 评审忠实度与相关性；
  产出 `docs/eval/RAG-JUDGE-REPORT.md` 并如实标注 LIVE。

指标：faithfulness / relevance（0-10，模型按 JSON 契约 `RagJudgeDraft` 输出）。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend"))

LOGGER = logging.getLogger("eval_rag_judge")

GOLD = ROOT / "docs" / "eval" / "question-retrieval-gold.json"
REPORT = ROOT / "docs" / "eval" / "RAG-JUDGE-REPORT.md"

#: 评审样本量：金标前 N 组（live 模式每例两次模型调用，控制配额）。
JUDGE_CASES = 8
TOP_K = 3
#: `--check` 门禁：至少 70% 的 case 能召回非空材料（检索臂的最低可用线）。
CHECK_RETRIEVAL_COVER_MIN = 0.70
DRY = "DRY-RUN（规则替身，零模型）"


def pct(value):
    return format(value * 100, ".1f") + "%"


def _run_case(query, expected, *, live):
    """单例评审：检索 →（生成）→（评审）。live 走真模型，否则走规则替身。"""
    from app.services.retrieval.answer import generate_answer, judge_answer, retrieve_for_answer

    retrieved = retrieve_for_answer(query, mode="hybrid", top_k=TOP_K)
    chunks = list(retrieved["items"])
    if not chunks:
        return {
            "query": query, "expected": expected, "retrieved": 0, "citations": [],
            "dropped": 0, "answer": "", "faithfulness": 0, "relevance": 0,
            "issues": ["检索零命中"], "live": live,
        }
    if not live:
        answer = str(chunks[0]["content"])[:200]
        citations = [chunks[0]["chunk_id"]]
        refs = {item["ref_id"] for item in chunks}
        faithfulness = 10 if answer in str(chunks[0]["content"]) else 6
        relevance = 10 if expected & refs else 5
        dropped = 0
        issues = []
    else:
        from app.services.ai.ai import AIClient

        client = AIClient()

        async def _both():
            draft = await generate_answer(query, chunks, client)
            cited_chunks = [
                chunk for chunk in chunks
                if chunk["chunk_id"] in set(draft.citations)
            ] or chunks[:1]
            verdict = await judge_answer(query, draft.answer, cited_chunks, client)
            return draft, verdict

        draft, verdict = asyncio.run(_both())
        answer = draft.answer
        citations = draft.citations
        dropped = draft.dropped_citations
        faithfulness = verdict.faithfulness
        relevance = verdict.relevance
        issues = verdict.issues
    return {
        "query": query, "expected": expected, "retrieved": len(chunks),
        "citations": citations, "dropped": dropped, "answer": answer,
        "faithfulness": faithfulness, "relevance": relevance, "issues": issues, "live": live,
    }


def evaluate(live: bool):
    """准备评测库 → 逐例跑「检索 → 生成 → 评审」三步。"""
    from scripts_eval_shared import prepare_eval_db

    gold = json.loads(GOLD.read_text(encoding="utf-8"))
    status = prepare_eval_db()
    cases = []
    for case in gold["cases"][:JUDGE_CASES]:
        expected = {str(x) for x in case["expected_question_ids"]}
        cases.append(_run_case(str(case["query"]).strip(), expected, live=live))
    n = len(cases)
    return {
        "mode_tag": ("LIVE（真实模型）" if live else DRY),
        "embedder": status["embedder"],
        "engine": status["engine"],
        "n": n,
        "retrieval_cover": sum(1 for c in cases if c["retrieved"] > 0) / n if n else 0.0,
        "citation_valid": all(c["dropped"] == 0 for c in cases),
        "faithfulness": sum(c["faithfulness"] for c in cases) / n if n else 0.0,
        "relevance": sum(c["relevance"] for c in cases) / n if n else 0.0,
        "cases": cases,
    }


def gate(m):
    failures = []
    if m["retrieval_cover"] < CHECK_RETRIEVAL_COVER_MIN:
        failures.append(
            "检索覆盖率 {} 低于 {}：检索臂在金标前 {} 组上大面积零命中".format(
                pct(m["retrieval_cover"]), pct(CHECK_RETRIEVAL_COVER_MIN), m["n"]
            )
        )
    if not m["citation_valid"]:
        failures.append("存在引用白名单外的引用（dropped_citations > 0）——管线引用校验失效")
    return failures


def build_stdout(m):
    bar = "-" * 64
    lines = [
        bar,
        " RAG 生成质量评审摘要（LLM-as-judge 轨，{}）".format(m["mode_tag"]),
        bar,
        " 样本量 n    : {}".format(m["n"]),
        " 检索覆盖率  : {}".format(pct(m["retrieval_cover"])),
        " 忠实度均值  : {:.2f} / 10".format(m["faithfulness"]),
        " 相关性均值  : {:.2f} / 10".format(m["relevance"]),
        " 引用合法    : {}".format("是" if m["citation_valid"] else "否"),
        bar,
    ]
    return "\n".join(lines)


def render(m):
    L = ["# RAG 生成质量评审报告", ""]
    L.append("> 模式：**{}** ｜ embedder `{}`（engine `{}`）｜ 样本量 n = {}".format(
        m["mode_tag"], m["embedder"], m["engine"], m["n"]))
    L.append(">")
    if not any(c["live"] for c in m["cases"]):
        L.append("> **DRY-RUN 的分数来自规则替身，不证明模型质量**；"
                 "真实模型评分需 `AI_LIVE=1 python -X utf8 scripts/eval_rag_judge.py --live`。")
    L.append("")
    L.append("| 指标 | 值 | 说明 |")
    L.append("| --- | --- | --- |")
    L.append("| 检索覆盖率 | {} | 检索到非空材料的 case 占比 |".format(pct(m["retrieval_cover"])))
    L.append("| 忠实度均值 | {:.2f} / 10 | 答案是否只由引用材料支撑 |".format(m["faithfulness"]))
    L.append("| 相关性均值 | {:.2f} / 10 | 答案是否切题且有信息量 |".format(m["relevance"]))
    L.append("")
    L.append("## 逐组明细")
    L.append("")
    L.append("| query | 召回数 | 忠实度 | 相关性 | 引用 |")
    L.append("| --- | --- | --- | --- | --- |")
    for c in m["cases"]:
        L.append("| {} | {} | {} | {} | {} |".format(
            c["query"], c["retrieved"], c["faithfulness"], c["relevance"],
            ", ".join(c["citations"]) or "—"))
    L.append("")
    return "\n".join(L)


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description="RAG 生成质量评审（LLM-as-judge）")
    parser.add_argument("--check", action="store_true", help="CI 门禁：DRY-RUN 只读，不写任何文件")
    parser.add_argument("--live", action="store_true",
                        help="真实模型评审（需 AI_LIVE=1 与已配置的 AI Key；不进 CI）")
    args = parser.parse_args(argv)

    live = args.live
    if live and os.environ.get("AI_LIVE") != "1":
        LOGGER.error("--live 需要 AI_LIVE=1 显式确认（会消耗第三方配额、产生真实网络调用）")
        return 2
    if args.check and live:
        LOGGER.error("--check 与 --live 互斥：CI 门禁只跑 DRY-RUN")
        return 2

    try:
        m = evaluate(live)
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        LOGGER.error("RAG 评审评测运行失败：%s", exc)
        return 2

    print(build_stdout(m))
    if args.check:
        failures = gate(m)
        if failures:
            LOGGER.error("RAG 评审门禁未通过（DRY-RUN，未写入任何文件）：")
            for line in failures:
                LOGGER.error("  - %s", line)
            return 1
        print("RAG 评审门禁通过（DRY-RUN 只读，未写入任何文件）")
        return 0

    report_path = REPORT.resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render(m), encoding="utf-8")
    print("报告已生成：" + str(report_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
