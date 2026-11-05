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

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from .. import repository
from ..errors import NOT_FOUND, VALIDATION_ERROR, AppError
from ..schemas import (
    InterviewSettings,
    Profile,
    Report,
    RoleFit,
    Severity,
    Shortfall,
    WeaknessItem,
)
from . import coach_copy, courses, resume_hints, role_fit, rules, weakness
from .ai import AIClient
from .history import _interviews_settings_of, score_of
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


#: r7 教练文案（AC-11）：只允许补「一句话薄弱描述」和「一句岗位结论」，键不可增删。
COACH_SYSTEM = (
    "你是编程学习教练。用户会给你「知识薄弱分组」清单（每组含名称、难度、必备级别、错题数/总题数、"
    "均分、已有模板描述）和目标岗位的差距摘要。请为每组改写一句中文薄弱描述（不超过 60 字，"
    "点出具体能力缺口，不要空话、不要改数值），并为岗位对标写一句中文结论（不超过 60 字，"
    "说明先补哪项）。key 必须原样返回，不得增删条目；没有岗位信息时 role_conclusion 返回 null。"
    '只输出 JSON：{"weaknesses":[{"key":"...","summary":"..."}],"role_conclusion":null}'
)


class _WeaknessCopy(BaseModel):
    """AI 补的一条薄弱描述（内部模型，不进 HTTP 契约）。"""

    key: str = Field(min_length=1)
    summary: str = Field(min_length=1)


class _CoachCopyDraft(BaseModel):
    """AI 补文案的响应模型：条目数、顺序、结论都可能缺失，调用方一律按 key 合并。"""

    weaknesses: list[_WeaknessCopy] = Field(default_factory=list)
    role_conclusion: str | None = None


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
    """合并指定（或最近一次）面试与笔试 → 诊断报告；AI 文案失败不影响成功。

    r7 结构（anti-goal 5）：先用纯函数把三块算完（零网络），再让**两路 AI 并发**——
    短板/教练文案串行两小步算一路，简历要点算另一路，用户可见延迟是两者的最大值而不是相加。
    任一路异常都退回纯函数结果（报告恒 200，只是文案变模板）。
    """
    runs = _resolve_runs(run_ids)
    shortfalls = attach_courses(build_shortfalls(runs))
    if not shortfalls:
        raise AppError(
            NOT_FOUND,
            "所选测评里还没有可诊断的作答，请先完成一次模拟面试或笔试",
            status=404,
        )
    weak_items = weakness.build_weakness_map(runs)
    profile = repository.latest_profile()
    settings = interview_settings_of(runs)
    resolved = role_fit.resolve_target_role(interview_settings=settings, profile=profile)
    # 传整个 `TargetRole`（而不是 `resolved.role`）：裸岗位名会让纯函数只能反向推断来源，
    # 「面试设定恰好与画像同值」这一情形会被误标成「简历画像」（AC-9 / D-1）。
    role = role_fit.build_role_fit(profile, resolved)
    ai = client or AIClient()

    async def _copies() -> tuple[list[Shortfall], list[WeaknessItem], RoleFit]:
        """同一 `AIClient` 上串行两次调用（共享连接更省），整体与简历要点并发。"""
        enriched = await _enrich_copy(shortfalls, client=ai)
        weak, role_out = await _enrich_coach(weak_items, role, client=ai)
        return enriched, weak, role_out

    copies, hints = await asyncio.gather(
        _copies(),
        resume_hints.build_resume_pointers(
            _resume_text_of(profile), profile, resolved.role, client=ai
        ),
        return_exceptions=True,
    )
    shortfalls, weak_items, role = _degrade_copies(copies, shortfalls, weak_items, role)
    if not isinstance(hints, resume_hints.ResumeHints):
        hints = resume_hints.ResumeHints([], coach_copy.RESUME_AI_FALLBACK)

    report = Report(
        id=f"rep-{uuid4().hex[:10]}",
        run_ids=[str(run.get("id") or "") for run in runs],
        interview_avg=_interview_avg(runs),
        exam_total=_exam_total(runs),
        shortfalls=shortfalls,
        generated_at=datetime.now(UTC).isoformat(),
        interview_settings=settings,
        weakness_map=weak_items,
        resume_pointers=hints.pointers,
        resume_pointers_notice=hints.notice,
        role_fit=role,
    )
    repository.insert_report(report)
    return report


def _degrade_copies(
    copies: Any,
    shortfalls: list[Shortfall],
    weak_items: list[WeaknessItem],
    role: RoleFit,
) -> tuple[list[Shortfall], list[WeaknessItem], RoleFit]:
    """`gather` 的任一异常 → 全部退回纯函数结果（模板文案仍然可用，AC-11 / anti-goal 5）。"""
    if isinstance(copies, BaseException) or not isinstance(copies, tuple):
        return shortfalls, weak_items, role
    enriched, weak_out, role_out = copies
    return enriched, weak_out, role_out


def _resume_text_of(profile: Profile | None) -> str | None:
    """简历正文（用于逐字定位）：无画像 / 无正文 → `None`，`resume_hints` 据此跳过 AI。"""
    if profile is None:
        return None
    resume_id = str(profile.resume_id or "").strip()
    if not resume_id:
        return None
    return repository.get_document_text(resume_id)


async def _enrich_coach(
    weakness: list[WeaknessItem], role: RoleFit, *, client: AIClient
) -> tuple[list[WeaknessItem], RoleFit]:
    """AI 只补薄弱描述与岗位结论；数值、条数、顺序一律不动，失败原样返回。"""
    has_role = role.model is not None
    if not weakness and not has_role:
        # 两块都没内容就不发请求（零额外延迟，也避免为一句空话付一次模型调用）。
        return weakness, role
    request = {
        "weaknesses": [
            {
                "key": item.key,
                "point": item.point,
                "difficulty": item.difficulty,
                "essentiality": item.essentiality,
                "wrong": item.wrong,
                "total": item.total,
                "rate": item.rate,
                "avg": item.avg,
                "summary": item.summary,
            }
            for item in weakness
        ],
        "role": None
        if not has_role
        else {
            "target_role": role.target_role,
            "level": role.model.label if role.model else None,
            "missing_must": role.missing_must,
            "first_fix": role.first_fix,
            "items": [
                {"name": row.name, "required": row.required, "user_level": row.user_level,
                 "gap": row.gap}
                for row in role.items
            ],
        },
    }
    try:
        draft = await client.complete_model(
            COACH_SYSTEM,
            "薄弱分组：" + json.dumps(request, ensure_ascii=False),
            _CoachCopyDraft,
        )
    except Exception:  # AI 降级是设计行为（anti-goal 5），不是异常路径
        return weakness, role

    copies = {copy.key.strip(): copy for copy in draft.weaknesses}
    enriched: list[WeaknessItem] = []
    for item in weakness:
        copy = copies.get(item.key.strip())
        summary = (copy.summary or "").strip() if copy is not None else ""
        enriched.append(item.model_copy(update={"summary": summary}) if summary else item)
    conclusion = (draft.role_conclusion or "").strip()
    if has_role and conclusion:
        role = role.model_copy(update={"conclusion": conclusion})
    return enriched, role


def interview_settings_of(runs: list[dict[str, Any]]) -> InterviewSettings | None:
    """本报告引用的「本次面试设定」：取 `runs` 里**最新一条**合法面试 run 的设定（AC-12）。

    报告是跨 run 合并的（一条短板可由多次面试归因），设定只能记一个 —— 因此取 `created_at`
    最新的那一场面试，`_resolve_runs` 的返回顺序（显式 id 顺序 / 自动取最近）都不影响结果。
    参与报告的面试全是旧 payload（无 `settings`）、或压根没有面试 → `None`，页面整行不渲染。

    解析口径不另写一份：直接复用历史的投影函数 `history._interviews_settings_of`，
    同一个 payload 在历史页与报告页必须给出同一份设定（否则两处「本场设定」会互相矛盾）。
    """
    candidates = [
        (str(run.get("created_at") or ""), settings)
        for run in runs
        if str(run.get("kind") or "") == "interview"
        for settings in [_interviews_settings_of(run.get("payload") or {})]
        if settings is not None
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


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
            if str(run.get("status") or "") != repository.RUN_COMPLETED:
                continue
            # 提前结束（一题未答）的会话也是 completed，但它没有任何可诊断的作答：
            # 跳过它，别挡住最近一次真正有成绩的同类测评。
            if score_of(kind, run.get("payload") or {}) is None:
                continue
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
