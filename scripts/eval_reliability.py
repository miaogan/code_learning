"""r53 可靠性治理的故障注入评估（零网络、纯标准库、确定性可复跑）。

对比同一串确定性故障下「无治理」与「退避重试 + 输出修复 + 熔断」的差异：

- 场景 A：200 次调用，第 60–110 次为上游突发抖动期；统计成功率、修复救回数、
  平均尝试次数与虚拟延迟分位。
- 场景 B：连续 30 次必失败上游；统计熔断器帮系统少打多少次上游。

**诚实边界**：这是纯模拟故障注入，虚拟时钟只用于比较重试策略，不代表真实网络延迟；
不连任何模型、不用任何 Key。结论只能用于回归检测与策略说明，不能写成生产 QPS。

用法：
    python -X utf8 scripts/eval_reliability.py            # 生成 docs/eval/RELIABILITY-REPORT.md
    python -X utf8 scripts/eval_reliability.py --check    # 只读门禁，不写文件
    python -X utf8 scripts/eval_reliability.py --json     # 机器可读输出
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import random
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "backend" / "app" / "services" / "ai" / "reliability.py"
REPORT = ROOT / "docs" / "eval" / "RELIABILITY-REPORT.md"

CALLS = 200
BURST_START = 60
BURST_END = 110
MAX_ATTEMPTS = 3
BASE_LATENCY_MS = 100.0
#: 门禁只防回归，不追求漂亮数字：固定 seed 下基线 55.5% / 治理 84.0%。
CHECK_SUCCESS_MIN = 0.80
CHECK_SUCCESS_GAIN_PP_MIN = 15.0
CHECK_UPSTREAM_SAVING_MIN = 0.50

_spec = importlib.util.spec_from_file_location("r53_reliability", MODULE_PATH)
if _spec is None or _spec.loader is None:  # pragma: no cover - 仓库结构固定
    raise RuntimeError("无法加载 reliability 模块")
reliability = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(reliability)


def _draw(seed: int, call_id: int, attempt: int, salt: str = "") -> float:
    """确定性伪随机：同一 (seed, call_id, attempt) 永远同一值，保证两组严格可比。"""
    raw = f"{seed}|{call_id}|{attempt}|{salt}".encode()
    return int(hashlib.sha256(raw).hexdigest()[:8], 16) / 0xFFFFFFFF


def _upstream(seed: int, call_id: int, attempt: int, burst: bool) -> tuple[str, str]:
    """返回 (kind, payload)。kind ∈ success|timeout|rate_limit|upstream_error。"""
    roll = _draw(seed, call_id, attempt)
    failure_rate = 0.90 if burst else 0.08
    if roll < failure_rate * 0.45:
        return "timeout", ""
    if roll < failure_rate * 0.75:
        return "rate_limit", ""
    if roll < failure_rate:
        return "upstream_error", ""
    payload = '{"skills": ["Python", "FastAPI"], "years": 3}'
    if _draw(seed, call_id, attempt, "malformed") < 0.20:
        # LLM 常见的尾随逗号：严格解析会失败，修复器可救回。
        payload = '{"skills": ["Python", "FastAPI",], "years": 3,}'
    return "success", payload


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[max(0, min(len(ordered) - 1, math.ceil(q * len(ordered)) - 1))]


def _run_baseline(seed: int) -> dict[str, Any]:
    """无治理：一次调用，严格 JSON 解析，失败即失败。"""
    success = 0
    latencies: list[float] = []
    for call_id in range(CALLS):
        burst = BURST_START <= call_id < BURST_END
        kind, payload = _upstream(seed, call_id, 1, burst)
        latencies.append(BASE_LATENCY_MS)
        if kind != "success":
            continue
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            success += 1
    return {
        "success_rate": round(success / CALLS, 4),
        "success": success,
        "total": CALLS,
        "upstream_calls": CALLS,
        "avg_attempts": 1.0,
        "repaired": 0,
        "exhausted": 0,
        "p50_ms": round(_percentile(latencies, 0.5), 1),
        "p95_ms": round(_percentile(latencies, 0.95), 1),
    }


def _run_governed(seed: int) -> dict[str, Any]:
    """有治理：退避重试 + 输出修复；熔断只在本场景统计快速失败次数。"""
    # 注入固定 seed 的随机源：生产抖动本就该随机，但评估报告必须逐次可复算。
    rng = random.Random(seed)
    success = 0
    repaired = 0
    upstream_calls = 0
    exhausted = 0
    total_attempts = 0
    latencies: list[float] = []
    for call_id in range(CALLS):
        burst = BURST_START <= call_id < BURST_END
        attempt_latency = 0.0
        done = False
        for attempt in range(1, MAX_ATTEMPTS + 1):
            total_attempts += 1
            upstream_calls += 1
            kind, payload = _upstream(seed, call_id, attempt, burst)
            attempt_latency += BASE_LATENCY_MS
            if kind == "success":
                try:
                    parsed = json.loads(payload)
                except json.JSONDecodeError:
                    parsed = reliability.repair_json_object(payload)
                    if parsed is not None:
                        repaired += 1
                if isinstance(parsed, dict):
                    success += 1
                    done = True
                    break
            if attempt < MAX_ATTEMPTS:
                # 虚拟时钟：累加退避而不真的 sleep，保证 CI 秒级完成。
                delay_ms = reliability.backoff_delay(attempt, rng=rng) * 1000
                attempt_latency += delay_ms
        if not done:
            # 三次都失败：记为「重试耗尽」。场景 A 不做熔断短路，熔断单独在场景 B 验证。
            exhausted += 1
        latencies.append(attempt_latency)
    return {
        "success_rate": round(success / CALLS, 4),
        "success": success,
        "total": CALLS,
        "upstream_calls": upstream_calls,
        "avg_attempts": round(total_attempts / CALLS, 3),
        "repaired": repaired,
        "exhausted": exhausted,
        "p50_ms": round(_percentile(latencies, 0.5), 1),
        "p95_ms": round(_percentile(latencies, 0.95), 1),
    }


def _run_circuit(seed: int, calls: int = 30) -> dict[str, Any]:
    """场景 B：上游持续失败，熔断后不再重复打上游。虚拟时钟驱动恢复窗口。"""
    clock = [0.0]
    breaker = reliability.CircuitBreaker(
        failure_threshold=5, recovery_timeout_s=2.0, half_open_max_calls=1,
        clock=lambda: clock[0],
    )
    baseline_calls = 0
    governed_calls = 0
    rejections = 0
    for call_id in range(calls):
        baseline_calls += 1
        clock[0] += 0.1
        if not breaker.allow():
            rejections += 1
            continue
        governed_calls += 1
        breaker.record_failure()  # 上游恒定失败
    saving = (baseline_calls - governed_calls) / baseline_calls if baseline_calls else 0.0
    return {
        "total": calls,
        "baseline_upstream_calls": baseline_calls,
        "governed_upstream_calls": governed_calls,
        "fast_rejections": rejections,
        "saving_rate": round(saving, 4),
        "final_state": breaker.state,
        "seed": seed,
    }


def evaluate(seed: int = 53) -> dict[str, Any]:
    baseline = _run_baseline(seed)
    governed = _run_governed(seed)
    circuit = _run_circuit(seed)
    return {
        "seed": seed,
        "calls": CALLS,
        "burst": [BURST_START, BURST_END],
        "max_attempts": MAX_ATTEMPTS,
        "baseline": baseline,
        "governed": governed,
        "circuit": circuit,
        "success_gain_pp": round(
            (governed["success_rate"] - baseline["success_rate"]) * 100, 2
        ),
    }


def render(m: dict[str, Any]) -> str:
    b, g, c = m["baseline"], m["governed"], m["circuit"]
    lines = [
        "# RELIABILITY-REPORT · 故障注入下的可靠性治理评估",
        "",
        "> 由 `python -X utf8 scripts/eval_reliability.py` 生成，数字来自实跑输出。",
        "> **纯模拟、零网络、零 Key**：不代表真实模型延迟或生产 QPS，用途是策略回归检测。",
        "",
        "## 1. 口径与边界",
        "",
        f"- 样本：{m['calls']} 次调用，固定 seed `{m['seed']}`；第 {m['burst'][0]}–{m['burst'][1]} 次为上游突发抖动期（失败率 90%），其余 8%。",
        "- 故障按 `(seed, 调用编号, 尝试次数)` 确定性哈希生成，两组面对**同一串故障**，严格可比。",
        f"- 基线：单次调用 + 严格 `json.loads`；治理组：最多 {m['max_attempts']} 次尝试 + 指数退避抖动 + `repair_json_object` 兜底。",
        "- 延迟是**虚拟时钟**（每次固定 100ms + 累计退避），不真实 sleep；只用于比较重试策略的相对代价。",
        "- 分位算法：排序后 `ceil(q*n)-1` 位置，与 `repository._percentile` 同口径。",
        "- 20% 的成功响应被注入尾随逗号，用于验证结构化输出修复是否真的救回。",
        "",
        "## 2. 场景 A：突发抖动下的成功率（%）",
        "",
        "| 组 | 成功率 | 成功数 / 总数 | 上游调用数 | 平均尝试次数 | 修复救回 | p50 (虚拟 ms) | p95 (虚拟 ms) |",
        "|---|---|---|---|---|---|---|---|",
        f"| 无治理基线 | {b['success_rate'] * 100:.1f}% | {b['success']}/{b['total']} | {b['upstream_calls']} | {b['avg_attempts']:.3f} | {b['repaired']} | {b['p50_ms']:.1f} | {b['p95_ms']:.1f} |",
        f"| 有治理 | {g['success_rate'] * 100:.1f}% | {g['success']}/{g['total']} | {g['upstream_calls']} | {g['avg_attempts']:.3f} | {g['repaired']} | {g['p50_ms']:.1f} | {g['p95_ms']:.1f} |",
        "",
        f"**成功率提升 {m['success_gain_pp']:+.2f} 个百分点**；代价是上游调用数从 {b['upstream_calls']} 增至 {g['upstream_calls']}、",
        f"虚拟 p95 从 {b['p95_ms']:.1f}ms 升至 {g['p95_ms']:.1f}ms。",
        f"治理组有 {g['exhausted']} 次「三次尝试仍失败」被记为重试耗尽。",
        "",
        "## 3. 场景 B：熔断避免雪崩",
        "",
        f"连续 {c['total']} 次上游必失败：无治理打满 {c['baseline_upstream_calls']} 次；治理组在连续 5 次失败后熔断，",
        f"实际只打 {c['governed_upstream_calls']} 次，快速失败 {c['fast_rejections']} 次，**上游调用减少 {c['saving_rate'] * 100:.1f}%**，",
        f"最终状态 `{c['final_state']}`。",
        "",
        "> 熔断的价值是「故障期不再无谓打上游」，**不是提高成功率**；两组在必失败场景下成功率都是 0%。",
        "> 因此 `CircuitBreaker` 在 `ai.py` 里默认只观测、不自动短路，需显式注入 `allow()` 才生效。",
        "",
        "## 4. 解读限制（写简历前必读）",
        "",
        "- 上游是**模拟函数**，不是真实模型；百分比不能写成「线上可用性从 X 提升到 Y」。",
        "- 虚拟延迟不是实测 p95，不能与 `docs/eval/PERF-REPORT.md` 的真实基准混用。",
        "- 故障率与突发窗口是人为设定，换一组参数结论会变；用途是**验证策略实现没回归**。",
        "- 真要写进简历的在线指标，需 `AI_LIVE=1` 打真实模型并留存 prompt/model 版本与轨迹。",
        "",
        "## 5. 复跑命令",
        "",
        "```bash",
        "python -X utf8 scripts/eval_reliability.py           # 生成本报告",
        "python -X utf8 scripts/eval_reliability.py --check   # 只读门禁（进 CI）",
        "python -X utf8 scripts/eval_reliability.py --json    # 机器可读指标",
        "```",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="r53 可靠性治理故障注入评估")
    parser.add_argument("--seed", type=int, default=53)
    parser.add_argument("--check", action="store_true", help="只读门禁，不写报告文件")
    parser.add_argument("--json", action="store_true", help="输出 JSON 指标")
    args = parser.parse_args(argv)
    metrics = evaluate(args.seed)
    g, b, c = metrics["governed"], metrics["baseline"], metrics["circuit"]
    if args.json:
        print(json.dumps(metrics, ensure_ascii=False, indent=2))
    else:
        print("r53 可靠性治理故障注入（模拟，零网络）")
        print(f"  基线成功率  : {b['success_rate'] * 100:.1f}%")
        print(
            f"  治理成功率  : {g['success_rate'] * 100:.1f}%"
            f"（{metrics['success_gain_pp']:+0.2f} pp）"
        )
        print(f"  修复救回    : {g['repaired']} 次")
        print(f"  熔断省下上游: {c['saving_rate'] * 100:.1f}%")
    if args.check:
        print(" --check 只读模式：未写入任何文件")
        if g["success_rate"] < CHECK_SUCCESS_MIN:
            print(f"门禁失败：治理组成功率低于 {CHECK_SUCCESS_MIN * 100:.0f}%")
            return 1
        if metrics["success_gain_pp"] < CHECK_SUCCESS_GAIN_PP_MIN:
            print(f"门禁失败：相对基线提升不足 {CHECK_SUCCESS_GAIN_PP_MIN:.0f} pp")
            return 1
        if g["success_rate"] <= b["success_rate"]:
            print("门禁失败：治理组未优于基线")
            return 1
        if c["saving_rate"] < CHECK_UPSTREAM_SAVING_MIN:
            print("门禁失败：熔断未有效减少上游调用")
            return 1
        print("可靠性门禁通过（--check 只读，未写入任何文件）")
        return 0
    if not args.json:
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(render(metrics), encoding="utf-8")
        print(f"报告已生成：{REPORT.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
