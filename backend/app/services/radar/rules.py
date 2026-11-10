"""r67 技术雷达规则层：结论闭集 + 四维夹取 + 确定性评估（**纯函数，零 IO**）。

分工与 r6 一致：闭集与结构闸门住这里，可调阈值（超时 / 条数 / 分钟）只住 `config.Settings`。
方向闭集不复制第二份，一律 import `services/report/rules.py` 的 `DIRECTIONS` / `SUBDIRECTIONS`。

四维口径（界面必须同时标注「1–5 粗档，不是精确评分」）：
- `relevance` 岗位相关度：与本产品 8 方向的关系 + 最新画像的薄弱方向 / 目标岗位。
- `adoption` 行业采用度：GitHub star 量级 + 7 日 star 增速 + 跨源出现次数。
- `maturity` 成熟度：仓库创建时长 + 近 30 天是否仍有推送 + 源类型。
- `effort` 学习成本：**数值越大越省力**（5 = 一个下午能上手），避免界面出现「学习成本 5 分」的误读。
"""

from __future__ import annotations

import math
from typing import Any

from app.services.report.rules import (
    DIRECTIONS,
    generic_sub_direction_of,
    is_valid_sub_direction,
)

#: 结论闭集（唯一出处）。越界值一律按 `skip` 落库并在 `reasons` 里说明（不做静默兜底）。
VERDICTS: tuple[str, ...] = ("must_learn", "worth_knowing", "watch", "skip")
VERDICT_LABELS: dict[str, str] = {
    "must_learn": "必学",
    "worth_knowing": "值得了解",
    "watch": "观望",
    "skip": "跳过",
}
#: 排序权重：结论优先 → 岗位相关度 → star 增速（PRD §5.1）。
VERDICT_WEIGHTS: dict[str, int] = {"must_learn": 3, "worth_knowing": 2, "watch": 1, "skip": 0}
#: 四维名称（前端直接复显，后端也用它拼提示词，避免两侧措辞漂移）。
DIMENSIONS: tuple[tuple[str, str], ...] = (
    ("relevance", "岗位相关度"),
    ("adoption", "行业采用度"),
    ("maturity", "成熟度"),
    ("effort", "学习成本"),
)
#: 降级顺序：必须降档时只往下走一格，`skip` 已是末档。
DOWNGRADE: dict[str, str] = {
    "must_learn": "worth_knowing",
    "worth_knowing": "watch",
    "watch": "skip",
    "skip": "skip",
}


def clamp(value: int, low: int = 1, high: int = 5) -> int:
    """四维夹取：越界即夹到 [1, 5]，不抛 500（模型给 0 / 8 只算噪声）。"""
    return max(low, min(high, int(value)))


def is_valid_verdict(verdict: str) -> bool:
    return verdict in VERDICTS


def label_of(verdict: str) -> str:
    return VERDICT_LABELS.get(verdict, VERDICT_LABELS["skip"])


def downgrade(verdict: str) -> str:
    """结论降一档（疑似刷 star 的仓库用，PRD §8）。"""
    return DOWNGRADE.get(verdict, "skip")


def normalize_direction(direction: str | None, sub_direction: str | None = "") -> tuple[str, str]:
    """方向 / 二级方向的脏值处理：方向不在闭集 → 兜底「AI 工程」；子方向越界 → 清空。"""
    resolved = direction if direction in DIRECTIONS else DIRECTIONS[4]
    sub = sub_direction if is_valid_sub_direction(resolved, sub_direction) else ""
    return resolved, sub


def fill_sub_direction(direction: str, sub_direction: str) -> str:
    """没指定子方向时给该方向的兜底名（`SUBDIRECTIONS` 最后一项）。"""
    return sub_direction or generic_sub_direction_of(direction)


def score_relevance(direction: str, weak_directions: list[str], target_role: str) -> int:
    """岗位相关度：命中薄弱方向 +2、命中目标岗位关键词 +1、属 8 方向 +1、其余 1。"""
    score = 1
    if direction in DIRECTIONS:
        score += 1
    if direction in weak_directions:
        score += 2
    role = (target_role or "").lower()
    if role and _role_hits_direction(direction, role):
        score += 1
    return clamp(score)


def _role_hits_direction(direction: str, role: str) -> bool:
    """目标岗位 → 方向的弱匹配（只认关键词，不做语义推断）。"""
    keywords: dict[str, tuple[str, ...]] = {
        "AI 工程": ("ai", "算法", "agent", "llm", "大模型", "智能"),
        "后端": ("后端", "服务端", "backend", "java", "go", "python"),
        "前端": ("前端", "web", "react", "vue"),
        "算法与数据结构": ("算法工程师", "数据结构"),
        "计算机基础": ("基础架构", "infra"),
        "中间件与运维": ("运维", "devops", "sre", "平台"),
        "SQL 与数据库": ("数据库", "dba", "数仓"),
        "研发工程实践": ("架构师", "tech lead", "技术专家"),
    }
    return any(word in role for word in keywords.get(direction, ()))


def score_adoption(stars: int, star_delta_7d: int, cross_source: int) -> int:
    """行业采用度：star 量级（每 100 倍 +1）+ 7 日增速 ≥ 50 + 跨源 ≥ 2。"""
    magnitude = math.floor(math.log10(max(stars, 1)) - 2)
    score = 1 + max(magnitude, 0)
    if star_delta_7d >= 50:
        score += 1
    if cross_source >= 2:
        score += 1
    return clamp(score)


def score_maturity(
    repo_age_days: int, pushed_within_30d: bool, source_key: str, cross_source: int
) -> int:
    """成熟度：存在 ≥180 天 + 近 30 天有推送 + 来自代码仓库 + 跨源出现 ≥ 2。"""
    score = 1
    if repo_age_days >= 180:
        score += 1
    if pushed_within_30d:
        score += 1
    if source_key == "github":
        score += 1
    if cross_source >= 2:
        score += 1
    return clamp(score)


def score_effort(repo_age_days: int, pushed_within_30d: bool, is_paper: bool) -> int:
    """学习成本（越大越省力）：论文 2、新兴仓库 3、成熟工具 5、其余 4。"""
    if is_paper:
        return 2
    if repo_age_days < 180:
        return 3
    return 5 if pushed_within_30d else 4


def verdict_of(relevance: int, adoption: int) -> str:
    """结论规则（PRD §4 的确定性公式，模型不可用时就是最终结论）。"""
    if relevance >= 4 and adoption >= 3:
        return "must_learn"
    if relevance >= 3:
        return "worth_knowing"
    if adoption >= 3:
        return "watch"
    return "skip"


def rule_assess(signals: dict[str, Any], profile: dict[str, Any] | None) -> dict[str, Any]:
    """规则评估（`rule_based=1` 的兜底口径）：只依赖快照信号 + 画像摘要，可复算。"""
    profile = profile or {"target_role": "", "weak_directions": [], "capabilities": 0}
    direction, _ = normalize_direction(str(signals.get("direction") or ""))
    relevance = score_relevance(
        direction,
        list(profile.get("weak_directions") or []),
        str(profile.get("target_role") or ""),
    )
    adoption = score_adoption(
        int(signals.get("stars") or 0),
        int(signals.get("star_delta_7d") or 0),
        int(signals.get("cross_source") or 1),
    )
    maturity = score_maturity(
        int(signals.get("repo_age_days") or 0),
        bool(signals.get("pushed_within_30d")),
        str(signals.get("source_key") or "manual"),
        int(signals.get("cross_source") or 1),
    )
    effort = score_effort(
        int(signals.get("repo_age_days") or 0),
        bool(signals.get("pushed_within_30d")),
        bool(signals.get("is_paper")),
    )
    verdict = verdict_of(relevance, adoption)
    reasons = [
        f"岗位相关度 {relevance}/5（方向「{direction}」"
        + ("命中你的薄弱方向" if direction in (profile.get("weak_directions") or []) else "属站内学习方向")
        + "）",
        f"行业采用度 {adoption}/5（star 约 {int(signals.get('stars') or 0)}、"
        f"7 日增速约 {int(signals.get('star_delta_7d') or 0)}、跨源 {int(signals.get('cross_source') or 1)} 次）",
        f"成熟度 {maturity}/5（仓库存在约 {int(signals.get('repo_age_days') or 0)} 天）",
        f"学习成本 {effort}/5（数值越大越省力，5 = 一个下午能上手）",
    ]
    if not profile.get("target_role"):
        reasons.append("无最新画像，按通用岗位评估")
    if signals.get("suspect"):
        verdict = downgrade(verdict)
        reasons.append("疑似刷 star（新建即巨量），结论已降一档")
    return {
        "verdict": verdict,
        "relevance": relevance,
        "adoption": adoption,
        "maturity": maturity,
        "effort": effort,
        "reasons": reasons,
        "evidence": list(signals.get("evidence") or []),
    }


def sort_key(item: dict[str, Any]) -> tuple[int, int, int, str]:
    """排序口径（PRD §5.1）：结论权重降序 → 岗位相关度降序 → star 增速降序 → 名称升序。"""
    return (
        -VERDICT_WEIGHTS.get(str(item.get("verdict") or "skip"), 0),
        -int(item.get("relevance") or 1),
        -int(item.get("star_delta_7d") or 0),
        str(item.get("name") or ""),
    )
