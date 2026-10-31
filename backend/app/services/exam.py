"""模拟笔试链（AC-4）：题智组卷、本地判分、服务端计时。

为什么笔试完全不调 AI：客观题判分必须确定，且「提交后 10s 内」出分（AC-4）。
因此答案只活在服务端 `runs.payload`，`ExamQuestion` 响应模型天然没有 `answer` 字段；
判分口径（单选集合相等 / 多选完全匹配不给部分分 / 简答不计分）只在 `grade_objective`
一处实现，`services/diagnosis.py` 复算短板时直接复用这个函数，不另写一份规则。

组卷口径（TECHNICAL §4）：
- 先按画像 `tech_stack + target_role` 命中的方向排序取客观题（`single`/`multiple`），取满 ≥8；
- 再用 `text` 补到 ≥10，≤12；某方向不足则跨方向补齐（**题量优先于方向纯度**）；
- 挑战题占比 ≤20%（`rules.max_challenge_count`）；
- 补齐后仍不足 10 题 → 400 中文「题库不足」，不出 9 题卷。

payload 形状（TECHNICAL §1.2 的笔试部分 + 判分回写扩展）：
`{"questions":[{id,kind,direction,prompt,options,answer,difficulty}],
  "started_at":..., "submitted_at":..., "answers":{qid: 作答},
  "per_question":[{question_id,correct,your_answer,correct_answer}],
  "correct_count":n, "objective_total":n, "total":x, "elapsed_s":y}`
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from .. import repository
from ..errors import NOT_FOUND, VALIDATION_ERROR, AppError
from ..schemas import (
    ExamKind,
    ExamOption,
    ExamQuestion,
    ExamResult,
    ExamRun,
    PerQuestionResult,
    Profile,
)
from . import rules, timeline

SEED_PATH = Path(__file__).resolve().parent.parent / "seed" / "questions.json"
EXAM_KIND = "exam"
OBJECTIVE_KINDS = frozenset({"single", "multiple"})
TEXT_KIND = "text"

#: 题库方向 → 画像线索关键词（方向名本身也算，见 `_affinity`）。
DIRECTION_KEYWORDS: dict[str, tuple[str, ...]] = {
    "前端": ("前端", "react", "vue", "angular", "typescript", "javascript", "css", "浏览器", "组件"),
    "后端": (
        "后端",
        "服务端",
        "python",
        "java",
        "golang",
        "go",
        "fastapi",
        "django",
        "sql",
        "sqlite",
        "database",
        "数据库",
        "并发",
        "缓存",
        "api",
    ),
    "算法与数据结构": ("算法", "数据结构", "复杂度", "动态规划", "leetcode", "红黑树", "堆"),
    "计算机基础": ("计算机基础", "操作系统", "网络", "linux", "git", "编译", "内存", "进程", "线程"),
}


# --- 题库 -----------------------------------------------------------------


def _expected_keys(question: dict[str, Any]) -> set[str]:
    """题库里客观题的标准答案（选项 key 集合）；简答题返回空集。"""
    raw = question.get("answer")
    if isinstance(raw, str):
        key = raw.strip()
        return {key} if key else set()
    if isinstance(raw, (list, tuple)):
        return {str(item).strip() for item in raw if isinstance(item, (str, int)) and str(item).strip()}
    return set()


def _usable(question: Any) -> bool:
    """题库条目的最低可用性：缺 id / kind / prompt 或客观题无答案，一律不出卷。"""
    if not isinstance(question, dict):
        return False
    if not str(question.get("id") or "").strip():
        return False
    if str(question.get("kind") or "") not in {*OBJECTIVE_KINDS, TEXT_KIND}:
        return False
    if not str(question.get("prompt") or "").strip():
        return False
    if str(question.get("kind") or "") in OBJECTIVE_KINDS:
        return bool(_expected_keys(question)) and isinstance(question.get("options"), list)
    return True


def _load_questions() -> list[dict[str, Any]]:
    """读静态题库：每次出卷重新读，题库（T6）随时可扩充，不缓存旧快照。"""
    try:
        raw = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    except OSError as exc:  # 题库文件缺失属于部署异常，映射成可读中文错误
        raise AppError(VALIDATION_ERROR, "题库文件不可用，暂无法出卷", status=400) from exc
    if not isinstance(raw, list):
        raise AppError(VALIDATION_ERROR, "题库文件格式异常，暂无法出卷", status=400)
    return [item for item in raw if _usable(item)]


# --- 组卷 -----------------------------------------------------------------


def _profile_tokens(profile: Profile) -> list[str]:
    tokens = [str(item).strip().lower() for item in profile.tech_stack if str(item).strip()]
    role = (profile.target_role or "").strip().lower()
    if role:
        tokens.append(role)
    return tokens


def _affinity(question: dict[str, Any], tokens: list[str]) -> int:
    """方向相关度：方向名直接出现在画像线索里得 3 分，命中关键词各得 1 分。"""
    direction = str(question.get("direction") or "").strip().lower()
    if not direction:
        return 0
    score = 3 if any(direction in token for token in tokens) else 0
    keywords = DIRECTION_KEYWORDS.get(direction, ())
    score += sum(1 for keyword in keywords if any(keyword in token for token in tokens))
    return score


def _is_challenge(question: dict[str, Any]) -> bool:
    return rules.is_challenge_difficulty(str(question.get("difficulty") or "basic"))


def _ordered(questions: list[dict[str, Any]], profile: Profile) -> list[dict[str, Any]]:
    """按画像相关度倒序；同分按题库 id 稳定排序，保证同画像同题库出同一份卷。"""
    tokens = _profile_tokens(profile)
    return sorted(
        questions,
        key=lambda question: (-_affinity(question, tokens), str(question.get("id") or "")),
    )


def _challenge_count(picked: list[dict[str, Any]]) -> int:
    return sum(1 for question in picked if _is_challenge(question))


def _respect_challenge_cap(
    picked: list[dict[str, Any]], pool: list[dict[str, Any]]
) -> list[dict[str, Any]] | None:
    """把挑战题压回 ≤20%：多出的按顺序丢弃，再用非挑战题补回题量下限。"""
    selected = picked[: rules.MAX_EXAM_QUESTIONS]
    allowed = rules.max_challenge_count(len(selected))
    excess = _challenge_count(selected) - allowed
    if excess > 0:
        trimmed = list(selected)
        for question in reversed(trimmed):
            if excess <= 0:
                break
            if _is_challenge(question):
                trimmed.remove(question)
                excess -= 1
        taken = {str(question.get("id") or "") for question in trimmed}
        for question in pool:
            if len(trimmed) >= rules.MIN_EXAM_QUESTIONS:
                break
            qid = str(question.get("id") or "")
            if qid in taken or _is_challenge(question):
                continue
            trimmed.append(question)
            taken.add(qid)
        selected = trimmed[: rules.MAX_EXAM_QUESTIONS]
    if len(selected) < rules.MIN_EXAM_QUESTIONS:
        return None
    if _challenge_count(selected) > rules.max_challenge_count(len(selected)):
        return None
    return selected


def _compose(questions: list[dict[str, Any]], profile: Profile) -> list[dict[str, Any]] | None:
    """出一份 10..12 题、客观 ≥8、挑战 ≤20% 的卷；客观题不足 8 或总数不足 10 返回 None。"""
    ordered = _ordered(questions, profile)
    objective = [q for q in ordered if str(q.get("kind") or "") in OBJECTIVE_KINDS]
    texts = [q for q in ordered if str(q.get("kind") or "") == TEXT_KIND]

    picked: list[dict[str, Any]] = []
    seen: set[str] = set()
    # 试卷按 10 题规划，因此挑战题额度按 10 题算；总量最多扩到 12 题，额度只会更宽。
    cap = rules.max_challenge_count(rules.MIN_EXAM_QUESTIONS)

    def take(pool: list[dict[str, Any]], need: int) -> int:
        taken = 0
        for question in pool:
            if taken >= need:
                break
            qid = str(question.get("id") or "")
            if not qid or qid in seen:
                continue
            if _is_challenge(question) and _challenge_count(picked) >= cap:
                continue
            picked.append(question)
            seen.add(qid)
            taken += 1
        return taken

    if take(objective, rules.MIN_OBJECTIVE_QUESTIONS) < rules.MIN_OBJECTIVE_QUESTIONS:
        return None  # 客观题不足 8 道：不出卷（AC-4 的判分分母必须成立）
    take(texts, rules.MIN_EXAM_QUESTIONS - len(picked))
    if len(picked) < rules.MIN_EXAM_QUESTIONS:
        # 简答题不够就用客观题补到 10 题（题量优先于题型配比，仍保住客观 ≥8 的分母）
        take(objective, rules.MIN_EXAM_QUESTIONS - len(picked))
    if len(picked) < rules.MIN_EXAM_QUESTIONS:
        return None
    return _respect_challenge_cap(picked, ordered)


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


def create_run(profile_id: str) -> ExamRun:
    """按画像出一份笔试卷并落库（`status=running`），答案只留在服务端 payload。"""
    profile = repository.get_profile(profile_id)
    if profile is None:
        raise AppError(NOT_FOUND, "找不到该画像，请先上传简历生成画像", status=404)
    selection = _compose(_load_questions(), profile)
    if selection is None:
        raise AppError(VALIDATION_ERROR, "题库不足，暂无法出卷，请稍后重试", status=400)

    run_id = uuid4().hex
    payload: dict[str, Any] = {
        "questions": [dict(question) for question in selection],
        "started_at": datetime.now(UTC).isoformat(),
        "submitted_at": None,
    }
    repository.insert_run(run_id, EXAM_KIND, profile_id, payload)
    return ExamRun(run_id=run_id, questions=[_public(question) for question in selection])


# --- 判分 -----------------------------------------------------------------


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

    简答题（`text`）没有可判分标准答案 → 恒为 False（`PerQuestionResult.correct=None` 由调用方处理）。
    """
    kind = str(question.get("kind") or "")
    if kind not in OBJECTIVE_KINDS:
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


def submit_run(run_id: str, answers: dict[str, list[str] | str]) -> ExamResult:
    """提交判分：服务端算 `elapsed_s`、回写逐题结果，重复提交 400。"""
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
        if str(question.get("kind") or "") not in OBJECTIVE_KINDS:
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
    repository.save_run(run_id, payload, repository.RUN_COMPLETED)
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
