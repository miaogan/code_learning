"""r54 在线质量评测 CLI：与离线回归门禁严格分轨，版本锁定 + 脱敏轨迹。

**默认 dry-run**：零网络、零配额，用金标里的响应快照跑通同一条评分管线与轨迹格式。
**真跑必须双开关**：显式 `--live` + 环境变量 `AI_LIVE=1`，且 AI 运行时就绪；
任何一条不满足都不出网。真跑会消耗第三方 API 配额，因此**不进 CI**。

被测系统复用产品真实链路：`PROFILE_SYSTEM` + `ProfileDraft` + `AIClient.complete_model(...,
retry_unavailable=True)`，不另写客户端 —— 否则评的就不是产品。

用法：
    python -X utf8 scripts/eval_live.py                 # dry-run，生成报告与轨迹
    python -X utf8 scripts/eval_live.py --check         # 只读门禁（可进 CI，零网络）
    AI_LIVE=1 python -X utf8 scripts/eval_live.py --live --limit 30
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.services.eval import live as live_core

GOLDEN = ROOT / "docs" / "eval" / "golden-v1.json"
BASELINE = ROOT / "docs" / "eval" / "baseline-v1.json"
REPORT = ROOT / "docs" / "eval" / "LIVE-REPORT.md"
TRACE_DIR = ROOT / "docs" / "eval" / "traces"

CHECK_MIN_SCHEMA = 0.90
CHECK_EXPECTED_CASES = 30


@contextlib.contextmanager
def _temp_database():
    """真跑用的独立库：跑完即删，绝不写开发库。

    r98 前这里用临时 SQLite 文件（`DB_PATH`）；SQLite 下线后改成「同一实例上的
    独立库」。**只改 `DATABASE_URL` 而不隔离库**会让评测数据混进真实账号的数据里，
    所以这里建库 / 建表 / 删除一条龙。
    """
    from urllib.parse import urlparse

    import psycopg
    from app.core.config import get_settings
    from app.core.db import close_pool, init_db

    base = os.environ.get("EVAL_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not base:
        raise RuntimeError(
            "真跑需要 PostgreSQL：请设置 EVAL_DATABASE_URL 或 DATABASE_URL"
        )
    parsed = urlparse(base)
    name = "sc_eval_live_" + str(os.getpid())
    admin = parsed._replace(path="/postgres").geturl()
    dsn = parsed._replace(path="/" + name).geturl()
    with psycopg.connect(admin, autocommit=True, connect_timeout=5) as conn:
        conn.execute('DROP DATABASE IF EXISTS "' + name + '" WITH (FORCE)')
        conn.execute('CREATE DATABASE "' + name + '"')

    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = dsn
    get_settings.cache_clear()
    close_pool()
    try:
        init_db()
        yield dsn
    finally:
        close_pool()
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        get_settings.cache_clear()
        with psycopg.connect(admin, autocommit=True, connect_timeout=5) as conn:
            conn.execute('DROP DATABASE IF EXISTS "' + name + '" WITH (FORCE)')


def _load_golden() -> tuple[dict[str, Any], str]:
    raw = GOLDEN.read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    return payload, hashlib.sha256(raw).hexdigest()


def _load_offline() -> dict[str, Any]:
    base = json.loads(BASELINE.read_text(encoding="utf-8"))
    return {
        "case_count": CHECK_EXPECTED_CASES,
        "schema_pass_rate": float(base.get("schema_pass_rate", 0.0)),
        "micro_f1": float(base.get("field_f1", 0.0)),
    }


def _dry_run_lines(golden: dict[str, Any], config: live_core.RunConfig, limit: int) -> list[dict[str, Any]]:
    """dry-run：用金标响应快照代替模型输出，走同一套评分与轨迹构造。"""
    lines: list[dict[str, Any]] = []
    for case in golden["cases"][:limit]:
        snap = case.get("response_snapshot") or {}
        fields = [str(item) for item in (snap.get("skills") or [])]
        fields += [str(item) for item in (snap.get("projects") or [])]
        years = snap.get("years_experience")
        schema_ok = isinstance(years, (int, float)) and not isinstance(years, bool)
        score = live_core.score_case(
            expected_fields=case["expected"].get("profile_fields") or [],
            predicted_fields=fields,
            must_not_contain=case["expected"].get("must_not_contain") or [],
            schema_ok=schema_ok,
        )
        lines.append(
            live_core.trace_line(
                config=config,
                case_id=case["id"],
                input_sha256=live_core.input_fingerprint(case["input"]["resume_excerpt"]),
                score=score,
                predicted_fields=fields,
                prompt_chars=len(case["input"]["resume_excerpt"]),
                response_chars=len(json.dumps(snap, ensure_ascii=False)),
                latency_ms=0.0,
                failure_kind="dry_run",
            )
        )
    return lines


async def _run_live_cases(
    golden: dict[str, Any], config: live_core.RunConfig, limit: int, system: str
) -> list[dict[str, Any]]:
    """真跑：逐例打真实模型，只把元数据交给纯函数层。"""
    from app.core.errors import AppError
    from app.schemas import ProfileDraft
    from app.services.ai.ai import AIClient, close_ai_pool

    ai = AIClient()
    lines: list[dict[str, Any]] = []
    try:
        for case in golden["cases"][:limit]:
            excerpt = case["input"]["resume_excerpt"]
            started = time.perf_counter()
            fields: list[str] = []
            schema_ok = True
            failure_kind = ""
            try:
                draft = await ai.complete_model(
                    system, excerpt, ProfileDraft, retry_unavailable=True
                )
                fields = [str(skill.name) for skill in draft.skills]
                fields += [str(item) for item in draft.tech_stack]
                fields += [str(project.name) for project in draft.projects]
            except AppError as exc:
                schema_ok = False
                failure_kind = str(exc.code)
            except Exception as exc:  # noqa: BLE001 - 失败分类要落轨迹，不能中断整轮
                schema_ok = False
                failure_kind = type(exc).__name__
            elapsed_ms = (time.perf_counter() - started) * 1000
            score = live_core.score_case(
                expected_fields=case["expected"].get("profile_fields") or [],
                predicted_fields=fields,
                must_not_contain=case["expected"].get("must_not_contain") or [],
                schema_ok=schema_ok,
            )
            lines.append(
                live_core.trace_line(
                    config=config,
                    case_id=case["id"],
                    input_sha256=live_core.input_fingerprint(excerpt),
                    score=score,
                    predicted_fields=fields,
                    prompt_chars=len(system) + len(excerpt),
                    response_chars=len(json.dumps(fields, ensure_ascii=False)),
                    latency_ms=elapsed_ms,
                    failure_kind=failure_kind,
                )
            )
    finally:
        await close_ai_pool()
    return lines


def _resolve_runtime() -> tuple[bool, str, str, str]:
    """只读探测运行时；绝不返回或打印 Key。"""
    try:
        from app.core.config import get_settings

        runtime = get_settings().resolve_ai()
        return runtime.ready, str(runtime.provider), str(runtime.model), ""
    except Exception as exc:  # noqa: BLE001 - 配置异常要转成中文原因，不外抛堆栈
        return False, "", "", type(exc).__name__


def _system_prompt() -> str:
    from app.services.profile.profile import PROFILE_SYSTEM

    return PROFILE_SYSTEM


def render(
    metrics: dict[str, Any],
    config: live_core.RunConfig,
    comparison: dict[str, Any],
    trace_path: str,
) -> str:
    is_live = config.mode == "live"
    badge = "**LIVE · 真实模型调用**" if is_live else "**DRY-RUN · 零网络，非真实模型**"
    lines = [
        "# LIVE-REPORT · 在线质量评测轨道",
        "",
        f"> 由 `scripts/eval_live.py` 生成。当前模式：{badge}。",
        "> **离线回归 ≠ 在线质量**：本报告评的是「模型 + 提示词版本」，离线门禁评的是「解析/校验管线」。",
        "",
        "## 1. 版本锁定",
        "",
        "| 项 | 值 |",
        "|---|---|",
        f"| run_id | `{config.run_id}` |",
        f"| 模式 | `{config.mode}` |",
        f"| 被测提示词版本 | `{config.prompt_version}` |",
        f"| 提示词 sha256 | `{config.system_sha256}` |",
        f"| provider / model | `{config.provider}` / `{config.model}` |",
        f"| rubric 版本 | `{config.rubric_version}` |",
        f"| 金标 sha256 | `{config.golden_sha256}` |",
        f"| 生成时间 | `{config.created_at}` |",
        "",
        "> 被测系统复用产品真实链路 `PROFILE_SYSTEM` + `ProfileDraft` + `AIClient.complete_model`；",
        "> 改提示词必须 bump `LIVE_PROMPT_VERSION`，否则跨版本对比无意义。",
        "",
        "## 2. 指标（分母写死 = case 数）",
        "",
        "| 指标 | 值 | 分母 |",
        "|---|---|---|",
        f"| 样本数 | {metrics['case_count']} | 金标 case 数 |",
        f"| schema 通过率 | {metrics['schema_pass_rate'] * 100:.1f}% | 全部 case |",
        f"| schema Wilson 95% | [{metrics['schema_wilson95'][0] * 100:.1f}%, {metrics['schema_wilson95'][1] * 100:.1f}%] | 同上 |",
        f"| 字段级 micro-P | {metrics['micro_precision'] * 100:.1f}% | TP + FP = {metrics['confusion']['tp'] + metrics['confusion']['fp']} |",
        f"| 字段级 micro-R | {metrics['micro_recall'] * 100:.1f}% | TP + FN = {metrics['confusion']['tp'] + metrics['confusion']['fn']} |",
        f"| 字段级 micro-F1 | {metrics['micro_f1'] * 100:.1f}% | P 与 R 的调和平均 |",
        f"| 负向 hallucination_rate | {metrics['hallucination_rate'] * 100:.1f}% | 标注了禁用词的 {metrics['hallucination_annotated']} 例 |",
        f"| p50 / p95 延迟 | {metrics['p50_ms']:.1f} / {metrics['p95_ms']:.1f} ms | 全部调用 |",
        f"| 请求 / 响应字符数 | {metrics['prompt_chars']} / {metrics['response_chars']} | 全部调用 |",
        "",
        "混淆矩阵：" + f"TP={metrics['confusion']['tp']} / FP={metrics['confusion']['fp']} / FN={metrics['confusion']['fn']}。",
        "失败分类：" + (", ".join(f"{k}={v}" for k, v in sorted(metrics["failure_kinds"].items())) or "无"),
        "",
        "> **token 成本未采集**：`AIClient` 不暴露上游 usage，改主链路才能拿到真实计费 token；",
        "> 这里只记请求 / 响应字符数，不编造 token 数字。",
        "",
        "## 3. 与离线基线并列（**不可比较**）",
        "",
        "| 轨道 | 样本数 | schema 通过率 | micro-F1 | 评测对象 |",
        "|---|---|---|---|---|",
        f"| 离线回归 | {comparison['offline']['case_count']} | {comparison['offline']['schema_pass_rate'] * 100:.1f}% | {comparison['offline']['micro_f1'] * 100:.1f}% | 固定响应快照 → 解析 / 校验 / 评分管线 |",
        f"| 在线质量 | {comparison['live']['case_count']} | {comparison['live']['schema_pass_rate'] * 100:.1f}% | {comparison['live']['micro_f1'] * 100:.1f}% | 真实模型 → 模型 + 提示词版本 |",
        "",
        f"> {comparison['notice']}",
        ">",
        "> **两列 schema 通过率口径也不同**：离线用 `Snapshot.model_validate()` 做 pydantic 结构校验；",
        "> dry-run 用轻量类型校验、真跑用产品 `ProfileDraft` 校验。三者的分母相同但判定不同，差值不可相减。",
        "",
        "## 4. 轨迹与解读限制",
        "",
        f"- 轨迹：`{trace_path}`（jsonl，每行一个 case）。只记元数据、输入 sha256 与合成字段词；",
        "  **不含简历正文 / Key / 提示词全文 / 模型原始响应**，可复算指标但不可还原原文。",
        "- 金标 30 例为**合成文本**、响应快照与标注同源；只证明管线可用与回归可检测，不是能力宣传。",
        "- 在线轨道**不含**产品的 `verify_quotes()` 溯源校验（那是确定性规则，属于离线管线范畴）；",
        "  因此这里评的是「AI 出网层的结构化输出」，不是「产品最终落库的画像」。",
        "- dry-run 的 schema 判定为轻量类型校验（只看 `years_experience` 是否为数值），",
        "  与离线 harness 的完整 pydantic 校验不同；dry-run 只用于验证脚手架与轨迹格式。",
        "- 真跑的延迟受上游抖动影响，跨次波动正常；**不进 CI**，只在本地留存版本化报告。",
    ]
    if not is_live:
        lines += [
            "- **DRY-RUN 的延迟恒为 0**，p50/p95 列无意义；失败分类为 `dry_run` 占位。",
            "- 本报告只能证明脚本与轨迹格式可复跑，**不能写进简历当成模型质量指标**。",
        ]
    lines += [
        "",
        "## 5. 复跑命令",
        "",
        "```bash",
        "python -X utf8 scripts/eval_live.py            # dry-run（零网络）",
        "python -X utf8 scripts/eval_live.py --check    # 只读门禁（可进 CI）",
        "AI_LIVE=1 python -X utf8 scripts/eval_live.py --live --limit 30   # 真跑，消耗配额",
        "```",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="r54 在线质量评测（默认 dry-run）")
    parser.add_argument("--live", action="store_true", help="真跑真实模型（需 AI_LIVE=1）")
    parser.add_argument("--check", action="store_true", help="只读门禁，不写任何文件")
    parser.add_argument("--limit", type=int, default=CHECK_EXPECTED_CASES)
    parser.add_argument("--golden", default=str(GOLDEN))
    args = parser.parse_args(argv)

    golden, golden_sha = _load_golden()
    limit = max(1, min(args.limit, len(golden["cases"])))
    try:
        system = _system_prompt()
    except Exception as exc:  # noqa: BLE001 - 环境缺依赖时给中文提示
        print(f"无法加载被测提示词：{type(exc).__name__}")
        return 1

    # dry-run 刻意不探测运行时，避免为了「不联网」反而去加载完整应用配置。
    probe_error = ""
    ready = False
    provider = ""
    model = ""
    if args.live:
        ready, provider, model, probe_error = _resolve_runtime()
    run_live, reason = live_core.should_run_live(args.live, os.environ.get("AI_LIVE"), ready)
    if args.live and not run_live:
        print(f"在线评测未启动：{reason}")
        return 2
    mode = "live" if run_live else "dry-run"
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_id = f"{stamp}-{mode}"
    config = live_core.build_run_config(
        run_id=run_id,
        mode=mode,
        provider=provider if run_live else "dry-run",
        model=model if run_live else "snapshot",
        rubric_version=str(golden.get("rubric_version", "r1")),
        golden_sha256=golden_sha,
        system=system,
    )

    if run_live:
        # 真跑把日志写进独立库，跑完即删，绝不污染开发库。
        with _temp_database():
            lines = asyncio.run(_run_live_cases(golden, config, limit, system))
    else:
        lines = _dry_run_lines(golden, config, limit)

    metrics = live_core.aggregate(lines, mode=mode)
    comparison = live_core.compare_with_offline(metrics, _load_offline())
    trace_name = "dry-run.jsonl" if mode == "dry-run" else f"{run_id}.jsonl"
    trace_rel = f"docs/eval/traces/{trace_name}"

    if args.check:
        print(" --check 只读模式：未写入任何文件")
        if metrics["case_count"] != CHECK_EXPECTED_CASES:
            print(f"门禁失败：样本数应为 {CHECK_EXPECTED_CASES}，实际 {metrics['case_count']}")
            return 1
        if metrics["schema_pass_rate"] < CHECK_MIN_SCHEMA:
            print(f"门禁失败：dry-run schema 通过率低于 {CHECK_MIN_SCHEMA * 100:.0f}%")
            return 1
        if any(tuple(line) != live_core.TRACE_KEYS for line in lines):
            print("门禁失败：轨迹键超出白名单")
            return 1
        print(
            f"在线评测脚手架门禁通过（dry-run，零网络）：{metrics['case_count']} 例，"
            f"schema {metrics['schema_pass_rate'] * 100:.1f}%"
        )
        return 0

    TRACE_DIR.mkdir(parents=True, exist_ok=True)
    trace_path = TRACE_DIR / trace_name
    trace_path.write_text(
        "\n".join(json.dumps(line, ensure_ascii=False) for line in lines) + "\n",
        encoding="utf-8",
    )
    REPORT.write_text(render(metrics, config, comparison, trace_rel), encoding="utf-8")
    print(f"模式：{mode}；{reason}")
    print(
        f"样本：{metrics['case_count']} 例，"
        f"schema {metrics['schema_pass_rate'] * 100:.1f}%，"
        f"micro-F1 {metrics['micro_f1'] * 100:.1f}%"
    )
    if probe_error:
        print(f"运行时探测异常：{probe_error}")
    print(f"轨迹：{trace_rel}")
    print("报告：docs/eval/LIVE-REPORT.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
