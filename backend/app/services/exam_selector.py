"""组卷选池 / 随机化 / 6 层兜底阶梯（r6 · TECHNICAL §4，**唯一实现**）。

`exam.py` 退回纯编排（读库 → 调本模块 → 落 payload）；本模块承担三件事，每件事只有一份实现：

1. `rank_pool()` —— 相关度（画像 `tech_stack` / `target_role` 命中的方向）分桶、(相关度, 难度档)
   成桶，**只在桶内**用注入的 `rng` 洗牌，桶序稳定（相关度降序、难度升序）。因此「随机」永远
   不会把结构随机掉：题量 / 客观题数 / 挑战题占比 / 方向覆盖由 `build_paper()` 这一个校验点兜住
   （AC-9 的「随机限同相关度同难度档」与「结构约束恒定成立」同时成立）。
2. `build_paper()` —— 结构闸门（原 `exam.py` 的 `_compose` + `_respect_challenge_cap` 合并搬迁，
   `exam.py` 不再保留第二份）。10–12 题 / 客观 ≥8 / 挑战 ≤20% / 方向 ≥ `require_directions`，
   任一条不满足返回 `None`（换池重试，**不是异常**，因此任何一层都不会因过滤 400）。
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

from ..schemas import Profile
from . import rules

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
    return sum(
        1 for question in questions if rules.is_objective_kind(str(question.get("kind") or ""))
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


def _fit_structure(
    picked: list[dict[str, Any]],
    pool: list[dict[str, Any]],
    *,
    require_directions: int,
) -> list[dict[str, Any]] | None:
    """把挑战题压回 ≤20% 后做**最终结构校验**（四个约束的唯一校验点）。

    压缩策略与 r1/r5 逐字一致：超额的挑战题按顺序丢弃，再用非挑战题从池子里补回题量下限
    （补题不会再引入挑战题，所以压缩结果稳定）。
    """
    selected = picked[: rules.MAX_EXAM_QUESTIONS]
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
        selected = trimmed[: rules.MAX_EXAM_QUESTIONS]
    if not rules.MIN_EXAM_QUESTIONS <= len(selected) <= rules.MAX_EXAM_QUESTIONS:
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
) -> list[dict[str, Any]] | None:
    """结构闸门（**唯一一份**）：从已排序候选里拼一份结构达标的卷，达不到返回 `None`。

    组卷口径与 r1/r5 逐字一致：先取 `MIN_OBJECTIVE_QUESTIONS`(8) 道客观题 → 用 `text` 补到
    `MIN_EXAM_QUESTIONS`(10) → 仍不足再用客观题补（题量优先于题型配比，但保住客观 ≥8 的分母）
    → 挑战题压回 `ceil(题数 × 20%)`。所有阈值来自 `rules.py`，本文件不写魔数。
    去重键是题目 `id`（`seen`），因此**卷内不重复在任何一层都恒成立**。
    """
    objective = [
        question
        for question in ranked
        if rules.is_objective_kind(str(question.get("kind") or ""))
    ]
    texts = [question for question in ranked if str(question.get("kind") or "") == rules.TEXT_KIND]
    # 客观题按方向轮转取（池子允许时），否则相关度排序会把卷子压成单一方向 —— 见
    # `_spread_by_direction()` 的说明；方向不足时原序，由阶梯换池重试。
    objective_order = _spread_by_direction(objective, require_directions)

    picked: list[dict[str, Any]] = []
    seen: set[str] = set()
    # 试卷按 MIN_EXAM_QUESTIONS 题规划，挑战题额度因此按 10 题算；总量扩到 12 题时额度只会更宽。
    cap = rules.max_challenge_count(rules.MIN_EXAM_QUESTIONS)

    def take(pool: list[dict[str, Any]], need: int) -> int:
        taken = 0
        for question in pool:
            if taken >= need:
                break
            question_id = str(question.get("id") or "")
            if not question_id or question_id in seen:
                continue
            if _is_challenge(question) and _challenge_count(picked) >= cap:
                continue
            picked.append(question)
            seen.add(question_id)
            taken += 1
        return taken

    if take(objective_order, rules.MIN_OBJECTIVE_QUESTIONS) < rules.MIN_OBJECTIVE_QUESTIONS:
        return None  # 客观题不足 8 道：判分分母不成立，这一层直接放弃（换池重试，不抛异常）
    take(texts, rules.MIN_EXAM_QUESTIONS - len(picked))
    if len(picked) < rules.MIN_EXAM_QUESTIONS:
        take(objective_order, rules.MIN_EXAM_QUESTIONS - len(picked))
    if len(picked) < rules.MIN_EXAM_QUESTIONS:
        return None
    return _fit_structure(picked, ranked, require_directions=require_directions)


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
) -> Paper | None:
    """L1→L6 逐层换池建卷，返回命中的 `Paper`；**只有 L6 也不足**才返回 `None`（调用方 400）。

    `proficient` 是熟练题 id 集合（`proficiency.proficient_ids()` 的结论），`recent` 是近 N 卷
    题 id 的 **newest-first** 列表（`repository.list_recent_exam_question_ids()` 的口径）。
    层序与每层回池来源写死在下方注释里，**不可重排**；每层都复用同一个 `rank_pool()` +
    `build_paper()`，因此任何一层都不会因过滤而 400。
    """
    available = [
        question
        for question in questions
        if isinstance(question, dict) and str(question.get("id") or "").strip()
    ]
    by_id = {str(question["id"]): question for question in available}
    known = set(by_id)
    proficient_hits = {question_id for question_id in known if question_id in proficient}
    must_know_hits = {
        question_id
        for question_id in proficient_hits
        if rules.essentiality_of(by_id[question_id]) == rules.MUST_KNOW
    }
    other_hits = proficient_hits - must_know_hits
    # `recent` 是 newest-first；L4 要**从最旧一卷起**逐卷放松，所以先摆成 oldest-first。
    papers = [set(item) & known for item in recent]
    papers = [item for item in papers if item]
    oldest_first = list(reversed(papers))
    recent_ids = set().union(*papers) if papers else set()

    def attempt(
        stage: str, ids: set[str], backfill: dict[str, int], require_directions: int
    ) -> Paper | None:
        # `sorted(ids)` 让「唯一随机源是 rng」成立：集合的迭代顺序不参与洗牌前顺序。
        ranked = rank_pool([by_id[question_id] for question_id in sorted(ids)], profile, rng=rng)
        picked = build_paper(ranked, require_directions=require_directions)
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

    # L2：放回「熟练 ∩ must_know」（必备题同样被过滤，只有兜底时才回流，AC-6）
    l2 = base | must_know_hits
    paper = attempt("L2", l2, _counts(must_know=len(must_know_hits)), 2)
    if paper is not None:
        return paper

    # L3：再放回其余熟练题（advanced / nice_to_know）
    l3 = l2 | other_hits
    paper = attempt(
        "L3", l3, _counts(must_know=len(must_know_hits), other=len(other_hits)), 2
    )
    if paper is not None:
        return paper

    # L4：历史卷**从最旧一卷起**逐卷放回，停在第一个能建卷的子步骤（stage 统一记 'L4'）
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
    # L5：全库（忽略熟练与历史），方向覆盖放宽到 ≥1（题量优先于方向纯度，承接 r1 口径）
    paper = attempt("L5", known, full, 1)
    if paper is not None:
        return paper

    # L6：全库，连方向覆盖都不再要求；到这里仍凑不出，才由调用方 400（唯一 400 出口，AC-8）
    return attempt("L6", known, full, 0)
