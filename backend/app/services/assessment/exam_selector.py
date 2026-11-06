"""组卷选池 / 随机化 / 6 层兜底阶梯（r6 · TECHNICAL §4，**唯一实现**）。

`exam.py` 退回纯编排（读库 → 调本模块 → 落 payload）；本模块承担三件事，每件事只有一份实现：

1. `rank_pool()` —— 相关度（画像 `tech_stack` / `target_role` 命中的方向）分桶、(相关度, 难度档)
   成桶，**只在桶内**用注入的 `rng` 洗牌，桶序稳定（相关度降序、难度升序）。因此「随机」永远
   不会把结构随机掉：题量 / 客观题数 / 挑战题占比 / 方向覆盖由 `build_paper()` 这一个校验点兜住
   （AC-9 的「随机限同相关度同难度档」与「结构约束恒定成立」同时成立）。
2. `build_paper()` —— 结构闸门（原 `exam.py` 的 `_compose` + `_respect_challenge_cap` 合并搬迁，
   `exam.py` 不再保留第二份）。10–12 题 / 客观 ≥8 / 挑战 ≤20% / 方向 ≥ `require_directions`，
   任一条不满足返回 `None`（换池重试，**不是异常**，因此任何一层都不会因过滤 400）。
   **「每种可用客观题型各 ≥1」不在本闸门的校验项里**，它是取题策略：候选列表先经
   `_prefer_kind_diversity()` 把每种可用客观题型的代表题提到队首（r11：判断题全落在
   intermediate/challenge 档，旧取题顺序下 basic 额度先被用尽，卷面上结构不可达）。
3. `select_paper()` —— L1→L6 唯一阶梯，顺序不可重排：先滤「熟练 + 近 N 卷」，逐层把过滤掉的题
   放回池子（L2 熟练 `must_know` → L3 熟练其余 → L4 历史卷逐卷 → L5 全库放宽方向 ≥1 →
   L6 全库不要求方向）。只有 L6 仍凑不出结构达标的卷，调用方才 400（AC-8 的唯一 400 出口）。

**配置分工（别漂）**：题量 / 占比 / 方向 / 难度 / 必备度 / 阶梯这些**闭集与结构常量**只来自
`services/rules.py`；熟练度窗口天数 / 答对次数 / 近卷去重卷数这些**可调阈值**只住
`config.Settings`，本模块一律不读（由 `exam.py` 取好 `proficient` / `recent` 传进来）。
本模块因此是**纯函数层**：不读时钟、不读配置、不碰数据库，`rng` 与候选池全部注入。

`backfill` 语义（payload 用，供 QA 断言阶梯顺序）：`{"must_know": n, "other": m, "history": k}`，
分别是 L2 / L3 / L4 把多少道此前被过滤的题放回了池子（三层各自独立计数；一道题可以既熟练
又在历史卷里，因此三项之和可能大于去重后的题数）。`filtered_count` 是**净过滤数**，
语义唯一出处见 `_filtered_count()`。
"""

from __future__ import annotations

import random
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from app.schemas import Profile
from app.services.report import rules

#: 组卷阶梯顺序（唯一定义在 `rules.PAPER_STAGES`，此处就近重导出，不另立第二份）。
PAPER_STAGES: tuple[str, ...] = rules.PAPER_STAGES

#: 简答题 kind / 必备度最高档的**唯一定义在 `rules.py`**（`rules.TEXT_KIND` / `rules.MUST_KNOW`），
#: 本文件只引用、不另立副本：闭集改档时字面量副本会静默失效（QA D-4）。

#: 方向 → 画像线索关键词。**下标与 `rules.DIRECTIONS` 逐位对齐**，方向名本身不重复列出
#: （`_affinity()` 里「方向名直接命中画像线索」另得 3 分）。方向闭集只在 `rules.py`，
#: 这里是相关度打分的词表，不是第二份闭集。
DIRECTION_KEYWORDS: tuple[tuple[str, ...], ...] = (
    ("react", "vue", "angular", "typescript", "javascript", "css", "浏览器", "组件", "hook"),
    (
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
    ("算法", "数据结构", "复杂度", "动态规划", "leetcode", "红黑树", "堆"),
    ("操作系统", "网络", "linux", "git", "编译", "内存", "进程", "线程"),
    (
        "ai",
        "rag",
        "agent",
        "llm",
        "大模型",
        "embedding",
        "向量",
        "prompt",
        "提示词",
        "检索增强",
        "微调",
        "多模态",
        "langchain",
        "智能体",
        "function calling",
        "工具调用",
    ),
)


@dataclass(frozen=True)
class Paper:
    """一次组卷的结果：入选题目（含 `answer`，只落 `runs.payload`）+ 透明度计数。

    `stage` 是命中的阶梯层号（`'L1'`..`'L6'`，与 `rules.PAPER_STAGES` 逐字一致，**永不为 None**）；
    `filtered_count` 是净过滤数；`backfill` 是三层回池计数（见模块 docstring）。
    """

    questions: list[dict[str, Any]]
    stage: str
    filtered_count: int
    backfill: dict[str, int]


# --- 相关度与排序 ----------------------------------------------------------


def _profile_tokens(profile: Profile) -> list[str]:
    """画像 → 打分线索：`tech_stack` 各项 + `target_role`，统一小写去空白。"""
    tokens = [
        str(item).strip().lower() for item in (profile.tech_stack or []) if str(item).strip()
    ]
    role = str(profile.target_role or "").strip().lower()
    if role:
        tokens.append(role)
    return tokens


def _keywords_for(direction: str) -> tuple[str, ...]:
    """方向 → 关键词（未知方向返回空元组：脏标签只少打分，绝不抛异常）。"""
    for index, known in enumerate(rules.DIRECTIONS):
        if known == direction:
            return DIRECTION_KEYWORDS[index] if index < len(DIRECTION_KEYWORDS) else ()
    return ()


def _affinity(question: dict[str, Any], tokens: list[str]) -> int:
    """方向相关度：方向名直接出现在画像线索里得 3 分，命中关键词各得 1 分（可累加）。"""
    direction = str(question.get("direction") or "").strip().lower()
    if not direction:
        return 0
    score = 3 if any(direction in token for token in tokens) else 0
    return score + sum(
        1 for keyword in _keywords_for(direction) if any(keyword in token for token in tokens)
    )


def _difficulty_of(question: dict[str, Any]) -> str:
    """难度档（脏值兜底到闭集首档 `basic`：难度只影响「挑战题」占比判定）。"""
    value = str(question.get("difficulty") or "").strip()
    return value if value in rules.DIFFICULTIES else rules.DIFFICULTIES[0]


def _difficulty_rank(difficulty: str) -> int:
    """难度档在闭集里的下标（basic < intermediate < challenge），桶排序用。"""
    try:
        return rules.DIFFICULTIES.index(difficulty)
    except ValueError:
        return 0


def rank_pool(
    questions: Iterable[dict[str, Any]],
    profile: Profile,
    rng: random.Random | None = None,
) -> list[dict[str, Any]]:
    """(相关度, 难度档) 分桶 → **桶内**随机 → 桶序稳定（相关度降序、难度升序）。

    随机只发生在桶内：同相关度、同难度档的候选等概率走到前面（AC-9 的「随机限同相关度同
    难度档」），而题量 / 客观题数 / 挑战题占比 / 方向覆盖与随机顺序无关（闸门在 `build_paper()`）。
    `rng` 可注入：测试传 `random.Random(seed)` 即可复现；生产传 `None` → 新建随机源。
    """
    shuffler = random.Random() if rng is None else rng
    tokens = _profile_tokens(profile)
    buckets: dict[tuple[int, str], list[dict[str, Any]]] = {}
    for question in questions:
        if not isinstance(question, dict):
            continue
        buckets.setdefault((_affinity(question, tokens), _difficulty_of(question)), []).append(
            question
        )
    ranked: list[dict[str, Any]] = []
    for key in sorted(buckets, key=lambda item: (-item[0], _difficulty_rank(item[1]))):
        bucket = buckets[key]
        shuffler.shuffle(bucket)
        ranked.extend(bucket)
    return ranked


# --- 结构闸门（唯一校验点）-------------------------------------------------


def _is_challenge(question: dict[str, Any]) -> bool:
    """挑战题判定（`difficulty` 闭集在 `rules`，读侧兜底在 `_difficulty_of`）。"""
    return rules.is_challenge_difficulty(_difficulty_of(question))


def _challenge_count(questions: Sequence[dict[str, Any]]) -> int:
    return sum(1 for question in questions if _is_challenge(question))


def _objective_count(questions: Sequence[dict[str, Any]]) -> int:
    """组卷侧客观题计数口径 = `rules.is_exam_objective_kind()`（客观题闭集 − 降级开关）。

    与取池口径必须同一份，否则 `EXAM_EXCLUDED_KINDS=("judge",)` 只把题挪出池子、却仍按
    「含 judge」的分母校验：开关拨了一半（D2 的教训）。
    """
    return sum(
        1 for question in questions if rules.is_exam_objective_kind(str(question.get("kind") or ""))
    )


def _direction_count(questions: Sequence[dict[str, Any]]) -> int:
    """覆盖的方向数（**空方向不计**：脏标签既不算覆盖，也不会把 L5 的「≥1」蒙过去）。"""
    directions = {
        str(question.get("direction") or "").strip()
        for question in questions
        if str(question.get("direction") or "").strip()
    }
    return len(directions)


def _spread_by_direction(
    questions: Sequence[dict[str, Any]], require_directions: int
) -> list[dict[str, Any]]:
    """方向轮转（**仅在池子允许时**）：按方向首次出现的顺序轮流取题，方向内部保持原顺序。

    为什么取题必须主动分散（而不是「按序取前 8 道再校验方向」）：`rank_pool()` 的相关度是
    **严格排序**的 —— 画像命中的方向整桶排在前面，因此按序取足够多的客观题时，一取就取满
    同一方向（r1 时代确实如此：当时根本没有方向覆盖要求）。r6 把「池子允许时 ≥2 个方向」
    变成结构约束后，若取题不分散，L1–L4 的方向校验永远失败、每份卷都掉到 L5，
    熟练度过滤（AC-6/AC-7）随之失效。这是本模块对 TECHNICAL §4.4 的**唯一实作补充**，
    语义完全落在「池子允许时」这句话里：方向数不足 `require_directions` 时保持原序，
    该层照样过不了校验，由阶梯换池重试（L5 → 1，L6 → 0）。
    """
    if require_directions <= 0:
        return list(questions)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for question in questions:
        grouped.setdefault(str(question.get("direction") or "").strip(), []).append(question)
    if not grouped or len([key for key in grouped if key]) < require_directions:
        return list(questions)
    spread: list[dict[str, Any]] = []
    for index in range(max(len(bucket) for bucket in grouped.values())):
        for bucket in grouped.values():
            if index < len(bucket):
                spread.append(bucket[index])
    return spread


def _prefer_kind_diversity(questions: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """把**每种可用客观题型各提一道到队首**，其余保持原序（题型可达性的唯一出口）。

    为什么必须有这一步：`_spread_by_direction()` 只做方向轮转，而轮转出来的队首全是
    各方向相关度最高、难度最低的题 —— r11 的判断题全落在 intermediate/challenge 档，
    8 个客观题额度在 basic 档就被用尽，于是「判断题进制」在卷面上**结构不可达**（QA D1：
    30 卷 300 题 0 道 judge）。题型覆盖必须显式写在取题顺序里，而不是指望难度分布恰好帮忙。

    代表题优先取**非挑战题**（挑战额度由 `_fit_structure()` 裁决，代表题不该去挤它）；
    某题型只有挑战题时仍补一道代表 —— 否则该题型在新数据下会静默消失。
    """
    remaining = list(questions)
    head: list[dict[str, Any]] = []
    covered: set[str] = set()
    for question in remaining:
        kind = str(question.get("kind") or "")
        if not kind or kind in covered or _is_challenge(question):
            continue
        covered.add(kind)
        head.append(question)
    for question in remaining:
        kind = str(question.get("kind") or "")
        if not kind or kind in covered:
            continue
        covered.add(kind)
        head.append(question)
    head_ids = {id(question) for question in head}
    return head + [question for question in remaining if id(question) not in head_ids]


def _fit_structure(
    picked: list[dict[str, Any]],
    pool: list[dict[str, Any]],
    *,
    require_directions: int,
    max_count: int,
) -> list[dict[str, Any]] | None:
    """把挑战题压回 ≤20% 后做**最终结构校验**（四个约束的唯一校验点）。"""
    selected = picked[:max_count]
    excess = _challenge_count(selected) - rules.max_challenge_count(len(selected))
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
            question_id = str(question.get("id") or "")
            if not question_id or question_id in taken or _is_challenge(question):
                continue
            trimmed.append(question)
            taken.add(question_id)
        selected = trimmed[:max_count]
    if not rules.MIN_EXAM_QUESTIONS <= len(selected) <= max_count:
        return None
    if _objective_count(selected) < rules.MIN_OBJECTIVE_QUESTIONS:
        return None
    if _challenge_count(selected) > rules.max_challenge_count(len(selected)):
        return None
    if _direction_count(selected) < require_directions:
        return None
    return selected


def build_paper(
    ranked: list[dict[str, Any]],
    *,
    require_directions: int = 2,
    max_count: int | None = None,
) -> list[dict[str, Any]] | None:
    """结构闸门（**唯一一份**）：从已排序候选里拼一份结构达标的卷，达不到返回 `None`。

    新增 `max_count`：覆盖默认上限 12（`rules.MAX_EXAM_QUESTIONS`），不传时逐字节兼容。
    下限由 `rules.MIN_EXAM_QUESTIONS`(10) 硬兜住。
    """
    cap = int(max_count or rules.MAX_EXAM_QUESTIONS)
    challenge_cap = rules.max_challenge_count(rules.MIN_EXAM_QUESTIONS)
    objective = [
        question
        for question in ranked
        if rules.is_exam_objective_kind(str(question.get("kind") or ""))
    ]
    texts = [question for question in ranked if str(question.get("kind") or "") == rules.TEXT_KIND]
    objective_order = _spread_by_direction(objective, require_directions)
    objective_order = _prefer_kind_diversity(objective_order)

    picked: list[dict[str, Any]] = []
    seen: set[str] = set()

    def take(pool: list[dict[str, Any]], need: int) -> int:
        taken = 0
        for question in pool:
            if taken >= need:
                break
            question_id = str(question.get("id") or "")
            if not question_id or question_id in seen:
                continue
            if _is_challenge(question) and _challenge_count(picked) >= challenge_cap:
                continue
            picked.append(question)
            seen.add(question_id)
            taken += 1
        return taken

    if take(objective_order, rules.MIN_OBJECTIVE_QUESTIONS) < rules.MIN_OBJECTIVE_QUESTIONS:
        return None
    take(texts, rules.MIN_EXAM_QUESTIONS - len(picked))
    if len(picked) < rules.MIN_EXAM_QUESTIONS:
        take(objective_order, rules.MIN_EXAM_QUESTIONS - len(picked))
    if len(picked) < rules.MIN_EXAM_QUESTIONS:
        return None
    return _fit_structure(picked, ranked, require_directions=require_directions, max_count=cap)


# --- 6 层兜底阶梯（唯一实现）-----------------------------------------------


def _counts(must_know: int = 0, other: int = 0, history: int = 0) -> dict[str, int]:
    """三层回池计数的唯一形状出处（payload 的 `backfill` 就长这样）。"""
    return {"must_know": must_know, "other": other, "history": history}


def _filtered_count(proficient_hits: set[str], picked: Sequence[dict[str, Any]]) -> int:
    """**净过滤数** = `|熟练 ∩ 可用| − |熟练 ∩ 本卷|`（恒 ≥ 0），语义唯一出处。

    L2/L3 会把熟练题放回卷面；那些题既然已经在卷面里，就**不算**「本次已过滤」——否则页面
    文案「本次已过滤 N 道你已熟练掌握的题」会与卷面自相矛盾（TECHNICAL §4.3）。
    """
    picked_ids = {str(question.get("id") or "") for question in picked}
    return max(len(proficient_hits) - len(proficient_hits & picked_ids), 0)


def select_paper(
    questions: Iterable[dict[str, Any]],
    profile: Profile,
    *,
    proficient: set[str],
    recent: list[set[str]],
    rng: random.Random | None = None,
    direction: str | None = None,
    difficulty: str | Sequence[str] | None = None,
    target_count: int | None = None,
) -> Paper | None:
    """L1→L6 逐层换池建卷，返回命中的 `Paper`；**只有 L6 也不足**才返回 `None`（调用方 400）。

    新增三个可选筛选参数：`direction` / `difficulty` / `target_count`。传入时在每层 attempt
    内部对候选池先做硬过滤再组卷，保持 6 层阶梯顺序不变；`target_count` 同时影响
    `build_paper()` 的上限（默认 12），下限由 `rules.MIN_EXAM_QUESTIONS` 硬兜住。
    不传三个参数 → 行为与改造前逐字节一致（向后兼容）。
    """
    available = [
        question
        for question in questions
        if isinstance(question, dict) and str(question.get("id") or "").strip()
    ]
    by_id = {str(question["id"]): question for question in available}
    known = set(by_id)

    # --- 全局硬过滤（方向 / 难度）：作用于 6 层阶梯共享的 `known` 集合 -------------------
    difficulty_set: set[str] | None = None
    if difficulty is not None:
        if isinstance(difficulty, str):
            difficulty_set = {difficulty}
        else:
            difficulty_set = {str(item) for item in difficulty if str(item).strip()}
    if direction is not None:
        direction = direction.strip() or None
    if direction is not None or difficulty_set is not None:
        known = {
            question_id
            for question_id in known
            if (direction is None or str(by_id[question_id].get("direction") or "").strip() == direction)
            and (
                difficulty_set is None
                or str(by_id[question_id].get("difficulty") or "").strip() in difficulty_set
            )
        }
        if not known:
            return None

    proficient_hits = {question_id for question_id in known if question_id in proficient}
    must_know_hits = {
        question_id
        for question_id in proficient_hits
        if rules.essentiality_of(by_id[question_id]) == rules.MUST_KNOW
    }
    other_hits = proficient_hits - must_know_hits
    papers = [set(item) & known for item in recent]
    papers = [item for item in papers if item]
    oldest_first = list(reversed(papers))
    recent_ids = set().union(*papers) if papers else set()

    # --- 题量上限：默认 12；target_count 传上来时 clamp 到 [10, 20] -------------------------
    if target_count is not None:
        target_count = max(rules.MIN_EXAM_QUESTIONS, min(20, int(target_count)))

    def attempt(
        stage: str, ids: set[str], backfill: dict[str, int], require_directions: int
    ) -> Paper | None:
        ranked = rank_pool([by_id[question_id] for question_id in sorted(ids)], profile, rng=rng)
        picked = build_paper(
            ranked,
            require_directions=require_directions,
            max_count=target_count,
        )
        if picked is None:
            return None
        return Paper(
            questions=picked,
            stage=stage,
            filtered_count=_filtered_count(proficient_hits, picked),
            backfill=backfill,
        )

    # L1：全库 − 熟练 − 近 N 卷（首选层；方向 ≥2）
    base = known - proficient_hits - recent_ids
    paper = attempt("L1", base, _counts(), 2)
    if paper is not None:
        return paper

    # L2：放回「熟练 ∩ must_know」
    l2 = base | must_know_hits
    paper = attempt("L2", l2, _counts(must_know=len(must_know_hits)), 2)
    if paper is not None:
        return paper

    # L3：再放回其余熟练题
    l3 = l2 | other_hits
    paper = attempt(
        "L3", l3, _counts(must_know=len(must_know_hits), other=len(other_hits)), 2
    )
    if paper is not None:
        return paper

    # L4：历史卷从最旧一卷起逐卷放回
    l4 = set(l3)
    for paper_ids in oldest_first:
        l4 |= paper_ids
        paper = attempt(
            "L4",
            l4,
            _counts(len(must_know_hits), len(other_hits), len(l4 - l3)),
            2,
        )
        if paper is not None:
            return paper

    full = _counts(len(must_know_hits), len(other_hits), len(recent_ids))
    # L5：全库，方向覆盖放宽到 ≥1
    paper = attempt("L5", known, full, 1)
    if paper is not None:
        return paper

    # L6：全库，连方向覆盖都不再要求
    return attempt("L6", known, full, 0)
