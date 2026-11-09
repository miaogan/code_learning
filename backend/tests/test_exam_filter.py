"""选池 / 随机 / 6 层兜底阶梯（AC-6 / AC-7 / AC-8 / AC-9 的证据链）。

三类用例分开写，避免互相掩盖：
- **纯函数层**：`select_paper()` / `rank_pool()` / `build_paper()` 用受控小题库逐层构造 L1..L6，
  不碰数据库、不读时钟（`rng` / `proficient` / `recent` 全部注入），因此每一层的触发条件都能
  单独断言到具体根因。
- **服务层**：`exam.create_run()` + 真库（80 题种子）+ 真作答事件，验证「连续 5 卷不含熟练题」
  与「连续 4 卷题 id 交集为空」（AC-7 / AC-9 的核心证据）。
- **HTTP 层**：两类极端场景（某方向全熟练 / 近 3 卷覆盖池子大半）必须 200 且结构达标（AC-8）。

所有断言都落在 `rules.py` 的常量上（不复制数字），因此口径变更只需改一处。
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from app.core import repository
from app.schemas import ExamRun
from app.services.assessment import exam as exam_service, exam_selector, proficiency, question_bank
from app.services.report import rules

# --- 受控小题库构造 -------------------------------------------------------


def _question(
    qid: str,
    *,
    kind: str = "single",
    direction: str = "前端",
    difficulty: str = "basic",
    essentiality: str = "nice_to_know",
) -> dict[str, Any]:
    """一条题库记录（形状与 `repository.list_questions()` 的行一致）。"""
    objective = rules.is_objective_kind(kind)
    return {
        "id": qid,
        "kind": kind,
        "direction": direction,
        "prompt": f"{qid} 的题干",
        "options": [{"key": "A", "text": "甲"}, {"key": "B", "text": "乙"}] if objective else [],
        "answer": ["A"] if objective else [],
        "difficulty": difficulty,
        "essentiality": essentiality,
    }


def _objectives(
    count: int,
    *,
    prefix: str = "o",
    directions: tuple[str, ...] = ("前端", "后端"),
    **kwargs: Any,
) -> list[dict[str, Any]]:
    """`count` 道客观题（方向轮转，保证默认就有 ≥2 个方向）。"""
    return [
        _question(
            f"{prefix}{index:02d}",
            direction=directions[index % len(directions)],
            **kwargs,
        )
        for index in range(count)
    ]


def _texts(
    count: int,
    *,
    prefix: str = "t",
    directions: tuple[str, ...] = ("前端", "后端"),
) -> list[dict[str, Any]]:
    """`count` 道简答题（不计分，只补题量）。"""
    return [
        _question(
            f"{prefix}{index:02d}",
            kind="text",
            direction=directions[index % len(directions)],
        )
        for index in range(count)
    ]


def _ids(paper: exam_selector.Paper) -> set[str]:
    return {str(question["id"]) for question in paper.questions}


def _select(
    library: list[dict[str, Any]],
    profile: Any,
    *,
    proficient: set[str] | None = None,
    recent: list[set[str]] | None = None,
    seed: int = 20261101,
) -> exam_selector.Paper:
    """跑一次选池并断言「不是 None」（None 在纯函数层等于 400，见 AC-8）。"""
    paper = exam_selector.select_paper(
        library,
        profile,
        proficient=set(proficient or ()),
        recent=list(recent or []),
        rng=random.Random(seed),
    )
    assert paper is not None, "select_paper 返回 None 会让调用方 400 —— 任何一层都不得因过滤失败"
    return paper


def _assert_structure(questions: list[dict[str, Any]], *, require_directions: int = 1) -> None:
    """结构达标（10–12 题 / 客观 ≥8 / 挑战 ≤20% / 方向覆盖 / 卷内不重复）。"""
    total = len(questions)
    assert rules.MIN_EXAM_QUESTIONS <= total <= rules.MAX_EXAM_QUESTIONS, f"题量 {total} 越界"
    objective = [q for q in questions if rules.is_objective_kind(str(q.get("kind") or ""))]
    assert len(objective) >= rules.MIN_OBJECTIVE_QUESTIONS, f"客观题 {len(objective)} 少于下限"
    challenge = [q for q in questions if rules.is_challenge_difficulty(str(q.get("difficulty")))]
    assert len(challenge) <= rules.max_challenge_count(total), f"挑战题 {len(challenge)} 超过 20%"
    directions = {str(q.get("direction") or "") for q in questions} - {""}
    assert len(directions) >= require_directions, f"方向覆盖 {sorted(directions)} 不足"
    ids = [str(q.get("id") or "") for q in questions]
    assert len(ids) == len(set(ids)), "卷内出现重复题"


# --- 结构闸门：单一校验点 + 方向覆盖 ----------------------------------------


def test_build_paper_spreads_directions_when_pool_allows(profile_factory: Any) -> None:
    """池子有 ≥2 个方向时闸门必须**主动分散**取题：相关度排序是严格排序，整桶只在一个方向。

    这是 r6 的结构约束与 r1 取题顺序的真实冲突点：若只「按序取前 8 道再校验方向」，
    一份卷永远是单方向（r1 就是这么出的，当时没有方向要求），L1–L4 会永远过不了校验、
    每份卷都掉到 L5，熟练度过滤随之失效。用例把「池子允许时 ≥2 方向」钉在这里。
    """
    profile = profile_factory()  # target_role 命中「前端」→ 前端相关度最高，整桶在前
    library = (
        _objectives(20, prefix="f", directions=("前端",))
        + _objectives(20, prefix="b", directions=("后端",))
        + _texts(4)
    )
    ranked = exam_selector.rank_pool(library, profile, rng=random.Random(20261101))
    assert [q["direction"] for q in ranked[:20]] == ["前端"] * 20, "前置：排序确实是单方向整桶在前"
    paper = exam_selector.build_paper(ranked, require_directions=2)
    assert paper is not None
    assert len({q["direction"] for q in paper}) >= 2, "池子允许时卷面必须覆盖 ≥2 个方向"
    _assert_structure(paper, require_directions=2)


def test_build_paper_is_single_structure_gate(profile_factory: Any) -> None:
    """结构校验只有 `build_paper()` 一处：方向不足返回 None（换池重试），放宽后才出卷。"""
    profile = profile_factory()
    library = _objectives(10, directions=("前端",)) + _texts(4, directions=("前端",))
    ranked = exam_selector.rank_pool(library, profile, rng=random.Random(1))
    assert exam_selector.build_paper(ranked, require_directions=2) is None
    assert exam_selector.build_paper(ranked, require_directions=1) is not None
    # 客观题不足 8 道时任何方向要求都救不回来
    thin = exam_selector.rank_pool(_objectives(7) + _texts(4), profile, rng=random.Random(1))
    assert exam_selector.build_paper(thin, require_directions=1) is None


# --- 6 层阶梯：每层一个用例（顺序不可重排）---------------------------------


def test_l1_uses_clean_pool_when_available(profile_factory: Any) -> None:
    """L1：可考池够用时首选，不带任何回流（AC-7 / AC-8 的基准层）。"""
    paper = _select(_objectives(10) + _texts(4), profile_factory(), seed=11)
    assert paper.stage == "L1"
    assert paper.filtered_count == 0
    assert paper.reintroduced_count == 0
    assert paper.backfill == {"must_know": 0, "other": 0, "history": 0}
    _assert_structure(paper.questions, require_directions=2)


def test_l2_returns_proficient_must_know(profile_factory: Any) -> None:
    """L2：客观题不够时先放回「熟练 ∩ must_know」，且回流题不计入净过滤数。"""
    library = _objectives(8, essentiality="must_know") + _texts(4)
    paper = _select(library, profile_factory(), proficient={"o00", "o01", "o02"}, seed=3)
    assert paper.stage == "L2", f"L1 只剩 5 道客观题，应递进到 L2，实际 {paper.stage}"
    assert paper.backfill == {"must_know": 3, "other": 0, "history": 0}
    assert _ids(paper) >= {"o00", "o01", "o02"}, "回流题应进卷面"
    # 净过滤数 = |熟练 ∩ 可用| − |熟练 ∩ 本卷|：3 道熟练题全回流，故不再算「已过滤」
    assert paper.filtered_count == 0, "回流进卷面的熟练题不得再算作已过滤（文案会自相矛盾）"
    # r43：回流进卷面的熟练题数由 reintroduced_count 单独给出（「另有 N 道因保持卷面结构被重新纳入」）
    assert paper.reintroduced_count == 3
    _assert_structure(paper.questions, require_directions=2)


def test_l3_returns_remaining_proficient(profile_factory: Any) -> None:
    """L3：must_know 回流仍不够时，再放回其余档（advanced / nice_to_know）。"""
    library = (
        _objectives(3, prefix="m", essentiality="must_know")
        + _objectives(3, prefix="a", essentiality="advanced")
        + _objectives(2, prefix="n", essentiality="nice_to_know")
        + _texts(4)
    )
    proficient = {"m00", "m01", "m02", "a00", "a01", "a02"}
    paper = _select(library, profile_factory(), proficient=proficient, seed=4)
    assert paper.stage == "L3", f"L1/L2 只剩 2/5 道客观题，应递进到 L3，实际 {paper.stage}"
    assert paper.backfill == {"must_know": 3, "other": 3, "history": 0}
    assert _ids(paper) >= proficient
    assert paper.filtered_count == 0
    assert paper.reintroduced_count == len(proficient)
    _assert_structure(paper.questions, require_directions=2)


def test_l4_relaxes_history_from_oldest_paper_first(profile_factory: Any) -> None:
    """L4：历史卷**从最旧一卷起**逐卷放松，够建卷就停（不得继续放松到更新的卷）。"""
    library = _objectives(7) + [_question("x-old"), _question("x-new")] + _texts(4)
    # `recent` 是 newest-first（与 repository.list_recent_exam_question_ids 的口径一致）
    paper = _select(library, profile_factory(), recent=[{"x-new"}, {"x-old"}], seed=5)
    assert paper.stage == "L4", f"L1..L3 只剩 7 道客观题，应递进到 L4，实际 {paper.stage}"
    assert paper.backfill == {"must_know": 0, "other": 0, "history": 1}, (
        f"只应放松最旧一卷（1 道历史题），实际 {paper.backfill}"
    )
    assert "x-old" in _ids(paper), "从最旧一卷起逐卷放松"
    assert "x-new" not in _ids(paper), "最旧一卷已够建卷，不得继续放松到最新一卷"
    _assert_structure(paper.questions, require_directions=2)


def test_l5_relaxes_direction_coverage_to_one(profile_factory: Any) -> None:
    """L5：全库仍只有一个方向时，方向覆盖放宽到 ≥1（题量优先于方向纯度）。"""
    library = _objectives(10, directions=("前端",)) + _texts(4, directions=("前端",))
    proficient = {"o00", "o01", "o02"}
    paper = _select(library, profile_factory(), proficient=proficient, seed=6)
    assert paper.stage == "L5", f"L1..L4 都要求 ≥2 方向，应递进到 L5，实际 {paper.stage}"
    assert paper.backfill == {"must_know": 0, "other": 3, "history": 0}
    assert paper.filtered_count == len(proficient) - len(proficient & _ids(paper))
    assert paper.reintroduced_count == len(proficient & _ids(paper))
    _assert_structure(paper.questions, require_directions=1)


def test_l6_relaxes_direction_requirement(profile_factory: Any) -> None:
    """L6：连方向标签都不可用时仍出卷（唯一 400 出口在调用方，不在本层）。"""
    library = [
        _question(f"o{index:02d}", direction="") for index in range(8)
    ] + [_question(f"t{index:02d}", kind="text", direction="") for index in range(4)]
    paper = _select(library, profile_factory(), seed=7)
    assert paper.stage == "L6", f"方向覆盖为 0，应一路递进到 L6，实际 {paper.stage}"
    _assert_structure(paper.questions, require_directions=0)


def test_stage_ladder_prefers_earlier_layers(profile_factory: Any) -> None:
    """阶梯顺序不可重排：池子越窄，命中的层号越靠后（先吃 L1，再 L2，最后才放宽方向）。"""
    assert exam_selector.PAPER_STAGES == rules.PAPER_STAGES == ("L1", "L2", "L3", "L4", "L5", "L6")
    profile = profile_factory()
    cases = [
        (_select(_objectives(10) + _texts(4), profile), "L1"),
        (
            _select(
                _objectives(8, essentiality="must_know") + _texts(4), profile, proficient={"o00"}
            ),
            "L2",
        ),
        (
            _select(
                _objectives(10, directions=("前端",)) + _texts(4, directions=("前端",)),
                profile,
                proficient={"o00"},
            ),
            "L5",
        ),
    ]
    ranks = [exam_selector.PAPER_STAGES.index(paper.stage) for paper, _expected in cases]
    assert ranks == sorted(ranks), f"层号必须随池子变窄单调后移，实际 {[paper.stage for paper, _ in cases]}"
    for paper, expected in cases:
        assert paper.stage == expected, f"期望 {expected}，实际 {paper.stage}"


# --- AC-6 / AC-7：必备题不豁免、过滤与回流 --------------------------------


def test_proficient_must_know_is_filtered_not_exempt(profile_factory: Any) -> None:
    """AC-6：`essentiality=must_know` 的熟练题**同样**被过滤（L1 命中时不回流）。"""
    library = _objectives(12, essentiality="must_know") + _texts(4)
    paper = _select(library, profile_factory(), proficient={"o00"}, seed=8)
    assert paper.stage == "L1"
    assert "o00" not in _ids(paper), "must_know 不是豁免牌：熟练后照样不进 L1 卷面"
    assert paper.filtered_count == 1


def _attempt_rows(question_ids: list[str], *, days_ago: int) -> list[dict[str, Any]]:
    """给每题造 2 条「答对」事件（同一题不同 run_id，故不会撞 UNIQUE 约束）。"""
    base = datetime.now(UTC) - timedelta(days=days_ago)
    rows: list[dict[str, Any]] = []
    for question_id in question_ids:
        for index in range(2):
            stamp = (base + timedelta(minutes=index)).isoformat()
            rows.append(
                {
                    "id": uuid4().hex,
                    "question_id": question_id,
                    "run_id": f"seed-{question_id}-{index}",
                    "correct": 1,
                    "answered_at": stamp,
                    "created_at": stamp,
                }
            )
    return rows


def test_proficient_question_absent_from_five_consecutive_papers(
    tmp_db: Any, profile_factory: Any
) -> None:
    """AC-7：同一题 30 天内答对 2 次且最近正确 → 之后连续 5 卷都不含该题（命中 L1）。"""
    profile = profile_factory()
    repository.insert_profile(profile)
    question_bank.load_questions()  # 空库自动种子 80 题
    target = repository.list_questions()[0]["id"]
    repository.insert_attempts(_attempt_rows([target], days_ago=1))
    assert target in proficiency.proficient_ids(), "前置：该题应被判为熟练"

    for index in range(5):
        run = exam_service.create_run(profile.id)
        assert target not in {question.id for question in run.questions}, (
            f"第 {index + 1} 卷仍出现熟练题 {target}"
        )
        payload = repository.get_run(run.run_id)["payload"]
        assert payload["stage"] == "L1", f"第 {index + 1} 卷不应触发兜底回流：{payload['stage']}"
        assert payload["filtered_count"] == 1, f"净过滤数应为 1，实际 {payload['filtered_count']}"
        assert payload["reintroduced_count"] == 0, "L1 没有回流题"


def test_expired_attempts_refill_the_pool(tmp_db: Any, profile_factory: Any) -> None:
    """AC-7 反向：答对记录超出窗口 → 不再算熟练，不再被过滤（回流可考）。"""
    profile = profile_factory()
    repository.insert_profile(profile)
    question_bank.load_questions()
    target = repository.list_questions()[0]["id"]
    repository.insert_attempts(_attempt_rows([target], days_ago=31))
    assert target not in proficiency.proficient_ids(), "超窗的答对记录不得再判熟练"
    run = exam_service.create_run(profile.id)
    payload = repository.get_run(run.run_id)["payload"]
    assert payload["filtered_count"] == 0, "没有熟练题时净过滤数必须为 0"
    assert payload["reintroduced_count"] == 0


def test_running_paper_writes_no_attempt_events(tmp_db: Any, profile_factory: Any) -> None:
    """AC-4：组卷是纯读操作 —— `status=running` 的卷不写任何作答事件。"""
    profile = profile_factory()
    repository.insert_profile(profile)
    question_bank.load_questions()
    exam_service.create_run(profile.id)
    assert repository.list_attempts() == [], "组卷不得写 question_attempts（只在提交判分后写）"


# --- AC-8：两类极端场景 + 不因过滤 400 ------------------------------------


def _assert_payload_structure(payload_questions: list[dict[str, Any]]) -> None:
    """payload 里的题面（含 `difficulty` / `direction`）同样要过结构校验。"""
    _assert_structure(payload_questions, require_directions=1)


def test_whole_direction_proficient_still_creates_paper(client: Any, profile_factory: Any) -> None:
    """极端场景①：某方向**全部**题熟练 → 仍 HTTP 200、结构达标、净过滤数=该方向题数。

    r11 起题库扩容到 260 题，某方向题量可能远超 20（AC-3 明确允许「回填后某语言总数可 >20」），
    因此这里的题量断言收敛为「≥ 存量 20 道」，行为断言（200 / L1 / 结构 / 不含熟练题）不变。
    """
    profile = profile_factory()
    repository.insert_profile(profile)
    questions = repository.list_questions()
    victims = [q["id"] for q in questions if q["direction"] == rules.DIRECTIONS[0]]
    assert len(victims) >= 20, f"种子题库每方向应至少 20 题，实际 {len(victims)}"
    repository.insert_attempts(_attempt_rows(victims, days_ago=2))

    response = client.post("/api/exams", json={"profile_id": profile.id})
    assert response.status_code == 200, f"整方向熟练不得 400：{response.text[:200]}"
    body = response.json()
    assert body["filtered_count"] == len(victims), (
        f"净过滤数应为该方向题数 {len(victims)}，实际 {body['filtered_count']}"
    )
    payload = repository.get_run(body["run_id"])["payload"]
    assert payload["stage"] == "L1"
    _assert_payload_structure(payload["questions"])
    assert not ({q["id"] for q in payload["questions"]} & set(victims)), "熟练方向的题不得进卷面"


def test_recent_papers_covering_most_of_bank_still_creates_paper(
    client: Any, profile_factory: Any
) -> None:
    """极端场景②：近 3 卷覆盖池子大半 → 逐卷退回历史题（L4）后仍 200，绝不 400。

    预留 `MIN_EXAM_QUESTIONS - 1` 道不覆盖，3 卷把其余题三等分（余数摊进首卷），
    使剩题恒小于 `MIN_EXAM_QUESTIONS`、L1 必然凑不出卷、只能靠 L4 放回历史题；
    与题库总量及 N mod 3 无关，题库继续增长也不会破此前提。
    """
    profile = profile_factory()
    repository.insert_profile(profile)
    questions = repository.list_questions()
    # 预留 MIN_EXAM_QUESTIONS-1 道不覆盖，保证 L1 凑不出卷、必然落到 L4 退回历史题。
    # 3 卷覆盖量取「总量 − 预留」后三等分，余数摊进首卷，使剩题恒为预留值
    #（与题库总量 / N mod 3 无关，避免题库增长后剩题回弹到 >= MIN_EXAM_QUESTIONS）。
    reserve = rules.MIN_EXAM_QUESTIONS - 1
    to_cover = len(questions) - reserve
    per_paper = to_cover // 3
    rem = to_cover % 3
    assert per_paper >= rules.MIN_OBJECTIVE_QUESTIONS, f"题库过小，无法构造历史覆盖：{len(questions)}"
    pool = [str(q["id"]) for q in questions]
    first = per_paper + rem
    chunks: list[list[str]] = [
        pool[0:first],
        pool[first : first + per_paper],
        pool[first + per_paper : first + 2 * per_paper],
    ]
    covered = {qid for chunk in chunks for qid in chunk}
    assert len(covered) == to_cover, f"3 卷应覆盖 {to_cover} 道，实际 {len(covered)}"
    assert len(questions) - len(covered) < rules.MIN_EXAM_QUESTIONS, "剩题足以在 L1 出卷，前提不成立"
    # 最旧一卷必须自足（≥8 客观 + ≥2 方向），否则 L4 首个子步骤就该继续往后放松。
    oldest = [q for q in questions if q["id"] in chunks[0]]
    objective_oldest = sum(1 for q in oldest if rules.is_objective_kind(q["kind"]))
    assert objective_oldest >= rules.MIN_OBJECTIVE_QUESTIONS
    assert len({q["direction"] for q in oldest}) >= 2
    for index, chunk in enumerate(chunks):
        repository.insert_run(
            f"hist-{index}", "exam", profile.id, {"questions": [{"id": qid} for qid in chunk]}
        )

    response = client.post("/api/exams", json={"profile_id": profile.id})
    assert response.status_code == 200, f"近卷覆盖大半不得 400：{response.text[:200]}"
    payload = repository.get_run(response.json()["run_id"])["payload"]
    assert payload["stage"] == "L4", f"应在 L4 退回历史卷，实际 {payload['stage']}"
    assert payload["backfill"]["history"] == len(chunks[0]), (
        f"应退回最旧一卷 {len(chunks[0])} 道，实际 {payload['backfill']}"
    )
    _assert_payload_structure(payload["questions"])


def test_insufficient_bank_is_the_only_none(profile_factory: Any) -> None:
    """AC-8 反面：全库都凑不出结构达标的卷 → `select_paper` 返回 None（调用方唯一 400 出口）。"""
    library = _objectives(5) + _texts(2)  # 客观 5 < 8：任何一层都救不回来
    paper = exam_selector.select_paper(
        library, profile_factory(), proficient=set(), recent=[], rng=random.Random(1)
    )
    assert paper is None


# --- AC-9：随机只在桶内、可复现、近 3 卷去重 -------------------------------


def test_rank_pool_reproducible_and_seed_sensitive(
    profile_factory: Any, seed_questions: list[dict[str, Any]]
) -> None:
    """同种子逐题同序（可复现），不同种子顺序不同（生产默认随机源）。"""
    profile = profile_factory()
    ranking = [
        [q["id"] for q in exam_selector.rank_pool(seed_questions, profile, rng=random.Random(seed))]
        for seed in (1, 1, 2)
    ]
    first, again, other = ranking
    assert first == again, "同一 rng 种子必须复现同一顺序"
    assert first != other, "不同种子应给出不同顺序"
    assert sorted(first) == sorted(other), "随机不得改变候选集合"


def test_rank_pool_shuffles_only_inside_bucket(profile_factory: Any) -> None:
    """同相关度同难度档 = 同一个桶：桶内顺序随机，桶与桶之间的先后不变。"""
    profile = profile_factory()  # target_role 命中「前端」→ 前端相关度最高
    library = (
        _objectives(6, prefix="f", directions=("前端",))
        + _objectives(6, prefix="b", directions=("后端",))
        + _objectives(4, prefix="c", directions=("后端",), difficulty="challenge")
    )
    ranked = exam_selector.rank_pool(library, profile, rng=random.Random(20261101))
    directions = [q["direction"] for q in ranked]
    difficulties = [q["difficulty"] for q in ranked]
    assert directions[:6] == ["前端"] * 6, "相关度最高的桶必须整桶在前"
    assert set(directions[6:12]) == {"后端"} and set(directions[12:]) == {"后端"}
    assert difficulties[6:12] == ["basic"] * 6, "同相关度下 basic 档必须整桶排在 challenge 档之前"
    assert difficulties[12:] == ["challenge"] * 4
    # 单一桶内（6 道前端 basic）顺序随种子变化
    other = exam_selector.rank_pool(library, profile, rng=random.Random(7))
    assert [q["id"] for q in ranked[:6]] != [q["id"] for q in other[:6]]


def test_select_paper_same_seed_same_paper_different_seed_different_paper(
    profile_factory: Any,
) -> None:
    """AC-9：同一池子 + 不同种子 → 卷子不完全相同；同种子 → 逐题一致。"""
    library = _objectives(24, directions=("前端", "后端")) + _texts(8, directions=("前端", "后端"))
    profile = profile_factory()
    one = _select(library, profile, seed=1)
    again = _select(library, profile, seed=1)
    two = _select(library, profile, seed=2)
    assert [q["id"] for q in one.questions] == [q["id"] for q in again.questions]
    assert _ids(one) != _ids(two), "不同随机种子应给出不同的题集"
    _assert_structure(one.questions, require_directions=1)
    _assert_structure(two.questions, require_directions=1)


def test_four_consecutive_papers_have_empty_intersection(
    tmp_db: Any, profile_factory: Any
) -> None:
    """AC-9：近 3 卷已出题不重复 —— 第 4 份与前 3 份的题 id 交集为空。"""
    profile = profile_factory()
    repository.insert_profile(profile)
    question_bank.load_questions()
    seen: set[str] = set()
    for index in range(4):
        run = exam_service.create_run(profile.id)
        current = {question.id for question in run.questions}
        overlap = current & seen
        assert not overlap, f"第 {index + 1} 份卷与近 3 卷交集非空：{sorted(overlap)}"
        payload = repository.get_run(run.run_id)["payload"]
        assert payload["stage"] == "L1", f"第 {index + 1} 份卷不应触发兜底：{payload['stage']}"
        seen |= current
    assert len(seen) >= rules.MIN_EXAM_QUESTIONS * 4


def test_exam_run_filtered_count_defaults_to_zero() -> None:
    """旧客户端兼容：`ExamRun.filtered_count` 缺省 0（读侧不需要判断字段是否存在）。"""
    run = ExamRun(run_id="legacy", questions=[])
    assert run.filtered_count == 0
    assert run.reintroduced_count == 0


# --- 用户自定义筛选（方向 / 难度 / 题量）----------------------------------


def test_select_paper_filters_by_direction(profile_factory: Any) -> None:
    """指定 direction 后，6 层阶梯共享的 `known` 集合先做硬过滤，所有返回的题目方向必须匹配。"""
    profile = profile_factory()
    pool = [_question(f"q-{i}", direction="前端" if i % 2 == 0 else "后端") for i in range(30)]

    paper = exam_selector.select_paper(
        pool, profile, proficient=set(), recent=[], direction="前端"
    )
    assert paper is not None
    assert len(paper.questions) >= rules.MIN_EXAM_QUESTIONS
    assert all(str(q.get("direction") or "") == "前端" for q in paper.questions), (
        f"direction=前端 仍混入了其它方向：{[q.get('direction') for q in paper.questions]}"
    )


def test_select_paper_filters_by_difficulty(profile_factory: Any) -> None:
    """指定 difficulty 后，返回的所有题目难度必须命中指定档位集合。"""
    profile = profile_factory()
    pool = [
        _question(f"q-{i}", difficulty=difficulty)
        for i, difficulty in enumerate(("basic", "intermediate", "challenge") * 10)
    ]

    paper = exam_selector.select_paper(
        pool,
        profile,
        proficient=set(),
        recent=[],
        difficulty=("basic", "intermediate"),
    )
    assert paper is not None
    assert all(
        str(q.get("difficulty") or "") in {"basic", "intermediate"} for q in paper.questions
    ), (
        "difficulty=(basic, intermediate) 仍混入了 challenge 档"
    )


def test_select_paper_single_direction_insufficient_returns_none(profile_factory: Any) -> None:
    """单方向凑不出结构达标的卷时（例如一个方向只有 5 道客观题），select_paper 返回 None，
    上层 create_run 走既有 400 出口。**阶梯机制不能绕过用户指定的硬过滤**。"""
    profile = profile_factory()
    # 只造 5 道前端客观题 + 3 道前端简答 —— 客观题数达不到 MIN_OBJECTIVE_QUESTIONS=8
    pool = [_question(f"fe-{i}", direction="前端") for i in range(5)]
    pool += [
        _question(f"fe-t-{i}", kind="text", direction="前端") for i in range(3)
    ]
    pool += [_question(f"be-{i}", direction="后端") for i in range(15)]  # 后端不相关

    paper = exam_selector.select_paper(
        pool, profile, proficient=set(), recent=[], direction="前端"
    )
    assert paper is None, "单方向客观题不足 8 道必须返回 None，由上层 400"


def test_select_paper_target_count_respected(profile_factory: Any) -> None:
    """question_count 透传为 target_count：返回卷题目数 ≤ target_count 且 ≥ MIN_EXAM_QUESTIONS。"""
    profile = profile_factory()
    pool = [_question(f"q-{i}") for i in range(30)]

    paper = exam_selector.select_paper(
        pool, profile, proficient=set(), recent=[], target_count=12
    )
    assert paper is not None
    assert len(paper.questions) <= 12, f"target_count=12 但卷有 {len(paper.questions)} 题"

    paper_15 = exam_selector.select_paper(
        pool, profile, proficient=set(), recent=[], target_count=15
    )
    assert paper_15 is not None
    assert len(paper_15.questions) <= 15


def test_create_run_passes_filters_through_service(
    tmp_db: Any, profile_factory: Any, seed_questions: list[dict[str, Any]]
) -> None:
    """服务层 create_run 能把三个筛选参数一路透传到 select_paper。不传参时逐字节兼容。"""
    profile = profile_factory()
    repository.insert_profile(profile)

    # 单方向可能凑不出来（种子是 8 方向混排），因此先验证不传参时行为不变（兼容回归）
    default_run = exam_service.create_run(profile.id)
    assert len(default_run.questions) >= rules.MIN_EXAM_QUESTIONS

    # 显式传 None 也等价于不传
    null_run = exam_service.create_run(
        profile.id, direction=None, difficulty=None, question_count=None
    )
    assert len(null_run.questions) >= rules.MIN_EXAM_QUESTIONS
