"""题库质量硬校验（r11 AC-4 · TECHNICAL §3.3）：八条断言，**同时**跑在种子 JSON 与导入后的库上。

为什么同一个断言要跑两遍：种子是源、库是运行时真身。只测种子会漏掉导入路径（JSON 解码、
`ON CONFLICT DO NOTHING`、默认值兜底）引入的漂移；只测库会漏掉「文件里写错了但没导入」的条目。
两处用同一批断言函数，任何一侧坏掉都直接红。

八条（对应 AC-4 ①–⑧）：

1. 题型形状：`single` 答案恰 1、`multiple` ≥2、`judge` 选项恰 2 且答案恰 1 并落在选项里。
2. 客观题答案 `⊆` 选项 key 集合。
3. 选项 2–6 个、key 唯一且落在 A–F。
4. 解析去空白后 ≥10 字符（全库口径，简答题也要有）。
5. 同语言内归一化题干重复数为 0。
6. AC-3 分布闸门（每语言 ==20、难度/题型/必备度配额、含代码块 ≥2、通用方向恒空）。
7. `_usable()` 复核后可用题数 == 库存题数（坏行 0）。
8. `kind` 闭集内不存在 `blank`，新增语言题不出现 `text`。
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from app import repository
from app.services import question_bank, rules

#: 新增 180 题的 id 前缀 → 语言（AC-3 的断言范围是「新增种子」）。
NEW_ID_LANGUAGE: dict[str, str] = {
    "py-": "python",
    "java-": "java",
    "go-": "go",
    "html-": "html",
    "css-": "css",
    "js-": "js",
    "ts-": "ts",
    "vue3-": "vue3",
    "react-": "react",
}

#: 存量题前缀（回填对象）：分布闸门只管新增题，存量题不因扩容被删改。
LEGACY_PREFIXES = ("fe-", "be-", "al-", "cs-")

#: 判断题的固定选项文案（TECHNICAL §4.1：纯文字，对读屏友好）。
JUDGE_OPTIONS = ("正确", "错误")

#: AC-3 的配额（下界 / 区间）。
LANGUAGE_QUOTA = 20
BASIC_RANGE = (10, 13)
INTERMEDIATE_RANGE = (5, 8)
CHALLENGE_RANGE = (2, 4)
MIN_SINGLE = 12
MIN_MULTIPLE = 3
MIN_JUDGE = 3
MIN_MUST_KNOW = 6
MIN_ADVANCED = 4
MIN_CODE_BLOCKS = 2
MIN_TOTAL = 260
MIN_GENERIC_PER_DIRECTION = 20

_OPTION_KEYS = tuple("ABCDEF")


def _normalize(prompt: str) -> str:
    """归一化题干：全半角统一、去空白、去标点 —— 只留语义字符，用于查重。"""
    text = unicodedata.normalize("NFKC", prompt)
    text = re.sub(r"\s+", "", text)
    return re.sub(r"[\W_]+", "", text)


def _is_new(question_id: str) -> bool:
    return question_id.startswith(tuple(NEW_ID_LANGUAGE))


def _new_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if _is_new(str(row["id"]))]


def _objective(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if rules.is_objective_kind(str(row["kind"]))]


@pytest.fixture(params=("seed", "db"))
def bank_rows(request: pytest.FixtureRequest, tmp_db: Path) -> list[dict[str, Any]]:
    """同一批断言的两个数据源：种子 JSON（源）与导入后的库（运行时真身）。"""
    if request.param == "seed":
        return question_bank.load_seed()
    question_bank.ensure_seeded()
    return question_bank.load_questions()


# --- ① 题型形状 ---------------------------------------------------------------
def test_question_shape_per_kind(bank_rows: list[dict[str, Any]]) -> None:
    """AC-4 ①：single 恰 1、multiple ≥2、judge 选项恰 2 且答案恰 1 并指向其中一个选项。"""
    for row in _objective(bank_rows):
        kind = str(row["kind"])
        answer = [str(item) for item in row.get("answer") or []]
        options = [str(option.get("key")) for option in row.get("options") or []]
        if kind == "single":
            assert len(answer) == 1, f"{row['id']} 单选答案应恰 1 个，实际 {answer}"
        elif kind == "multiple":
            assert len(answer) >= 2, f"{row['id']} 多选答案应 ≥2 个，实际 {answer}"
        else:  # judge
            assert len(options) == 2, f"{row['id']} 判断题必须恰 2 个选项，实际 {options}"
            texts = [str(option.get("text")) for option in row.get("options") or []]
            assert tuple(texts) == JUDGE_OPTIONS, f"{row['id']} 判断题选项文案不符：{texts}"
            assert len(answer) == 1, f"{row['id']} 判断题答案应恰 1 个，实际 {answer}"
            assert answer[0] in options, f"{row['id']} 判断题答案不在选项里：{answer}"


def test_text_questions_have_no_objective_payload(bank_rows: list[dict[str, Any]]) -> None:
    """简答题是主观题：不入练习池、不判分，因此没有选项与标准答案。"""
    for row in bank_rows:
        if str(row["kind"]) != rules.TEXT_KIND:
            continue
        assert row.get("options") == [], f"{row['id']} 简答题不应有选项"
        assert row.get("answer") == [], f"{row['id']} 简答题不应有标准答案"


# --- ② 答案 ⊆ 选项 -------------------------------------------------------------
def test_objective_answer_subset_of_options(bank_rows: list[dict[str, Any]]) -> None:
    """AC-4 ②：客观题（含判断题）的答案 key 必须都是选项 key 之一。"""
    for row in _objective(bank_rows):
        keys = {str(option.get("key")) for option in row.get("options") or []}
        answer = {str(item) for item in row.get("answer") or []}
        assert answer <= keys, f"{row['id']} 答案 {sorted(answer)} 越出选项 {sorted(keys)}"
        assert answer, f"{row['id']} 客观题没有答案"


# --- ③ 选项结构 ---------------------------------------------------------------
def test_option_keys_are_unique_and_in_range(bank_rows: list[dict[str, Any]]) -> None:
    """AC-4 ③：客观题选项 2–6 个、key 唯一致且落在 A–F、选项文本非空。"""
    for row in _objective(bank_rows):
        options = row.get("options") or []
        assert 2 <= len(options) <= 6, f"{row['id']} 选项数 {len(options)} 越界"
        keys = [str(option.get("key")) for option in options]
        assert len(set(keys)) == len(keys), f"{row['id']} 选项 key 重复：{keys}"
        for option in options:
            assert str(option.get("key")) in _OPTION_KEYS, f"{row['id']} 选项 key 越界：{option}"
            assert str(option.get("text") or "").strip(), f"{row['id']} 存在空选项文本"


# --- ④ 解析非空 ---------------------------------------------------------------
def test_explanations_non_empty(bank_rows: list[dict[str, Any]]) -> None:
    """AC-4 ④：全库每道题的解析去空白后 ≥10 字符（含简答题与存量回填题）。"""
    for row in bank_rows:
        text = re.sub(r"\s+", "", str(row.get("explanation") or ""))
        assert len(text) >= 10, f"{row['id']} 解析过短或缺失（{len(text)} 字符）"


# --- ⑤ 同语言去重 -------------------------------------------------------------
def test_no_duplicate_prompts_within_language(bank_rows: list[dict[str, Any]]) -> None:
    """AC-4 ⑤：同语言内归一化题干重复数为 0（跨语言允许同题，不同语言是不同题）。"""
    seen: dict[tuple[str, str], str] = {}
    for row in bank_rows:
        key = (str(row.get("language") or ""), _normalize(str(row.get("prompt") or "")))
        assert key[1], f"{row['id']} 题干为空"
        assert key not in seen, f"{row['id']} 与 {seen[key]} 在同语言内题干重复"
        seen[key] = str(row["id"])


# --- ⑥ 分布闸门 ---------------------------------------------------------------
def test_language_distribution_gates(bank_rows: list[dict[str, Any]]) -> None:
    """AC-3：新增 9 个语言各恰 20 道，难度/题型/必备度配额与代码块数达标。"""
    new = _new_rows(bank_rows)
    assert len(new) == len(NEW_ID_LANGUAGE) * LANGUAGE_QUOTA, f"新增题量应为 180，实际 {len(new)}"
    by_language = Counter(str(row["language"]) for row in new)
    for prefix, language in NEW_ID_LANGUAGE.items():
        rows = [row for row in new if str(row["id"]).startswith(prefix)]
        assert len(rows) == LANGUAGE_QUOTA, f"{language} 新增题量 {len(rows)} ≠ 20"
        assert all(str(row["language"]) == language for row in rows), f"{language} id 前缀与 language 不符"

        difficulty = Counter(str(row["difficulty"]) for row in rows)
        for tier, (low, high) in (
            ("basic", BASIC_RANGE),
            ("intermediate", INTERMEDIATE_RANGE),
            ("challenge", CHALLENGE_RANGE),
        ):
            assert low <= difficulty[tier] <= high, (
                f"{language} 的 {tier} 数量 {difficulty[tier]} 不在 [{low},{high}]"
            )
        assert sum(difficulty.values()) == LANGUAGE_QUOTA, f"{language} 难度合计不符"

        kind = Counter(str(row["kind"]) for row in rows)
        assert kind["single"] >= MIN_SINGLE, f"{language} single {kind['single']} < {MIN_SINGLE}"
        assert kind["multiple"] >= MIN_MULTIPLE, f"{language} multiple {kind['multiple']} < {MIN_MULTIPLE}"
        assert kind["judge"] >= MIN_JUDGE, f"{language} judge {kind['judge']} < {MIN_JUDGE}"
        assert sum(kind.values()) == LANGUAGE_QUOTA, f"{language} 题型合计不符"
        assert kind[rules.TEXT_KIND] == 0, f"{language} 不得出现简答题"

        essentiality = Counter(str(row["essentiality"]) for row in rows)
        assert essentiality[rules.MUST_KNOW] >= MIN_MUST_KNOW, f"{language} must_know 不足"
        assert essentiality["advanced"] >= MIN_ADVANCED, f"{language} advanced 不足"

        code_blocks = sum(1 for row in rows if "```" in str(row["prompt"]))
        assert code_blocks >= MIN_CODE_BLOCKS, f"{language} 含代码块题目 {code_blocks} < {MIN_CODE_BLOCKS}"

    assert sum(by_language.values()) == len(new)
    for language in rules.LANGUAGES:
        if language:
            assert by_language[language] == LANGUAGE_QUOTA, f"{language} 新增题量不符"


def test_total_size_and_generic_directions(bank_rows: list[dict[str, Any]]) -> None:
    """AC-3：库存总量 ≥260；算法与数据结构 / 计算机基础 各 ≥20 且 language 恒空串。"""
    assert len(bank_rows) >= MIN_TOTAL, f"库存总量 {len(bank_rows)} < {MIN_TOTAL}"
    language_directions = set(rules.LANGUAGE_DIRECTION.values())
    for direction in rules.DIRECTIONS:
        rows = [row for row in bank_rows if str(row["direction"]) == direction]
        assert len(rows) >= MIN_GENERIC_PER_DIRECTION, f"{direction} 题量 {len(rows)} < 20"
        if direction in language_directions:
            continue
        offenders = [row["id"] for row in rows if str(row.get("language") or "") != ""]
        assert not offenders, f"{direction} 应恒为通用题（language 空串），越界：{offenders}"


def test_legacy_questions_survive_the_expansion(bank_rows: list[dict[str, Any]]) -> None:
    """扩容不得删存量题：fe-/be-/al-/cs- 各 20 道仍在，且都补上了 language 与 explanation。"""
    for prefix in LEGACY_PREFIXES:
        rows = [row for row in bank_rows if str(row["id"]).startswith(prefix)]
        assert len(rows) == 20, f"{prefix} 存量题被删改，只剩 {len(rows)} 道"
        for row in rows:
            assert row.get("language") in rules.LANGUAGES, f"{row['id']} language 缺失或越界"
            assert len(re.sub(r"\s+", "", str(row.get("explanation") or ""))) >= 10, (
                f"{row['id']} 解析未补齐"
            )


# --- ⑦ 可用性 == 库存 ---------------------------------------------------------
def test_all_questions_usable(bank_rows: list[dict[str, Any]], tmp_db: Path) -> None:
    """AC-4 ⑦：`_usable()` 复核后可用题数 == 库存题数（坏行 0）。"""
    question_bank.ensure_seeded()
    stored = repository.count_questions()
    usable = len(question_bank.load_questions())
    assert usable == stored, f"可用 {usable} 道与库存 {stored} 道不一致（存在坏行）"
    assert usable == len(bank_rows), "同一次读取的题量与传入数据源不一致"


# --- ⑧ kind 闭集 --------------------------------------------------------------
def test_kind_closed_set_has_no_blank(bank_rows: list[dict[str, Any]]) -> None:
    """AC-4 ⑧：kind 全部落在闭集内，且闭集里不存在 `blank`（本版无填空题）。"""
    allowed = set(rules.QUESTION_KINDS)
    assert "blank" not in allowed, "kind 闭集被污染"
    for row in bank_rows:
        assert str(row["kind"]) in allowed, f"{row['id']} 的 kind 越界：{row['kind']!r}"


def test_generated_bank_has_no_ai_placeholder(bank_rows: list[dict[str, Any]]) -> None:
    """内容兜底：题干不得是 AI 占位/待补文案（这类题一旦入库，用户第一眼就不信）。"""
    markers = ("TODO", "待补", "占位", "示例题目", "lorem")
    for row in _new_rows(bank_rows):
        prompt = str(row["prompt"])
        for marker in markers:
            assert marker not in prompt, f"{row['id']} 题干含占位文案 {marker!r}"


# ---------------------------------------------------------------------------
# r12 · 题库素材合并（260 → 779）—— **只追加**，上面 r11 的断言一字不改
#
# 为什么零处改基数：r11 的题量类断言全部收敛在「前缀子集」（`fe-/be-/al-/cs-` 存量 +
# 九个语言前缀）或按 `len(bank_rows)` 动态推导，本批新前缀（`tiji-` / `l100-` / `iq380-` /
# `fei-`）不在任何前缀集合里，因此合并后 r11 的配额断言照旧成立（TECH-CHANGE §5「0 处需改」）。
# 这里只加三条**新口径**：来源枚举与计数、合并后总量、通用方向恒空 language。
# ---------------------------------------------------------------------------

#: r12 新增来源闭集（与 `question_merge.SOURCES` 同一口径；门禁是唯一断言点故写字面量）。
R12_SOURCES = ("tiji", "local100", "iq380", "fe-interview")
#: 每来源条数：`seed` 是存量 260 行（种子不写 `source`，读侧缺省 `'seed'`）。
R12_SOURCE_COUNTS = {
    "seed": 260,
    "tiji": 20,
    "local100": 100,
    "iq380": 379,
    "fe-interview": 20,
}
#: 合并后总量（= 存量 260 + 本批 519）。
R12_TOTAL = 779


def test_r12_source_enum_and_per_source_counts(bank_rows: list[dict[str, Any]]) -> None:
    """r12：来源只允许「存量缺省 seed + 本批 4 个」，且每来源条数与素材一一对应。"""
    counts = Counter(str(row.get("source") or "seed") for row in bank_rows)
    assert dict(counts) == R12_SOURCE_COUNTS, f"来源分布不符：{dict(counts)}"
    assert set(counts) <= {"seed", *R12_SOURCES}, "出现了未登记的来源"
    for row in bank_rows:
        source = str(row.get("source") or "seed")
        if source == "seed":
            assert str(row["id"]).startswith(LEGACY_PREFIXES + tuple(NEW_ID_LANGUAGE)), (
                f"{row['id']} 缺 source 却不是 r11 已知前缀：来源不明（可能是合并时漏写）"
            )


def test_r12_total_after_merge_is_779(bank_rows: list[dict[str, Any]]) -> None:
    """r12：合并后总量恰 779（260 存量 + 519 新增），且 519 道全是客观题。"""
    assert len(bank_rows) == R12_TOTAL, f"题库总量 {len(bank_rows)} ≠ {R12_TOTAL}"
    merged = [row for row in bank_rows if str(row.get("source") or "") in R12_SOURCES]
    assert len(merged) == R12_TOTAL - R12_SOURCE_COUNTS["seed"]
    assert all(str(row["kind"]) in rules.OBJECTIVE_KINDS for row in merged), (
        "本批素材全为客观题，出现 text 说明归一化越界放行了"
    )
    assert len(_new_rows(bank_rows)) == len(NEW_ID_LANGUAGE) * LANGUAGE_QUOTA, (
        "r11 的 180 道语言题不得被合并逻辑吞掉（id 前缀判定口径不变）"
    )


def test_r12_generic_directions_stay_language_free(bank_rows: list[dict[str, Any]]) -> None:
    """r12：算法与数据结构 / 计算机基础 恒 `language == ""`（方向纠正不得把语言引进来）。"""
    language_directions = set(rules.LANGUAGE_DIRECTION.values())
    generic = [name for name in rules.DIRECTIONS if name not in language_directions]
    assert generic, "通用方向必须由 rules 派生，不得在此另写一份"
    for direction in generic:
        rows = [row for row in bank_rows if str(row["direction"]) == direction]
        assert len(rows) >= MIN_GENERIC_PER_DIRECTION, f"{direction} 题量 {len(rows)} < 20"
        offenders = [row["id"] for row in rows if str(row.get("language") or "")]
        assert not offenders, f"{direction} 应恒为通用题（language 空串），越界：{offenders}"

