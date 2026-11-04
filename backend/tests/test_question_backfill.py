"""存量题语言回填算法（r11 AC-2 · TECHNICAL §3.2）：表驱动用例 + 确定性 + 方向约束。

为什么不写「读一遍种子看结果对不对」：回填的价值全在**确定性**——同一份输入跑两次必须
得到同一份输出，且方向约束不能靠人手把关。因此这里的用例分四组：

1. `test_backfill_table_driven`（≥8 条）：方向 × 文本 → 期望语言，含「前端方向命中 python
   关键词必须被方向约束丢弃后继续找」与「`go` 不得命中 `algorithm`/`django`、`js` 不得命中
   `json`」这类边界反例。表里任何一行改动都等于改口径。
2. `test_algorithm_directions_stay_empty`：算法与数据结构 / 计算机基础 恒留空（即使文本里
   明写语言名），这是第 1 步「方向预判」的唯一正确性证明。
3. `test_backfill_is_deterministic`：两次运行的序列化结果**逐字相等**、第二次判定 0 条。
4. `test_seed_languages_match_algorithm`：种子内 80 道存量题的语言**必须等于算法输出**——
   手改某一题的语言会让这条用例变红（AC-2 的「不许用手感改」）。
"""

from __future__ import annotations

from typing import Any

import pytest

from app.services import rules
from app.services.question_backfill import (
    BACKFILL_KEYWORDS,
    backfill_seed,
    dumps,
    infer_language,
    ordered_keywords,
    question_text,
)

#: 存量题 id 前缀（fe-/be-/al-/cs-）：它们才是「回填」的对象，新题的语言是人工写死的。
LEGACY_PREFIXES = ("fe-", "be-", "al-", "cs-")

#: 表驱动用例：(方向, 文本, 期望语言)。最后三列是反例，缺一不可。
BACKFILL_CASES: tuple[tuple[str, str, str], ...] = (
    # --- 正向命中 ---------------------------------------------------------
    ("后端", "Python 中装饰器与生成器的作用是什么？", "python"),
    ("后端", "django 的 ORM 与数据库索引该怎么配合？", "python"),
    ("后端", "JVM 的垃圾回收与线程池该怎么调优？", "java"),
    ("后端", "Go 的 goroutine 与操作系统线程的区别", "go"),
    ("后端", "defer 与 panic 的执行顺序", "go"),
    ("前端", "React 中 useEffect 的清理逻辑什么时候执行？", "react"),
    ("前端", "useState 与 useReducer 该怎么选？", "react"),
    ("前端", "Vue 3 的组合式 API 相比选项式有什么优势？", "vue3"),
    ("前端", "TypeScript 的类型体操指的是什么？", "ts"),
    ("前端", "javascript 的事件循环与微任务", "js"),
    ("前端", "CSS 选择器权重如何计算？", "css"),
    ("前端", "HTML 语义化标签有哪些好处？", "html"),
    ("前端", "无障碍访问中 aria 属性怎么用？", "html"),
    # --- 方向约束反例 -----------------------------------------------------
    # 前端方向命中 python 关键词 → 丢弃并继续；随后命中 js → 返回 js。
    ("前端", "Python 的列表推导与 JS 的 map 有何区别", "js"),
    # 前端方向只命中 python 关键词 → 全部丢弃 → 留空（不硬凑）。
    ("前端", "django 的 ORM 与索引设计", ""),
    # 后端的 goroutine 在「算法与数据结构」方向恒留空。
    ("算法与数据结构", "Python 实现快速排序", ""),
    # --- 边界安全反例 -----------------------------------------------------
    # `go` 不得命中 algorithm；`js` 不得命中 json。
    ("后端", "algorithm 的时间复杂度该怎么分析？", ""),
    ("后端", "json 序列化与反序列化的开销", ""),
    # 没有任何关键词的通用题留空。
    ("后端", "HTTP 状态码 401 与 403 的区别", ""),
)


@pytest.mark.parametrize(("direction", "text", "expected"), BACKFILL_CASES)
def test_backfill_table_driven(direction: str, text: str, expected: str) -> None:
    """AC-2 表驱动：方向约束 → 长词优先 → 命中即停 → 未命中留空。"""
    assert infer_language(direction, text) == expected, f"{direction} / {text!r} 回填结果不符"


@pytest.mark.parametrize("direction", sorted(rules.DIRECTIONS))
def test_algorithm_directions_stay_empty(direction: str) -> None:
    """第 1 步方向预判：与语言无关的方向恒留空——即使文本明写 python / react。"""
    has_languages = direction in set(rules.LANGUAGE_DIRECTION.values())
    text = "Python 的装饰器与 React 的 useEffect 有什么区别？"
    inferred = infer_language(direction, text)
    assert inferred == ("" if not has_languages else inferred)
    if not has_languages:
        assert inferred == "", f"{direction} 不应归属任何语言"
        return
    assert inferred in set(rules.languages_for_direction(direction)), (
        f"{direction} 只能得到该方向下的语言：{inferred!r}"
    )


def test_direction_constraint_never_crosses() -> None:
    """方向约束是硬边界：把某个语言的关键词丢给**另一个方向**，只可能得到该方向内的语言。

    允许「非空」：`interface{}` 这类词在前端方向确实同时是 TS 的 `interface`，于是得到 `ts`
    —— 这不是越界，而是另一个方向内的合法归属。越界只有一种形态：得到原方向的语言。
    """
    for keyword, language in ordered_keywords():
        owner = rules.direction_of_language(language)
        assert owner is not None, f"{language} 未归属任何方向"
        others = [
            item
            for item in rules.DIRECTIONS
            if item != owner and item in set(rules.LANGUAGE_DIRECTION.values())
        ]
        for other in others:
            inferred = infer_language(other, keyword)
            assert inferred != language, f"{other} 方向被 {keyword!r} 越界命中 {inferred}"
            assert rules.is_language_allowed(inferred, other), (
                f"{other} 方向得到不属于它的语言：{inferred!r}"
            )


def test_zero_width_and_case_insensitive() -> None:
    """大小写与紧贴写法都要命中：`Python的装饰器`（中文紧贴）与 `PYTHON` 同效。"""
    assert infer_language("后端", "Python的装饰器怎么写？") == "python"
    assert infer_language("后端", "PYTHON 的列表推导") == "python"
    assert infer_language("前端", "React 的hooks 规则") == "react"


def test_ordered_keywords_are_longest_first() -> None:
    """长词优先是全局全序：任何一对相邻项都满足「不短于」，且语言序稳定。"""
    ordered = ordered_keywords()
    assert ordered, "关键词表不得为空"
    for (left, left_lang), (right, right_lang) in zip(ordered, ordered[1:], strict=False):
        assert len(left) >= len(right), f"长词优先被破坏：{left!r} 在 {right!r} 之前"
        if len(left) == len(right):
            assert rules.LANGUAGES.index(left_lang) <= rules.LANGUAGES.index(right_lang)


def test_keyword_table_only_uses_closed_set_languages() -> None:
    """关键词表不得出现闭集外的语言（否则回填会产出非法值）。"""
    for language, keywords in BACKFILL_KEYWORDS.items():
        assert language in rules.LANGUAGES, f"{language} 不在语言闭集内"
        assert language != "", "通用题不该有关键词表"
        assert keywords, f"{language} 的关键词表为空"
        for keyword in keywords:
            assert keyword == keyword.lower(), f"{keyword!r} 应为小写（匹配前统一小写化）"


#: 造一批「r11 之前」的行：没有 language 键。
_LEGACY_ROWS: list[dict[str, Any]] = [
    {
        "id": "fe-x1",
        "direction": "前端",
        "kind": "single",
        "difficulty": "basic",
        "essentiality": "must_know",
        "prompt": "React 中 key 的作用是什么？",
        "options": [{"key": "A", "text": "标识元素身份"}],
        "answer": ["A"],
    },
    {
        "id": "be-x1",
        "direction": "后端",
        "kind": "single",
        "difficulty": "basic",
        "essentiality": "must_know",
        "prompt": "Python 的 GIL 是什么？",
        "options": [{"key": "A", "text": "全局解释器锁"}],
        "answer": ["A"],
    },
    {
        "id": "al-x1",
        "direction": "算法与数据结构",
        "kind": "single",
        "difficulty": "basic",
        "essentiality": "nice_to_know",
        "prompt": "快速排序的平均复杂度？",
        "options": [{"key": "A", "text": "O(n log n)"}],
        "answer": ["A"],
    },
]


def test_backfill_is_deterministic() -> None:
    """AC-2：同一份输入两次运行结果字节相等，且第二次判定 0 条（幂等）。"""
    first, first_hits = backfill_seed(_LEGACY_ROWS)
    second, second_hits = backfill_seed(_LEGACY_ROWS)
    assert dumps(first) == dumps(second), "两次回填结果不一致（算法不确定）"
    assert first_hits == second_hits

    again, again_hits = backfill_seed(first)
    assert again_hits == {}, "已回填的行不应被再次判定"
    assert dumps(again) == dumps(first), "回填后的行被改写了"


def test_backfill_keeps_explicit_language() -> None:
    """人工写死的语言不被算法改写（新题是人工标注的，算法只补缺失）。"""
    row = dict(_LEGACY_ROWS[1], language="go")
    out, hits = backfill_seed([row])
    assert hits == {}, "已有 language 的行不应参与判定"
    assert out[0]["language"] == "go", "人工语言被算法覆盖"


def test_backfill_returns_new_objects() -> None:
    """纯函数：不改入参（否则「两次运行结果相等」会被就地修改掩盖）。"""
    rows = [dict(_LEGACY_ROWS[0])]
    out, _ = backfill_seed(rows)
    assert "language" not in rows[0], "入参被就地改写"
    assert out[0] is not rows[0]


def test_seed_languages_match_algorithm() -> None:
    """AC-2 收口：种子内 80 道存量题的语言必须等于当前算法的输出（禁止手改）。"""
    from app.services.question_bank import SEED_PATH, load_seed

    rows = load_seed(SEED_PATH)
    legacy = [row for row in rows if str(row["id"]).startswith(LEGACY_PREFIXES)]
    assert len(legacy) == 80, f"存量题应为 80 道，实际 {len(legacy)}"
    drifted = [
        (row["id"], row["language"], infer_language(str(row["direction"]), question_text(row)))
        for row in legacy
        if str(row.get("language") or "") != infer_language(str(row["direction"]), question_text(row))
    ]
    assert not drifted, f"以下存量题的语言与算法输出不一致（被手改？）：{drifted}"


def test_seed_is_fully_backfilled() -> None:
    """种子内每道题都有 language 键（含显式留空的 `""`），且取值落在闭集内。"""
    from app.services.question_bank import SEED_PATH, load_seed

    for row in load_seed(SEED_PATH):
        assert "language" in row, f"{row['id']} 缺少 language 键"
        assert row["language"] in rules.LANGUAGES, f"{row['id']} 的 language 越界：{row['language']!r}"
