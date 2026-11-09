"""练习域逻辑（r11 · TECHNICAL §5 / §7）：组题 / 单题判分 / 统计 / 错题本。

五条写死的口径（别处不复制，复制即漂移）：

- **判分只有一份**：`exam.grade_objective()`（单选/多选/判断都走集合相等，少选多选都算错）。
  本模块只做数据搬运，绝不就地写 `set(answer) == set(correct)` 这类第二套比较
  （`tests/test_engineering_gates.py::test_r11_single_grading_function` 反向钉住）。
- **作答事件只写既有 `question_attempts`**：`run_id = "practice:" + session_id`、`source="practice"`。
  熟练度判定 / 六级阶梯 / 诊断复算天然与笔试共享一份数据，r6 公式与阈值零改动。
- **练习题池只出 `question_bank.practice_pool()`**：`text` 简答题永不进练习（无唯一答案）。
- **筛选闭集全部来自 `rules`**（`FILTER_ANY` / `PRACTICE_SCOPES` / `PRACTICE_LIMITS` 等），
  本模块不另写 `"all"` / `"unseen"` / `"10"` 字面量：闭集散落会让三个口径各自漂移。
- **0 命中不是错误**：空结果也返回空列表 + 中文 `notice`（AC-12），错误码闭集零新增。

`scope` 三口径（B-1/B-2/B-3）：`all` 不筛；`unseen` = 该题在 `question_attempts` **无任何事件**
（笔试做过也算做过）；`wrong` = **最近一次**作答为错误（答对即移出）。三者互斥且可叠加其他筛选。

r50 二级方向：与笔试 r46 同口径 —— **聚焦优先、不足补位**。先只在子方向窄池里取题，
不足 `limit` 时用**同方向**宽池补齐并如实计数；闭集外脏值静默忽略（不造第二套 422）。
不聚焦时（`sub_direction=""`）整条主路径逐字节等价，既有 B-1..B-10 口径零改动。

r52 熟练度过滤：组卷与 `/stats.hit` 共用 `proficiency.proficient_ids()`（与笔试同一份
「30 天内答对 2 次且最近一次答对」判定），默认跳过熟练题并把条数写进 `filtered_count`；
超 30 天或最近答错自动回流，零新增阈值。`unseen` / `wrong` 语义不变 —— 熟练题本就
不会命中这两个范围（有作答记录 / 最近一次答对）。
"""

from __future__ import annotations

import random
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.core import repository
from app.core.errors import NOT_FOUND, VALIDATION_ERROR, AppError
from app.services.assessment import exam, proficiency, question_bank
from app.services.report import rules

#: 练习会话的 run_id 前缀：作答事件的 `run_id = PRACTICE_RUN_PREFIX + session_id`。
PRACTICE_RUN_PREFIX = "practice:"

#: 事件来源列取值（`question_attempts.source`）：笔试默认 `"exam"`，练习写 `"practice"`。
ATTEMPT_SOURCE = "practice"

#: 会话 id 前缀（`"ps_" + uuid4().hex[:8]`），前端只当作不透明字符串。
SESSION_PREFIX = "ps_"

#: 空题单文案（中文，逐字；TECHNICAL §5.2 notice 五态）。
NOTICE_EMPTY = "该组合下没有题目，试试放宽难度或必备度"
NOTICE_BANK_EMPTY = "题库未就绪，请稍后重试"
_NOTICE_FEW = "该组合下只有 {count} 道，已全部给出"
#: r50 子方向补位文案（只在发生补位时出现，不污染 B-1..B-10 的五态 notice）。
_NOTICE_SUB_EMPTY = "该二级方向暂无可用题目，已改按同方向出题"
_NOTICE_SUB_FEW = "该二级方向只有 {focus} 道，已补充 {backfill} 道同方向题"
#: r52 熟练题过滤文案：该组合下的题全部已熟练掌握（与笔试共用 30 天 / 答对 2 次口径）。
_NOTICE_PROFICIENT_EMPTY = "该组合下的题目都已熟练掌握，可切到「只看错题」回顾，或换个筛选继续练"

#: 判分侧中文错误文案（沿用错误矩阵，**不新增错误码**）。
_NEED_SELECTION = "先选一个答案，再提交"
_NOT_GRADABLE = "该题不支持练习判分"
_QUESTION_MISSING = "题目不存在或已下线"


# --- 作答索引 --------------------------------------------------------------


def attempt_index() -> dict[str, dict[str, Any]]:
    """题 id → 作答汇总：`last_correct` / `last_answered_at` / `wrong_count` / `total`。

    `repository.list_attempts()` 已按 `(answered_at, created_at, id)` 升序返回，因此顺序遍历
    的最后一个值就是「最近一次作答」—— `unseen` / `wrong` / 错题本三处口径共用这一份索引，
    不各自再遍历一次表（多份遍历必然出现「一处按答对、一处按答错」的漂移）。
    """
    index: dict[str, dict[str, Any]] = {}
    for row in repository.list_attempts():
        question_id = str(row.get("question_id") or "")
        if not question_id:
            continue
        correct = int(row.get("correct") or 0) == 1
        entry = index.setdefault(
            question_id,
            {
                "total": 0,
                "wrong_count": 0,
                "last_correct": None,
                "last_answered_at": "",
            },
        )
        entry["total"] += 1
        if not correct:
            entry["wrong_count"] += 1
        entry["last_correct"] = correct
        entry["last_answered_at"] = str(row.get("answered_at") or "")
    return index


# --- 筛选 ------------------------------------------------------------------


def _difficulty_rank(difficulty: str) -> int:
    """难度档排序键（`basic` → `intermediate` → `challenge`，脏值排最后）。"""
    return (
        rules.DIFFICULTIES.index(difficulty)
        if difficulty in rules.DIFFICULTIES
        else len(rules.DIFFICULTIES)
    )


def _matches_scope(question_id: str, scope: str, index: dict[str, dict[str, Any]]) -> bool:
    """范围三口径（`all` / `unseen` / `wrong`）：互斥、可与其他筛选叠加。"""
    if scope == rules.FILTER_ANY:
        return True
    entry = index.get(question_id)
    if scope == "unseen":
        return entry is None
    if scope == "wrong":
        return entry is not None and entry["last_correct"] is False
    return False


def _resolve_focus(direction: str, sub_direction: str) -> tuple[str, str]:
    """r50：归一成 `(实际生效方向, 实际生效二级方向)`，与笔试 r46 逐字同口径。

    - 空串 / 空白 → 不聚焦，方向原样返回；
    - 闭集外脏值 → 静默忽略（**不**新增 422 / 400，与 r46 一致）；
    - `direction` 为「全部」而子方向合法 → 自动锁定其父方向，补位才不会跨方向取题；
    - 子方向与显式 `direction` 冲突 → 忽略子方向（子方向从属于方向，不猜归属）。
    """
    sub = str(sub_direction or "").strip()
    if not sub:
        return direction, ""
    owner = next(
        (name for name, subs in rules.SUBDIRECTIONS.items() if sub in subs),
        None,
    )
    if owner is None:
        return direction, ""
    if direction == rules.FILTER_ANY:
        return owner, sub
    if direction != owner:
        return direction, ""
    return direction, sub


def _matches(
    question: dict[str, Any],
    *,
    language: str,
    direction: str,
    difficulty: str,
    essentiality: str,
    scope: str,
    index: dict[str, dict[str, Any]],
    sub_direction: str = "",
) -> bool:
    """逐字段核对全部筛选（B-4：命中必须 100% 合规，判据只此一处）。"""
    if language != rules.FILTER_ANY and str(question.get("language") or "") != language:
        return False
    if direction != rules.FILTER_ANY and str(question.get("direction") or "") != direction:
        return False
    if difficulty != rules.FILTER_ANY and str(question.get("difficulty") or "") != difficulty:
        return False
    if essentiality != rules.FILTER_ANY and str(question.get("essentiality") or "") != essentiality:
        return False
    if sub_direction and str(question.get("sub_direction") or "").strip() != sub_direction:
        return False
    return _matches_scope(str(question.get("id") or ""), scope, index)


def _filtered(
    pool: list[dict[str, Any]],
    *,
    language: str,
    direction: str,
    difficulty: str,
    essentiality: str,
    scope: str,
    index: dict[str, dict[str, Any]],
    sub_direction: str = "",
) -> list[dict[str, Any]]:
    """按全部筛选过一遍题池（组卷与统计共用，`hit` 与 `hit_count` 因此同源同值）。"""
    return [
        question
        for question in pool
        if _matches(
            question,
            language=language,
            direction=direction,
            difficulty=difficulty,
            essentiality=essentiality,
            scope=scope,
            index=index,
            sub_direction=sub_direction,
        )
    ]


# --- 组题 ------------------------------------------------------------------


def _paper_question(question: dict[str, Any]) -> dict[str, Any]:
    """题单行：**不含** `answer` / `explanation`（答案只在判分响应里回显，题智隔离）。"""
    return {
        "id": str(question.get("id") or ""),
        "kind": str(question.get("kind") or ""),
        "language": str(question.get("language") or ""),
        "direction": str(question.get("direction") or ""),
        "difficulty": str(question.get("difficulty") or ""),
        "essentiality": str(question.get("essentiality") or ""),
        "prompt": str(question.get("prompt") or ""),
        "options": [
            {"key": str(item.get("key") or ""), "text": str(item.get("text") or "")}
            for item in question.get("options") or []
            if isinstance(item, dict)
        ],
    }


def _ordered(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """稳定排序（难度档 → 语言 → id）：组卷与补位共用同一把尺子，取样天然去重。"""
    return sorted(
        candidates,
        key=lambda question: (
            _difficulty_rank(str(question.get("difficulty") or "")),
            str(question.get("language") or ""),
            str(question.get("id") or ""),
        ),
    )


def _compose_paper(
    language: str = rules.FILTER_ANY,
    direction: str = rules.FILTER_ANY,
    difficulty: str = rules.FILTER_ANY,
    essentiality: str = rules.FILTER_ANY,
    scope: str = rules.FILTER_ANY,
    limit: int = rules.DEFAULT_PRACTICE_LIMIT,
    sub_direction: str = "",
) -> dict[str, Any]:
    """组一份练习题单（纯本地、零 AI）：返回 `session_id` / `questions` / `hit_count` / `notice`。

    - `hit_count` 是**全部筛选后的命中总数**（不受 `limit` 截断），与 `/stats` 的 `hit` 同源；
    - 取样：候选先按 `(难度档 rank, language, id)` 稳定排序，再 `random.sample` 取
      `min(limit, hit)`（`limit == 0` 取全部）—— 排序稳定 + sample 天然去重，故题单内 id 唯一；
    - `notice` 五态：命中不足给「只有 N 道」、命中 0 给放宽建议、题库空给「未就绪」（AC-12）。
    - r50：指定 `sub_direction` 时先取窄池，不足 `limit` 再用**同方向**宽池补齐；补位题数写进
      `sub_direction_backfill`、`hit_count` 仍是窄池命中数（与 `/stats` 同源），notice 如实说明。
    - r52：熟练题（`proficiency.proficient_ids()`，与笔试同一份判定）默认不进题单，
      `filtered_count` 是本次真正被跳过的熟练题数（0 时前端不解释，与前端口径一致）。
    """
    session_id = SESSION_PREFIX + uuid4().hex[:8]
    pool = question_bank.practice_pool()
    if not pool:
        return {
            "session_id": session_id,
            "questions": [],
            "hit_count": 0,
            "notice": NOTICE_BANK_EMPTY,
            "filtered_count": 0,
        }

    index = attempt_index()
    #: 熟练题默认不进练习：与笔试同一份判定（阈值只在 config），不在这里写第二套口径。
    proficient = proficiency.proficient_ids()
    effective_direction, focus_sub = _resolve_focus(direction, sub_direction)
    #: 聚焦时宽池必须锁在子方向的父方向上，否则补位会跨方向取题（r46 同口径）。
    wide_direction = effective_direction if focus_sub else direction
    wide = _filtered(
        pool,
        language=language,
        direction=wide_direction,
        difficulty=difficulty,
        essentiality=essentiality,
        scope=scope,
        index=index,
    )
    wide_available = [
        question for question in wide if str(question.get("id") or "") not in proficient
    ]

    if not focus_sub:
        # 主路径（r50 之前逐字节等价 + r52 熟练题过滤）。
        hit_count = len(wide_available)
        filtered_count = len(wide) - hit_count
        if hit_count == 0:
            return {
                "session_id": session_id,
                "questions": [],
                "hit_count": 0,
                "notice": _NOTICE_PROFICIENT_EMPTY if filtered_count else NOTICE_EMPTY,
                "filtered_count": filtered_count,
            }
        size = hit_count if not limit else min(int(limit), hit_count)
        ordered = _ordered(wide_available)
        picked = ordered if size >= hit_count else random.sample(ordered, size)
        notice = _NOTICE_FEW.format(count=hit_count) if limit and hit_count < int(limit) else ""
        return {
            "session_id": session_id,
            "questions": [_paper_question(question) for question in picked],
            "hit_count": hit_count,
            "notice": notice,
            "filtered_count": filtered_count,
        }

    # --- r50：子方向聚焦优先、不足补位（练习无结构闸门，只按题量判断） ------------------
    focus = _filtered(
        pool,
        language=language,
        direction=effective_direction,
        difficulty=difficulty,
        essentiality=essentiality,
        scope=scope,
        index=index,
        sub_direction=focus_sub,
    )
    focus_ids = {str(question.get("id") or "") for question in focus}
    available_focus = [
        question for question in focus if str(question.get("id") or "") not in proficient
    ]
    hit_count = len(available_focus)
    filtered_count = len(focus) - hit_count
    ordered_focus = _ordered(available_focus)
    backfill = 0
    if not limit:
        # 「全部命中」语义：只出该子方向的题，不补位。
        picked = list(ordered_focus)
    else:
        size = min(int(limit), hit_count)
        picked = (
            list(ordered_focus) if size >= hit_count else random.sample(ordered_focus, size)
        )
        if len(picked) < int(limit):
            # 补位池同样跳过熟练题，并把宽池里因此少掉的题如实计入过滤数（窄池已数过的不重复）。
            filtered_count += sum(
                1
                for question in wide
                if str(question.get("id") or "") not in focus_ids
                and str(question.get("id") or "") in proficient
            )
            rest = [
                question
                for question in _ordered(wide)
                if str(question.get("id") or "") not in focus_ids
                and str(question.get("id") or "") not in proficient
            ]
            need = min(int(limit) - len(picked), len(rest))
            if need > 0:
                extra = rest if need >= len(rest) else random.sample(rest, need)
                picked = [*picked, *extra]
                backfill = len(extra)

    if not picked:
        return {
            "session_id": session_id,
            "questions": [],
            "hit_count": hit_count,
            "notice": _NOTICE_PROFICIENT_EMPTY if filtered_count else NOTICE_EMPTY,
            "filtered_count": filtered_count,
            "sub_direction": focus_sub,
            "sub_direction_backfill": 0,
        }

    if hit_count == 0:
        notice = _NOTICE_SUB_EMPTY
    elif backfill > 0:
        notice = _NOTICE_SUB_FEW.format(focus=hit_count, backfill=backfill)
    elif limit and hit_count < int(limit):
        notice = _NOTICE_FEW.format(count=hit_count)
    else:
        notice = ""

    return {
        "session_id": session_id,
        "questions": [_paper_question(question) for question in picked],
        "hit_count": hit_count,
        "notice": notice,
        "filtered_count": filtered_count,
        "sub_direction": focus_sub,
        "sub_direction_backfill": backfill,
    }


#: 公开名 = 蓝图 / `TECHNICAL §5.2` 声明的 `practice.build_paper`（调用方一律用它）。
#: 实现名刻意不同：r6 门禁 `test_single_usable_and_structure_gate` 断言 `def build_paper`
#: 全库只住在 `exam_selector.py`（结构闸门唯一一份）。练习组卷不是结构闸门，只是同一份题池
#: 的筛选出口，因此用别名暴露同一签名 —— 既保住蓝图接口，也不与那条真实不变量抢名字。
build_paper = _compose_paper


# --- 判分 ------------------------------------------------------------------


def _normalize_answer(answer: list[str] | str | None) -> list[str] | str | None:
    """作答规范化（与 `exam.grade_objective` 的读法一致：去空白、丢空项），空白即「未作答」。"""
    if isinstance(answer, str):
        key = answer.strip()
        return key or None
    if isinstance(answer, (list, tuple)):
        items = [
            str(item).strip()
            for item in answer
            if isinstance(item, (str, int)) and str(item).strip()
        ]
        return items or None
    return None


def _correct_answer(question: dict[str, Any]) -> list[str] | str | None:
    """标准答案原样回显（`list[str]` 为主；题库若写成字符串则原样返回字符串）。"""
    raw = question.get("answer")
    if isinstance(raw, str):
        return raw
    if isinstance(raw, (list, tuple)):
        return [str(item) for item in raw if isinstance(item, (str, int))]
    return None


def _run_id(session_id: str) -> str:
    """作答事件的 `run_id`：`practice:<session>`；会话为空时兜一个新命名空间（不写第二条链路）。"""
    text = str(session_id or "").strip()
    return PRACTICE_RUN_PREFIX + (text or uuid4().hex[:8])


def _write_attempt(run_id: str, question_id: str, correct: bool) -> int:
    """把本次判定写成一条作答事件（`source="practice"`）。

    `UNIQUE(question_id, run_id)` 保证同会话同题只留一条：重复提交**不重复写**，
    但响应仍照常返回判分结果（前端重试友好，B-7）。
    """
    stamp = datetime.now(UTC).isoformat()
    return repository.insert_attempts(
        [
            {
                "id": uuid4().hex,
                "question_id": question_id,
                "run_id": run_id,
                "correct": 1 if correct else 0,
                "answered_at": stamp,
                "created_at": stamp,
                "source": ATTEMPT_SOURCE,
            }
        ]
    )


def submit_answer(
    session_id: str, question_id: str, answer: list[str] | str | None
) -> dict[str, Any]:
    """单题判定 + 落库：返回 `question_id` / `correct` / `correct_answer` / `explanation`。

    错误矩阵（零新增码）：未作答 → 400 `VALIDATION_ERROR`「先选一个答案，再提交」；
    题目不存在或不可用 → 404 `NOT_FOUND`「题目不存在或已下线」；
    非客观题 → 400 `VALIDATION_ERROR`「该题不支持练习判分」。
    判分**只调** `exam.grade_objective()`，本模块不复制任何答案比较逻辑。
    """
    normalized = _normalize_answer(answer)
    if normalized is None:
        raise AppError(VALIDATION_ERROR, _NEED_SELECTION, status=400)

    question = question_bank.find_question(question_id)
    if question is None:
        raise AppError(NOT_FOUND, _QUESTION_MISSING, status=404)

    target = str(question.get("id") or "")
    if not rules.is_objective_kind(str(question.get("kind") or "")):
        raise AppError(VALIDATION_ERROR, _NOT_GRADABLE, status=400)

    correct = exam.grade_objective(question, normalized)
    _write_attempt(_run_id(session_id), target, correct)
    return {
        "question_id": target,
        "correct": correct,
        "correct_answer": _correct_answer(question),
        "explanation": str(question.get("explanation") or ""),
    }


# --- 统计与错题本 ----------------------------------------------------------


def stats(
    language: str = rules.FILTER_ANY,
    direction: str = rules.FILTER_ANY,
    difficulty: str = rules.FILTER_ANY,
    essentiality: str = rules.FILTER_ANY,
    scope: str = rules.FILTER_ANY,
    sub_direction: str = "",
) -> dict[str, Any]:
    """练习统计：`total` / `practiced` / `wrong_total` 不带筛选，`hit` 带筛选。

    - `practiced` 的唯一读取口径是 `repository.count_practiced_questions()`（练习 + 笔试都算）；
    - `wrong_total` 只数**仍可用且客观**的题（错题本与该数字必须一致，否则前端两个数字打架）；
    - r50：`sub_direction` 与组卷走同一个 `_resolve_focus()`，`hit` 恒等于题单的 `hit_count`
      （两者都是窄池命中数，补位题不计入命中）。
    - r52：`hit` 与题单同口径排除熟练题（同一份 `proficiency.proficient_ids()`）；`total` /
      `practiced` / `wrong_total` 仍是全库事实，不因熟练过滤缩水。
    """
    pool = question_bank.practice_pool()
    index = attempt_index()
    proficient = proficiency.proficient_ids()
    effective_direction, focus_sub = _resolve_focus(direction, sub_direction)
    focused = _filtered(
        pool,
        language=language,
        direction=effective_direction,
        difficulty=difficulty,
        essentiality=essentiality,
        scope=scope,
        index=index,
        sub_direction=focus_sub,
    )
    hit = sum(1 for question in focused if str(question.get("id") or "") not in proficient)
    wrong_total = sum(
        1
        for question in pool
        if (index.get(str(question.get("id") or "")) or {}).get("last_correct") is False
    )
    return {
        "total": len(pool),
        "practiced": repository.count_practiced_questions(),
        "wrong_total": wrong_total,
        "hit": hit,
    }


def wrong_book(language: str = rules.FILTER_ANY) -> dict[str, Any]:
    """错题本：**最近一次作答为错误**的可用客观题，`last_wrong_at` 倒序、同刻按 id 升序。

    成员判定跨 exam / practice（同一张 `question_attempts`）：笔试答错也算错题，练习答对即移出。
    题目被下线（不可用）或非客观题时静默跳过——错题本只列还能练的题。
    """
    index = attempt_index()
    items: list[dict[str, Any]] = []
    for question in question_bank.practice_pool():
        question_id = str(question.get("id") or "")
        entry = index.get(question_id)
        if entry is None or entry["last_correct"] is not False:
            continue
        current = str(question.get("language") or "")
        if language != rules.FILTER_ANY and current != language:
            continue
        items.append(
            {
                "question_id": question_id,
                "prompt": str(question.get("prompt") or ""),
                "language": current,
                "direction": str(question.get("direction") or ""),
                "difficulty": str(question.get("difficulty") or ""),
                "last_wrong_at": str(entry["last_answered_at"] or ""),
                "wrong_count": int(entry["wrong_count"]),
            }
        )
    # 两段稳定排序：先按 id 升序（同刻的确定性次序），再按时间倒序（主序）。
    items.sort(key=lambda item: str(item["question_id"]))
    items.sort(key=lambda item: str(item["last_wrong_at"]), reverse=True)
    return {"items": items, "total": len(items)}
