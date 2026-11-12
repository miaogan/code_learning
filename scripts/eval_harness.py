"""r51 离线评测 Harness（**零网络**）：把「管线有没有回归」变成可复跑的指标与 CI 门禁。

诚实边界（务必先读）：
- 本轨道输入是**固定的模型响应快照 + 人工标注**，衡量的是解析 / 结构校验 / 字段比对管线，
  **不代表模型质量提升**。真实模型质量需在线轨道（AI_LIVE=1、锁定 prompt/model 版本）另行评测。
- 指标分母全部写死在 `evaluate()`：schema 通过率 = 通过校验数 / 全部用例；
  micro-P = TP/(TP+FP)，micro-R = TP/(TP+FN)；小样本比例一律给 Wilson 95% 区间。
- 本地耗时是「解析 + 校验 + 比对」的微秒数，**不是**模型延迟，报告里单独标注。

用法：
    python -X utf8 scripts/eval_harness.py                     # 生成 docs/eval/REPORT.md
    python -X utf8 scripts/eval_harness.py --write-baseline    # 固化基线（提交进仓库）
    python -X utf8 scripts/eval_harness.py --check             # CI 门禁：跌破基线 ±2pp 即退出 1
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "docs" / "eval" / "golden-v1.json"
BASELINE = ROOT / "docs" / "eval" / "baseline-v1.json"
REPORT = ROOT / "docs" / "eval" / "REPORT.md"

#: 门禁波动带：±2 个百分点，避免快照抖动把 CI 变红（r48「持续集成门禁波动带」同题）。
TOLERANCE = 0.02
CORE_METRICS = ("schema_pass_rate", "field_precision", "field_recall", "field_f1")
#: 负向指标：编造词命中率上升超过波动带同样判红。
NEGATIVE_METRICS = ("hallucination_rate",)
WILSON_Z = 1.96


class Snapshot(BaseModel):
    """预录响应快照的结构契约：字段类型不合规即记一次 schema 失败。"""

    skills: list[str]
    projects: list[str]
    years_experience: int
    summary: str


def wilson(successes: int, total: int) -> tuple[float, float]:
    """小样本比例的 Wilson 95% 区间；total=0 时给 (0, 0)，不编造置信度。"""
    if total <= 0:
        return (0.0, 0.0)
    p = successes / total
    denominator = 1 + WILSON_Z**2 / total
    center = (p + WILSON_Z**2 / (2 * total)) / denominator
    margin = (
        WILSON_Z
        * math.sqrt(p * (1 - p) / total + WILSON_Z**2 / (4 * total**2))
        / denominator
    )
    return (round(max(0.0, center - margin), 4), round(min(1.0, center + margin), 4))


def _percentile(values: list[int], quantile: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(quantile * len(ordered)) - 1))
    return ordered[index]


def evaluate(golden_path: Path) -> dict[str, Any]:
    raw = golden_path.read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    cases = payload["cases"]
    tp = fp = fn = 0
    schema_ok = 0
    hallucination_hits = 0
    annotated = 0
    local_us: list[int] = []
    per_case: list[dict[str, Any]] = []

    for case in cases:
        started = time.perf_counter()
        snapshot = case.get("response_snapshot") or {}
        try:
            Snapshot.model_validate(snapshot)
            schema_ok += 1
            schema_valid = True
        except ValidationError:
            schema_valid = False
        # 字段比对用原始快照：解析在校验之前已完成，schema 失败不抹掉已抽取的字段。
        predicted = {
            str(value)
            for key in ("skills", "projects")
            for value in (snapshot.get(key) or [])
            if isinstance(value, str)
        }
        expected = {str(value) for value in case["expected"]["profile_fields"]}
        hit = len(predicted & expected)
        tp += hit
        fp += len(predicted - expected)
        fn += len(expected - predicted)
        forbidden = {str(value) for value in case["expected"].get("must_not_contain", [])}
        if forbidden:
            annotated += 1
            if predicted & forbidden:
                hallucination_hits += 1
        local_us.append(int((time.perf_counter() - started) * 1_000_000))
        per_case.append(
            {
                "id": case["id"],
                "schema_valid": schema_valid,
                "hit": hit,
                "missing": len(expected - predicted),
                "extra": len(predicted - expected),
                "forbidden_hit": bool(predicted & forbidden),
            }
        )

    total = len(cases)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    metrics: dict[str, Any] = {
        "version": payload.get("version", "v1"),
        "rubric_version": payload.get("rubric_version", "r1"),
        "golden_sha256": hashlib.sha256(raw).hexdigest(),
        "case_count": total,
        "schema_pass_rate": round(schema_ok / total, 4) if total else 0.0,
        "field_precision": round(precision, 4),
        "field_recall": round(recall, 4),
        "field_f1": round(f1, 4),
        "hallucination_rate": round(hallucination_hits / annotated, 4) if annotated else None,
        "hallucination_annotated": annotated,
        "p50_local_us": _percentile(local_us, 0.5),
        "p95_local_us": _percentile(local_us, 0.95),
        "confusion": {"tp": tp, "fp": fp, "fn": fn},
        "intervals": {
            "schema_pass_rate": wilson(schema_ok, total),
            "field_precision": wilson(tp, tp + fp),
            "field_recall": wilson(tp, tp + fn),
        },
    }
    metrics["per_case"] = per_case
    return metrics


def _percent(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.1f}%"


def render(metrics: dict[str, Any], golden_path: Path) -> str:
    lines = [
        "# 离线评测报告（r51）",
        "",
        "> **口径**：本轨道是**管线回归门禁** —— 输入为固定模型响应快照 + 人工标注，",
        "> 衡量解析 / 结构校验 / 字段比对是否退化，**不代表模型质量提升**。",
        "> 在线质量评测需锁定 prompt / model 版本打真实模型，另行留轨迹，不进 CI。",
        "",
        f"- 金标集：`{golden_path.relative_to(ROOT).as_posix()}`（{metrics['case_count']} 例，全合成/脱敏）",
        f"- 金标 sha256：`{metrics['golden_sha256']}`",
        f"- rubric 版本：`{metrics['rubric_version']}`；门禁波动带：±{TOLERANCE * 100:.0f} 个百分点",
        "- 生成命令：`python -X utf8 scripts/eval_harness.py`",
        "",
        "## 指标（分母写死）",
        "",
        "| 指标 | 值 | 95% Wilson 区间 | 分母 |",
        "| --- | --- | --- | --- |",
    ]
    denominators = {
        "schema_pass_rate": "通过结构校验数 / 全部用例",
        "field_precision": "TP / (TP+FP)，逐字段 micro",
        "field_recall": "TP / (TP+FN)，逐字段 micro",
        "field_f1": "2PR/(P+R)",
    }
    for key in CORE_METRICS:
        interval = metrics["intervals"].get(key)
        span = (
            f"[{interval[0] * 100:.1f}%, {interval[1] * 100:.1f}%]"
            if interval
            else "—（由 P/R 派生）"
        )
        lines.append(
            f"| `{key}` | {_percent(metrics[key])} | {span} | {denominators[key]} |"
        )
    lines.extend(
        [
            (
                f"| `hallucination_rate`（负向） | {_percent(metrics['hallucination_rate'])} | — | "
                f"命中编造词的用例 / 标注了禁用词的用例（{metrics['hallucination_annotated']} 例） |"
            ),
            "",
            (
                f"混淆矩阵：TP={metrics['confusion']['tp']} / FP={metrics['confusion']['fp']} / "
                f"FN={metrics['confusion']['fn']}。"
            ),
            "",
            "## 本地处理耗时（**非模型延迟**）",
            "",
            f"- p50 = {metrics['p50_local_us']} 微秒，p95 = {metrics['p95_local_us']} 微秒",
            "- 口径：单例「读取快照 → pydantic 校验 → 集合比对」耗时，排序取分位。",
            "- 评分 MAE **未计入**：当前金标只标了得分区间（score_band），没有逐例人工打分，",
            "  缺少可复算的 `human` 标签；不编造该指标。",
            "",
            "## 逐例结果",
            "",
            "| id | schema | 命中 | 缺失 | 多余 | 命中编造词 |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    for row in metrics["per_case"]:
        lines.append(
            f"| {row['id']} | {'通过' if row['schema_valid'] else '失败'} | {row['hit']} | "
            f"{row['missing']} | {row['extra']} | {'是' if row['forbidden_hit'] else '否'} |"
        )
    lines.append("")
    return "\n".join(lines)


def compare_with_baseline(metrics: dict[str, Any], baseline_path: Path) -> int:
    if not baseline_path.exists():
        print(f"门禁失败：缺少基线文件 {baseline_path}，请先跑 --write-baseline 并提交")
        return 1
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    failures: list[str] = []
    for key in CORE_METRICS:
        if metrics[key] < baseline[key] - TOLERANCE:
            failures.append(
                f"{key} {_percent(metrics[key])} < 基线 {_percent(baseline[key])} - {TOLERANCE * 100:.0f}pp"
            )
    for key in NEGATIVE_METRICS:
        current = metrics[key]
        target = baseline.get(key)
        if current is None or target is None:
            continue
        if current > target + TOLERANCE:
            failures.append(
                f"{key} {_percent(current)} > 基线 {_percent(target)} + {TOLERANCE * 100:.0f}pp"
            )
    if failures:
        print("离线评测门禁未通过：")
        for line in failures:
            print(f"  - {line}")
        return 1
    print(
        f"离线评测门禁通过：{metrics['case_count']} 例，"
        f"schema {_percent(metrics['schema_pass_rate'])}，"
        f"micro-F1 {_percent(metrics['field_f1'])}（波动带 ±{TOLERANCE * 100:.0f}pp）"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="r51 离线评测 Harness（零网络）")
    parser.add_argument("--golden", default=str(GOLDEN), help="金标集 JSON 路径")
    parser.add_argument("--report", default=str(REPORT), help="Markdown 报告输出路径")
    parser.add_argument("--baseline", default=str(BASELINE), help="基线 JSON 路径")
    parser.add_argument("--write-baseline", action="store_true", help="把当前指标固化为基线")
    parser.add_argument("--check", action="store_true", help="CI 门禁：跌破基线即非零退出")
    args = parser.parse_args(argv)

    golden_path = Path(args.golden).resolve()
    metrics = evaluate(golden_path)
    report_path = Path(args.report).resolve()
    if args.check:
        # `--check` 是只读门禁：写报告会把「本地处理耗时」的抖动带进 git diff，
        # CI 上更不该产生工作区改动（与 eval_question_retrieval.py 同一口径）。
        print(" --check 只读模式：未写入任何文件")
    else:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(render(metrics, golden_path), encoding="utf-8")
        print(
            f"报告已生成：{report_path}（{metrics['case_count']} 例，"
            f"schema {_percent(metrics['schema_pass_rate'])}，micro-F1 {_percent(metrics['field_f1'])}）"
        )

    if args.write_baseline:
        baseline_path = Path(args.baseline).resolve()
        slim = {key: metrics[key] for key in (*CORE_METRICS, *NEGATIVE_METRICS)}
        slim["golden_sha256"] = metrics["golden_sha256"]
        baseline_path.write_text(
            json.dumps(slim, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"基线已写入：{baseline_path}")
    return compare_with_baseline(metrics, Path(args.baseline).resolve()) if args.check else 0


if __name__ == "__main__":
    raise SystemExit(main())
