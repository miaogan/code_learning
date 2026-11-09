"""r7 AC-1/2/3 知识薄弱地图：把**已计分**的客观题按「方向 × 难度 × 必备级别」重新分组投影。

本模块是 `diagnosis` 的**第二次投影**，刻意不做两件事：
1. **不重算分**：题源一律 `diagnosis._scored(run)`（与短板主轴同一循环、同一判分口径），
   简答题天然不产出分数，因此不进分子也不进分母（AC-3 的硬约束）。
2. **不猜标签**：难度/必备级别取「payload 自带的闭集值优先 → 题库行兜底 → 两处都没有则该组
   两列均为 `[]`」，绝不填默认档（题库外的面试题本来就没有这两个维度）。

排序键为全序且可复算（`必备rank → 错误率↓ → 均分↑ → 题量↓ → key`），因此同一份 runs 两次
调用逐字相同，AI 成败都不影响顺序（AC-19）。
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

from app.schemas import WeaknessItem, WeaknessSample
from app.services.assessment import question_bank
from app.services.report import diagnosis, rules
from app.services.report.markdown import format_score
from app.services.resume import coach_copy

#: 单条薄弱分组的证据条数上限（与短板卡「一条证据」不同，这里给 1–3 条）。
SAMPLE_LIMIT = 3

#: 必备度档位权重：取 `rules.ESSENTIALITIES` 的**下标**（不复制闭集字面量）。
ESSENTIALITY_RANK: dict[str, int] = {
    value: index for index, value in enumerate(rules.ESSENTIALITIES)
}

#: 无必备度标签的组排在有标签的组之后（`must_know`=0 ... 无标签=闭集长度）。
UNLABELED_RANK: int = len(rules.ESSENTIALITIES)


@dataclass(frozen=True)
class _Group:
    """一个分组的累计态：标签在首次遇到时定下，之后同 key 的题一律并入。"""

    point: str
    direction: str
    difficulty: list[str]
    essentiality: list[str]


def _closed(value: Any, closed: tuple[str, ...]) -> list[str]:
    """闭集取值：命中返回单元素列表，未命中返回 `[]`（不猜、不兜底到首档）。"""
    text = str(value or "").strip()
    return [text] if text in closed else []


def _labels_of(
    question: dict[str, Any], bank: dict[str, dict[str, Any]]
) -> tuple[list[str], list[str], str]:
    """取 (难度, 必备级别, 方向)：payload 自带值优先，题库行兜底，都没有就留空。"""
    row = bank.get(str(question.get("id") or "")) or {}
    difficulty = _closed(
        question.get("difficulty") or row.get("difficulty"), rules.DIFFICULTIES
    )
    essentiality = _closed(
        question.get("essentiality") or row.get("essentiality"), rules.ESSENTIALITIES
    )
    direction = str(question.get("direction") or row.get("direction") or "").strip()
    return difficulty, essentiality, direction


def _bank_index() -> dict[str, dict[str, Any]]:
    """题库索引（每份报告只建一次）；题库不可用时降级成空索引，标签留空而不是报错。"""
    try:
        rows = question_bank.load_questions()
    except Exception:  # 题库不可用属于运行时环境问题，不该让报告挂掉
        return {}
    return {str(row.get("id") or ""): row for row in rows if row.get("id")}


def _sub_direction_of(
    question: dict[str, Any], bank: dict[str, dict[str, Any]], direction: str
) -> str:
    """r49：payload 自带值优先、题库行兜底；只认该方向闭集内的合法值，取不到留空。

    与 `_labels_of` 同一口径：不猜、不填默认档。面试题与早期 payload 都没有这个维度，
    一律空串，调用方据此回落方向级选章。
    """
    row = bank.get(str(question.get("id") or "")) or {}
    value = str(question.get("sub_direction") or row.get("sub_direction") or "").strip()
    if not value or not rules.is_valid_sub_direction(direction, value):
        return ""
    return value


def _dominant_sub_direction(counts: Counter[str], direction: str) -> str:
    """组内众数；平局按 `rules.SUBDIRECTIONS` 顺序取靠前者，保证逐字可复算。"""
    if not counts:
        return ""
    order = {name: index for index, name in enumerate(rules.SUBDIRECTIONS.get(direction, ()))}
    return min(counts, key=lambda name: (-counts[name], order.get(name, len(order))))


def build_summary(item: WeaknessItem) -> str:
    """一句话薄弱描述（模板文案；AI 只可能替换它，绝不改数值）。"""
    labels = [
        coach_copy.DIFFICULTY_LABEL.get(value, value) for value in item.difficulty
    ] + [
        coach_copy.ESSENTIALITY_LABEL.get(value, value) for value in item.essentiality
    ]
    head = "·".join([item.point, *labels])
    # 尾巴随错题数分岔：0 错题组没有错题可复议，说「再过一遍错题」会与「错 0 题」自相矛盾（AC-2）。
    if item.wrong == 0:
        tail = "这一组已经全部答对，把复习时间挪到更薄弱的方向"
    else:
        tail = "先回到这一组最基础的概念再过一遍错题"
    return f"{head} 共 {item.total} 题错 {item.wrong} 题，均分 {format_score(item.avg)}/10，{tail}"


def _sort_key(item: WeaknessItem) -> tuple[int, float, float, int, str]:
    """全序：必备优先 → 错误率高 → 均分低 → 题量多 → key（稳定、可复算）。"""
    rank = min(
        (ESSENTIALITY_RANK.get(value, UNLABELED_RANK) for value in item.essentiality),
        default=UNLABELED_RANK,
    )
    return (rank, -item.rate, item.avg, -item.total, item.key)


def build_weakness_map(runs: list[dict[str, Any]]) -> list[WeaknessItem]:
    """把多份 run 的已计分客观题聚合成薄弱地图；无已计分题 → `[]`（AC-19 空态）。"""
    bank = _bank_index()
    entries: dict[str, list[tuple[int, str, float]]] = {}
    groups: dict[str, _Group] = {}
    #: r49：分组键不变，子方向只作为组内众数附加到 WeaknessItem，不参与分组与排序。
    sub_counts: dict[str, Counter[str]] = {}

    for run in runs:
        kind = str(run.get("kind") or "")
        for index, question, score in diagnosis._scored(run):
            difficulty, essentiality, direction = _labels_of(question, bank)
            # 方向缺失时用题库补齐再交给主轴同一个命名函数，保证地图与短板的点名叫法一致。
            lookup = dict(question)
            if direction and not lookup.get("direction"):
                lookup["direction"] = direction
            point = diagnosis._bucket_name(kind, lookup)
            key = f"{point}|{','.join(difficulty)}|{','.join(essentiality)}"
            groups.setdefault(
                key, _Group(point=point, direction=direction, difficulty=difficulty,
                            essentiality=essentiality)
            )
            entries.setdefault(key, []).append(
                (index, str(question.get("id") or ""), float(score))
            )
            sub = _sub_direction_of(question, bank, direction)
            if sub:
                sub_counts.setdefault(key, Counter())[sub] += 1

    items: list[WeaknessItem] = []
    for key, group in groups.items():
        rows = entries[key]
        total = len(rows)
        if not total:
            continue
        wrong = sum(1 for _, _, score in rows if score < rules.SEVERITY_MEDIUM_BELOW)
        avg = round(sum(score for _, _, score in rows) / total, 1)
        worst = sorted(rows, key=lambda row: (row[2], row[0]))[:SAMPLE_LIMIT]
        item = WeaknessItem(
            key=key,
            point=group.point,
            direction=group.direction,
            sub_direction=_dominant_sub_direction(
                sub_counts.get(key, Counter()), group.direction
            ),
            wrong=wrong,
            total=total,
            rate=round(wrong / total, 3),
            avg=avg,
            difficulty=list(group.difficulty),
            essentiality=list(group.essentiality),
            samples=[
                WeaknessSample(
                    question_id=question_id,
                    score=score,
                    evidence=f"Q{index} · {format_score(score)}/10",
                )
                for index, question_id, score in worst
                if question_id
            ],
            summary="",
        )
        items.append(item.model_copy(update={"summary": build_summary(item)}))

    items.sort(key=_sort_key)
    return items
