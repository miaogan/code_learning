"""历史成绩（AC-10）：`runs` → `RunSummary` 投影，分数、短板数、时间倒序。

不新建表：历史只是既有 `runs` / `reports` 的一层投影（TECHNICAL §6·T5）。因此这里只做
「读 → 换算 → 组装」，SQL 一律走 `repository`（唯一 SQL 出口），本文件不碰 sqlite3。

分数口径（与报告、页面同源，下游不得二次换算；实现见公开函数 `score_of`）：
- 面试 = 均分：`payload.questions[].score` 去掉尚未评分的 `null` 后取均值（保留 1 位小数）；
  这样「答到一半的卷子」不会被按 0 分拉低均分。
- 笔试 = 总分：优先取服务端判分时写入的 `payload.total`（即 `ExamResult.total` 同名字段，
  §1.2 的 payload 由此扩展一格）；若后续字段名有变，再按 `per_question[].correct` 复算
  （客观题正确率 ×100，与 `ExamResult.total` 同一算式），仍无依据则记 `None`。

短板数：`reports` 只有「最新一份」这一条读取路径（`repository.latest_report()`，无列表接口）。
最新报告参与了本次测评（`run_ids` 含该 run）时取该报告的短板条数，否则记 `None` ——
不硬凑 0。报告不按 run 拆条（一条短板可由多次测评合并归因），故同报告内的多个 run 显示同一数值。

分页：`limit` 是每页条数（沿用旧字段名），`page` 从 1 起；`total` 是命中总数。
排序：`repository.history_rows()` 已按 `created_at DESC` 返回，本层**不再二次排序**（口径单一来源）。
"""

from typing import Any

from app.core import repository
from app.schemas import InterviewSettings, Report, RunSummary
from app.services.report import rules

INTERVIEW_KIND = "interview"
EXAM_KIND = "exam"

MIN_LIMIT = 1
MAX_LIMIT = 50
DEFAULT_LIMIT = 10
#: 分页多取的行数：页尾两行若类型不同，各需要再往下 1 条才能找到「上一同类」，
#: 因此多取 2 行即可保证本页每一行的对比对象都算得出来（只用于计算，不返回）。
LOOKAHEAD = 2


def _round1(value: float) -> float:
    return round(value, 1)


def _mean(scores: list[float]) -> float | None:
    return None if not scores else _round1(sum(scores) / len(scores))


def _interview_score(payload: dict[str, Any]) -> float | None:
    """面试均分：只统计已评分的题（未作答的题 score 为 null，不参与分母）。"""
    scores = [
        float(question["score"])
        for question in (payload.get("questions") or [])
        if isinstance(question, dict) and isinstance(question.get("score"), int | float)
    ]
    return _mean(scores)


def _exam_score(payload: dict[str, Any]) -> float | None:
    """笔试总分：优先判分时写入的 `total`（含 `result.total` 嵌套形态），否则按客观题复算。"""
    total = payload.get("total")
    if isinstance(total, int | float):
        return _round1(float(total))
    result = payload.get("result")
    if isinstance(result, dict) and isinstance(result.get("total"), int | float):
        return _round1(float(result["total"]))

    # 复算兜底：只认「判过对错」的客观题（text 题 correct 为 null，不计入分母）
    objective = [
        question
        for question in (payload.get("per_question") or [])
        if isinstance(question, dict) and question.get("correct") is not None
    ]
    if not objective:
        return None
    correct = sum(1 for question in objective if question.get("correct"))
    return _round1(correct / len(objective) * 100)


def score_of(kind: str, payload: dict[str, Any]) -> float | None:
    """分数口径的**唯一实现**：`interview` → 均分，`exam` → 总分，未知 kind → `None`。

    公开（原私有 `_score_of`，函数体零改动）：r3 时间线要写同一口径的分数快照，
    复制一份算式就会变成两套口径（AC-2 要求与历史页差 ≤0.05）。
    """
    if kind == INTERVIEW_KIND:
        return _interview_score(payload)
    if kind == EXAM_KIND:
        return _exam_score(payload)
    return None


def _interviews_settings_of(payload: dict[str, Any]) -> InterviewSettings | None:
    """面试 run 的本场设定投影：`payload.settings` 合法则回读，缺失/非法 → `None`（r5 AC-11）。

    「不补给」是刻意的：r5 之前的面试 run（payload v1）没有 `settings`，笔试 payload 从不写它 ——
    一律返回 `None` 让页面显示「未记录设定」，绝不用今天的默认值兜底，否则历史记录的
    「当时设定」会被填成一场从未发生过的配置。返回的是**投影**，不回写任何 run。

    解析口径不在这里另写一份（QA D-5）：唯一实现在 `rules.settings_or_none`，与面试会话页
    共用，缺一个键的脏 payload 在两处都必须是 `None`，不能一边 `None`、一边补默认值。
    """
    return rules.settings_or_none(payload)


def _shortfall_count(run_id: str, report: Report | None = None) -> int | None:
    """反查最新报告：该 run 参与生成时返回短板条数，未参与则 `None`。

    `report` 可由调用方传入以避免逐行重复读库（同一个最新报告对整批行都一样）。
    """
    if report is None:
        report = repository.latest_report()
    if report is None or run_id not in report.run_ids:
        return None
    return len(report.shortfalls)


def kind_counts() -> dict[str, int]:
    """面试 / 笔试各自的历史总数：页面筛选标签的统计口径（不受当前筛选影响）。"""
    return {
        kind: repository.count_history_rows(kind) for kind in (INTERVIEW_KIND, EXAM_KIND)
    }


def list_history(
    limit: int = DEFAULT_LIMIT, page: int = 1, kind: str | None = None
) -> tuple[list[RunSummary], int]:
    """已完成测评的**分页**投影，返回 `(本页条目, 命中总数)`。

    `kind` 只接受 `interview` / `exam`（其它值按「不筛选」处理，路由层已用闭集拦一次）；
    `total` 与列表同一过滤口径，前端据此算总页数。`limit` 越界由路由层
    `Query(ge=1, le=50)` 拦下（422 → 统一 envelope）；这里只做防御性截断。
    """
    limit = min(max(limit, MIN_LIMIT), MAX_LIMIT)
    page = max(page, 1)
    if kind not in {INTERVIEW_KIND, EXAM_KIND}:
        kind = None
    offset = (page - 1) * limit
    report = repository.latest_report()  # 短板数共用同一份最新报告：一次读库，不逐行反查
    total = repository.count_history_rows(kind)
    # 多取 LOOKAHEAD 行只为页尾行找「上一同类」；这 2 行不返回给调用方。
    rows = repository.history_rows(kind, limit=limit + LOOKAHEAD, offset=offset)
    scored = [(row, score_of(row["kind"], row["payload"] or {})) for row in rows]
    summaries: list[RunSummary] = []
    for index, (row, score) in enumerate(scored[:limit]):
        previous = next(
            (pair for pair in scored[index + 1 :] if pair[0]["kind"] == row["kind"]), None
        )
        run_kind = row["kind"]
        summaries.append(
            RunSummary(
                id=row["id"],
                kind=run_kind,
                score=score,
                shortfall_count=_shortfall_count(row["id"], report),
                created_at=row["created_at"],
                interview_settings=(
                    _interviews_settings_of(row["payload"] or {})
                    if run_kind == INTERVIEW_KIND
                    else None
                ),
                prev_score=None if previous is None else previous[1],
                has_prev=previous is not None,
            )
        )
    return summaries, total
