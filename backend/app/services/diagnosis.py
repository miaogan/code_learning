"""诊断报告（AC-5 / AC-6）：本地统计 → 3..5 条短板 → 课程映射 → AI 仅补文案。

职责边界（改之前先看）：
- 统计与排序必须可复算：`build_shortfalls` 只做聚类统计，`evidence` / `question_ref` 一律从
  run payload 里**真实存在**的题目推导；题目 id 缺失或对不上的候选整条丢弃，不许用「大概第几题」糊过去。
- 阈值与严重度分档唯一出处是 `rules.py`，本文件只 re-export `SEVERITY_ORDER`（下游 import 不会漂移）。
- 课程匹配唯一出口是 `courses.match_for_shortfall`（兜底入门课）；本文件不得自行筛课程清单，
  否则兜底课会被绕过（anti-goal 4）。
- AI 只补 `diagnosis` / `actions`：未配置、超时、结构不合一律降级为模板文案，报告照常成功 ——
  否则 AC-5 直接不可用。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from .. import repository
from ..errors import NOT_FOUND, VALIDATION_ERROR, AppError
from ..schemas import Report, Severity, Shortfall
from . import courses, rules
from .ai import AIClient
from .markdown import SEVERITY_LABEL, format_score

#: 严重度排序的单一出处（`rules.py`）；本文件只做转出，方便下游 `from .diagnosis import SEVERITY_ORDER`。
SEVERITY_ORDER: dict[Severity, int] = rules.SEVERITY_ORDER

INTERVIEW_KIND_NAMES: dict[str, str] = {
    "technical": "技术基础",
    "project": "项目深挖",
    "challenge": "挑战题应对",
}
INTERVIEW_DEFAULT_NAME = "面试表达"
EXAM_DEFAULT_DIRECTION = "笔试综合"
QUESTION_CANDIDATE_SUFFIX = "（重点题）"

REPORT_SYSTEM = (
    "你是编程学习教练。用户会给你一份短板清单（每条含名称、严重度、证据分数）。"
    "请为每条短板写一段中文诊断（不超过 80 字，指出具体能力缺口，不要空话）与 3 条当天可执行的动作"
    "（每条不超过 40 字，动词开头）。name 必须原样返回，不得改写、不得增删条目。"
    '只输出 JSON：{"shortfalls":[{"name":"...","diagnosis":"...","actions":["...","...","..."]}]}'
)


class _ShortfallCopy(BaseModel):
    """AI 补文案的响应模型（内部模型，不进 HTTP 契约）。"""

    name: str = Field(min_length=1)
    diagnosis: str = Field(min_length=1)
    actions: list[str] = Field(default_factory=list)


class _ReportCopyDraft(BaseModel):
    shortfalls: list[_ShortfallCopy]


@dataclass(frozen=True)
class _Candidate:
    """一条短板候选：聚类得到的均分 + 最差那道真题作为证据。"""

    name: str
    severity: Severity
    avg: float
    evidence: str
    question_ref: str
    run_id: str
    count: int = 1


# --- 统计 ----------------------------------------------------------------


def _sort_key(candidate: _Candidate) -> tuple[int, float, str]:
    """排序口径：严重度升序（high 先），同档内均分低者先，末位用题目 id 稳定排序。"""
    return (SEVERITY_ORDER[candidate.severity], candidate.avg, candidate.question_ref)


def _bucket_name(kind: str, question: dict[str, Any]) -> str:
    """聚类维度：面试按题型（kind），笔试按方向（direction）。"""
    if kind == "interview":
        return INTERVIEW_KIND_NAMES.get(str(question.get("kind") or ""), INTERVIEW_DEFAULT_NAME)
    return str(question.get("direction") or EXAM_DEFAULT_DIRECTION)


def _numeric(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _interview_scores(run: dict[str, Any]) -> list[tuple[int, dict[str, Any], float]]:
    """面试：payload 里每题回写的 `score`（未作答的题为 null，不计分）。"""
    out: list[tuple[int, dict[str, Any], float]] = []
    for index, question in enumerate(_questions_of(run), start=1):
        score = _numeric(question.get("score"))
        if score is not None:
            out.append((index, question, score))
    return out


def _exam_scores(run: dict[str, Any]) -> list[tuple[int, dict[str, Any], float]]:
    """笔试：逐题对错。优先读 payload 回写的结果，退化为用服务端答案本地比对。"""
    questions = _questions_of(run)
    explicit = _explicit_results(run.get("payload") or {})
    answers = (run.get("payload") or {}).get("answers")
    out: list[tuple[int, dict[str, Any], float]] = []
    for index, question in enumerate(questions, start=1):
        question_id = str(question.get("id") or "")
        if not question_id:
            continue
        score: float | None = explicit.get(question_id)
        if score is None and isinstance(answers, dict) and question_id in answers:
            graded = _grade(question, answers[question_id])
            if graded is not None:
                score = 10.0 if graded else 0.0
        if score is None:
            continue
        out.append((index, question, score))
    return out


def _questions_of(run: dict[str, Any]) -> list[dict[str, Any]]:
    payload = run.get("payload") or {}
    questions = payload.get("questions")
    if not isinstance(questions, list):
        return []
    return [item for item in questions if isinstance(item, dict)]


def _explicit_results(payload: dict[str, Any]) -> dict[str, float]:
    """从 payload 里读逐题结果（`per_question` 或 `result.per_question`）。"""
    raw: list[Any] = []
    direct = payload.get("per_question")
    if isinstance(direct, list):
        raw = direct
    result = payload.get("result")
    if not raw and isinstance(result, dict) and isinstance(result.get("per_question"), list):
        raw = result["per_question"]
    out: dict[str, float] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        question_id = str(item.get("id") or item.get("question_id") or "")
        if not question_id:
            continue
        score = _numeric(item.get("score"))
        if score is not None:
            out[question_id] = score
            continue
        correct = item.get("correct")
        if isinstance(correct, bool):
            out[question_id] = 10.0 if correct else 0.0
    return out


def _grade(question: dict[str, Any], answer: Any) -> bool | None:
    """判分口径唯一出处是 `services/exam.py`：这里只借它的函数，不另写一份评分规则。"""
    from . import exam as exam_service  # 延迟导入：避免与本模块形成导入环

    grader = getattr(exam_service, "grade_objective", None)
    if not callable(grader):
        return None
    try:
        return bool(grader(question, answer))
    except (TypeError, ValueError, KeyError):
        return None


def _scored(run: dict[str, Any]) -> list[tuple[int, dict[str, Any], float]]:
    kind = str(run.get("kind") or "")
    return _exam_scores(run) if kind == "exam" else _interview_scores(run)


def _cluster(
    scored: list[tuple[int, dict[str, Any], float]], kind: str
) -> list[tuple[str, list[tuple[int, dict[str, Any], float]]]]:
    buckets: dict[str, list[tuple[int, dict[str, Any], float]]] = {}
    for entry in scored:
        buckets.setdefault(_bucket_name(kind, entry[1]), []).append(entry)
    return list(buckets.items())


def _candidate_of(
    run: dict[str, Any], name: str, entries: list[tuple[int, dict[str, Any], float]]
) -> _Candidate:
    avg = round(sum(score for _, _, score in entries) / len(entries), 1)
    index, question, score = min(entries, key=lambda entry: (entry[2], entry[0]))
    return _Candidate(
        name=name,
        severity=rules.severity_of(avg),
        avg=avg,
        evidence=f"Q{index} · {format_score(score)}/10",
        question_ref=str(question["id"]),
        run_id=str(run.get("id") or ""),
        count=len(entries),
    )


def _merge_named(candidates: list[_Candidate]) -> list[_Candidate]:
    """同一方向跨多次 run 合并成一条短板，避免报告里出现两行同名短板。"""
    buckets: dict[str, list[_Candidate]] = {}
    for candidate in candidates:
        buckets.setdefault(candidate.name, []).append(candidate)
    merged: list[_Candidate] = []
    for items in buckets.values():
        if len(items) == 1:
            merged.append(items[0])
            continue
        total = sum(item.count for item in items)
        avg = round(sum(item.avg * item.count for item in items) / total, 1)
        worst = min(items, key=lambda item: (item.avg, item.question_ref))
        merged.append(
            _Candidate(
                name=worst.name,
                severity=rules.severity_of(avg),
                avg=avg,
                evidence=worst.evidence,
                question_ref=worst.question_ref,
                run_id=worst.run_id,
                count=total,
            )
        )
    return merged


def _per_question_candidates(
    run: dict[str, Any], name: str, entries: list[tuple[int, dict[str, Any], float]]
) -> list[_Candidate]:
    """题量太少（不足 3 条短板）时补位：单题候选，名称带后缀以区分聚类候选。"""
    return [
        _candidate_of(run, f"{name}{QUESTION_CANDIDATE_SUFFIX}", [entry]) for entry in entries
    ]


def build_shortfalls(runs: list[dict[str, Any]]) -> list[Shortfall]:
    """把 run payload 汇聚成 3..5 条短板（未挂课程，由 `attach_courses` 补）。"""
    groups: list[_Candidate] = []
    singles: list[_Candidate] = []
    for run in runs:
        if not isinstance(run, dict):
            continue
        kind = str(run.get("kind") or "")
        for name, entries in _cluster(_scored(run), kind):
            groups.append(_candidate_of(run, name, entries))
            singles.extend(_per_question_candidates(run, name, entries))

    groups.sort(key=_sort_key)
    groups = _merge_named(groups)
    singles.sort(key=_sort_key)

    picked = groups[: rules.MAX_SHORTFALLS]
    if len(picked) < rules.MIN_SHORTFALLS:
        seen = {(item.name, item.question_ref) for item in picked}
        for candidate in singles:
            if len(picked) >= rules.MIN_SHORTFALLS:
                break
            if (candidate.name, candidate.question_ref) in seen:
                continue
            picked.append(candidate)
            seen.add((candidate.name, candidate.question_ref))

    picked = sorted(picked[: rules.MAX_SHORTFALLS], key=_sort_key)
    return [_to_shortfall(candidate) for candidate in picked]


def _to_shortfall(candidate: _Candidate) -> Shortfall:
    diagnosis, actions = _template_copy(candidate.name, candidate.avg, candidate.severity)
    return Shortfall(
        name=candidate.name,
        severity=candidate.severity,
        evidence=candidate.evidence,
        diagnosis=diagnosis,
        actions=actions,
        courses=[],
        question_ref=candidate.question_ref,
    )


def _template_copy(name: str, avg: float, severity: Severity) -> tuple[str, list[str]]:
    """AI 不可用时的兜底文案：必须本身就是可读、可执行的建议（不是占位符）。"""
    label = SEVERITY_LABEL.get(severity, severity)
    if severity == "low":
        diagnosis = (
            f"「{name}」平均得分 {format_score(avg)}/10（{label}）：整体可用，"
            "但边界情况与追问深度不够，连续追问时容易散。"
        )
    else:
        diagnosis = (
            f"「{name}」平均得分 {format_score(avg)}/10（{label}）：作答停在概念复述，"
            "缺少具体做法、取舍与结果，说明这条方向还没形成自己的解题路径。"
        )
    actions = [
        f"复述「{name}」的 3 个核心概念，每个配一个能跑通的最小例子",
        "把本次最低分那题重写一遍作答：先给结论，再给关键步骤与取舍",
        "限时 3 分钟口头讲一遍并录音回听，删掉含糊的表述",
    ]
    return diagnosis, actions


# --- 课程映射 -------------------------------------------------------------


def attach_courses(shortfalls: list[Shortfall]) -> list[Shortfall]:
    """给每条短板挂课程：唯一出口 `courses.match_for_shortfall`（自带入门课兜底）。"""
    filled: list[Shortfall] = []
    for item in shortfalls:
        matched = courses.match_for_shortfall(item.name, limit=3)
        filled.append(item.model_copy(update={"courses": matched}))
    return filled


# --- 报告 ----------------------------------------------------------------


async def build_report(
    run_ids: list[str] | None = None, *, client: AIClient | None = None
) -> Report:
    """合并指定（或最近一次）面试与笔试 → 诊断报告；AI 文案失败不影响成功。"""
    runs = _resolve_runs(run_ids)
    shortfalls = attach_courses(build_shortfalls(runs))
    if not shortfalls:
        raise AppError(
            NOT_FOUND,
            "所选测评里还没有可诊断的作答，请先完成一次模拟面试或笔试",
            status=404,
        )
    shortfalls = await _enrich_copy(shortfalls, client=client)
    report = Report(
        id=f"rep-{uuid4().hex[:10]}",
        run_ids=[str(run.get("id") or "") for run in runs],
        interview_avg=_interview_avg(runs),
        exam_total=_exam_total(runs),
        shortfalls=shortfalls,
        generated_at=datetime.now(UTC).isoformat(),
    )
    repository.insert_report(report)
    return report


def _resolve_runs(run_ids: list[str] | None) -> list[dict[str, Any]]:
    """选定被诊断的 run：显式 id 一律校验存在；缺省取最近一次已完成的面试 + 笔试。"""
    if run_ids:
        runs: list[dict[str, Any]] = []
        for run_id in run_ids:
            run = repository.get_run(run_id)
            if run is None:
                raise AppError(
                    NOT_FOUND, "指定的测评记录不存在，请重新选择后再生成报告", status=404
                )
            runs.append(run)
        return runs

    auto: list[dict[str, Any]] = []
    for kind in ("interview", "exam"):
        for run in repository.list_runs(kind, limit=5):
            if str(run.get("status") or "") == repository.RUN_COMPLETED:
                auto.append(run)
                break
    if not auto:
        raise AppError(
            VALIDATION_ERROR,
            "还没有已完成的测评，请先完成一次模拟面试或笔试再生成报告",
            status=400,
        )
    return auto


def _interview_avg(runs: list[dict[str, Any]]) -> float | None:
    scores = [
        score
        for run in runs
        if str(run.get("kind") or "") == "interview"
        for _, _, score in _interview_scores(run)
    ]
    return round(sum(scores) / len(scores), 1) if scores else None


def _exam_total(runs: list[dict[str, Any]]) -> float | None:
    totals = [
        total
        for run in runs
        if str(run.get("kind") or "") == "exam"
        for total in [_exam_total_of(run)]
        if total is not None
    ]
    return round(sum(totals) / len(totals), 1) if totals else None


def _exam_total_of(run: dict[str, Any]) -> float | None:
    """笔试总分：优先 payload 里已回写的结果，退化为用逐题结果复算。"""
    payload = run.get("payload") or {}
    for candidate in _stated_totals(payload):
        if candidate is not None:
            return candidate
    scored = _exam_scores(run)
    if scored:
        correct = sum(1 for _, _, score in scored if score >= 10.0)
        return round(correct / len(scored) * 100, 1)
    return _numeric(payload.get("total"))


def _stated_totals(payload: dict[str, Any]) -> list[float | None]:
    result = payload.get("result")
    nested = _numeric(result.get("total")) if isinstance(result, dict) else None
    correct_count = _numeric(payload.get("correct_count"))
    objective_total = _numeric(payload.get("objective_total"))
    ratio = (
        round(correct_count / objective_total * 100, 1)
        if correct_count is not None and objective_total
        else None
    )
    return [
        nested,
        _numeric(payload.get("exam_total")),
        _numeric(payload.get("score")),
        ratio,
    ]


async def _enrich_copy(
    shortfalls: list[Shortfall], *, client: AIClient | None = None
) -> list[Shortfall]:
    """AI 只补诊断/动作文案；任何失败都退回模板文案（报告不许因此失败）。"""
    ai = client or AIClient()
    request = {
        "shortfalls": [
            {"name": item.name, "severity": item.severity, "evidence": item.evidence}
            for item in shortfalls
        ]
    }
    try:
        draft = await ai.complete_model(
            REPORT_SYSTEM,
            "短板清单：" + json.dumps(request, ensure_ascii=False),
            _ReportCopyDraft,
        )
    except Exception:  # AI 降级是设计行为（AC-5 可用性），不是异常路径
        return shortfalls

    copies = {copy.name.strip(): copy for copy in draft.shortfalls}
    enriched: list[Shortfall] = []
    for item in shortfalls:
        copy = copies.get(item.name.strip())
        if copy is None or not copy.actions:
            enriched.append(item)
            continue
        enriched.append(
            item.model_copy(update={"diagnosis": copy.diagnosis, "actions": list(copy.actions)})
        )
    return enriched
