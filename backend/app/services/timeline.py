"""成长时间线（r3 AC-1 / AC-2 / AC-3 / AC-5）：事件**写入与读取的唯一入口**。

口径纪律（下游不得二次实现，否则同一 run 会出现两套数值）：
- 分数只调 `history.score_of(kind, payload)` —— 历史页与时间线对同一 run 必须同源（差 ≤0.05）；
- 短板只调 `diagnosis.build_shortfalls([run])`，条数取其长度、名称取 `name`；
- 排序只由 `repository.list_timeline_events`（`occurred_at DESC, created_at DESC`）决定；
- 对比（`delta` / 短板复现 / 消失）由 `build_comparison` 在**服务端**算好，前端零减法。

异常策略（PRD §5.2 / AC-3）：两个 `record_*` 内部一律吞异常并返回 `None`。时间线是成长
记录的**旁路**，写入失败绝不能把「答完最后一题」「提交笔试」「画像合并成功」这类主流程
打断；页面用「事件数 < 趋势表行数」派生提示，不靠抛错表达。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from .. import repository
from ..schemas import TimelineComparison, TimelineEvent, TimelineMetrics
from . import diagnosis, history

#: `record_run_event` 只接测评类 run（简历事件走 `record_resume_event`）。
RUN_KINDS = frozenset({history.INTERVIEW_KIND, history.EXAM_KIND})

#: 与 `GET /api/history` 同一取值区间（路由 `Query(ge=1, le=50)`）；默认 20 = 页面滚动区 4 屏。
MIN_LIMIT = history.MIN_LIMIT
MAX_LIMIT = history.MAX_LIMIT
DEFAULT_LIMIT = 20

#: `type` → 参与对比的指标名。`TimelineComparison.metric` 只认这两种量纲（面试均分 / 笔试总分），
#: 简历事件没有同量纲数值，因此 `build_comparison` 对它恒返回 `None`。
_METRIC_OF_KIND: dict[str, str] = {
    history.INTERVIEW_KIND: "interview_avg",
    history.EXAM_KIND: "exam_total",
}

#: 摘要里类型的中文名（服务端组装 `summary`，前端只渲染不快拼）。摘要不带量纲后缀 ——
#: 卡片自己就渲染 `interview_avg /10`、`exam_total /100`，摘要里再写一次会重复。
_LABEL_OF_KIND: dict[str, str] = {
    history.INTERVIEW_KIND: "面试",
    history.EXAM_KIND: "笔试",
}


def _now_iso() -> str:
    """`occurred_at` 的默认值：事件发生的**完成时刻**（UTC ISO8601），不做本地时区换算。"""
    return datetime.now(UTC).isoformat()


def _names(names: list[str]) -> list[str]:
    """去重去空：短板名可能因 `question_ref` 不同而重名，集合差与展示都要唯一。"""
    seen: set[str] = set()
    unique: list[str] = []
    for name in names:
        key = str(name).strip()
        if key and key not in seen:
            seen.add(key)
            unique.append(key)
    return unique


def _num(value: float | None) -> str:
    """数值文案：整数不带 `.0`，否则保留 1 位（与前端 `num()` / `markdown.format_score` 同规）。"""
    if value is None:
        return "—"
    rounded = round(float(value), 1)
    return str(int(rounded)) if rounded.is_integer() else f"{rounded:.1f}"


def _delta_text(comparison: TimelineComparison | None) -> str:
    if comparison is None:
        return ""
    if comparison.delta == 0:
        return " · 较上次 ＝ 持平"
    arrow = "↑ +" if comparison.delta > 0 else "↓ −"
    return f" · 较上次 {arrow}{_num(abs(comparison.delta))}"


def _run_summary(
    kind: str,
    score: float | None,
    shortfall_count: int,
    comparison: TimelineComparison | None,
) -> str:
    """服务端组装的中文一句话（前端只渲染，不复算差值、不拼单位）。

    例：`面试均分 7.8 · 短板 3 条 · 较上次 ↑ +0.7`（DESIGN §2.1 的摘要口径，量纲见卡片本体）。
    """
    label = _LABEL_OF_KIND.get(kind, "测评")
    metric_word = "均分" if kind == history.INTERVIEW_KIND else "总分"
    head = f"{label}{metric_word} {_num(score)}" if score is not None else f"{label}已完成"
    return f"{head} · 短板 {shortfall_count} 条{_delta_text(comparison)}"


def build_comparison(
    current: TimelineEvent, previous: TimelineEvent | None
) -> TimelineComparison | None:
    """本次 vs 同类上一条：分数差 + 短板复现 / 消失，**全部服务端算好**（AC-5）。

    三种「不成立」都返回 `None`（前端渲染「首次…，暂无对比」，绝不外显 0.0 / NaN）：
    ① 没有上一条；② 上一条是另一类型；③ 任一侧该指标缺失（例如答到一半的卷子）。
    """
    if previous is None or str(previous.type) != str(current.type):
        return None
    metric = _METRIC_OF_KIND.get(str(current.type))
    if metric is None:
        return None
    prev_value = getattr(previous.key_metrics, metric, None)
    current_value = getattr(current.key_metrics, metric, None)
    if prev_value is None or current_value is None:
        return None

    prev_names = _names(previous.shortfall_names)
    current_names = _names(current.shortfall_names)
    prev_set = set(prev_names)
    current_set = set(current_names)
    prev_score = round(float(prev_value), 1)
    current_score = round(float(current_value), 1)
    return TimelineComparison(
        prev_event_id=previous.id,
        prev_occurred_at=previous.occurred_at,
        metric=metric,
        prev_value=prev_score,
        current_value=current_score,
        delta=round(current_score - prev_score, 1),
        repeated_shortfalls=[name for name in current_names if name in prev_set],
        disappeared_shortfalls=[name for name in prev_names if name not in current_set],
    )


def record_run_event(
    run: dict[str, Any], *, occurred_at: str | None = None
) -> TimelineEvent | None:
    """把一次**已完成**的测评写成 1 条成长事件；已写过返回 `None`（幂等，AC-3）。

    `run` 是 `repository.get_run` 形状的字典（`id` / `kind` / `payload`），由完成钩子传入；
    `occurred_at` 只在需要钉住时间顺序时显式给（测试与补录），默认取完成时刻。
    """
    try:
        kind = str(run.get("kind") or "")
        run_id = str(run.get("id") or "")
        if kind not in RUN_KINDS or not run_id:
            return None  # 非测评 run 不属于时间线；不抛错，钩子照常继续

        payload = dict(run.get("payload") or {})
        when = occurred_at or _now_iso()
        metric = _METRIC_OF_KIND[kind]
        score = history.score_of(kind, payload)
        shortfalls = diagnosis.build_shortfalls([{**run, "kind": kind, "payload": payload}])
        names = _names([str(item.name) for item in shortfalls])

        event_id = uuid4().hex
        previous = repository.previous_timeline_event(kind, when, exclude_id=event_id)
        # 集合差保留**上一次事件的展示顺序**，与 `build_comparison` 的 `disappeared_shortfalls` 一致。
        prev_names = _names(previous.shortfall_names) if previous is not None else []
        prev_set = set(prev_names)
        current_set = set(names)

        event = TimelineEvent(
            id=event_id,
            type=kind,
            ref_id=run_id,
            occurred_at=when,
            key_metrics=TimelineMetrics(**{metric: score, "shortfall_count": len(shortfalls)}),
            shortfall_names=names,
            added_shortfalls=[name for name in names if name not in prev_set],
            removed_shortfalls=(
                [name for name in prev_names if name not in current_set] if previous else []
            ),
            summary=_run_summary(kind, score, len(shortfalls), None),
            duplicate=False,
            comparison=None,
        )
        comparison = build_comparison(event, previous)
        if comparison is not None:
            event = event.model_copy(
                update={
                    "comparison": comparison,
                    "summary": _run_summary(kind, score, len(shortfalls), comparison),
                }
            )
        if not repository.insert_timeline_event(event):
            return None  # 同一 (type, ref_id) 已存在：重复完成 / 重放 / 重复提交
        return event
    except Exception:  # noqa: BLE001 - 旁路写入失败不得阻断主流程（AC-3）
        return None


def record_resume_event(
    *,
    resume_id: str,
    skill_added: list[str],
    skill_removed: list[str],
    duplicate: bool = False,
    occurred_at: str | None = None,
) -> TimelineEvent | None:
    """把一次简历上传（画像新建 / 合并成功）写成 1 条成长事件；已写过返回 `None`。

    `duplicate=True` 表示与当前画像来源是同一份简历（Q4：仍记事件，页面弱化显示「同一份简历」）。
    """
    try:
        resume_id = str(resume_id or "").strip()
        if not resume_id:
            return None
        added = _names(skill_added)
        removed = _names(skill_removed)
        when = occurred_at or _now_iso()

        parts: list[str] = ["同一份简历再次识别，画像已更新" if duplicate else "简历画像已更新"]
        if added:
            parts.append(f"新增 {len(added)} 项能力")
        if removed:
            parts.append(f"{len(removed)} 项转为历史")

        event = TimelineEvent(
            id=uuid4().hex,
            type="resume",
            ref_id=resume_id,
            occurred_at=when,
            key_metrics=TimelineMetrics(skill_added=len(added), skill_removed=len(removed)),
            shortfall_names=[],
            added_shortfalls=[],
            removed_shortfalls=[],
            summary=" · ".join(parts),
            duplicate=bool(duplicate),
            comparison=None,
        )
        if not repository.insert_timeline_event(event):
            return None
        return event
    except Exception:  # noqa: BLE001 - 旁路写入失败不得阻断画像主流程（AC-3）
        return None


def list_timeline(limit: int = DEFAULT_LIMIT) -> list[TimelineEvent]:
    """最近 `limit` 条事件，`occurred_at` 倒序；**不二次排序**（顺序唯一来源是 repository）。"""
    return repository.list_timeline_events(limit=min(max(int(limit), MIN_LIMIT), MAX_LIMIT))
