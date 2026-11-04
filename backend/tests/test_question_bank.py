"""题库落库与标签回填（AC-1 / AC-2 / AC-3 的证据链 · TECHNICAL §2.3/§2.4）。

只测**真实种子文件 → 真库**这一条链（`test_exam_filter.py` 用合成小库测选池，不覆盖这里）：

- 幂等迁移（AC-1）：两次 `import_seed()` 后行数恒为种子题量、第二次新增 0；改一行的种子再导入
  **不覆盖**既有行（`ON CONFLICT(id) DO NOTHING`），标签回填只认首次导入那一刻。
- 标签分布（AC-2，**存量 80 题口径**）：四方向各 20、kind 48/20/12、difficulty 全库 60/12/8
  （客观题口径 48/12/8，`challenge` 恰 8）、essentiality 20/20/40、每方向 `must_know`=5 ∈[4,10]
  且覆盖两种 kind、每方向三档皆非空。
- 闭集一致性（AC-3）：种子里的方向 / 难度 / 必备度 / kind 全部落在 `rules.py` 的闭集内，
  数字断言一律引用 `rules` 常量与本地期望表，不另立口径。

口径说明（r11 起）：全库 `basic`=60 是**80 题存量口径**（`single` 48 + `multiple` 12 基础题 +
`text` 12 全部基础）。r11 新增 180 道语言题后，「每方向 20 题」被 AC-3 显式取代（回填后某方向
总数可 >20，且不得为凑 20 删存量题），因此本文件把 r6 的分布断言收敛到 `LEGACY_PREFIXES`
（fe-/be-/al-/cs-）子集：语义不变、口径不再漂移。新增题的分布闸门在
`tests/test_question_bank_quality.py`（每语言 ==20、难度/题型/必备度配额）。
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from app import repository
from app.services import question_bank, rules

#: 全库难度分布（存量 80 题口径）与客观题难度分布（`single`+`multiple` 口径）。
FULL_DIFFICULTY = {"basic": 60, "intermediate": 12, "challenge": 8}
OBJECTIVE_DIFFICULTY = {"basic": 48, "intermediate": 12, "challenge": 8}

#: 四方向各 20；kind 分布；必备度三档 20/20/40（TECHNICAL §2.4）。
EXPECTED_DIRECTION_COUNT = 20
EXPECTED_KINDS = {"single": 48, "multiple": 20, "text": 12}
EXPECTED_ESSENTIALITY = {"must_know": 20, "advanced": 20, "nice_to_know": 40}

#: 原始四方向（存量 260 题覆盖，各 20 道）：r11 起的 staging 来源（AI 工程 / 中间件与运维等）
#: 无存量题，不适用「每方向 == 20 道存量」的结构不变量，故该不变量只收敛到这四个方向。
LEGACY_DIRECTIONS = ("前端", "后端", "算法与数据结构", "计算机基础")

#: 存量题 id 前缀：r6 分布断言的适用范围（r11 起新增题走 `test_question_bank_quality.py`）。
LEGACY_PREFIXES = ("fe-", "be-", "al-", "cs-")


def _seed_rows() -> list[dict[str, Any]]:
    return question_bank.load_seed()


def _legacy_rows(rows: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """只取存量 80 题（fe-/be-/al-/cs-）：r6 的分布口径作用域。"""
    rows = _seed_rows() if rows is None else rows
    return [row for row in rows if str(row["id"]).startswith(LEGACY_PREFIXES)]


def _write_seed(tmp_path: Path, rows: list[dict[str, Any]]) -> Path:
    """把改过的种子写到临时文件，用于验证「重复导入不覆盖」（不碰真实种子）。"""
    path = tmp_path / "questions.json"
    path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    return path


def test_import_seed_is_idempotent(tmp_db: Path) -> None:
    """AC-1：首次导入 == 种子题量，二次 0 新增且行数不变（迁移可重复执行）。"""
    assert repository.count_questions() == 0, "tmp_db 应从未导入的空库开始"
    expected = len(_seed_rows())

    assert question_bank.import_seed() == expected, f"首次导入应新增 {expected} 行"
    assert repository.count_questions() == expected

    assert question_bank.import_seed() == 0, "重复导入不得新增（ON CONFLICT(id) DO NOTHING）"
    assert repository.count_questions() == expected, "两次导入后行数必须恒定"


def test_import_seed_never_overwrites_existing_rows(tmp_db: Path) -> None:
    """AC-1：既有行绝不覆盖 —— 改过的种子再导入，库里仍是首次导入的内容与标签。"""
    question_bank.import_seed()
    original = {row["id"]: row for row in repository.list_questions()}

    rows = _seed_rows()
    for row in rows:
        if row["id"] == "fe-q1":
            row["prompt"] = "被改过的题干（不得覆盖已入库的行）"
            row["essentiality"] = rules.ESSENTIALITIES[-1]
            break
    assert question_bank.import_seed(_write_seed(tmp_db.parent, rows)) == 0, "既有行不得新增"

    stored = {row["id"]: row for row in repository.list_questions()}
    assert stored["fe-q1"]["prompt"] == original["fe-q1"]["prompt"], "既有题干被覆盖"
    assert stored["fe-q1"]["essentiality"] == original["fe-q1"]["essentiality"], "既有标签被覆盖"


def test_ensure_seeded_imports_every_time_and_stays_idempotent(tmp_db: Path) -> None:
    """r11 改口径：每次 ensure 都导入（存量库才能拿到新增题），但重复调用 0 新增。

    这是 AC-5「存量 app.db 启动即升级」的关键行为；r6 的「仅空库导入」会让老库永远缺新题。
    """
    expected = len(_seed_rows())
    assert question_bank.ensure_seeded() == expected, f"空库应收敛到 {expected} 行"
    assert question_bank.ensure_seeded() == expected, "再次 ensure 不得新增或改动（幂等）"


def test_ensure_seeded_refreshes_stale_rows_on_startup(tmp_db: Path) -> None:
    """r14 · P3-1：已部署库里的旧行（旧选项顺序 / 旧判断题答案）启动时被种子覆写。

    模拟存量库：先导入一份改过 `fe-q1` 题干与答案的旧种子 → 插一条该题的历史作答 →
    `ensure_seeded()`（真实种子）应把该行刷回种子内容，且历史作答逐条不变。
    """
    real_rows = _seed_rows()
    real = {row["id"]: row for row in real_rows}["fe-q1"]

    stale_rows = json.loads(json.dumps(real_rows, ensure_ascii=False))
    for row in stale_rows:
        if row["id"] == "fe-q1":
            row["prompt"] = "旧库里的过期题干"
            row["answer"] = ["D"]
            break
    question_bank.import_seed(_write_seed(tmp_db.parent, stale_rows))
    assert repository.count_questions() == len(real_rows), "旧种子导入后行数应等于种子题量"

    attempts = [
        {
            "id": "attempt-r14-1",
            "question_id": "fe-q1",
            "run_id": "run-r14-1",
            "correct": 0,
            "answered_at": "2026-11-01T00:00:00+00:00",
        }
    ]
    assert repository.insert_attempts(attempts) == 1
    before_attempts = repository.list_attempts()

    assert question_bank.ensure_seeded() == len(real_rows), "覆写既有行不得改变行数"
    stored = {row["id"]: row for row in repository.list_questions()}
    assert stored["fe-q1"]["prompt"] == real["prompt"], "启动未把旧题干刷回种子"
    assert stored["fe-q1"]["answer"] == real["answer"], "启动未把旧答案刷回种子"
    assert repository.list_attempts() == before_attempts, "覆写题目行不得动历史作答"

    assert question_bank.refresh_from_seed() == 0, "库内已与种子一致时刷新必须 0（幂等）"


def test_refresh_questions_ignores_unknown_and_empty_rows(tmp_db: Path) -> None:
    """r14 · P3-1：刷新只覆盖**已存在**的同 id 行 —— 未知 id 不新增，空列表直接 0。"""
    question_bank.import_seed()
    assert repository.refresh_questions([]) == 0, "空列表不得写库"
    unknown = {
        "id": "r14-unknown-1",
        "direction": rules.DIRECTIONS[0],
        "kind": "single",
        "difficulty": rules.DIFFICULTIES[0],
        "essentiality": rules.ESSENTIALITIES[0],
        "prompt": "刷新不得新增题",
        "options": ["甲", "乙", "丙", "丁"],
        "answer": ["A"],
    }
    assert repository.refresh_questions([unknown]) == 0, "未知 id 不得被写成新行"
    assert "r14-unknown-1" not in {row["id"] for row in repository.list_questions()}


def test_seed_labels_are_within_closed_sets() -> None:
    """AC-3：种子的方向 / 难度 / 必备度 / kind 全部落在 `rules.py` 闭集内。"""
    rows = _seed_rows()
    assert len(rows) >= 80, f"种子题量异常（{len(rows)}）"
    assert len(_legacy_rows(rows)) == 80, "存量 80 题不得被删改"
    for row in rows:
        assert row.get("direction") in rules.DIRECTIONS, f"{row.get('id')} 方向越界"
        assert row.get("difficulty") in rules.DIFFICULTIES, f"{row.get('id')} 难度越界"
        assert row.get("essentiality") in rules.ESSENTIALITIES, f"{row.get('id')} 必备度越界"
        assert row.get("kind") in rules.QUESTION_KINDS, f"{row.get('id')} kind 越界"


def test_seed_kind_and_essentiality_distribution() -> None:
    """AC-2（存量口径）：kind 48/20/12；必备度三档皆非空且为 20/20/40。"""
    rows = _legacy_rows()
    assert Counter(str(row["kind"]) for row in rows) == Counter(EXPECTED_KINDS)
    assert Counter(str(row["essentiality"]) for row in rows) == Counter(EXPECTED_ESSENTIALITY)


def test_seed_difficulty_distribution_per_scope() -> None:
    """AC-2（存量口径）：全库 60/12/8（`challenge` 恰 8）；客观题口径 48/12/8 —— 两个口径分别断言。"""
    rows = _legacy_rows()
    full = Counter(str(row["difficulty"]) for row in rows)
    assert full == Counter(FULL_DIFFICULTY), f"存量难度分布 {dict(full)} 与 §2.4 不符"

    objective_rows = [row for row in rows if rules.is_objective_kind(str(row["kind"]))]
    objective = Counter(str(row["difficulty"]) for row in objective_rows)
    assert len(objective_rows) == 68, "客观题应为 single 48 + multiple 20 = 68 道"
    assert objective == Counter(OBJECTIVE_DIFFICULTY), f"客观题难度分布 {dict(objective)} 与 §2.4 不符"


def test_intermediate_tier_is_the_declared_twelve() -> None:
    """AC-2：存量 `intermediate` 恰是 §2.4 表里的 12 道（每方向 3 道，id 逐条比对）。"""
    declared = {
        "fe-q5", "fe-q10", "fe-q13",
        "be-q11", "be-q15", "be-q17",
        "al-q7", "al-q10", "al-q13",
        "cs-q11", "cs-q13", "cs-q15",
    }
    actual = {row["id"] for row in _legacy_rows() if row.get("difficulty") == "intermediate"}
    assert actual == declared, f"intermediate 题 id 与 §2.4 不符：差集 {actual ^ declared}"


def test_each_direction_has_all_three_essentiality_tiers() -> None:
    """AC-2（存量口径）：四方向各 20；每方向 `must_know`=5 ∈[4,10] 且三档皆非空、覆盖 ≥2 种 kind。

    r11 扩容后某方向总数会 >20（AC-3 明确允许），因此「==20」只对存量题成立，方向总量只要求 ≥20。
    """
    legacy = _legacy_rows()
    rows = _seed_rows()
    for direction in LEGACY_DIRECTIONS:
        rows_dir = [row for row in legacy if row.get("direction") == direction]
        assert len(rows_dir) == EXPECTED_DIRECTION_COUNT, f"{direction} 存量题量 {len(rows_dir)} ≠ 20"
        assert len([row for row in rows if row.get("direction") == direction]) >= EXPECTED_DIRECTION_COUNT
        tiers = Counter(str(row["essentiality"]) for row in rows_dir)
        assert set(tiers) == set(rules.ESSENTIALITIES), f"{direction} 三档不齐：{dict(tiers)}"
        must = [row for row in rows_dir if row["essentiality"] == rules.MUST_KNOW]
        assert 4 <= len(must) <= 10, f"{direction} must_know {len(must)} 超出 [4,10]"
        assert len({str(row["kind"]) for row in must}) >= 2, f"{direction} must_know 只覆盖单一 kind"


def test_load_questions_returns_stored_rows(tmp_db: Path) -> None:
    """AC-1：组卷读库（不是现读 JSON）—— 库内行数 == 种子题量且 `answer` 解码后仍是 list。"""
    question_bank.ensure_seeded()
    rows = question_bank.load_questions()
    assert len(rows) == len(_seed_rows())
    assert all(isinstance(row.get("answer"), list) for row in rows), "answer 应解码为 list"
    assert {row["id"] for row in rows} == {row["id"] for row in _seed_rows()}


def test_usable_rows_filter_broken_entries(tmp_db: Path) -> None:
    """AC-1：可用性校验只有 `question_bank._usable` 一份，坏行不进可考池。"""
    question_bank.ensure_seeded()
    stored = repository.count_questions()
    broken = {
        "id": "qa-broken-1",
        "direction": rules.DIRECTIONS[0],
        "kind": "single",
        "difficulty": rules.DIFFICULTIES[0],
        "essentiality": rules.ESSENTIALITIES[0],
        "prompt": "缺 options 与 answer 的客观题",
        "options": [],
        "answer": [],
        "source": "qa",
    }
    assert repository.insert_question(broken) is True
    assert repository.count_questions() == stored + 1, "坏行仍会入库（入库不等于可考）"
    assert "qa-broken-1" not in {row["id"] for row in question_bank.load_questions()}, "坏行进了可考池"


@pytest.mark.parametrize("field", ("direction", "difficulty", "essentiality", "kind"))
def test_stored_rows_keep_closed_set_labels(tmp_db: Path, field: str) -> None:
    """AC-1/AC-3：库内标签与闭集一致（导入后逐行复核，脏值兜底不掩盖闭集漂移）。"""
    question_bank.ensure_seeded()
    for row in repository.list_questions():
        assert row.get(field) in getattr(
            rules, {"direction": "DIRECTIONS", "difficulty": "DIFFICULTIES",
                    "essentiality": "ESSENTIALITIES", "kind": "QUESTION_KINDS"}[field]
        ), f"{row.get('id')} 的 {field} 越界：{row.get(field)!r}"
