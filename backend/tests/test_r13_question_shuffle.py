"""r13 常驻门禁：答案位置分布 / 判断题极性 / 答案长度比 / key 闭集 / 解析引用 / 幂等。

口径一律从工具派生：位置与极性读 `seed` 并经 `question_shuffle.apply()` 的指标复算，
判断题选项文案引用 `question_merge.JUDGE_OPTIONS`（不另抄字面量），解析引用统一走
`question_shuffle.classify_refs()`（不在本文件复制正则）。
"""

from __future__ import annotations

import json
import os
import statistics
from collections import Counter
from pathlib import Path

import pytest

from app.services.assessment import question_merge, question_shuffle

#: 单选答案四个位置的占比区间（需求「20%–30% 且任一位置 ≤35%」，上界抬到 32% 容纳 551 样本抽样波动）。
SINGLE_POSITION_RATIO = (0.20, 0.32)
#: 判断题「正确」占比区间（156 样本 p=0.5 时 σ≈4%，取 ±10% ≈ 2.5σ）。
JUDGE_TRUE_RATIO = (0.40, 0.60)
#: >3x 的答案长度比条数上限（r14 · P3-2 起由 `LENGTH_REWRITES` 改写，必须为 0）。
MAX_LONG_ANSWER_COUNT = 0
#: 2–3x 的抽检门槛（只出清单，不自动改写语义）。
LENGTH_RATIO_SPOTCHECK = 2.0
#: 判断题极性改写表条数（r13 的 29 条 + r14（P3-3）双向调整后的净条数）。
JUDGE_FLIP_COUNT = 38
#: 按语言分桶的门禁：单选样本 ≥20 才断言 20%–32%，判断题样本 ≥6 才断言 40%–60%。
MIN_SINGLE_SAMPLE_PER_LANGUAGE = 20
MIN_JUDGE_SAMPLE_PER_LANGUAGE = 6

SEED_PATH = Path(
    os.environ.get("R13_SEED_PATH")
    or (Path(__file__).resolve().parents[1] / "app" / "seed" / "questions.json")
)
#: `R13_SEED_PATH` 是**变红证据**用的只读注入点：指向一份刻意变异的 seed，门禁必须红。
#: 默认值永远是仓库里被 git 追踪的那份，CI 不设该变量。


def _seed_rows() -> list[dict[str, object]]:
    return json.loads(SEED_PATH.read_text(encoding="utf-8"))


def _shuffled() -> tuple[list[dict[str, object]], dict[str, object]]:
    """磁盘 seed 经工具重算：`apply()` 是幂等的，故这里等价于「线上行的分布」。"""
    return question_shuffle.apply(_seed_rows())


def _distribution(rows: list[dict[str, object]], kind: str) -> Counter[str]:
    return Counter(
        str(row["answer"][0])  # type: ignore[index]
        for row in rows
        if str(row["kind"]) == kind and isinstance(row.get("answer"), list)
        and len(row["answer"]) == 1  # type: ignore[arg-type]
    )


def test_single_option_positions_balanced() -> None:
    """单选答案落在哪一位置必须均衡（「全选 A」不再能白拿多数题）。"""
    rows, _metrics = _shuffled()
    counts = _distribution(rows, "single")
    total = sum(counts.values())
    assert total > 0, "没有单选题，分布门禁失去意义"
    ratios = {key: counts.get(key, 0) / total for key in question_shuffle.KEYS}
    low, high = SINGLE_POSITION_RATIO
    offenders = {key: round(value, 3) for key, value in ratios.items() if not low <= value <= high}
    assert not offenders, f"单选位置占比越界（区间 {low}-{high}）：{offenders}，实际 {ratios}"


def test_committed_seed_is_already_balanced() -> None:
    """**落盘**的 seed 分布必须已经是修好的（并集口径：全部单选 / 全部判断题）。

    这条与上一条分工：上一条管「工具是否会把偏置改回来」（退化即红），这一条管
    「提交进仓库的数据是否真的修过」——忘跑 `--write`、手改 seed、新增题没重算，
    都会先在这里变红（TECH-CHANGE §6 的变红证据正是靠它）。
    """
    rows = _seed_rows()
    counts = _distribution(rows, "single")
    total = sum(counts.values())
    assert total > 0, "没有单选题，分布门禁失去意义"
    low, high = SINGLE_POSITION_RATIO
    ratios = {key: counts.get(key, 0) / total for key in question_shuffle.KEYS}
    offenders = {key: round(value, 3) for key, value in ratios.items() if not low <= value <= high}
    assert not offenders, (
        f"落盘 seed 的单选位置占比越界（区间 {low}-{high}）：{offenders}，实际 {ratios}；"
        "偏置题库可能没跑 --write"
    )

    judge_counts = _distribution(rows, "judge")
    judge_total = sum(judge_counts.values())
    assert judge_total > 0
    judge_low, judge_high = JUDGE_TRUE_RATIO
    true_ratio = judge_counts.get("A", 0) / judge_total
    assert judge_low <= true_ratio <= judge_high, (
        f"落盘 seed 的判断题「正确」占比 {true_ratio:.3f} 越界 {judge_low}-{judge_high}；"
        "29 条极性改写可能没落盘"
    )


def test_judge_polarity_half_half() -> None:
    """判断题「正确 / 错误」近似 50 / 50（只改陈述、不动两选项顺序）。"""
    rows, _metrics = _shuffled()
    counts = _distribution(rows, "judge")
    total = sum(counts.values())
    assert total > 0
    true_ratio = counts.get("A", 0) / total
    low, high = JUDGE_TRUE_RATIO
    assert low <= true_ratio <= high, f"判断题「正确」占比 {true_ratio:.3f} 越界 {low}-{high}"


def _by_language(rows: list[dict[str, object]], kind: str) -> dict[str, Counter[str]]:
    """按 `language` 分桶的答案 key 计数（`""` 是通用题，不是「未填」）。"""
    buckets: dict[str, Counter[str]] = {}
    for row in rows:
        if str(row["kind"]) != kind or not isinstance(row.get("answer"), list):
            continue
        if len(row["answer"]) != 1:  # type: ignore[arg-type]
            continue
        language = str(row.get("language") or "")
        buckets.setdefault(language, Counter())[str(row["answer"][0])] += 1  # type: ignore[index]
    return buckets


def test_single_positions_balanced_per_language() -> None:
    """P3-4：单选按 `language` 分桶后，每个语言子集也要落在 20%–32%（样本 ≥20 才断言）。

    全局分布达标不代表子集达标：整体均衡时某一语言仍可能「几乎全 A」，按语言出题
    的练习就会重新暴露偏置。`by_language` 指标必须与实时重算分布逐桶一致。
    """
    rows, metrics = _shuffled()
    buckets = _by_language(rows, "single")
    low, high = SINGLE_POSITION_RATIO
    offenders: dict[str, dict[str, float]] = {}
    for language, counts in sorted(buckets.items()):
        total = sum(counts.values())
        if total < MIN_SINGLE_SAMPLE_PER_LANGUAGE:
            continue
        ratios = {key: counts.get(key, 0) / total for key in question_shuffle.KEYS}
        if not all(low <= value <= high for value in ratios.values()):
            offenders[language or "（通用）"] = {key: round(value, 3) for key, value in ratios.items()}
    assert not offenders, f"按语言分桶的单选位置占比越界（区间 {low}-{high}）：{offenders}"

    reported = metrics["single"]["by_language"]["after"]  # type: ignore[index]
    expected = {
        language: {key: counts.get(key, 0) for key in question_shuffle.KEYS}
        for language, counts in buckets.items()
    }
    assert reported == expected, "single.by_language 指标与实时重算分布不一致"


def test_judge_polarity_half_half_per_language() -> None:
    """P3-4：判断题按 `language` 分桶后，每个语言子集的「正确」占比落在 40%–60%。

    样本 ≥6 才断言（小样本 ±1 题就是 8%+ 的摆动）；`by_language` 指标同样要与
    实时重算逐桶一致，否则报表里的「按语言表」可以悄悄写错。
    """
    rows, metrics = _shuffled()
    buckets = _by_language(rows, "judge")
    low, high = JUDGE_TRUE_RATIO
    offenders: dict[str, float] = {}
    for language, counts in sorted(buckets.items()):
        total = sum(counts.values())
        if total < MIN_JUDGE_SAMPLE_PER_LANGUAGE:
            continue
        ratio = counts.get("A", 0) / total
        if not low <= ratio <= high:
            offenders[language or "（通用）"] = round(ratio, 3)
    assert not offenders, f"按语言分桶的判断题「正确」占比越界（区间 {low}-{high}）：{offenders}"

    reported = metrics["judge"]["by_language"]["after"]  # type: ignore[index]
    expected = {
        language: {key: counts.get(key, 0) for key in question_shuffle.KEYS}
        for language, counts in buckets.items()
    }
    assert reported == expected, "judge.by_language 指标与实时重算分布不一致"


def test_judge_options_stay_two_choices() -> None:
    """判断题选项恒为 `question_merge.JUDGE_OPTIONS` 两项且顺序固定（打乱不得动它）。"""
    expected = [item["text"] for item in question_merge.JUDGE_OPTIONS]
    for row in _shuffled()[0]:
        if str(row["kind"]) != "judge":
            continue
        assert [str(opt["text"]) for opt in row["options"]] == expected, row["id"]  # type: ignore[index]


def test_option_keys_are_positions_in_order() -> None:
    """`options` 数组顺序必须恒等于 key 位置序（A..D），答案 key 必须是位置的子集。"""
    for row in _shuffled()[0]:
        if str(row["kind"]) not in ("single", "multiple"):
            continue
        keys = [str(opt["key"]) for opt in row["options"]]  # type: ignore[index]
        assert keys == list(question_shuffle.KEYS), f"{row['id']} 的 key 不是位置序：{keys}"
        answer = [str(key) for key in row["answer"]]  # type: ignore[union-attr]
        assert answer and set(answer) <= set(keys), f"{row['id']} 的 answer 越界：{answer}"


def test_long_answer_ratio_within_budget() -> None:
    """>3x 的「正确项远长于干扰项」条数必须为 0（P3-2 起由 `LENGTH_REWRITES` 自动压缩）。"""
    _rows, metrics = _shuffled()
    ratio = metrics["length_ratio"]  # type: ignore[index]
    assert int(ratio["sample"]) > 0
    assert len(ratio["long"]) <= MAX_LONG_ANSWER_COUNT, (
        f">3x 的题过多（{len(ratio['long'])} > {MAX_LONG_ANSWER_COUNT}）："
        f"{[item['id'] for item in ratio['long']][:5]}"
    )
    assert float(ratio["median"]) <= LENGTH_RATIO_SPOTCHECK, (
        f"答案长度比中位 {ratio['median']} 已超过抽检线 {LENGTH_RATIO_SPOTCHECK}"
    )


def test_length_rewrites_are_current() -> None:
    """P3-2：改写表的 `before` 必须与 seed 现状逐字对得上（stale 为空）。

    `stale` 非空 = 表里某题的正确项既不是 `before` 也不是 `after`（素材/存量被换过，
    这张绝对映射表已失效）。此时改写会静默跳过、比值门禁随之失守，必须先人工复核。
    """
    _rows, metrics = _shuffled()
    rewrites = metrics["length_rewrites"]  # type: ignore[index]
    assert not rewrites["stale"], f"改写表基线失配（正确项既非 before 也非 after）：{rewrites['stale']}"
    assert len(question_shuffle.LENGTH_REWRITES) > 0, "改写表为空，P3-2 等于没做"
    covered = set(rewrites["applied"]) | set(rewrites["already"])
    assert covered == set(question_shuffle.LENGTH_REWRITES), (
        "改写表里的每一条都必须在流水线里被识别（applied 或 already）"
    )


def test_shuffled_rows_have_no_unparseable_letter_refs() -> None:
    """真的被重排过的题，解析里不得残留「无法判角」的字母。

    「谁被打乱」只从工具指标 `metrics["skipped"]["ids"]` 读：若改用 `classify_refs`
    的返回值判定同一件事，断言会与被断言对象同义而恒真（等于没有门禁）。
    """
    rows, metrics = _shuffled()
    skipped = {str(item) for item in metrics["skipped"]["ids"]}  # type: ignore[index]
    total_movable = [row for row in rows if str(row["kind"]) in ("single", "multiple")]
    movable = [row for row in total_movable if str(row["id"]) not in skipped]
    # 指标与行之间的账必须对得上：否则「跳过」口径可以悄悄偏向任何一边。
    assert len(movable) + len(skipped & {str(row["id"]) for row in total_movable}) == len(
        total_movable
    ), "skipped 计数与可重排题数不自洽"
    assert movable, "没有任何一道题被打乱，门禁失效"
    dangling: dict[str, list[int]] = {}
    for row in movable:
        valid = {str(opt["key"]) for opt in row["options"]}  # type: ignore[index]
        _refs, unknown = question_shuffle.classify_refs(str(row.get("explanation") or ""), valid)
        if unknown:
            dangling[str(row["id"])] = unknown
    assert not dangling, f"打乱后的题残留无法判角的字母引用：{sorted(dangling.items())[:3]}"


def test_explanation_refs_stay_consistent_with_answers() -> None:
    """重编 key 后解析的字母引用必须仍与 `answer` 自洽（本轮最大技术风险的兜底门禁）。

    口径直接读工具的双校验指标：`X 项错误 ⇔ X ∉ answer`、`正确项集合 == answer`。
    """
    _rows, metrics = _shuffled()
    refs = metrics["refs_consistency"]  # type: ignore[index]
    assert int(refs["pairs"]) > 0, "一处字母引用都没校验到，说明口径失效"
    assert refs["ok"] is True, f"解析引用与答案错位：{refs['violations'][:3]}"
    assert not refs["violations"], f"解析引用与答案错位：{refs['violations'][:3]}"
    # 白名单只在真出现违规时才登记（reviewed 非空＝还有未修的错位被豁免，必须红）。
    assert not refs["reviewed"], f"仍有被豁免的错位引用：{refs['reviewed']}"


def test_judge_flip_table_is_self_consistent() -> None:
    """绝对映射表自洽：条数、id 唯一、答案落在表内声明的 key、题面已生效。

    r14（P3-3）起表是**双向**的：`answer` 缺省 `B`（正确→错误），显式 `A` 表示把
    伪命题改写成真命题。两个方向都必须存在，否则「单向翻转」会悄悄退化成
    「只把正确改错、永远不补真命题」。
    """
    flips = question_shuffle.JUDGE_FLIPS
    assert len(flips) == JUDGE_FLIP_COUNT, f"翻转表条数 {len(flips)} 与常量 {JUDGE_FLIP_COUNT} 不一致"
    ids = [str(item["id"]) for item in flips]
    assert len(set(ids)) == len(ids), f"翻转表 id 重复：{ids}"
    directions = {str(item.get("answer") or "B") for item in flips}
    assert directions == {"A", "B"}, f"翻转表必须同时含 A→B 与 B→A 两个方向，实际 {directions}"
    rows = {str(row["id"]): row for row in _shuffled()[0]}
    missing = [item_id for item_id in ids if item_id not in rows]
    assert not missing, f"翻转表引用了不存在的题：{missing}"
    for item in flips:
        row = rows[str(item["id"])]
        expected = [str(item.get("answer") or "B")]
        assert str(row["kind"]) == "judge", f"{item['id']} 不是判断题"
        assert str(row["prompt"]) == str(item["statement"]), f"{item['id']} 题面未按表改写"
        assert [str(key) for key in row["answer"]] == expected, (
            f"{item['id']} 改写后答案应为 {expected}，实际 {row['answer']}"
        )


def test_apply_is_idempotent() -> None:
    """`apply(apply(rows)) == apply(rows)`：`--write` 重读已打乱的 seed 后必须收敛。"""
    rows = _seed_rows()
    snapshot = json.dumps(rows, ensure_ascii=False, sort_keys=True)
    once, metrics_once = question_shuffle.apply(rows)
    twice, metrics_twice = question_shuffle.apply(once)
    # 纯函数契约：`build_seed()` 会把同一份列表交给下游，原地改写会污染上游统计。
    assert json.dumps(rows, ensure_ascii=False, sort_keys=True) == snapshot, "apply() 改写了入参"
    assert twice == once, "apply() 不幂等：重算会与磁盘 seed 分叉"
    assert metrics_twice["single"]["after"] == metrics_once["single"]["after"]
    assert metrics_twice["skipped"]["count"] == metrics_once["skipped"]["count"]


def test_seed_bytes_are_reproducible() -> None:
    """`question_merge.dumps()` 重算结果与磁盘 seed 逐字节一致（序列化出口只有一处）。"""
    rows, _metrics = _shuffled()
    expected = question_merge.dumps(rows).encode("utf-8")
    assert SEED_PATH.read_bytes() == expected, "seed 与重算不一致：先跑 --write 再提交"
    assert len(rows) == int(json.loads(SEED_PATH.read_text(encoding="utf-8")).__len__())


@pytest.mark.parametrize("kind", ["single", "multiple"])
def test_explanation_not_empty(kind: str) -> None:
    """打乱没把解析写坏：客观题解析仍非空且长度 ≥ 10。"""
    lengths = [
        len(str(row.get("explanation") or ""))
        for row in _shuffled()[0]
        if str(row["kind"]) == kind
    ]
    assert lengths and min(lengths) >= 10, f"{kind} 有解析过短：{sorted(lengths)[:5]}"
    assert statistics.median(lengths) >= 10


def test_shuffle_report_matches_recomputed_metrics() -> None:
    """报表必须与 `--write` 的同一次重算同源：手改报表或忘跑 `--write` 即红。

    r13 交付自检抓到过一份陈旧的「打乱前」行（数字既不等于本次重算的输入、
    也不等于 r12 基线），原因是报表没跟着最后一次 `--write` 重生成；本断言把那次的
    「报表落后于数据」钉成常驻红点，避免下次重算再出现「证据与数据分叉」。
    """
    _, stats = question_merge.build_seed(question_merge.STAGING_DIR, question_merge.SEED_PATH)
    expected = question_shuffle.render_report(stats["shuffle"])
    actual = question_shuffle.REPORT_PATH.read_text(encoding="utf-8")
    assert actual == expected, "SHUFFLE-REPORT.md 与重算指标不一致：重跑 --write 生成报表"
