"""跃迁档案聚合（r108）：把已有事实汇成一屏，零 AI / 零新表 / 零重算。

三块数据的唯一口径：

- **目标岗位差距**：直接取最近一份报告的 `role_fit`（报告生成时算好），读取侧不重算
  差距、不重新匹配岗位模型；无报告就如实给中文指引。
- **项目工程证据**：画像项目逐条（bullets + 溯源条数）＋ 落库规模事实 ＋ RAG / 雷达
  状态，全部来自既有 repository 函数，只报事实不做质量判断。
- **面试表达**：取最近若干场面试里已作答的发言，分数 / 点评直接沿用当场写入的值；
  另做一次「问题—方案—指标—踩坑」**文本自检**——它只是关键词层面的启发式提示，
  不构成评分、不是能力结论，更不能把模拟面试或 dry-run 说成生产经验（r56 原则 4）。

服务层不写数据库语句、不新建表、不读裸配置；`MAX_*` 是本模块的取数上限，与熟练度
阈值无关，刻意不复用 config 的字段（那些有独立语义，见 test_proficiency_thresholds...）。
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from app.core import repository
from app.schemas import (
    LeapArchive,
    LeapEngineering,
    LeapEngineeringItem,
    LeapExpression,
    LeapExpressionItem,
    LeapExpressionStructure,
    LeapRoleGap,
)
from app.services.retrieval import indexer

#: 最多回看的最近面试场次（再多不进看板，避免把历史旧答案堆成一面墙）。
MAX_INTERVIEW_RUNS = 5
#: 每场最多取几条已作答发言。
MAX_PER_RUN = 6
#: 整份看板最多展示的面试表达条数。
MAX_EXPRESSION_ITEMS = 12

# 四要素关键词闭集：只用于文本自检的命中提示，不参与任何评分或能力判定。
_PROBLEM_WORDS = ("问题", "难点", "痛点", "背景", "挑战", "目标", "现状", "为什么", "遇到")
_SOLUTION_WORDS = ("方案", "做法", "实现", "采用", "用了", "改成", "引入", "通过", "设计")
_PITFALL_WORDS = ("坑", "失败", "教训", "注意", "风险", "返工", "回滚", "事故", "限制", "不足", "反思")
_TREND_WORDS = ("提升", "下降", "降低", "减少", "增长", "提高", "缩短", "优化到")
_FROM_TO = re.compile(r"从.{1,24}?到")
_NUMBER_WITH_UNIT = re.compile(r"\d+(?:\.\d+)?\s*(?:%|％|倍|ms|s\b|秒|分钟|qps|QPS|万|k\b|K\b|条|个)")

_LABELS = (
    ("has_problem", "问题 / 背景"),
    ("has_solution", "方案 / 做法"),
    ("has_metric", "指标 / 数据"),
    ("has_pitfall", "踩坑 / 反思"),
)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _any_word(text: str, words: tuple[str, ...]) -> bool:
    return any(word in text for word in words)


def _has_metric(text: str) -> bool:
    """量化迹象：带单位的数量，或趋势词 + 数字。纯字符串判断，不解读数字含义。"""
    if _NUMBER_WITH_UNIT.search(text):
        return True
    if _FROM_TO.search(text):
        return True
    return _any_word(text, _TREND_WORDS) and bool(re.search(r"\d", text))


def check_expression_structure(answer: str) -> LeapExpressionStructure:
    """四要素文本自检：只看答案里有没有出现对应措辞，不判断说得对不对、真不真。

    这是**启发式**，误判与漏判都可能发生；`hint` 必须明说自检非评分，避免用户把
    「命中四个关键词」当成「表达已经过关」或当成生产经验的凭证。
    """
    has_metric = _has_metric(answer)
    result = LeapExpressionStructure(
        has_problem=_any_word(answer, _PROBLEM_WORDS),
        has_solution=_any_word(answer, _SOLUTION_WORDS),
        has_metric=has_metric,
        has_pitfall=_any_word(answer, _PITFALL_WORDS),
    )
    result.hit_count = sum(
        1 for key in ("has_problem", "has_solution", "has_metric", "has_pitfall")
        if getattr(result, key)
    )
    missing = [label for key, label in _LABELS if not getattr(result, key)]
    if not missing:
        result.hint = (
            "四项措辞都出现了；这只是文本自检而非评分，不代表表达质量结论，"
            "也不等于项目已经上线或可作为生产经验。"
        )
    else:
        result.hint = (
            f"答案里未检出「{'、'.join(missing)}」相关表述；仅为关键词自检，不构成评分或能力结论，"
            "请结合题目自行判断，不要把模拟回答写成生产经验。"
        )
    return result


def _role_gap() -> LeapRoleGap:
    report = repository.latest_report()
    if report is None:
        return LeapRoleGap(
            notice="还没有诊断报告。先完成一次面试或笔试并生成报告，这里就能看到目标岗位差距。"
        )
    if report.role_fit is None:
        return LeapRoleGap(
            notice="这份报告没有目标岗位差距（画像与面试设定里都没有岗位）。补充目标岗位后重新生成报告即可。"
        )
    return LeapRoleGap(role_fit=report.role_fit, notice=report.role_fit.notice)


def _engineering() -> LeapEngineering:
    profile = repository.latest_profile()
    projects: list[LeapEngineeringItem] = []
    if profile is not None:
        for item in profile.projects:
            projects.append(
                LeapEngineeringItem(
                    name=item.name,
                    role=item.role,
                    period=item.period,
                    bullets=list(item.bullets),
                    evidence_count=len(item.source_quotes),
                    status=item.status,
                )
            )
    radar = repository.radar_latest_run()
    return LeapEngineering(
        projects=projects,
        data_scale=repository.evidence_data_scale(),
        tables=repository.public_table_count(),
        rag=indexer.index_status() or None,
        radar_techs_seen=int(radar.get("techs_seen") or 0),
        radar_finished_at=str(radar.get("finished_at") or ""),
        notice=None
        if projects
        else "画像里还没有项目。上传简历并完成画像后，这里会列出逐条溯源的项目证据。",
    )


def _expression() -> LeapExpression:
    runs = repository.list_runs(kind="interview", limit=MAX_INTERVIEW_RUNS)
    items: list[LeapExpressionItem] = []
    for run in runs:
        if len(items) >= MAX_EXPRESSION_ITEMS:
            break
        payload: dict[str, Any] = dict(run.get("payload") or {})
        entries = payload.get("questions")
        if not isinstance(entries, list):
            continue
        run_id = str(run.get("id") or "")
        taken = 0
        for entry in entries:
            if len(items) >= MAX_EXPRESSION_ITEMS or taken >= MAX_PER_RUN:
                break
            if not isinstance(entry, dict):
                continue
            answer = entry.get("answer")
            if not isinstance(answer, str) or not answer.strip():
                continue
            # 只展示已评分的发言：面试里「答过」的唯一判据是 score 为数字（与 history /
            # interview 的 `_score_of` 同口径），未评分的在途/跳过发言不进看板。
            score = entry.get("score")
            if isinstance(score, bool) or not isinstance(score, (int, float)):
                continue
            comment = entry.get("comment")
            items.append(
                LeapExpressionItem(
                    run_id=run_id,
                    question_id=str(entry.get("id") or ""),
                    prompt=str(entry.get("prompt") or ""),
                    answer=answer,
                    score=float(score),
                    comment=comment if isinstance(comment, str) else None,
                    structure=check_expression_structure(answer),
                )
            )
            taken += 1
    return LeapExpression(
        items=items,
        notice=None
        if items
        else "还没有已作答的面试发言。完成一次模拟面试后，这里会按「问题—方案—指标—踩坑」逐条自检表达。",
    )


def build_leap_archive() -> LeapArchive:
    """一次组装三块：全部读既有 repository / indexer，不写库、不调模型、不重算分数。"""
    return LeapArchive(
        role_gap=_role_gap(),
        engineering=_engineering(),
        expression=_expression(),
        generated_at=_now_iso(),
    )
