"""在线质量评测的纯函数层：版本锁定、脱敏轨迹、指标分母、双轨对比。

**与离线回归的分工**（TECHNICAL §3.3）：

| 轨道 | 输入 | 评测对象 | 是否进 CI |
|---|---|---|---|
| 离线 | 固定响应快照 | 解析 / 校验 / 评分**管线** | 是，零网络 |
| 在线 | 同一金标打真实模型 | 模型 + 提示词版本 | **否**，需 Key 且结果不确定 |

本模块不含网络调用、不含数据库访问、不含任何敏感原文；CLI 负责取响应后把结果交进来。
轨迹只记元数据与合成字段词，**绝不写简历正文 / Key / prompt 全文 / 模型原始响应** ——
这是「可回放」与「隐私边界」的交换：能复算指标，不能还原原文。
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

#: 与 `services/profile/profile.py::PROFILE_SYSTEM` 绑定；改提示词必须 bump 本版本，
#: 否则跨版本的指标对比会失去意义（这是在线轨道最容易翻车的地方）。
LIVE_PROMPT_VERSION = "profile-r1"

#: 轨迹允许出现的键白名单。测试用同一份常量断言「多一个键都不行」。
TRACE_KEYS: tuple[str, ...] = (
    "run_id",
    "created_at",
    "mode",
    "case_id",
    "provider",
    "model",
    "prompt_version",
    "rubric_version",
    "golden_sha256",
    "system_sha256",
    "input_sha256",
    "schema_ok",
    "predicted_fields",
    "prompt_chars",
    "response_chars",
    "latency_ms",
    "failure_kind",
    "tp",
    "fp",
    "fn",
    "hallucination",
)


def prompt_fingerprint(system: str) -> str:
    """提示词版本指纹：只存哈希，轨迹与报告里不出现提示词全文。"""
    return hashlib.sha256(system.encode("utf-8")).hexdigest()


def input_fingerprint(resume_excerpt: str) -> str:
    """输入指纹：轨迹只存哈希，绝不写简历正文（金标是合成文本，但口径不放松）。"""
    return hashlib.sha256(resume_excerpt.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RunConfig:
    """一次在线评测的版本锁定快照；同一 run 内所有 case 共用。"""

    run_id: str
    created_at: str
    mode: str
    provider: str
    model: str
    prompt_version: str
    rubric_version: str
    golden_sha256: str
    system_sha256: str


def build_run_config(
    *,
    run_id: str,
    mode: str,
    provider: str,
    model: str,
    rubric_version: str,
    golden_sha256: str,
    system: str,
    created_at: str | None = None,
) -> RunConfig:
    return RunConfig(
        run_id=run_id,
        created_at=created_at or datetime.now(UTC).isoformat(),
        mode=mode,
        provider=provider,
        model=model,
        prompt_version=LIVE_PROMPT_VERSION,
        rubric_version=rubric_version,
        golden_sha256=golden_sha256,
        system_sha256=prompt_fingerprint(system),
    )


def _normalize(fields: list[str]) -> set[str]:
    return {str(item).strip().lower() for item in fields if str(item).strip()}


def score_case(
    *,
    expected_fields: list[str],
    predicted_fields: list[str],
    must_not_contain: list[str],
    schema_ok: bool,
) -> dict[str, Any]:
    """字段级混淆矩阵 + 负向幻觉命中。分母口径与离线轨道一致（逐字段集合比对）。

    `schema_ok=False` 时仍保留预测字段参与统计 —— 结构不合规但内容抽对，属于
    「管线可修」而非「模型不会」，分开记才不会把两类问题混成一个数字。
    """
    expected = _normalize(expected_fields)
    predicted = _normalize(predicted_fields)
    banned = _normalize(must_not_contain)
    return {
        "tp": len(expected & predicted),
        "fp": len(predicted - expected),
        "fn": len(expected - predicted),
        "hallucination": bool(banned & predicted),
        "schema_ok": bool(schema_ok),
    }


def trace_line(
    *,
    config: RunConfig,
    case_id: str,
    input_sha256: str,
    score: dict[str, Any],
    predicted_fields: list[str],
    prompt_chars: int,
    response_chars: int,
    latency_ms: float,
    failure_kind: str = "",
) -> dict[str, Any]:
    """构造一行 jsonl 轨迹。**只允许 TRACE_KEYS 里的键**，杜绝顺手把原文塞进去。"""
    line = {
        "run_id": config.run_id,
        "created_at": config.created_at,
        "mode": config.mode,
        "case_id": case_id,
        "provider": config.provider,
        "model": config.model,
        "prompt_version": config.prompt_version,
        "rubric_version": config.rubric_version,
        "golden_sha256": config.golden_sha256,
        "system_sha256": config.system_sha256,
        "input_sha256": input_sha256,
        "schema_ok": score["schema_ok"],
        "predicted_fields": [str(item) for item in predicted_fields],
        "prompt_chars": max(int(prompt_chars), 0),
        "response_chars": max(int(response_chars), 0),
        "latency_ms": round(max(float(latency_ms), 0.0), 3),
        "failure_kind": failure_kind,
        "tp": score["tp"],
        "fp": score["fp"],
        "fn": score["fn"],
        "hallucination": score["hallucination"],
    }
    assert tuple(line) == TRACE_KEYS  # 白名单与实现单一真源，加字段必须同步改两处
    return line


def wilson(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """小样本比例给 Wilson 95% 区间，不写裸百分比。"""
    if total <= 0:
        return 0.0, 0.0
    p = successes / total
    denom = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denom
    margin = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denom
    return round(max(0.0, center - margin), 4), round(min(1.0, center + margin), 4)


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(q * len(ordered)) - 1))
    return round(ordered[index], 3)


def aggregate(lines: list[dict[str, Any]], *, mode: str) -> dict[str, Any]:
    """把轨迹行聚合成指标。**所有分母写死**：比例一律除以 case 总数，延迟除以调用总数。"""
    total = len(lines)
    if total == 0:
        return {"case_count": 0, "mode": mode, "notice": "无评测样本"}
    tp = sum(int(line["tp"]) for line in lines)
    fp = sum(int(line["fp"]) for line in lines)
    fn = sum(int(line["fn"]) for line in lines)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    schema_ok = sum(1 for line in lines if line["schema_ok"])
    hallucinated = sum(1 for line in lines if line["hallucination"])
    annotated = total  # 金标每例都带 must_not_contain，分母即样本数
    failures: dict[str, int] = {}
    for line in lines:
        kind = str(line["failure_kind"]) or "success"
        failures[kind] = failures.get(kind, 0) + 1
    latencies = [float(line["latency_ms"]) for line in lines]
    lo, hi = wilson(schema_ok, total)
    return {
        "mode": mode,
        "case_count": total,
        "schema_pass_rate": round(schema_ok / total, 4),
        "schema_wilson95": [lo, hi],
        "micro_precision": round(precision, 4),
        "micro_recall": round(recall, 4),
        "micro_f1": round(f1, 4),
        "confusion": {"tp": tp, "fp": fp, "fn": fn},
        "hallucination_rate": round(hallucinated / annotated, 4),
        "hallucination_annotated": annotated,
        "p50_ms": _percentile(latencies, 0.5),
        "p95_ms": _percentile(latencies, 0.95),
        "failure_kinds": failures,
        "prompt_chars": sum(int(line["prompt_chars"]) for line in lines),
        "response_chars": sum(int(line["response_chars"]) for line in lines),
        "token_usage": None,
        "notice": "",
    }


def compare_with_offline(live: dict[str, Any], offline: dict[str, Any]) -> dict[str, Any]:
    """并列展示两轨，**不给「提升」结论**：评测对象与输入都不同，差值不可归因。"""
    return {
        "comparable": False,
        "notice": "离线轨道用固定响应快照评管线，在线轨道打真实模型评模型+提示词；两者评测对象不同，差值不能写成「准确率提升」。",
        "live": {
            "case_count": live.get("case_count", 0),
            "schema_pass_rate": live.get("schema_pass_rate", 0.0),
            "micro_f1": live.get("micro_f1", 0.0),
        },
        "offline": {
            "case_count": offline.get("case_count", 0),
            "schema_pass_rate": offline.get("schema_pass_rate", 0.0),
            "micro_f1": offline.get("micro_f1", 0.0),
        },
    }


def should_run_live(requested: bool, env_value: str | None, ready: bool) -> tuple[bool, str]:
    """真跑的**双开关**：CLI 显式 `--live` + 环境变量 `AI_LIVE=1` + 运行时配置就绪。

    返回 `(是否真跑, 中文原因)`。任何一条不满足都退回 dry-run 或报错，绝不静默出网。
    """
    if not requested:
        return False, "CLI 未指定 --live，按 dry-run 执行（零网络）"
    if env_value != "1":
        return False, "真跑需同时设置环境变量 AI_LIVE=1（防止误触发消耗配额）"
    if not ready:
        return False, "AI 运行时未就绪：请检查 backend/.env 的 Key / base_url / model"
    return True, "版本锁定后打真实模型"


def config_as_dict(config: RunConfig) -> dict[str, Any]:
    return asdict(config)
