"""r12 题库素材合并的回归网（TECH-CHANGE §3）：工具口径 + 数据不变量 + 回滚与许可。

与 `test_question_bank_quality.py` 分层：那个文件断言「题库**对外**质量」（题型形状、
答案 ⊆ 选项、分布配额）；本文件断言「**合并在离线阶段**是否正确」（归一化、去重取舍、
字节级序列化、幂等、来源枚举、回滚、许可）。失败时一眼能区分是数据错还是工具错。

三条硬约束在这里被钉住：
- 归一化口径必须与 r11 测试侧 `_normalize()` 逐字一致（跨侧无共享代码，只能对拍）；
- `dumps()` 必须逐字节复现已提交 seed —— 它同时被 `--write` 与 `--check` 使用，
  换成 `json.dump(indent=2)` 会让文件变成 216281+ 字节的全文件重写；
- 回滚只经 `repository.delete_questions_by_source()`，且只删本批 4 个来源。
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from app import repository
from app.config import get_settings
from app.services import question_bank, question_merge as qm, rules

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
NOTICE_PATH = REPO_ROOT / "docs" / "question-bank-staging" / "NOTICE-fe-interview.md"

#: r14 基线（由 r13 就地迁移，语义不变）：合并后**前 260 行**的序列化
#: 必须是这个长度（动过任何一行存量数据，这条就会红——「存量逐字节不变」的机器化）。
#: r14（P3-3）把 8 道存量判断题（ts/react/js/html/vue3 的 q17/q20）改写成真命题；
#: r14（P3-2）又按 `LENGTH_REWRITES` 压缩了 23 道存量题（cs-q11 / cs-q13 / css-q2 /
#: css-q5 / css-q7 / fe-q15 / html-q11 / html-q2 / java-q4·q7·q8·q9 / js-q7·q10 /
#: react-q2·q4·q5·q6 / ts-q3·q5·q7 / vue3-q2·q6）正确项的措辞（语义不变、判分 key 不变）。
#: 字节数因此由 r13 的 192073 → r14 的 191954 → 191135。
#: r17 修正存量错题 `py-q1`（默认参数 + `print` 参数共享同一个 list 的复合坑）：
#: 标注答案由「`[1] [1, 2]`」改为「`[1, 2] [1, 2]`」，解析按真实行为重写 → 191135 → 191300。
#: r17 全库审查又修正 `al-q17` 解析的事实错误（「选择排序虽然稳定」→ 选择排序不稳定），
#: 解析变长 → 191300 → 191372。
#: r17 方向重归类：17 道存量通用题（be-q* / fe-q*）按主题迁到新方向，direction 字段
#: 长度变化 → 191372 → 191537。题干/选项/答案/解析均未改动。
R13_SEED_BYTES = 191537

#: 存量 260 行序列化块的 sha256：**内容**级冻结。只钉字节数挡不住「等长改写」
#: （QA D-1：改一个字、字节数不变），这里钉摘要才能让内容漂移真正变红。
#: r13 的选项打乱与判断题陈述改写、r14 的双向极性调整（P3-3）与长答案改写（P3-2）
#: 都已落在这 260 行上（行序/行数/来源不变），故基线由 r11 → r13 → r14 逐轮迁移：
#: 真要再动存量行，必须同时改这个常量并在任务夹留痕。
#:
#: r15（「AI 工程」）+ r16（本次「中间件与运维」方向，mw-* 题）：两者均为 `language=""`
#: 的通用方向题，与 al-/cs- 同处 `""` 语言桶。新增 mw 题会让 `question_shuffle.apply()` 的
#: 「按最低计数位置轮转」在该桶里重新分配，进而**只改变存量里通用方向题的选项位置序**
#: （题干/解析/正确项文本、答案正确性不变）。等长改写使 `R13_SEED_BYTES` 仍为 191135，
#: 但 sha256 随桶内轮转态漂移。这是全局均衡的确定性副作用，已确认重算幂等
#: （重跑 `--write` 首末两遍 first-260 字节一致），故在此同步刷新基线。
#:
#: r17（修正 `py-q1` 错题）：该题属存量 260 行，答案与解析均被改动，是**内容级**变更
#: 而非轮转副作用——`print(f(1), f(2))` 两个参数引用同一个默认列表，`print` 先求值
#: 完两个实参再统一转字符串，故两次调用后两处都打印 `[1, 2]`。基线随之迁移。
#: 同一轮全库审查中 `al-q17` 的解析事实错误也落在存量行，基线再次迁移。
#: r17 方向重归类又改了 17 道存量行的 `direction`（等长替换之外还有字段值变化），
#: 属有意为之的分类修正，基线随之迁移；已确认所有带语言的行方向与 `LANGUAGE_DIRECTION` 一致。
R13_SEED_SHA256 = "022a706209330d13b16ca4e0d41289a601d0062eaa88397d9e830e11db39e884"

#: 合并后的期望规模与来源分布（TECH-CHANGE §3.4 逐项）。门禁是唯一断言点，故允许字面量。
EXPECTED_TOTAL = 1038
EXPECTED_SOURCES = {
    "seed": 260,
    "tiji": 20,
    "local100": 100,
    "iq380": 379,
    "fe-interview": 20,
    "ai-eng": 103,
    "mw": 76,
    "sql": 50,
    "algo": 30,
}

_EXPLANATION = "这是一段足够长的解析文本，用于满足解析非空与长度门槛的断言。"


def _load_r11_quality_module() -> Any:
    """按文件路径加载 r11 的质量测试模块，只为取它的 `_normalize()` 做口径对拍。

    不 `import tests.xxx`：`backend/tests` 不是包（无 `__init__.py`），路径加载是唯一稳定方式。
    """
    path = Path(__file__).with_name("test_question_bank_quality.py")
    spec = importlib.util.spec_from_file_location("r12_r11_quality_probe", path)
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def _options(count: int = 4) -> list[dict[str, str]]:
    return [{"key": key, "text": f"选项 {key} 的文本"} for key in ("A", "B", "C", "D")[:count]]


def _row(
    prompt: str,
    *,
    source: str = "tiji",
    kind: str = "single",
    language: str = "python",
    direction: str = "后端",
    difficulty: str = "basic",
    essentiality: str = "must_know",
    explanation: str = _EXPLANATION,
    answer: list[str] | None = None,
    options: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """构造一条**种子形态**的行（供工具函数直接消费，不经过素材 JSON）。"""
    row: dict[str, Any] = {
        "id": "tiji-000",
        "direction": direction,
        "kind": kind,
        "difficulty": difficulty,
        "essentiality": essentiality,
        "language": language,
        "prompt": prompt,
        "options": _options() if options is None else options,
        "answer": ["A"] if answer is None else answer,
        "explanation": explanation,
    }
    if source:
        row["source"] = source
    return row


def _judge_record(answer: str, keys: tuple[str, str] = ("A", "B")) -> dict[str, Any]:
    """一条**素材形态**的判断题（key 可能是中文、answer 可能是中文）。"""
    return {
        "kind": "judge",
        "stem": "判断：React 的 useEffect 在依赖数组变化后会重新执行。",
        "options": [
            {"key": key, "text": text} for key, text in zip(keys, ("正确", "错误"), strict=True)
        ],
        "answer": answer,
        "explanation": "useEffect 在依赖变化后重新执行，返回的清理函数先于下一次执行调用。",
        "difficulty": "basic",
        "essentiality": "must_know",
        "language": "react",
        "direction": "前端",
    }


# --- ① 归一化口径 -------------------------------------------------------------
def test_normalize_prompt_matches_r11_normalization() -> None:
    """工具侧归一化必须与 r11 测试侧 `_normalize()` 逐字一致（跨侧无共享代码，只能对拍）。"""
    quality = _load_r11_quality_module()
    samples = [
        "在 JavaScript 中，以下哪个表达式的 typeof 结果为 \"number\"？",
        "Ｖｕｅ３ 的 ｒｅａｃｔｉｖｅ 何时触发依赖收集？",  # 全角
        "  前后都有空白   且中间\n有换行\t制表符  ",
        "`typeof null` 返回什么？",
        "a_b_c 与 a-b-c 归一后应当相同",
        "```\nprint('hello')\n``` 这段代码输出什么？",
        "？ ？ ？",
        "",
    ]
    samples.extend(str(row["prompt"]) for row in question_bank.load_seed()[:12])
    for sample in samples:
        assert qm.normalize_prompt(sample) == quality._normalize(sample), (
            f"工具侧口径与 r11 测试侧不一致：{sample!r}"
        )
    # 归一后确实抹平了全半角 / 空白 / 标点差异
    assert qm.normalize_prompt("a_b c") == qm.normalize_prompt("a-b  c") == "abc"
    assert qm.normalize_prompt("   ") == ""


# --- ② 判断题 ----------------------------------------------------------------
@pytest.mark.parametrize(
    ("raw_answer", "keys", "expected"),
    [
        ("正确", ("正确", "错误"), ["A"]),  # 01 的 4 条：key 与 answer 都是中文
        ("错误", ("正确", "错误"), ["B"]),
        ("正确", ("A", "B"), ["A"]),  # 其余 116 条：key 已是 A/B、答案仍是中文
        ("错误", ("A", "B"), ["B"]),
        ("对", ("A", "B"), ["A"]),
        ("否", ("A", "B"), ["B"]),
    ],
)
def test_normalize_record_judge_answer_and_keys(
    raw_answer: str, keys: tuple[str, str], expected: list[str]
) -> None:
    """判断题一律重建 `JUDGE_OPTIONS`（A 正确 / B 错误）并把中文答案映射到 key。"""
    row = qm.normalize_record(_judge_record(raw_answer, keys), "tiji", 7)
    assert row is not None, f"判断题被误判为越界：answer={raw_answer} keys={keys}"
    assert row["options"] == [
        {"key": "A", "text": "正确"},
        {"key": "B", "text": "错误"},
    ], "判断题选项必须与存量 seed 的 36 道逐字一致（前端按 options 原样渲染）"
    assert row["answer"] == expected
    assert row["id"] == "tiji-007", "id = 前缀 + 三位源内原序"
    assert row["source"] == "tiji"
    assert list(row) == [
        "id",
        "direction",
        "kind",
        "difficulty",
        "essentiality",
        "language",
        "prompt",
        "options",
        "answer",
        "explanation",
        "source",
    ], "键序即文件格式（dumps 按它输出）"

    assert qm.normalize_record(_judge_record("不确定", ("A", "B")), "tiji", 8) is None, (
        "越界答案不得猜一个「看起来合理」的 key，必须整条丢弃并记账"
    )


# --- ③ 答案切分 --------------------------------------------------------------
@pytest.mark.parametrize(
    ("kind", "raw_answer", "expected"),
    [
        ("single", "B", ["B"]),
        ("single", "b", ["B"]),
        ("multiple", "A,B,D", ["A", "B", "D"]),
        ("multiple", "A、B、D", ["A", "B", "D"]),
        ("multiple", "A，B D", ["A", "B", "D"]),
        ("multiple", ["A", "C"], ["A", "C"]),
    ],
)
def test_normalize_record_answer_is_list(kind: str, raw_answer: Any, expected: list[str]) -> None:
    """`answer` 从字符串切成 key 列表（single 恰 1、multiple ≥2）。"""
    raw = {
        "kind": kind,
        "stem": "关于 Python 的 GIL，下列说法正确的是？",
        "options": _options(),
        "answer": raw_answer,
        "explanation": _EXPLANATION,
        "difficulty": "intermediate",
        "essentiality": "advanced",
        "language": "python",
        "direction": "后端",
    }
    row = qm.normalize_record(raw, "iq380", 3)
    assert row is not None
    assert row["answer"] == expected
    assert isinstance(row["answer"], list)


@pytest.mark.parametrize(
    ("kind", "raw_answer"),
    [("single", "A,B"), ("multiple", "A"), ("single", ""), ("single", "Z")],
)
def test_normalize_record_rejects_bad_answers(kind: str, raw_answer: str) -> None:
    """越界答案（单选多答案 / 多选单答案 / 空 / key 越界）整条丢弃，不静默改。"""
    raw = {
        "kind": kind,
        "stem": "关于 Go 的 map 并发安全，下列说法正确的是？",
        "options": _options(),
        "answer": raw_answer,
        "explanation": _EXPLANATION,
        "difficulty": "basic",
        "essentiality": "must_know",
        "language": "go",
        "direction": "后端",
    }
    assert qm.normalize_record(raw, "iq380", 4) is None


# --- ④ 方向派生 --------------------------------------------------------------
@pytest.mark.parametrize(
    ("language", "raw_direction", "expected"),
    [
        ("html", "", "前端"),  # 04-fe-interview20.json 缺 direction
        ("css", "后端", "前端"),  # 冲突：以 language 为准（后端 + css）
        ("javascript", "", None),  # 未收录语言 → 不是闭集成员 → 丢弃
        ("java", "计算机基础", "后端"),
        ("react", "算法与数据结构", "前端"),
        ("go", "", "后端"),
        ("", "计算机基础", "计算机基础"),  # 通用方向：direction_of_language 返回 None → 保留原值
        ("", "算法与数据结构", "算法与数据结构"),
        ("", "", None),  # 通用题连方向都没有 → 越界
    ],
)
def test_normalize_record_direction_derives_from_language(
    language: str, raw_direction: str, expected: str | None
) -> None:
    """方向归一只有一条派生规则：`direction_of_language(language) or 原 direction`。

    一条规则同时覆盖「缺 direction 按语言推断」「方向↔语言冲突以语言为准」
    「通用方向（算法与数据结构 / 计算机基础）恒不归属语言」三件事，不写三份代码。
    """
    raw = {
        "kind": "single",
        "stem": "以下哪项描述最符合参考答案要点？",
        "options": _options(),
        "answer": "A",
        "explanation": _EXPLANATION,
        "difficulty": "basic",
        "essentiality": "must_know",
        "language": language,
        "direction": raw_direction,
    }
    row = qm.normalize_record(raw, "local100", 1)
    if expected is None:
        assert row is None
        return
    assert row is not None
    assert row["direction"] == expected
    assert row["language"] == language, "方向纠正不得改动 language（language 才是归属来源）"
    assert row["direction"] == (
        rules.direction_of_language(language) or raw_direction
    ), "方向必须由 rules.direction_of_language() 派生，不得另写映射"


# --- ⑤ 近重复相似度 ----------------------------------------------------------
def test_ngram_jaccard_is_symmetric_and_bounded() -> None:
    """相似度对称、落在 [0, 1]、自比为 1、不相关为低值、空串不被当成「全等」。"""
    left = "关于 JavaScript 闭包下列说法正确的有"
    right = "关于 JavaScript 模块化下列说法正确的有"
    assert qm.ngram_jaccard(left, left) == pytest.approx(1.0)
    assert qm.ngram_jaccard(left, right) == pytest.approx(qm.ngram_jaccard(right, left))
    assert 0.0 <= qm.ngram_jaccard(left, right) < qm.ngram_jaccard(left, left)
    assert qm.ngram_jaccard(left, "数据库事务的隔离级别共有四种，分别是") < 0.2
    assert qm.ngram_jaccard(left, "") == 0.0
    assert qm.ngram_jaccard("", "") == 0.0
    # 归一化在比较前生效：全角 / 空白 / 标点差异不影响相似度
    assert qm.ngram_jaccard("Python 的 GIL", "Ｐｙｔｈｏｎ 的 GＩＬ") == pytest.approx(1.0)


# --- ⑥ 去重取舍 --------------------------------------------------------------
def test_merge_keeps_existing_rows_verbatim() -> None:
    """存量行恒保留：命中字面重复 / 近重复的候选被丢弃，存量行逐字不变（不补 `source`）。"""
    existing = [_row("Vue3 的 ref 与 reactive 有什么区别？", source="")]
    literal = _row("Vue3 的 ref 与 reactive 有什么区别？", source="tiji")
    near = _row("Vue3 的 ref 与 reactive 有什么区别呢？", source="local100")

    merged, stats = qm.merge_rows(existing, [literal, near])

    assert merged == existing, "存量行被改动了（只允许追加）"
    assert list(merged[0]) == list(existing[0]), "存量行不得被补上 source 键"
    assert stats["sources"]["tiji"]["literal_dup"] == 1
    assert stats["sources"]["local100"]["near_dup"] == 1
    assert qm.ngram_jaccard(existing[0]["prompt"], near["prompt"]) >= qm.NEAR_DUP_JACCARD, (
        "近重复用例本身必须真的越过阈值，否则这条断言什么也没测"
    )


def test_merge_prefers_source_priority_then_longer_explanation_then_sha1() -> None:
    """批内冲突三级取舍：来源优先级 → 解析更长者 → 题干 sha1 小者（全部确定性）。"""
    prompt = "关于 JavaScript 闭包下列说法正确的有？"

    # 1) 来源优先级：tiji 高于 iq380
    merged, stats = qm.merge_rows(
        [], [_row(prompt, source="iq380"), _row(prompt, source="tiji")]
    )
    assert [row["source"] for row in merged] == ["tiji"], "同题冲突必须取来源优先级高者"
    assert stats["sources"]["iq380"]["literal_dup"] == 1

    # 2) 同源 → 解析更长者。两条题干互为近重复（不是字面重复）。
    long_prompt = "关于 Go 的 map 并发安全下列说法正确的有，请选出全部正确项"
    short_prompt = "关于 Go 的 map 并发安全下列说法正确的有，请选出全部正确条"
    assert qm.ngram_jaccard(long_prompt, short_prompt) >= qm.NEAR_DUP_JACCARD
    merged, stats = qm.merge_rows(
        [],
        [
            _row(long_prompt, source="local100", explanation=_EXPLANATION),
            _row(short_prompt, source="local100", explanation=_EXPLANATION + "补充一句更长。"),
        ],
    )
    assert [row["prompt"] for row in merged] == [short_prompt], "同源冲突必须取解析更长者"
    assert stats["sources"]["local100"]["near_dup"] == 1

    # 3) 解析长度也相同 → 题干 sha1 小者（同名同长的两条，取舍完全可复现）
    first = "关于 CSS 相邻兄弟选择器下列说法正确的有，请选出全部正确项"
    second = "关于 CSS 相邻兄弟选择器下列说法正确的有，请选出全部正确条"
    assert qm.ngram_jaccard(first, second) >= qm.NEAR_DUP_JACCARD
    hashes = {
        qm.normalize_prompt(first): hashlib.sha1(qm.normalize_prompt(first).encode()).hexdigest(),
        qm.normalize_prompt(second): hashlib.sha1(qm.normalize_prompt(second).encode()).hexdigest(),
    }
    winner = min(hashes, key=lambda key: hashes[key])
    merged, _stats = qm.merge_rows(
        [], [_row(first, source="iq380"), _row(second, source="iq380")]
    )
    assert [qm.normalize_prompt(row["prompt"]) for row in merged] == [winner], (
        "同源同长的冲突必须按题干 sha1 小者取舍（否则每次运行结果可能不同）"
    )

    # 4) 交叉来源的追加顺序：来源序（SOURCES）→ 源内原序（id）
    merged, _stats = qm.merge_rows(
        [],
        [
            _row("iq380 来源的第一题题干足够长以便区分", source="iq380"),
            _row("tiji 来源的第一题题干足够长以便区分", source="tiji"),
        ],
    )
    assert [row["source"] for row in merged] == ["tiji", "iq380"], "写盘顺序按 SOURCES"


# --- ⑦ 幂等与字节级序列化 -----------------------------------------------------
def test_dumps_reproduces_current_seed_bytes() -> None:
    """`dumps()` 逐字节复现已提交 seed；前 260 行仍是冻结基线（R13_SEED_BYTES 字节）。"""
    raw = qm.SEED_PATH.read_bytes()
    rows = json.loads(raw.decode("utf-8"))
    assert len(rows) == EXPECTED_TOTAL
    assert qm.dumps(rows).encode("utf-8") == raw, "dumps() 与已提交 seed 不一致（--check 永不成立）"

    legacy = qm.dumps(rows[:260]).encode("utf-8")
    assert len(legacy) == R13_SEED_BYTES, "存量 260 行的字节数变了（动了历史数据或格式）"
    assert hashlib.sha256(legacy).hexdigest() == R13_SEED_SHA256, (
        "存量 260 行的内容变了（等长改写也算）：这一块必须与 r13 基线逐字节一致，"
        "改它等于改历史数据，需要产品确认并同步更新 R13_SEED_SHA256"
    )
    assert raw.startswith(legacy[:-3]), "前 260 行必须与 r13 基线逐字节一致"
    assert raw[len(legacy) - 3 : len(legacy) - 2] == b",", "存量块之后应紧跟新增块"

    indented = json.dumps(rows, ensure_ascii=False, indent=2)
    assert len(indented.encode("utf-8")) != len(raw), (
        "序列化退化成了 json.dump(indent=2)：那等于把整个文件重写一遍，--check 不可能 0 差异"
    )


def test_merge_is_idempotent_byte_identical() -> None:
    """`--write` 可重复：每次重算都得到同一串字节，且与磁盘上的 seed 一致（`--check` 成立）。"""
    first, stats = qm.build_seed()
    assert qm.dumps(first).encode("utf-8") == qm.SEED_PATH.read_bytes(), "重算结果与磁盘 seed 不一致"
    assert stats["total"]["added"] == 778, "按素材重算应恒报 778 条新增（上一批不当作存量）"
    assert stats["total"]["read"] == 778
    assert stats["total"]["literal_dup"] == 0
    assert stats["total"]["near_dup"] == 0
    assert stats["total"]["out_of_range"] == 0
    assert stats["total"]["corrected"] == 9, "方向↔语言冲突必须恰好纠正 9 条（TECH-CHANGE §3.1）"
    assert stats["total"]["derived"] == 20, "04-fe-interview20.json 的 20 条方向由语言推断"
    assert qm.check(), "--check 必须 0 差异"

    second, again = qm.build_seed()
    assert qm.dumps(second) == qm.dumps(first), "两次重算的字节不同（不稳定 → --check 抖动）"
    assert second == first
    assert again["total"] == stats["total"]


# --- ⑧ 数据不变量 ------------------------------------------------------------
def test_seed_has_no_literal_or_near_duplicates() -> None:
    """字面重复全局 0；**本批新增行**不参与任何 ≥0.62 的近重复对（存量 260 行 r12 不动）。

    存量 260 行内部有一对 0.717 的近似题（JavaScript「闭包」↔「模块化」通用题干模板，
    r11 时代就存在）。r12 的口径是「只增不删」，因此这条只钉本批 519 行；
    删改存量行是另一件事（会同时破坏 `test_dumps_reproduces_current_seed_bytes`）。
    """
    rows = question_bank.load_seed()
    assert len(rows) == EXPECTED_TOTAL

    prompts = [qm.normalize_prompt(str(row["prompt"])) for row in rows]
    duplicated = [text for text, count in Counter(prompts).items() if count > 1]
    assert not duplicated, f"题库出现字面重复题干：{duplicated[:3]}"

    grams = [
        {text[index : index + qm.NGRAM] for index in range(len(text) - qm.NGRAM + 1)}
        for text in prompts
    ]
    offenders: list[tuple[str, str, float]] = []
    for left_index, left in enumerate(rows):
        for right_index in range(left_index + 1, len(rows)):
            right = rows[right_index]
            if not (left.get("source") or right.get("source")):
                continue  # 存量 ↔ 存量：r12 不处理（见 docstring）
            first, second = grams[left_index], grams[right_index]
            union = first | second
            if not union:
                continue
            # 长度差本身就能排除：Jaccard ≤ min/max，比值低于阈值时不可能命中
            shorter, longer = sorted((len(first), len(second)))
            if not longer or shorter / longer < qm.NEAR_DUP_JACCARD:
                continue
            score = len(first & second) / len(union)
            if score < qm.NEAR_DUP_JACCARD:
                continue
            offenders.append((str(left["id"]), str(right["id"]), score))
    assert not offenders, f"本批出现近重复（≥{qm.NEAR_DUP_JACCARD}）：{offenders[:3]}"

    # 工具侧相似度与上面这份「测试侧」算法必须一致（否则阈值实际生效值不可信）
    probe = qm.ngram_jaccard(rows[0]["prompt"], rows[1]["prompt"])
    first, second = grams[0], grams[1]
    assert probe == pytest.approx(len(first & second) / len(first | second))


def test_seed_source_enum_and_counts() -> None:
    """来源枚举闭合、每来源计数与蓝图一致；存量行不写 `source`，新行前缀与来源对应。"""
    rows = question_bank.load_seed()
    counts = Counter(str(row.get("source") or "seed") for row in rows)
    assert dict(counts) == EXPECTED_SOURCES, f"来源分布不符：{dict(counts)}"
    assert set(counts) == {"seed"} | set(qm.SOURCES)
    assert set(qm.STAGING_FILES) == set(qm.SOURCES) == set(qm.ID_PREFIX)

    for row in rows:
        source = str(row.get("source") or "")
        if source:
            assert source in qm.SOURCES, f"{row['id']} 的 source 越界：{source}"
            assert str(row["id"]).startswith(qm.ID_PREFIX[source]), (
                f"{row['id']} 的 id 前缀与来源 {source} 不符"
            )
        else:
            assert "source" not in row, (
                f"{row['id']} 存量行被写上了 source：新库/旧库/种子会分叉（TECH-CHANGE §7-④）"
            )

    ids = [str(row["id"]) for row in rows]
    assert len(ids) == len(set(ids)), "id 重复"
    for source in qm.SOURCES:
        batch = [row for row in rows if str(row.get("source") or "") == source]
        assert len(batch) == EXPECTED_SOURCES[source], f"{source} 条数不符"
        assert all(str(row["kind"]) in rules.OBJECTIVE_KINDS for row in batch), (
            f"{source} 混入了非客观题（本批素材全为 single/multiple/judge）"
        )


# --- ⑨ 回滚 -----------------------------------------------------------------
def test_rollback_deletes_only_batch_sources(tmp_db: Path) -> None:
    """回滚只删本批 8 个来源（1038 → 260），且幂等（再跑一次删 0 行）。绝不碰存量行。"""
    total = question_bank.ensure_seeded()
    assert total == EXPECTED_TOTAL, f"导入后总量 {total} ≠ {EXPECTED_TOTAL}"

    # 库里的存量行是 `_row_of()` 写的缺省 `'seed'`（种子行没有 source 键，入库后补缺省值）。
    legacy_ids = {
        str(row["id"])
        for row in question_bank.load_questions()
        if str(row.get("source")) == "seed"
    }
    assert len(legacy_ids) == EXPECTED_SOURCES["seed"]

    removed = qm.rollback()
    assert removed == EXPECTED_TOTAL - EXPECTED_SOURCES["seed"], "回滚删除的必须是本批 778 行"
    assert repository.count_questions() == EXPECTED_SOURCES["seed"]
    assert qm.rollback() == 0, "回滚必须幂等（未导入 / 已删过 → 0）"

    remaining = {str(row["id"]) for row in question_bank.load_questions()}
    assert remaining == legacy_ids, "回滚误删或改动了存量行"
    prefixes = tuple(qm.ID_PREFIX.values())
    assert not any(row_id.startswith(prefixes) for row_id in remaining)

    assert repository.delete_questions_by_source([]) == 0, "空来源列表不得生成非法占位符"
    assert repository.delete_questions_by_source(["不存在的来源"]) == 0


def test_rollback_reports_uninitialized_db_without_creating_it(
    monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    """QA D-3：库不存在/未初始化时回滚给中文原因 + 非 0 退出码，不打栈、不建 0 字节库。"""
    scratch = Path(__file__).resolve().parent / ".tmp"
    scratch.mkdir(parents=True, exist_ok=True)
    missing = scratch / f"{uuid4().hex}-uninit.db"
    monkeypatch.setenv("DB_PATH", str(missing))
    get_settings.cache_clear()
    try:
        with pytest.raises(qm.RollbackUnavailable):
            qm.rollback()
        assert not missing.exists(), "回滚不得把未初始化的库顺手创建成 0 字节文件"

        code = qm.main(["--rollback"])
        out = capfd.readouterr().out
        assert code != 0, "未初始化库上回滚必须失败退出（不是 exit 0 的假成功）"
        assert "无法回滚" in out and "未初始化" in out, "必须给中文原因，提示先启动后端"
        assert "Traceback" not in out, "不得把 sqlite3 异常原样抛给使用者"
        assert not missing.exists()
    finally:
        get_settings.cache_clear()
        missing.unlink(missing_ok=True)


# --- ⑩ 许可 ----------------------------------------------------------------
def test_license_notice_present_when_third_party_source_in_seed() -> None:
    """seed 里只要出现 `source=fe-interview`，就必有含 https 上游链接的 MIT NOTICE。

    确认不了上游 URL 时整源剔除（857 → 837），这条自动放行 —— 两条路都合规，绝不伪造 URL。
    """
    rows = question_bank.load_seed()
    third_party = [row for row in rows if str(row.get("source") or "") == "fe-interview"]
    if not third_party:
        pytest.skip("seed 未收录 fe-interview（整源剔除后全库 759），无需 NOTICE")

    assert NOTICE_PATH.is_file(), f"引入 MIT 素材却没有许可凭证：{NOTICE_PATH}"
    text = NOTICE_PATH.read_text(encoding="utf-8")
    assert "MIT License" in text, "NOTICE 缺 MIT 许可证全文"
    assert "Copyright (c) 2019 haizhilin" in text, "NOTICE 缺上游版权行（照抄上游 LICENSE）"
    assert re.search(r"https://github\.com/haizlin/fe-interview\b", text), "NOTICE 缺可访问的上游 URL"
    assert "改写" in text, "NOTICE 必须说明这是 AI 改写版而不是原样转载"
    assert len(third_party) == EXPECTED_SOURCES["fe-interview"]
    assert all(len(row["options"]) == 4 for row in third_party), "改写后应统一为四选一"
    assert all(str(row["language"]) in ("html", "css", "js") for row in third_party), (
        "fe-interview 只覆盖前端三语言"
    )


# --- ⑪ 正文元信息（r15） ------------------------------------------------------
#: r12 合并素材时残留的**编辑用语**：题干以「以下哪种做法最符合参考答案要点？」收尾，
#: 解析以「参考答案要点：」开头。它暴露的是出题过程而非考点，r15 起由
#: `question_merge.sanitize_text()` 在流水线里清理，本段是常驻门禁（防素材重导入回潮）。
META_PHRASE = "参考答案要点"

#: 清理前后应命中的替换次数（occurrence 级：题干 45 + 解析 15，两者重叠 11 道）。
#: 素材若重新导入，这个数变了就要同步复核并在任务夹留痕（与 EXPECTED_TOTAL 同理）。
META_PHRASE_HITS = 60


def test_sanitize_text_only_rewrites_meta_phrase() -> None:
    """`sanitize_text()` 只替换 `_TEXT_REWRITES` 列出的字段与原串：返回新字典、不改入参、二次调用无变化。"""
    row = _row(
        "以下哪种做法最符合参考答案要点？",
        explanation="参考答案要点：先读后写，再考虑加锁。",
    )
    snapshot = json.loads(json.dumps(row, ensure_ascii=False))
    cleaned = qm.sanitize_text(row)
    assert cleaned is not row, "必须返回新字典（就地改会让「重算 vs 已提交 seed」的比对失去意义）"
    assert row == snapshot, "入参被就地修改"
    assert cleaned == {
        **snapshot,
        "prompt": "以下哪种做法最符合要求？",
        "explanation": "参考要点：先读后写，再考虑加锁。",
    }, "除固定串外题干/解析必须逐字不动（替换不是改写）"
    assert qm.sanitize_text(cleaned) == cleaned, "替换后不含原串，二次调用必须无变化（幂等）"

    plain = _row("以下哪项是 Python 的不可变类型？")
    assert qm.sanitize_text(plain) == plain, "不含该串的行必须零改动"
    assert "source" in qm.sanitize_text(plain), "清理不得丢掉 `source` 等非正文键"


def test_seed_text_has_no_staging_meta_phrase() -> None:
    """落盘 seed 的题干/解析不得再含「参考答案要点」（r15 门禁：读磁盘、不读重算结果）。"""
    rows = question_bank.load_seed()
    offenders = [
        (str(row["id"]), field)
        for row in rows
        for field in ("prompt", "explanation")
        if META_PHRASE in str(row.get(field) or "")
    ]
    assert not offenders, f"题干/解析仍含素材编辑用语：{offenders[:5]}"


def test_sanitize_text_only_touches_meta_phrase_in_real_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """真实数据对拍：seed 的题干/解析 = 未清理版本**只**做固定串替换（防止顺手改题）。

    把 `sanitize_text()` 临时换成恒等函数再跑一次 `build_seed()`，与落盘 seed 逐题比正文。
    只比 `prompt` / `explanation`：选项重排的定位哈希与题干文本相关，清理会改变分配结果，
    比 `answer` / `options` 只会产生与本次清理无关的误红。
    """
    identity: Any = lambda row: row  # noqa: E731
    monkeypatch.setattr(qm, "sanitize_text", identity)
    uncleaned, _ = qm.build_seed()
    rows = question_bank.load_seed()
    assert [row["id"] for row in uncleaned] == [row["id"] for row in rows], (
        "重算与落盘 seed 的题序/题量不一致：对拍前提不成立"
    )

    hits = 0
    for before, after in zip(uncleaned, rows, strict=True):
        for key in ("id", "direction", "kind", "difficulty", "essentiality", "language"):
            assert after[key] == before[key], f"{before['id']} 的 {key} 被正文清理波及"
        for field, old, new in qm._TEXT_REWRITES:
            value = str(before[field])
            hits += value.count(old)
            assert str(after[field]) == value.replace(old, new), (
                f"{before['id']} 的 {field} 与「只把 {old} 换成 {new}」不符（可能顺手改了题）"
            )
    assert hits == META_PHRASE_HITS, (
        f"清理命中 {hits} 处，与 r15 核定的 {META_PHRASE_HITS} 处不符：素材已变，需重新复核口径"
    )
