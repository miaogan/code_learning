"""r53 LLM 可靠性治理：退避 / 熔断 / 结构化输出修复 / 幂等键 / 影子对比。

设计原则（与 README 设计取舍同源）：**可注入、默认不改变主链路语义**。

- `repair_json_object()` 作为 `_extract_json_object()` 的兜底默认启用：只有原本会解析失败
  的响应才可能被救回，成功路径逐字节不变。
- `backoff_delay()` 只在 `retry_unavailable=True` 的重试分支生效，前台交互调用不翻倍等待。
- `CircuitBreaker` 是可注入状态机，**默认只观测不短路**（`AIClient` 显式注入后才 `allow()`），
  避免把全局状态偷偷塞进 646 条既有测试的调用链。故障注入验证见
  `scripts/eval_reliability.py` / `docs/eval/RELIABILITY-REPORT.md`。
- `idempotency_key()` / `compare_shadow()` 是纯函数：前者给后台任务去重，后者只输出差异
  **键名**与一致率，绝不回传模型正文（简历片段属于敏感数据）。

本模块不含任何数据库访问与网络调用，SQL 唯一出口门禁对它是中性文件。
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import time
from collections.abc import Callable
from typing import Any

#: 退避默认参数：base 刻意取小值，避免后台任务重试把用户等待拉长。
BACKOFF_BASE_S = 0.25
BACKOFF_CAP_S = 4.0
BACKOFF_JITTER = 0.2

#: 熔断默认参数：阈值偏保守，宁可多试一次也不误熔断。
BREAKER_FAILURE_THRESHOLD = 5
BREAKER_RECOVERY_S = 30.0
BREAKER_HALF_OPEN_CALLS = 2

_TRAILING_COMMA = re.compile(r",\s*([}\]])")
_FENCE = re.compile(r"^\s*```[a-zA-Z0-9_+-]*\s*|\s*```\s*$")
_LINE_COMMENT = re.compile(r"(?m)^\s*//[^\n]*$")
_SINGLE_QUOTED = re.compile(r"'([^'\\\n]*(?:\\.[^'\\\n]*)*)'")


def backoff_delay(
    attempt: int,
    *,
    base: float = BACKOFF_BASE_S,
    cap: float = BACKOFF_CAP_S,
    jitter: float = BACKOFF_JITTER,
    rng: random.Random | None = None,
) -> float:
    """指数退避 + 对称抖动。

    `attempt` 从 1 起；`delay = min(cap, base * 2^(attempt-1)) * (1 ± jitter)`。
    不传 `rng` 时用模块级随机源（生产抖动本就该随机）；测试注入 `random.Random(seed)`
    即可完全复算。返回值保留 6 位小数，便于断言。
    """
    index = max(1, int(attempt)) - 1
    raw = min(max(float(cap), 0.0), max(float(base), 0.0) * (2**index))
    source = rng if rng is not None else random
    spread = max(0.0, min(float(jitter), 1.0))
    factor = 1.0 + source.uniform(-spread, spread)
    return round(max(0.0, raw * factor), 6)


def idempotency_key(system: str, user: str, model: str, *, version: str = "v1") -> str:
    """同一 (版本, 模型, system, user) 稳定映射到同一键，供后台任务去重。

    只返回哈希，不缓存也不落盘正文；`version` 让提示词迭代后自然失效，避免旧结果复用。
    """
    payload = "\x00".join((version, model, system, user))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def repair_json_object(text: str) -> object | None:
    """把常见 LLM「差一点就合法」的 JSON 输出修成对象；救不回则返回 None。

    依次处理：代码围栏 → 行注释 → 首尾解释文字 → 尾随逗号 → 单引号键/值。
    每一步都先尝试解析，只有失败才继续下一步，避免对合法 JSON 做多余改写。
    """
    if not isinstance(text, str) or not text.strip():
        return None
    candidates: list[str] = []
    cleaned = _FENCE.sub("", text.strip()).strip()
    candidates.append(cleaned)
    no_comments = _LINE_COMMENT.sub("", cleaned).strip()
    if no_comments != cleaned:
        candidates.append(no_comments)
    for candidate in list(candidates):
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start != -1 and end > start:
            sliced = candidate[start : end + 1]
            if sliced != candidate:
                candidates.append(sliced)
    expanded: list[str] = []
    for candidate in candidates:
        expanded.append(candidate)
        without_commas = _TRAILING_COMMA.sub(r"\1", candidate)
        if without_commas != candidate:
            expanded.append(without_commas)
        single = _SINGLE_QUOTED.sub(lambda m: json.dumps(m.group(1)), without_commas)
        if single != without_commas:
            expanded.append(single)
    for candidate in expanded:
        try:
            parsed = json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


class CircuitBreaker:
    """三态熔断器：closed → open → half_open → closed。

    `clock` 可注入（默认 `time.monotonic`），让恢复窗口在测试里不用真的 sleep。
    **本类只维护状态与统计，不做网络调用，也不自动短路任何主链路**；调用方显式
    调用 `allow()` 决定是否在 open 态快速失败。
    """

    def __init__(
        self,
        *,
        failure_threshold: int = BREAKER_FAILURE_THRESHOLD,
        recovery_timeout_s: float = BREAKER_RECOVERY_S,
        half_open_max_calls: int = BREAKER_HALF_OPEN_CALLS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.failure_threshold = max(1, int(failure_threshold))
        self.recovery_timeout_s = max(0.0, float(recovery_timeout_s))
        self.half_open_max_calls = max(1, int(half_open_max_calls))
        self._clock = clock
        self._state = "closed"
        self._failures = 0
        self._successes = 0
        self._opened_at: float | None = None
        self._half_open_inflight = 0

    @property
    def state(self) -> str:
        return self._state

    def allow(self) -> bool:
        if self._state == "closed":
            return True
        if self._state == "half_open":
            if self._half_open_inflight >= self.half_open_max_calls:
                return False
            self._half_open_inflight += 1
            return True
        assert self._opened_at is not None
        if self._clock() - self._opened_at < self.recovery_timeout_s:
            return False
        self._state = "half_open"
        self._half_open_inflight = 1
        return True

    def record_success(self) -> None:
        self._successes += 1
        if self._state == "half_open":
            self._half_open_inflight = max(0, self._half_open_inflight - 1)
            self._state = "closed"
            self._failures = 0
            self._opened_at = None
        elif self._state == "closed":
            self._failures = 0

    def record_failure(self) -> None:
        self._failures += 1
        if self._state == "half_open":
            self._half_open_inflight = max(0, self._half_open_inflight - 1)
            self._state = "open"
            self._opened_at = self._clock()
        elif self._state == "closed" and self._failures >= self.failure_threshold:
            self._state = "open"
            self._opened_at = self._clock()

    def snapshot(self) -> dict[str, Any]:
        """只读快照，供日志 / 看板使用；不含任何请求内容。"""
        return {
            "state": self._state,
            "failures": self._failures,
            "successes": self._successes,
            "failure_threshold": self.failure_threshold,
            "recovery_timeout_s": self.recovery_timeout_s,
        }


def compare_shadow(primary: dict[str, Any], shadow: dict[str, Any]) -> dict[str, Any]:
    """双模型影子对比：只比较两边都有的键，输出一致率与差异**键名**，不输出值。

    用于评估换模型 / 换提示词的回归风险；差异列表按字典序，保证确定性。
    """
    keys = sorted(set(primary) & set(shadow))
    matched = [key for key in keys if primary[key] == shadow[key]]
    divergent = [key for key in keys if primary[key] != shadow[key]]
    total = len(keys)
    return {
        "compared_fields": total,
        "matched_fields": len(matched),
        "divergent_keys": divergent,
        "agreement_rate": round(len(matched) / total, 4) if total else 0.0,
        "primary_only_keys": sorted(set(primary) - set(shadow)),
        "shadow_only_keys": sorted(set(shadow) - set(primary)),
    }
