"""r67 评估层：采集信号 + 本账号画像 → 四维读数与结论。

两条轨道严格分层（与 r53 的「离线回归 ≠ 在线质量」同一纪律）：
- **规则基线**（`rules.rule_assess`）：零 IO、可复算，模型不可用时它就是最终结论（`rule_based=1`）。
- **模型细化**（本模块 `model_assess`）：只给本轮排名最前的几项打分（`radar_max_assess_per_round`），
  产出仍要过四维夹取 / 结论闭集 / **证据白名单**（不在快照里的 URL 一律丢弃并计数），
  避免出现「模型编了一条不存在的来源」。

画像只取「目标岗位 + 薄弱方向 + 能力项数」三项摘要，**不读简历正文**；摘要算 sha256 存进评估行，
换简历后能看出「同一结论是拿另一份画像算的」。
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core import repository
from app.core.config import get_settings
from app.services.ai.ai import AIClient
from app.services.radar import rules

logger = logging.getLogger("app.radar.assess")

#: 提示词版本：改措辞必须改这里，否则评估行无法区分「换了提示词」与「换了模型」。
PROMPT_VERSION = "radar-r1"

#: 一条理由 / 一条证据的长度上限（落库与界面同口径）。
MAX_REASON_CHARS = 120
MAX_REASONS = 5
#: 每轮参与模型细化的条数上限的默认值（真实值在 `configuration`）。
DEFAULT_MAX_ASSESS = 3

RADAR_SYSTEM = """你是技术雷达评估器。给定一条「新技术 / 热门技术」快照和一个工程师的画像摘要，
判断它对这位工程师是否值得学，并给出四个 1–5 的粗档读数。

四维口径：
- relevance 岗位相关度：该技术所属方向与画像的目标岗位、薄弱方向的关系；
- adoption 行业采用度：star 量级、近 7 日增速、是否被多个信息源同时提到；
- maturity 成熟度：项目存在时长、近 30 天是否仍有推送、是否为代码仓库；
- effort 学习成本：**数值越大越省力**（5 = 一个下午能上手）。

硬性规则：
1. 只依据给出的快照与画像摘要，不引入任何外部事实，不编造 star 数、版本号、发布日期。
2. `evidence` 只能逐字复制输入里出现过的链接；没有就返回空数组，宁缺毋造。
3. `verdict` 只能是 must_learn / worth_knowing / watch / skip 之一。
4. 只输出 JSON，不要解释性文字或 Markdown。"""


class AssessmentDraft(BaseModel):
    """模型产出的评估草稿（字段全部可校验后夹取，脏值不抛 500）。"""

    model_config = ConfigDict(extra="ignore")

    verdict: str = ""
    relevance: int = 1
    adoption: int = 1
    maturity: int = 1
    effort: int = 1
    reasons: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)


def profile_summary() -> dict[str, Any]:
    """画像摘要：目标岗位 + 薄弱方向（只取有题目的分组）+ 能力项数。全部来自只读仓储。"""
    profile = repository.latest_profile()
    target_role = str(getattr(profile, "target_role", None) or "").strip() if profile else ""
    skills = [s.name for s in profile.skills if s.status != "historical"] if profile else []
    weak: list[str] = []
    report = repository.latest_report()
    if report is not None:
        for item in report.weakness_map:
            direction = str(item.direction or "")
            if direction and item.total > 0 and direction not in weak:
                weak.append(direction)
    return {
        "target_role": target_role,
        "weak_directions": weak,
        "capabilities": len(skills),
    }


def profile_digest(summary: dict[str, Any]) -> str:
    """画像摘要的指纹（同一个人换了简历 → 指纹变化，评估行可追溯）。"""
    payload = json.dumps(summary, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def input_sha256(item: dict[str, Any], signals: dict[str, Any], digest: str) -> str:
    """「快照 + 信号 + 画像」的指纹：同一输入重复评估可判为同一结论（幂等索引的另一半）。"""
    payload = json.dumps(
        {
            "slug": item.get("slug"),
            "stars": signals.get("stars"),
            "delta": signals.get("star_delta_7d"),
            "cross": signals.get("cross_source"),
            "profile": digest,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def model_sha(base: str) -> str:
    """模型轨的指纹：与规则轨用同一份输入时也必须落成两条行（两轨结论不可互替）。"""
    return hashlib.sha256(f"{base}|model".encode()).hexdigest()[:32]


def allowed_evidence(signals: dict[str, Any]) -> set[str]:
    """证据白名单：只有快照里真实出现过的链接才算证据（模型给的其余 URL 一律丢弃）。"""
    return {str(url) for url in (signals.get("evidence") or []) if str(url).strip()}


def sanitize(
    draft: AssessmentDraft,
    signals: dict[str, Any],
    fallback: dict[str, Any],
) -> tuple[dict[str, Any], int]:
    """模型草稿 → 可落库结果，返回 `(结果, 被丢弃的证据条数)`。

    - 结论越界 → 回落到规则结论，并追加一条中文理由（不静默改写）；
    - 四维一律夹到 1–5；
    - 证据按白名单过滤，丢弃条数如实上报（界面复显「已丢弃 N 条无依据引用」）。
    """
    allowed = allowed_evidence(signals)
    kept: list[str] = []
    dropped = 0
    for url in draft.evidence:
        text = str(url).strip()
        if text in allowed:
            if text not in kept:
                kept.append(text)
        else:
            dropped += 1
    reasons = [
        str(reason).strip()[:MAX_REASON_CHARS]
        for reason in draft.reasons
        if str(reason).strip()
    ][:MAX_REASONS]
    verdict = draft.verdict if rules.is_valid_verdict(draft.verdict) else str(fallback["verdict"])
    if verdict != draft.verdict:
        reasons.append(f"模型给出的结论「{draft.verdict or '空'}」不在允许范围，已按规则结论处理")
    result = {
        "verdict": verdict,
        "relevance": rules.clamp(draft.relevance),
        "adoption": rules.clamp(draft.adoption),
        "maturity": rules.clamp(draft.maturity),
        "effort": rules.clamp(draft.effort),
        "reasons": reasons[:MAX_REASONS],
        "evidence": kept,
    }
    if signals.get("suspect"):
        result["verdict"] = rules.downgrade(result["verdict"])
    return result, dropped


def build_user_prompt(
    item: dict[str, Any], signals: dict[str, Any], summary: dict[str, Any]
) -> str:
    """把快照与画像摘要压成一段可复现的提示词（不含简历正文 / 不含 Key）。"""
    lines = [
        f"技术名称：{item.get('name')}",
        f"方向：{signals.get('direction')}",
        f"简介：{item.get('summary') or '（无）'}",
        f"链接：{item.get('url') or '（无）'}",
        f"信息源：{signals.get('source_key')}",
        f"star 数：{int(signals.get('stars') or 0)}",
        f"7 日 star 增量：{int(signals.get('star_delta_7d') or 0)}",
        f"跨源出现次数：{int(signals.get('cross_source') or 1)}",
        f"项目存在天数：{int(signals.get('repo_age_days') or 0)}",
        f"近 30 天有推送：{'是' if signals.get('pushed_within_30d') else '否'}",
        f"疑似刷 star：{'是' if signals.get('suspect') else '否'}",
        f"画像目标岗位：{summary.get('target_role') or '（未设置）'}",
        f"画像薄弱方向：{'、'.join(summary.get('weak_directions') or []) or '（无报告）'}",
        f"画像能力项数：{int(summary.get('capabilities') or 0)}",
    ]
    return "\n".join(lines)


async def model_assess(
    item: dict[str, Any],
    signals: dict[str, Any],
    summary: dict[str, Any],
    client: AIClient,
) -> dict[str, Any]:
    """模型细化一次评估（`rule_based=0`）。失败由调用方兜底为规则结论，这里不吞异常。"""
    fallback = rules.rule_assess(signals, summary)
    draft = await client.complete_model(
        RADAR_SYSTEM,
        build_user_prompt(item, signals, summary),
        AssessmentDraft,
        timeout_s=get_settings().radar_assess_timeout_s,
    )
    result, dropped = sanitize(draft, signals, fallback)
    result["dropped_evidence"] = dropped
    return result
