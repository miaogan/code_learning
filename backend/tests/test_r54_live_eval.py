"""r54 在线质量评测：版本锁定 / 脱敏轨迹 / 指标分母 / 双开关回归。"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from app.services.eval import live

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "eval_live.py"
REPORT = ROOT / "docs" / "eval" / "LIVE-REPORT.md"


def _config() -> live.RunConfig:
    return live.build_run_config(
        run_id="unit-run",
        mode="dry-run",
        provider="unit",
        model="snapshot",
        rubric_version="r1",
        golden_sha256="a" * 64,
        system="固定的提示词",
        created_at="2026-11-09T00:00:00+00:00",
    )


def _score(**overrides):
    base = live.score_case(
        expected_fields=["Python", "FastAPI"],
        predicted_fields=["FastAPI", "Redis"],
        must_not_contain=["Kubernetes"],
        schema_ok=True,
    )
    base.update(overrides)
    return base


def test_prompt_fingerprint_is_stable_and_distinct() -> None:
    assert live.prompt_fingerprint("固定的提示词") == live.prompt_fingerprint("固定的提示词")
    assert live.prompt_fingerprint("固定的提示词") != live.prompt_fingerprint("改过的提示词")
    assert len(live.prompt_fingerprint("x")) == 64


def test_build_run_config_locks_versions() -> None:
    config = _config()
    assert config.prompt_version == live.LIVE_PROMPT_VERSION == "profile-r1"
    assert config.system_sha256 == live.prompt_fingerprint("固定的提示词")
    assert live.config_as_dict(config)["golden_sha256"] == "a" * 64


def test_trace_line_is_whitelisted_and_has_no_plaintext() -> None:
    line = live.trace_line(
        config=_config(),
        case_id="g-001",
        input_sha256="b" * 64,
        score=_score(),
        predicted_fields=["FastAPI", "Redis"],
        prompt_chars=120,
        response_chars=80,
        latency_ms=12.3456,
        failure_kind="dry_run",
    )
    assert tuple(line) == live.TRACE_KEYS
    assert line["latency_ms"] == 12.346
    serialized = json.dumps(line, ensure_ascii=False)
    for forbidden in ("resume_excerpt", "api_key", "source_quote", "某电商公司", "固定的提示词"):
        assert forbidden not in serialized


def test_score_case_confusion_matrix_and_hallucination() -> None:
    result = _score()
    assert (result["tp"], result["fp"], result["fn"]) == (1, 1, 1)
    assert result["hallucination"] is False
    assert result["schema_ok"] is True
    hit = live.score_case(
        expected_fields=["Python"],
        predicted_fields=["Python", "Kubernetes"],
        must_not_contain=["Kubernetes"],
        schema_ok=False,
    )
    assert hit["hallucination"] is True
    assert hit["schema_ok"] is False


def test_aggregate_denominators_and_percentiles() -> None:
    lines = []
    for index, (schema_ok, latency) in enumerate(((True, 10.0), (False, 30.0))):
        score = _score(schema_ok=schema_ok, tp=2, fp=0, fn=0, hallucination=index == 1)
        lines.append(
            live.trace_line(
                config=_config(),
                case_id=f"g-{index}",
                input_sha256="c" * 64,
                score=score,
                predicted_fields=[],
                prompt_chars=10,
                response_chars=5,
                latency_ms=latency,
                failure_kind="dry_run" if schema_ok else "schema_invalid",
            )
        )
    metrics = live.aggregate(lines, mode="dry-run")
    assert metrics["case_count"] == 2
    assert metrics["schema_pass_rate"] == 0.5
    assert metrics["micro_precision"] == 1.0
    assert metrics["micro_recall"] == 1.0
    assert metrics["micro_f1"] == 1.0
    assert metrics["hallucination_rate"] == 0.5
    assert metrics["p50_ms"] == 10.0
    assert metrics["p95_ms"] == 30.0
    assert metrics["failure_kinds"] == {"dry_run": 1, "schema_invalid": 1}
    assert metrics["token_usage"] is None  # 不编造 token 数字
    assert live.aggregate([], mode="dry-run")["case_count"] == 0


def test_wilson_bounds_are_ordered_and_clamped() -> None:
    lo, hi = live.wilson(28, 30)
    assert 0.0 <= lo <= 28 / 30 <= hi <= 1.0
    assert live.wilson(0, 0) == (0.0, 0.0)


def test_compare_with_offline_never_claims_improvement() -> None:
    result = live.compare_with_offline(
        {"case_count": 30, "schema_pass_rate": 0.967, "micro_f1": 0.985},
        {"case_count": 30, "schema_pass_rate": 0.933, "micro_f1": 0.985},
    )
    assert result["comparable"] is False
    assert "不能" in result["notice"]
    assert "提升" in result["notice"] or "不可归因" in result["notice"]


def test_should_run_live_requires_both_switches_and_ready_runtime() -> None:
    assert live.should_run_live(False, None, True)[0] is False
    assert live.should_run_live(True, None, True)[0] is False
    assert live.should_run_live(True, "1", False)[0] is False
    assert live.should_run_live(True, "0", True)[0] is False
    run, reason = live.should_run_live(True, "1", True)
    assert run is True
    assert "版本锁定" in reason


def test_cli_check_is_readonly_and_exits_zero() -> None:
    before = REPORT.read_bytes() if REPORT.exists() else b""
    proc = subprocess.run(
        [sys.executable, "-X", "utf8", str(SCRIPT), "--check"],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "只读模式" in proc.stdout
    assert "门禁通过" in proc.stdout
    assert (REPORT.read_bytes() if REPORT.exists() else b"") == before


def test_cli_live_without_env_switch_refuses_to_call_out() -> None:
    proc = subprocess.run(
        [sys.executable, "-X", "utf8", str(SCRIPT), "--live"],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    )
    assert proc.returncode == 2
    assert "AI_LIVE=1" in proc.stdout
    assert "未启动" in proc.stdout
