"""模拟笔试链（AC-4）：读库组卷、本地判分、作答事件写入、服务端计时。

为什么笔试完全不调 AI：客观题判分必须确定，且「提交后 10s 内」出分（AC-4）。
因此答案只活在服务端 `runs.payload`，`ExamQuestion` 响应模型天然没有 `answer` 字段；
判分口径（单选集合相等 / 多选完全匹配不给部分分 / 简答不计分）只在 `grade_objective`
一处实现，`services/diagnosis.py` 复算短板时直接复用这个函数，不另写一份规则。

r6 起本模块退回**纯编排**职责（TECHNICAL §4 / §7）：
- 题库承载 = `services/question_bank`（读库 + 空库幂等种子 + 可用性校验唯一一份）；
- 选池 / 随机 / 6 层兜底阶梯 / 结构闸门 = `services/exam_selector`（唯一实现）；
- 熟练度窗口判定 = `services/proficiency`（纯函数，注入 now 与阈值）；
- 可调阈值（熟练度窗口天数 / 窗口内答对次数 / 近卷去重卷数）只在 `config.Settings`
  单一出处（数值不在此处出现，避免阈值二次出处），闭集与结构常量只在 `services/rules`
  ——两类配置不混，两块 docstring 互相点名。

组卷口径（TECHNICAL §4.3）：先排除「已熟练题 + 近 N 卷已出题」，同相关度同难度档内随机；
不足按 L1→L6 唯一阶梯逐层放宽，任何一层因过滤失败都不 400，只有 L6 也凑不出结构达标的
卷才 400（中文「题库不足」，不新增错误码）。

payload 形状（TECHNICAL §4.3 笔试部分 + 判分回写扩展）：
`{"questions":[{id,kind,direction,prompt,options,answer,difficulty,essentiality}],
  "started_at":..., "stage":"L1".."L6", "filtered_count":n,
  "backfill":{"must_know":n,"other":m,"history":k}, "submitted_at":...,
  "answers":{qid: 作答}, "per_question":[{question_id,correct,your_answer,correct_answer}],
  "correct_count":n, "objective_total":n, "total":x, "elapsed_s":y}`
旧卷（r5 及更早）没有 `stage`/`filtered_count`/`backfill`，读侧一律 `.get()` 兜底，
不得 `KeyError`（AC-8 / AC-10）。

作答事件（AC-4 / AC-7）：客观题的判分结果在 `save_run()` **之前**算好、**之后**单事务写入
`question_attempts`；简答题不计分故永不写事件，`status=running` 的卷零事件，重复提交在
400 分支提前返回，因此事件写入恒为「一卷一次、一题一行」。
"""

from __future__ import annotations

import random
from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

from .. import repository
from ..config import get_settings
from ..errors import NOT_FOUND, VALIDATION_ERROR, AppError
from ..schemas import (
    ExamKind,
    ExamOption,
    ExamQuestion,
    ExamResult,
    ExamRun,
    PerQuestionResult,
)
from . import exam_selector, proficiency, question_bank, rules, timeline

EXAM_KIND = "exam"


# --- 组卷（编排）-----------------------------------------------------------


def create_run(
    profile_id: str,
    *,
    now: datetime | None = None,
    rng: random.Random | None = None,
) -> ExamRun:
    """按画像从题库选一份卷并落库（`status=running`），答案只留在服务端 payload。

    只做编排，不实现任何选池/结构规则：读库 → 读熟练度与近卷去重事实 → `select_paper()`
    → 落 payload。`now` / `rng` 可注入（测试要逐层构造阶梯与可复现随机），生产不传。
    位置参数保持 r5 兼容（既有调用点 `create_run(profile.id)` 不改）。
    """
    profile = repository.get_profile(profile_id)
    if profile is None:
        raise AppError(NOT_FOUND, "找不到该画像，请先上传简历生成画像", status=404)

    settings = get_settings()
    proficient = proficiency.proficient_ids(now=now)
    recent = repository.list_recent_exam_question_ids(settings.recent_paper_exclude)
    paper = exam_selector.select_paper(
        question_bank.load_questions(),
        profile,
        proficient=proficient,
        recent=recent,
        rng=rng,
    )
    if paper is None:
        # 唯一 400 出口：L6 用全库仍凑不出 10–12 题 / 客观 ≥8 / 挑战 ≤20%（AC-8）。
        raise AppError(VALIDATION_ERROR, "题库不足，暂无法出卷，请稍后重试", status=400)

    started_at = datetime.now(UTC) if now is None else now
    run_id = uuid4().hex
    payload: dict[str, Any] = {
        "questions": [dict(question) for question in paper.questions],
        "started_at": started_at.isoformat(),
        "submitted_at": None,
        # 阶梯与过滤透明度（AC-12 的一行文案读 filtered_count；stage/backfill 供 QA 断言）
        "stage": paper.stage,
        "filtered_count": paper.filtered_count,
        "backfill": dict(paper.backfill),
    }
    repository.insert_run(run_id, EXAM_KIND, profile_id, payload)
    return ExamRun(
        run_id=run_id,
        questions=[_public(question) for question in paper.questions],
        filtered_count=paper.filtered_count,
    )


def _public(question: dict[str, Any]) -> ExamQuestion:
    """响应题面：**绝不带 answer / difficulty**（题智隔离，AC-4）。"""
    options = [
        ExamOption(key=str(item.get("key") or ""), text=str(item.get("text") or ""))
        for item in question.get("options") or []
        if isinstance(item, dict)
    ]
    return ExamQuestion(
        id=str(question.get("id") or ""),
        kind=cast(ExamKind, str(question.get("kind") or "")),
        direction=str(question.get("direction") or ""),
        prompt=str(question.get("prompt") or ""),
        options=options,
    )


# --- 判分 -----------------------------------------------------------------


def _expected_keys(question: dict[str, Any]) -> set[str]:
    """题库里客观题的标准答案（选项 key 集合）；简答题返回空集。"""
    raw = question.get("answer")
    if isinstance(raw, str):
        key = raw.strip()
        return {key} if key else set()
    if isinstance(raw, (list, tuple)):
        return {str(item).strip() for item in raw if isinstance(item, (str, int)) and str(item).strip()}
    return set()


def _normalize_answer(answer: list[str] | str | None) -> set[str]:
    if isinstance(answer, str):
        key = answer.strip()
        return {key} if key else set()
    if isinstance(answer, (list, tuple)):
        return {
            str(item).strip()
            for item in answer
            if isinstance(item, (str, int)) and str(item).strip()
        }
    return set()


def _echo_answer(answer: Any) -> list[str] | str | None:
    """作答原样回显（list[str] | str | None），非法类型落成 None。"""
    if isinstance(answer, str):
        return answer
    if isinstance(answer, (list, tuple)):
        return [str(item) for item in answer if isinstance(item, (str, int))]
    return None


def grade_objective(question: dict[str, Any], answer: list[str] | str | None) -> bool:
    """本地判分：单选=选项集合相等；多选=完全集合相等（**少选/多选都算错**，不给部分分）。

    简答题（`text`）没有可判分标准答案 → 恒为 False（`PerQuestionResult.correct=None`
    由调用方处理）。客观题闭集只在 `rules.is_objective_kind()` 一处判定。
    """
    if not rules.is_objective_kind(str(question.get("kind") or "")):
        return False
    expected = _expected_keys(question)
    given = _normalize_answer(answer)
    if not expected or not given:
        return False
    return expected == given


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


# --- 提交与作答事件 --------------------------------------------------------


def _attempt_rows(
    run_id: str, results: list[PerQuestionResult], answered_at: datetime
) -> list[dict[str, Any]]:
    """把本卷客观题的判分结果翻译成 `question_attempts` 行（简答题不进 `per_question`）。

    只做纯数据映射，不碰库：调用方先算后写，写库的原子性由
    `repository.insert_attempts()` 的单事务 + `UNIQUE(question_id, run_id)` 保证。
    """
    stamp = answered_at.isoformat()
    rows: list[dict[str, Any]] = []
    for item in results:
        question_id = str(item.question_id or "").strip()
        if not question_id:
            continue
        rows.append(
            {
                "id": uuid4().hex,
                "question_id": question_id,
                "run_id": run_id,
                "correct": 1 if item.correct is True else 0,
                "answered_at": stamp,
                "created_at": stamp,
            }
        )
    return rows


def submit_run(run_id: str, answers: dict[str, list[str] | str]) -> ExamResult:
    """提交判分：服务端算 `elapsed_s`、回写逐题结果、重复提交 400、写客观题作答事件。

    判分块与 r5 逐字一致（零 AI、确定性、10s 预算）。事件写入严格排在
    `save_run()` 之后：卷面先落成 `completed`，再单事务落事件，异常不存在半条记录。
    """
    run = repository.get_run(run_id)
    if run is None or str(run.get("kind") or "") != EXAM_KIND:
        raise AppError(NOT_FOUND, "找不到这份笔试卷，请重新出卷", status=404)
    if str(run.get("status") or "") == repository.RUN_COMPLETED:
        raise AppError(
            VALIDATION_ERROR,
            "这份笔试卷已提交，重考请重新开始一次笔试",
            status=400,
        )

    payload: dict[str, Any] = dict(run.get("payload") or {})
    questions = [item for item in payload.get("questions") or [] if isinstance(item, dict)]

    submitted_at = datetime.now(UTC)
    started_at = _parse_time(payload.get("started_at"))
    elapsed_s = 0.0 if started_at is None else round(
        max((submitted_at - started_at).total_seconds(), 0.0), 1
    )

    echoed: dict[str, list[str] | str | None] = {}
    per_question: list[PerQuestionResult] = []
    correct_count = 0
    objective_total = 0
    for question in questions:
        qid = str(question.get("id") or "")
        if not qid:
            continue
        raw = answers.get(qid) if isinstance(answers, dict) else None
        if qid in answers:
            echoed[qid] = _echo_answer(raw)
        if not rules.is_objective_kind(str(question.get("kind") or "")):
            continue  # 简答题不计分、不进 per_question（前端只展示客观题对错）
        objective_total += 1
        correct = grade_objective(question, raw)
        correct_count += 1 if correct else 0
        per_question.append(
            PerQuestionResult(
                question_id=qid,
                correct=correct,
                your_answer=_echo_answer(raw),
                correct_answer=sorted(_expected_keys(question)),
            )
        )

    total = round(correct_count / objective_total * 100, 1) if objective_total else 0.0

    payload.update(
        {
            "submitted_at": submitted_at.isoformat(),
            "answers": echoed,
            "per_question": [item.model_dump() for item in per_question],
            "correct_count": correct_count,
            "objective_total": objective_total,
            "total": total,
            "elapsed_s": elapsed_s,
        }
    )
    # 先算后写：事件行在这里全部成型，下面 save_run 成功后才落库。
    attempt_rows = _attempt_rows(run_id, per_question, submitted_at)
    repository.save_run(run_id, payload, repository.RUN_COMPLETED)
    repository.insert_attempts(attempt_rows)
    # 时间线是旁路：写失败自行返回 None，绝不打断提交判分（r3 AC-1/AC-3）。
    timeline.record_run_event(
        {"id": run_id, "kind": EXAM_KIND, "payload": payload, "status": repository.RUN_COMPLETED}
    )

    return ExamResult(
        total=total,
        correct_count=correct_count,
        objective_total=objective_total,
        elapsed_s=elapsed_s,
        per_question=per_question,
    )
