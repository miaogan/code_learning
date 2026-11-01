"""API 契约模型（pydantic v2）。前端镜像见 frontend/src/api/types.ts，改字段必须两侧同步。"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Severity = Literal["high", "medium", "low"]
CourseLevel = Literal["入门", "进阶"]
RunKind = Literal["interview", "exam"]
QuestionKind = Literal["technical", "project", "challenge"]
ExamKind = Literal["single", "multiple", "text"]
#: 能力项状态：`active` 参与出题/诊断，`historical` 只留在画像里做记忆（消失项不删，r3 AC-6）。
SkillStatus = Literal["active", "historical"]
#: 时间线事件类型：面试 / 笔试 / 简历上传（各写 1 条，r3 AC-1）。
TimelineType = Literal["interview", "exam", "resume"]
#: 润色建议所属段落（与简历正文的自然段落一一对应）。
PolishSection = Literal["project", "experience", "education", "summary"]


class HealthResponse(BaseModel):
    status: str
    version: str
    ai_configured: bool
    db: str


class ResumeMeta(BaseModel):
    resume_id: str
    file_name: str
    chars: int
    sections: int


class Evidence(BaseModel):
    """一条可溯源证据：`quote` 逐字来自其来源简历正文（旧→新累积，r3 §2.2）。

    `resume_id` / `file_name` / `captured_at` 有缺省值，是为了让存量 payload（以及
    `verify_quotes` 这类只关心片段的调用方）可以只传 `quote` 构造。
    """

    quote: str = Field(min_length=1, description="简历原文片段，逐字来自其来源简历正文")
    resume_id: str = Field(default="", description="来源 documents.id（存量行留空）")
    file_name: str = Field(default="", description="来源文件名，用于「来源 · xxx.pdf」")
    captured_at: str = Field(default="", description="来源简历抓取时间（ISO UTC）")


def _backfill_evidence(entry: Any) -> Any:
    """存量 payload 兼容回填（`model_validator(mode="after")` 的两个条目模型共用）。

    1. `source_quotes` 为空 → 用单条 `source_quote` 补齐（老行读出来就是一条证据）；
    2. 维持不变式「`source_quote` ≡ `source_quotes[0].quote`」（前端单条溯源展示的稳定入口）。

    只在「证据链为空」时补齐、不重排已有条目：跨请求累积顺序（旧→新）因此由写入方独占。
    """
    quotes = list(entry.source_quotes or [])
    if not quotes and entry.source_quote:
        quotes = [Evidence(quote=entry.source_quote)]
    if quotes:
        entry.source_quotes = quotes
        entry.source_quote = quotes[0].quote
    return entry


class ProfileSkill(BaseModel):
    name: str
    source_quote: str = Field(min_length=1, description="简历原文片段（≤200 字），用于溯源")
    source_quotes: list[Evidence] = Field(
        default_factory=list, description="证据链（旧→新）；存量行读回时由 source_quote 回填"
    )
    status: SkillStatus = Field(default="active", description="historical = 已消失，仅留记忆")

    _normalize_evidence = model_validator(mode="after")(_backfill_evidence)


class ProfileProject(BaseModel):
    name: str
    role: str
    period: str
    bullets: list[str]
    source_quote: str = Field(min_length=1)
    source_quotes: list[Evidence] = Field(
        default_factory=list, description="证据链（旧→新）；存量行读回时由 source_quote 回填"
    )
    status: SkillStatus = Field(default="active", description="historical = 已消失，仅留记忆")

    _normalize_evidence = model_validator(mode="after")(_backfill_evidence)


class ProfileDraft(BaseModel):
    """模型直接产出的 5 维度草稿（无 id / 时间戳），落库前由 Profile 组装。"""

    model_config = ConfigDict(extra="ignore")

    skills: list[ProfileSkill]
    tech_stack: list[str]
    years_experience: float | None = None
    projects: list[ProfileProject]
    target_role: str | None = None


class Profile(ProfileDraft):
    id: str
    resume_id: str
    updated_at: str


class ProfilePatch(BaseModel):
    model_config = ConfigDict(extra="ignore")

    skills: list[ProfileSkill] | None = None
    tech_stack: list[str] | None = None
    years_experience: float | None = None
    projects: list[ProfileProject] | None = None
    target_role: str | None = None


class InterviewCreateRequest(BaseModel):
    """面试出题请求体。profile_id 必须走 body，裸函数签名会被 FastAPI 当 query。"""

    profile_id: str


class InterviewQuestion(BaseModel):
    id: str
    kind: QuestionKind
    prompt: str
    hint: str


class InterviewRun(BaseModel):
    run_id: str
    questions: list[InterviewQuestion]


class AnswerRequest(BaseModel):
    question_id: str
    answer: str


class ScoreResult(BaseModel):
    score: float = Field(ge=0, le=10)
    comment: str


class ExamOption(BaseModel):
    key: str
    text: str


class ExamCreateRequest(BaseModel):
    """笔试组卷请求体（同上：profile_id 只走 body）。"""

    profile_id: str


class ExamQuestion(BaseModel):
    id: str
    kind: ExamKind
    direction: str
    prompt: str
    options: list[ExamOption]


class ExamRun(BaseModel):
    run_id: str
    questions: list[ExamQuestion]


class ExamAnswers(BaseModel):
    answers: dict[str, list[str] | str]


class PerQuestionResult(BaseModel):
    question_id: str
    correct: bool | None
    your_answer: list[str] | str | None
    correct_answer: list[str] | str | None


class ExamResult(BaseModel):
    total: float
    correct_count: int
    objective_total: int
    elapsed_s: float
    per_question: list[PerQuestionResult]


class Course(BaseModel):
    id: str
    title: str
    direction: str
    level: CourseLevel
    url: str | None = None
    why: str


class Shortfall(BaseModel):
    name: str
    severity: Severity
    evidence: str = Field(description="题目 id + 得分，如「Q3 · 4/10」")
    diagnosis: str
    actions: list[str]
    courses: list[Course]
    question_ref: str | None = Field(
        default=None,
        description="证据来源的原始题目 id（如 fe-q1 / iq-3），供报告页溯源",
    )


class ReportGenerateRequest(BaseModel):
    """报告生成请求体：run_ids 缺省时由服务端取最近面试 + 最近笔试各一次。"""

    run_ids: list[str] | None = None


class Report(BaseModel):
    id: str
    run_ids: list[str] = Field(default_factory=list, description="本报告引用的测评 run id")
    interview_avg: float | None = None
    exam_total: float | None = None
    shortfalls: list[Shortfall]
    generated_at: str


class RunSummary(BaseModel):
    id: str
    kind: RunKind
    score: float | None = None
    shortfall_count: int | None = None
    created_at: str


# --- 成长时间线（r3 AC-1 / AC-2 / AC-5）---------------------------------------


class TimelineMetrics(BaseModel):
    """事件的指标快照：写入那一刻定格，重算报告不会让历史分数漂移（AC-2）。"""

    interview_avg: float | None = Field(default=None, description="与 history.score_of 同源")
    exam_total: float | None = Field(default=None, description="与 ExamResult.total 同源")
    shortfall_count: int | None = Field(default=None, description="len(build_shortfalls([run]))")
    skill_added: int = Field(default=0, description="resume 事件：新增能力项数")
    skill_removed: int = Field(default=0, description="resume 事件：转历史的能力项数")


class TimelineComparison(BaseModel):
    """与同类型上一条事件的对比：**服务端算好**，前端零减法（AC-5）。"""

    prev_event_id: str
    prev_occurred_at: str
    metric: str = Field(description="interview_avg 或 exam_total")
    prev_value: float
    current_value: float
    delta: float = Field(description="round(current - prev, 1)")
    repeated_shortfalls: list[str] = Field(
        default_factory=list, description="两次都在 = 复现/持续"
    )
    disappeared_shortfalls: list[str] = Field(
        default_factory=list, description="上次有、本次无"
    )


class TimelineEvent(BaseModel):
    id: str
    type: TimelineType
    ref_id: str
    occurred_at: str
    key_metrics: TimelineMetrics
    shortfall_names: list[str] = Field(default_factory=list)
    added_shortfalls: list[str] = Field(
        default_factory=list, description="本次有、上次无（无上次则 = 全部）"
    )
    removed_shortfalls: list[str] = Field(default_factory=list, description="上次有、本次无")
    summary: str = Field(description="中文一句话，由服务端组装")
    duplicate: bool = Field(
        default=False, description="同一份简历重复上传仍记事件（时间线不丢一次成长）"
    )
    comparison: TimelineComparison | None = None


# --- 画像合并（r3 AC-6）------------------------------------------------------


class ProfileMergeSummary(BaseModel):
    """一次合并的净变化：随响应一次性返回，不写进 `profiles.payload`。"""

    added: int = Field(default=0, description="新增能力项（技能）")
    historical: int = Field(default=0, description="本次转为历史的能力项")
    evidence_added: int = Field(default=0, description="证据净增条数")
    duplicate: bool = Field(default=False, description="与当前画像来源是同一份简历")


class ProfileWithMerge(Profile):
    """`POST /api/resumes/{id}/profile` 响应：画像 + 本次合并摘要（AC-6/7）。"""

    merge_summary: ProfileMergeSummary | None = None


# --- 简历润色（r3 AC-8 ~ AC-13）----------------------------------------------


class PolishSuggestion(BaseModel):
    id: str
    section: PolishSection
    original_text: str = Field(description="与简历正文逐字相等（字节级）")
    suggested_text: str = Field(description="已过反幻觉校验；缺数值处含〈待补充〉")
    reason: str
    target_role: str | None = None
    flags: list[str] = Field(
        default_factory=list, description="numeric_added / proper_noun_added 等降级原因"
    )
    start: int = Field(default=0, description="原句在正文中的起始偏移（服务端算，前端切片预览用）")
    end: int = Field(default=0, description="原句结束偏移（半开区间，与 start 成对）")


class PolishRequest(BaseModel):
    target_role: str | None = Field(
        default=None, description="临时目标岗位：只用于本次调用，不写库（AC-12）"
    )


class PolishResponse(BaseModel):
    polish_id: str = Field(description="本次建议集的一次性句柄，供 `/polish/full` 复用同一次结果")
    resume_id: str
    target_role: str | None = None
    resume_text: str = Field(
        description=(
            "简历正文，与 `documents.text` 逐字相等（字节级）；「原版」Tab 的唯一真源"
            "（成稿只取 `/polish/full` 的 markdown，本字段不参与拼装）"
        )
    )
    file_name: str = Field(
        default="", description="来源文件名（`documents.file_name`），导出命名用；存量数据可能为空串"
    )
    suggestions: list[PolishSuggestion]
    dropped_count: int = Field(default=0, description="未通过事实校验被整条剔除的条数")
    insufficient_reason: str | None = Field(default=None, description="条目不足时的中文说明")


class PolishFullRequest(BaseModel):
    polish_id: str | None = None
    target_role: str | None = None
    suggestion_ids: list[str] | None = Field(default=None, description="None = 全部采纳")


class PolishFullResponse(BaseModel):
    id: str
    markdown: str = Field(description="成稿唯一真源：导出/复制只取这份文本，前端零变换")
    dropped_count: int = 0
    regenerated: bool = Field(default=False, description="True = 缓存失效后重跑了一套建议")


class ErrorBody(BaseModel):
    code: str
    message: str
    retryable: bool
