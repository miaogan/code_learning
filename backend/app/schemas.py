"""API 契约模型（pydantic v2）。前端镜像见 frontend/src/api/types.ts，改字段必须两侧同步。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Severity = Literal["high", "medium", "low"]
CourseLevel = Literal["入门", "进阶"]
RunKind = Literal["interview", "exam"]
QuestionKind = Literal["technical", "project", "challenge"]
ExamKind = Literal["single", "multiple", "text"]


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


class ProfileSkill(BaseModel):
    name: str
    source_quote: str = Field(min_length=1, description="简历原文片段（≤200 字），用于溯源")


class ProfileProject(BaseModel):
    name: str
    role: str
    period: str
    bullets: list[str]
    source_quote: str = Field(min_length=1)


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


class ErrorBody(BaseModel):
    code: str
    message: str
    retryable: bool
