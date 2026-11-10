"""简历版本对比（r60）：`documents` 列表 → 版本摘要与单版明细。

只做「读 → 投影 → 组装」：SQL 一律走 `repository`（唯一 SQL 出口），本文件不碰 sqlite3；
分数口径与历史页同源（`services.interview.history.score_of`），本层不二次换算，
因此同一次测评在版本页与成绩趋势页显示的分数必然一致。
"""

from typing import Any, Literal

from app.core import repository
from app.schemas import Profile, ResumeVersionDetail, ResumeVersionSummary
from app.services.interview.history import EXAM_KIND, INTERVIEW_KIND, score_of

SourceType = Literal["pdf", "docx", "txt", "image"]

MIN_LIMIT = 1
MAX_LIMIT = 50
DEFAULT_LIMIT = 20
#: 单版本分数聚合的读取窗口：页面只展示「最近一场」与总场数，100 场已远超真实用量。
RUNS_WINDOW = 100


def source_type_of(mime: str) -> SourceType:
    """由存储的 MIME 反推来源类型（`documents` 表不单存 `source_type`）。"""
    low = (mime or "").lower()
    if low.startswith("image/"):
        return "image"
    if "wordprocessingml" in low or low.startswith("application/msword"):
        return "docx"
    if low.startswith("text/"):
        return "txt"
    return "pdf"


def score_projection(runs: list[dict[str, Any]]) -> tuple[float | None, float | None]:
    """（最近一次有分面试的均分, 最近一次有分笔试的总分）。

    `runs` 已按 `created_at` 倒序（repository 口径），因此首个命中的就是「最近」；
    取「有分」而非「最新一条」是刻意的：提前结束且一题未答的面试 `score=None`，
    用它占位会让版本页显示「暂无成绩」，而更早那次真实成绩反而被挡住。
    """
    interview_avg: float | None = None
    exam_total: float | None = None
    for run in runs:
        kind = run["kind"]
        if kind == INTERVIEW_KIND and interview_avg is None:
            interview_avg = score_of(kind, run["payload"])
        elif kind == EXAM_KIND and exam_total is None:
            exam_total = score_of(kind, run["payload"])
        if interview_avg is not None and exam_total is not None:
            break
    return interview_avg, exam_total


def _summary(
    document: dict[str, Any],
    profile: Profile | None,
    runs: list[dict[str, Any]],
) -> ResumeVersionSummary:
    interview_avg, exam_total = score_projection(runs)
    return ResumeVersionSummary(
        resume_id=str(document["resume_id"]),
        file_name=str(document["file_name"]),
        source_type=source_type_of(str(document.get("mime") or "")),
        chars=int(document["chars"]),
        sections=int(document["sections"]),
        created_at=str(document["created_at"]),
        has_profile=profile is not None,
        interview_avg=interview_avg,
        exam_total=exam_total,
        judged_count=len(runs),
    )


def _version(
    document: dict[str, Any], profile: Profile | None
    ) -> ResumeVersionDetail:
    runs = repository.list_runs_for_document(str(document["resume_id"]), RUNS_WINDOW)
    summary = _summary(document, profile, runs)
    return ResumeVersionDetail(**summary.model_dump(), profile=profile)


def list_versions(limit: int = DEFAULT_LIMIT) -> list[ResumeVersionSummary]:
    """简历版本列表（上传时间倒序，`limit` 防御性截断在 1..50）。"""
    limit = min(max(limit, MIN_LIMIT), MAX_LIMIT)
    versions: list[ResumeVersionSummary] = []
    for document in repository.list_documents(limit):
        resume_id = str(document["resume_id"])
        profile = repository.latest_profile_for_document(resume_id)
        runs = repository.list_runs_for_document(resume_id, RUNS_WINDOW)
        versions.append(_summary(document, profile, runs))
    return versions


def get_version(resume_id: str) -> ResumeVersionDetail | None:
    """单份简历版本明细（含画像）；该用户下没有这份简历时 `None`。"""
    meta = repository.get_document_version(resume_id)
    if meta is None:
        return None
    document = {"resume_id": resume_id, **meta}
    return _version(document, repository.latest_profile_for_document(resume_id))
