"""API 契约模型（pydantic v2）。前端镜像见 frontend/src/api/types.ts，改字段必须两侧同步。"""

from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.core.config import JsonMode

Severity = Literal["high", "medium", "low"]
CourseLevel = Literal["入门", "进阶"]
RunKind = Literal["interview", "exam"]
QuestionKind = Literal["technical", "project", "challenge"]
ExperienceBand = Literal["应届", "1-3年", "3-5年", "5-10年", "10年以上"]
InterviewMarket = Literal["国内", "北美", "欧洲", "其他"]
CompanySize = Literal["大厂", "中型", "初创"]
#: 题型闭集（r11 扩 `judge` 判断题）：单一出处是 `services/rules.py:OBJECTIVE_KINDS` →
#: `QUESTION_KINDS`（由本 Literal 派生），改一处必须改两处。
ExamKind = Literal["single", "multiple", "judge", "text"]
#: 题目难度三档（r6：`basic` / `intermediate` / `challenge`）。闭集单一出处在
#: `services/rules.py:DIFFICULTIES` —— 那份元组与本 Literal 逐字对齐，改一处必须改两处。
ExamDifficulty = Literal["basic", "intermediate", "challenge"]
#: 题目必备度三档（r6）：必备 / 进阶 / 加分项。闭集单一出处在
#: `services/rules.py:ESSENTIALITIES`，语义见 `rules.essentiality_of()`。
QuestionEssentiality = Literal["must_know", "advanced", "nice_to_know"]
#: 能力项状态：`active` 参与出题/诊断，`historical` 只留在画像里做记忆（消失项不删，r3 AC-6）。
SkillStatus = Literal["active", "historical"]
#: 时间线事件类型：面试 / 笔试 / 简历上传（各写 1 条，r3 AC-1）。
TimelineType = Literal["interview", "exam", "resume"]
#: 润色建议所属段落（与简历正文的自然段落一一对应）。
PolishSection = Literal["project", "experience", "education", "summary"]

# --- r11 题库语言维度与练习闭集（镜像 `services/rules.py`，逐字对齐）--------
#: 题干语言闭集。**`""` 是闭集成员**（通用 / 算法题），不是「全部」——
#: 筛选里的「全部」是 `rules.FILTER_ANY`（字面量 `"all"`），两条语义不得混用。
QuestionLanguage = Literal["", "python", "java", "go", "html", "css", "js", "ts", "vue3", "react"]
#: 练习语言筛选 = 闭集成员 + 「全部」（`"all"` 与 `""` 并列，故类型上必须并存）。
PracticeLanguageFilter = Literal[
    "all", "", "python", "java", "go", "html", "css", "js", "ts", "vue3", "react"
]
#: 练习方向筛选：闭集只此一份（`rules.DIRECTIONS`），**刻意不在 schemas.py 复写方向字面量** ——
#: 既有门禁 `test_direction_literals_not_duplicated` 把 `schemas.py` 算在 r6 改动面内，
#: 再写一份方向字面量就是第二份闭集。这里用 `Annotated` 校验器，越界值在模型层被拒，
#: FastAPI 仍统一映射 422 `VALIDATION_ERROR`（错误矩阵不变）。
def _check_direction_filter(value: str) -> str:
    """方向筛选闭集校验（`rules.DIRECTIONS` + `rules.FILTER_ANY`）。

    延迟导入是刻意的：`rules` 反向上依赖本模块（`ExamKind` / `InterviewSettings`），
    模块级导入会成环；校验器在请求到达时才执行，那时两个模块都已就绪。
    """
    from app.services.report import rules

    if value != rules.FILTER_ANY and value not in rules.DIRECTIONS:
        raise ValueError("direction 越出闭集")
    return value


PracticeDirectionFilter = Annotated[str, AfterValidator(_check_direction_filter)]
#: 练习难度筛选 = 三档（`rules.DIFFICULTIES`）+ 「全部」。
PracticeDifficultyFilter = Literal["all", "basic", "intermediate", "challenge"]
#: 练习必备度筛选 = 三档（`rules.ESSENTIALITIES`）+ 「全部」。
PracticeEssentialityFilter = Literal["all", "must_know", "advanced", "nice_to_know"]
#: 练习范围闭集（`rules.PRACTICE_SCOPES`）：全部 / 未做过 / 最近一次答错。
PracticeScope = Literal["all", "unseen", "wrong"]
#: 练习题量闭集（`rules.PRACTICE_LIMITS`，`0` = 全部命中）。
PracticeLimit = Literal[10, 20, 0]
#: 练习二级方向筛选（r50）：空串 = 不聚焦。闭集来自 `rules.SUBDIRECTIONS`，
#: 与 r46 笔试同口径 —— 越界脏值由服务层**静默忽略**，不在模型层造第二套 422。
PracticeSubDirectionFilter = str


class HealthResponse(BaseModel):
    """探活响应（`/health`，契约面）。

    r9 追加的三个字段是**运维白名单**：只暴露「当前解析成哪套端点/模型/JSON 模式」，
    永远不包含 `api_key` 的任何片段（key 只在 `AiRuntime` 里，且带 `repr=False`）。
    三个值由 `Settings.resolve_ai()` 一次解析给出，故 `ai_configured` 与它们同源，
    不会出现「说已配置、却报了 legacy」的两套就绪语义。
    """

    status: str
    version: str
    ai_configured: bool
    db: str
    ai_provider: str
    ai_model: str
    ai_json_mode: str


class ResumeMeta(BaseModel):
    resume_id: str
    file_name: str
    chars: int
    sections: int
    #: r41：来源类型；存量文档响应默认 `pdf`，旧客户端不受影响。
    source_type: Literal["pdf", "docx", "txt", "image"] = "pdf"
    #: 仅 `source_type=image` 时大于 1（同一次上传的多张照片拼成一份简历）。
    image_count: int = 1


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
    """项目条目。`role` / `period` 可空（r8）：提示词明确允许模型对「无法判断」给 `null`，
    契约必须接受同一语义，否则真实模型下画像生成必 502；`None` 表示「简历没写」，
    与用户编辑清空（落库前归一为 `None`）同解，渲染侧统一吞掉，不出现 `null` / 悬空分隔符。
    """

    name: str
    role: str | None = None
    period: str | None = None
    bullets: list[str] = Field(default_factory=list, description="缺省 []；模型偶尔给 null")
    source_quote: str = Field(min_length=1)
    source_quotes: list[Evidence] = Field(
        default_factory=list, description="证据链（旧→新）；存量行读回时由 source_quote 回填"
    )
    status: SkillStatus = Field(default="active", description="historical = 已消失，仅留记忆")

    _normalize_evidence = model_validator(mode="after")(_backfill_evidence)

    @field_validator("bullets", mode="before")
    @classmethod
    def _null_bullets(cls, value: Any) -> Any:
        """模型对「无要点」既可能给 []、也可能给 null；两者都归一为 []。

        只动列表形状的缺省，不碰元素校验（`:memory:` 去重、`min_length` 照旧）。
        """
        return [] if value is None else value


#: 提示词允许给 `null` 表示「这一维没写」的三个维度（r8）；键缺失与显式 null 同解。
_NULL_LIST_FIELDS = ("skills", "tech_stack", "projects")


class ProfileDraft(BaseModel):
    """模型直接产出的 5 维度草稿（无 id / 时间戳），落库前由 Profile 组装。

    `Profile` 继承本模型 ⇒ 一个 before-validator 同时覆盖「模型草稿 / 响应落地 / 存量读回」
    三条路径；`ProfilePatch` 不继承，其顶层 `None` 仍是「不改这一维」，两套语义不混。
    """

    model_config = ConfigDict(extra="ignore")

    skills: list[ProfileSkill]
    tech_stack: list[str]
    years_experience: float | None = None
    projects: list[ProfileProject]
    target_role: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _normalize_null_lists(cls, data: Any) -> Any:
        """提示词第 3 条允许整个维度给 null；键缺失与显式 null 一视同仁 → []。

        只动「列表形状的缺省」，不碰元素校验：`name` / `source_quote` 仍必填非空，
        因此「AI 编造内容」仍会在元素级 ValidationError 处被拦。
        """
        if not isinstance(data, dict):
            return data
        patch = {name: [] for name in _NULL_LIST_FIELDS if data.get(name) is None}
        return {**data, **patch} if patch else data


class Profile(ProfileDraft):
    id: str
    resume_id: str
    updated_at: str


class ResumeVersionSummary(BaseModel):
    """简历版本摘要（r60 版本对比）：上传的展示元信息 + 该版本最近一次测评成绩。

    `interview_avg` / `exam_total` 与历史页同源（`services.interview.history.score_of`），
    页面零换算；`judged_count` 是该版本下已完成测评的场数（含面试与笔试）。
    """

    resume_id: str
    file_name: str
    source_type: Literal["pdf", "docx", "txt", "image"] = "pdf"
    chars: int
    sections: int
    created_at: str
    has_profile: bool = Field(default=False, description="该版本是否已生成过画像")
    interview_avg: float | None = Field(default=None, description="最近一场已完成面试的均分 /10")
    exam_total: float | None = Field(default=None, description="最近一场已完成笔试的卷面总分 /100")
    judged_count: int = Field(default=0, description="该版本下已完成的测评场数")


class ResumeVersionDetail(ResumeVersionSummary):
    """单份简历版本详情：摘要 + 画像（未生成画像时 `profile=None`）。"""

    profile: Profile | None = Field(default=None, description="该版本最近一次生成的画像")


class ProfilePatch(BaseModel):
    model_config = ConfigDict(extra="ignore")

    skills: list[ProfileSkill] | None = None
    tech_stack: list[str] | None = None
    years_experience: float | None = None
    projects: list[ProfileProject] | None = None
    target_role: str | None = None


class InterviewSettings(BaseModel):
    """本场面试的设定：r5 四项 + r44 可选方向聚焦，落 runs.payload.settings，永不写回画像。

    `direction` / `sub_direction` 空串 = 不限（老 payload 缺这两键时按空串补，四项解析口径不变）；
    取值闭集由 `services.report.rules` 校验，不在本模块重复字面量。
    """

    target_role: str = Field(default="通用软件工程师", min_length=1)
    years_experience: ExperienceBand = "1-3年"
    market: InterviewMarket = "国内"
    company_size: CompanySize = "中型"
    direction: str = ""
    sub_direction: str = ""


class InterviewSettingsPatch(BaseModel):
    """开局请求里的设定补丁：四项 + 可选方向全可选，缺省由服务端按画像/默认值补全。"""

    target_role: str | None = None
    years_experience: ExperienceBand | None = None
    market: InterviewMarket | None = None
    company_size: CompanySize | None = None
    #: 取值见 rules.DIRECTIONS / rules.SUBDIRECTIONS；空 = 不限。
    direction: str | None = None
    sub_direction: str | None = None


class InterviewCreateRequest(BaseModel):
    """面试出题请求体。profile_id 必须走 body，裸函数签名会被 FastAPI 当 query。"""

    profile_id: str
    settings: InterviewSettingsPatch | None = None


class InterviewQuestion(BaseModel):
    id: str
    kind: QuestionKind
    prompt: str
    hint: str
    parent_id: str | None = Field(default=None, description="追问：父题 id；正题为 None")


class InterviewRun(BaseModel):
    """开局响应：只投放第 1 条发言（计划正文在 payload.plan，不随响应外泄）。"""

    run_id: str
    settings: InterviewSettings
    question: InterviewQuestion
    total: int


class InterviewSessionQuestion(BaseModel):
    """会话回溯用的单条发言（题目 + 该题的答案/分数/点评，未答为 None）。"""

    id: str
    kind: QuestionKind
    prompt: str
    hint: str
    parent_id: str | None = None
    answer: str | None = None
    score: float | None = Field(default=None, ge=0, le=10)
    comment: str | None = None


class InterviewSession(BaseModel):
    """GET /api/interviews/{run_id}：刷新/重进后的完整会话镜像。"""

    run_id: str
    status: str
    settings: InterviewSettings | None = None
    questions: list[InterviewSessionQuestion] = Field(default_factory=list)
    answered_count: int
    total: int
    current_id: str | None = None
    interview_avg: float | None = None


class InterviewSessionSummary(BaseModel):
    """GET /api/interviews：历史面试列表的一行（在途场次也列出，方便回去接着答）。"""

    run_id: str
    status: str
    created_at: str
    settings: InterviewSettings | None = None
    total: int
    answered_count: int
    interview_avg: float | None = None


class AnswerRequest(BaseModel):
    question_id: str
    answer: str


class ScoreResult(BaseModel):
    score: float = Field(ge=0, le=10)
    comment: str


class InterviewTurn(ScoreResult):
    """单轮响应：本轮评分 + 下一条发言（ScoreResult 超集，score/comment 原样保留）。"""

    next_question: InterviewQuestion | None = None
    run_status: str
    answered_count: int
    total: int
    interview_avg: float | None = None


class ExamOption(BaseModel):
    key: str
    text: str


class ExamCreateRequest(BaseModel):
    """笔试组卷请求体。

    全部筛选字段可选：不传时走默认阶梯（画像相关度 + 6 层兜底）。
    传入时在候选池先做硬过滤，再走阶梯；若单方向/难度凑不出结构达标的卷，
    整轮仍以 400 出口（与 AC-8 一致）。
    """

    profile_id: str
    #: 指定方向（取值见 rules.DIRECTIONS）。None = 不过滤。
    direction: str | None = None
    #: 指定二级方向（如 "python" / "react" / "动态规划"，取值见 rules.SUBDIRECTIONS[direction]）。
    #: None = 不过滤；传值时**必须**同时传 direction（二级方向从属于一级方向）。
    sub_direction: str | None = None
    #: 指定难度档（如 "basic" 或 ("basic", "intermediate")）。None = 不过滤。
    difficulty: str | tuple[str, ...] | None = None
    #: 目标题量。None = 默认 10–12。至少 10，低于会被结构闸门拒掉。
    question_count: int | None = None


class ExamQuestion(BaseModel):
    id: str
    kind: ExamKind
    direction: str
    prompt: str
    options: list[ExamOption]


class ExamRun(BaseModel):
    run_id: str
    questions: list[ExamQuestion]
    #: 本次**净过滤**掉的熟练题数 = `|熟练 ∩ 可用| − |熟练 ∩ 本卷|`（r6 AC-12）。
    #: 恒 `>= 0`；声明必填但给默认 0，旧客户端/旧 payload 不会因缺字段而炸；服务端恒显式赋值。
    filtered_count: int = 0
    #: r43：本卷里**已熟练但被兜底放回**的题数（= `|熟练 ∩ 本卷|`），用于「另有 N 道因保持卷面结构被重新纳入」。
    #: 旧客户端兼容默认 0；不从 payload 读（出卷响应专属字段）。
    reintroduced_count: int = 0
    #: r46：实际生效的子方向（闭集内取值）；未指定或闭集外脏参数时为空串（= 未聚焦）。
    sub_direction: str = ""
    #: r46：本卷中**不属于所选子方向**、因该子方向题量不足而补齐的题数（0 = 全部命中）。
    sub_direction_backfill: int = 0


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


# --- r11 练习四端点契约（/api/practice/paper|answer|stats|wrong-book）--------
# 与 `frontend/src/api/types.ts` 逐字镜像（字段名 snake_case，零转换）：任一侧改名即
# `tests/test_r11_contract.py` 转红。判分/事件表复用笔试那一份（`question_attempts`）。


class PracticePaperRequest(BaseModel):
    """练习组卷请求体（`POST /api/practice/paper`，闭集越界由 FastAPI 统一映射 422）。"""

    language: PracticeLanguageFilter = "all"
    direction: PracticeDirectionFilter = "all"
    difficulty: PracticeDifficultyFilter = "all"
    essentiality: PracticeEssentialityFilter = "all"
    scope: PracticeScope = "all"
    limit: PracticeLimit = 10
    #: r50：二级方向聚焦，空串 = 不限；与 `direction` 冲突时按笔试 r46 口径归一。
    sub_direction: PracticeSubDirectionFilter = ""


class PracticeQuestion(BaseModel):
    """练习题单里的一道题：**不含** `answer`（答案只在判分响应里回显）。"""

    id: str
    kind: ExamKind
    language: str
    direction: str
    difficulty: str
    essentiality: str
    prompt: str
    options: list[ExamOption]


class PracticePaper(BaseModel):
    """练习题单（`POST /api/practice/paper`）：空结果也 200，靠 `notice` 说中文原因。"""

    session_id: str
    questions: list[PracticeQuestion]
    #: 全部筛选后的命中总数（不受 `limit` 截断），与 `/stats` 的 `hit` 同源同值。
    hit_count: int
    #: 空 / 截断 / 题库未就绪的中文提示（正常满额时为空串）。
    notice: str = ""
    #: r50：实际生效的二级方向（闭集内取值）；未聚焦或脏参数归一后为空串。
    sub_direction: str = ""
    #: r50：本份题单里**不属于所选二级方向**、因聚焦池题量不足而补齐的题数（0 = 全命中）。
    sub_direction_backfill: int = 0
    #: r52：本次被熟练度过滤跳过的题数（与笔试同一份 30 天 / 答对 2 次判定；0 = 未过滤）。
    filtered_count: int = 0


class PracticeAnswerRequest(BaseModel):
    """单题判定请求（`POST /api/practice/answer`）；`answer` 空由服务端 400 兜底。"""

    session_id: str
    question_id: str
    answer: list[str] | str | None = None


class PracticeAnswerResult(BaseModel):
    """单题判定结果：判分只走 `exam.grade_objective()`，这里只做数据搬运。"""

    question_id: str
    correct: bool
    correct_answer: list[str] | str | None = None
    #: 解析恒 `str`（库内为空时也返回空串，前端显示「本题暂无解析」降级文案）。
    explanation: str = ""


class PracticeStats(BaseModel):
    """练习统计（`GET /api/practice/stats`）：`hit` 是当前筛选命中数。"""

    total: int
    practiced: int
    wrong_total: int
    hit: int


class PracticeWrongItem(BaseModel):
    """错题本一行：最近一次作答为错误的题。"""

    question_id: str
    prompt: str
    language: str
    direction: str
    difficulty: str
    #: 最近一次答错时间（UTC ISO8601），前端格式化为 `MM-dd HH:mm`。
    last_wrong_at: str
    wrong_count: int


class PracticeWrongBook(BaseModel):
    """错题本（`GET /api/practice/wrong-book`）：空列表也是 200。"""

    items: list[PracticeWrongItem]
    total: int


class EvalModelStat(BaseModel):
    """r51 看板：单个模型的聚合行。"""

    total: int
    success_rate: float
    p95_ms: int


class EvalTrendPoint(BaseModel):
    """r51 看板：按 UTC 日期聚合的一天。"""

    day: str
    total: int
    success_rate: float


class EvalSummary(BaseModel):
    """r51 模型调用质量看板（GET /api/eval/summary）：按当前用户聚合，零 AI、零 Key 回传。"""

    window_days: int
    total: int
    success_rate: float
    p50_ms: int
    p95_ms: int
    by_kind: dict[str, int]
    by_model: dict[str, EvalModelStat]
    trend: list[EvalTrendPoint]
    notice: str = ""


class QuestionSearchRequest(BaseModel):
    """r51 题目检索请求：方向 / 子方向是闭集外一律静默忽略的可选过滤。"""

    query: str = ""
    direction: str = ""
    sub_direction: str = ""
    limit: int = 5


class QuestionSearchItem(BaseModel):
    """题目检索命中行：**不含 answer**，与练习 / 笔试的答案口径一致。"""

    question_id: str
    prompt: str
    direction: str
    sub_direction: str = ""
    score: float = 0.0


class QuestionSearchResponse(BaseModel):
    """r51 题目检索结果：mode = fts5 | like（降级），notice 说明降级原因。"""

    items: list[QuestionSearchItem]
    total: int
    mode: str
    notice: str = ""


class LearnChapterProgress(BaseModel):
    """单个教程章节的已读状态（r61 上云：与前端 localStorage 结构逐字同构）。"""

    seen: list[str] = Field(default_factory=list, description="已读小节 id（章节内唯一）")
    last_section_id: str | None = Field(default=None, description="该章读到的小节 id")
    updated_at: int = Field(default=0, description="毫秒时间戳，仅用于跨设备合并取新")


class LearnProgress(BaseModel):
    """整份阅读进度：`last_chapter_id` 是「继续学习」入口，`chapters` 按章节 id 索引。"""

    last_chapter_id: str | None = None
    chapters: dict[str, LearnChapterProgress] = Field(default_factory=dict)


class PlanStatePayload(BaseModel):
    """7 天计划打卡状态：`daily_minutes` 是时长偏好，`done` 只记「做完」。"""

    daily_minutes: Literal[15, 30, 60] = 30
    done: dict[str, bool] = Field(default_factory=dict, description="task_id → 是否已打卡")


class PlanState(PlanStatePayload):
    """读回的计划状态：`updated_at` 空串表示该报告还没有任何打卡记录（前端据此决定是否回推本地）。"""

    report_id: str
    updated_at: str = ""


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


# --- 诊断报告三块补强（r7 AC-13：全部可选、带默认值，旧 payload 直接反序列化）--------
#
# 三块语义（**必须照此实现**，`None` 与 `[]` 在页面/`.md` 上是两套文案）：
# - `None`  = 旧报告，字段从未落库 → 「旧报告不含该区块，重新生成可补全」
# - `[]`    = 新报告但本块无内容 → 各块自己的中文空态（文案见 `services/coach_copy.py`）
# - 非空    = 正常渲染
# 前端**禁止** `?? []` 兜底（会把旧报告误报成「没有计分题」），三态判定集中在 `lib/coach.ts`。


class WeaknessSample(BaseModel):
    """薄弱分组里的单条证据：题目 id + 得分，与短板主轴同一口径。"""

    question_id: str
    score: float
    evidence: str = Field(description="如「Q3 · 4/10」，由 `markdown.format_score` 生成")


class WeaknessItem(BaseModel):
    """知识薄弱地图的一条：方向 × 难度 × 必备级别 的分组聚合结果（只投影、不重算）。"""

    key: str = Field(description="分组键 `方向|难度,|必备度,`，前端 React key 与 AI 合并键")
    point: str = Field(description="展示名，来自 `diagnosis._bucket_name`（与主轴同口径）")
    direction: str = Field(default="", description="组内题目的方向；无标签组为空串")
    #: r49 纯附加字段：组内题目出现最多的合法二级方向。不进分组 key、不改条数与排序，
    #: 缺省 "" 让旧报告反序列化零改动；前端学习计划据此优先选同子方向的教程章。
    sub_direction: str = Field(default="", description="组内题目众数二级方向；无标签组为空串")
    wrong: int = Field(description="低于 `rules.SEVERITY_MEDIUM_BELOW` 的题数")
    total: int
    rate: float = Field(description="错误率 = round(wrong/total, 3)，服务端算好")
    avg: float = Field(description="组内均分，round(...,1)")
    difficulty: list[str] = Field(default_factory=list, description="⊆ rules.DIFFICULTIES；无标签为 []")
    essentiality: list[str] = Field(default_factory=list, description="⊆ rules.ESSENTIALITIES；无标签为 []")
    samples: list[WeaknessSample] = Field(default_factory=list, description="1..3 条，按得分升序")
    summary: str = Field(description="一句话薄弱描述（模板文案，AI 可替换）")


class ResumePointer(BaseModel):
    """简历改进要点的一条：锚点是简历正文里的**逐字**切片，点跳 `/polish` 靠它定位。"""

    section: PolishSection
    location: str = Field(description="如「项目经历 · 第 12 行」，由服务端算出的 start 推出")
    anchor_text: str = Field(description="正文逐字切片（≤40 字），无改写、无归一化")
    issue: str = Field(description="一句话问题，≤60 字")
    focus_key: str = Field(description="定位键；当前语义即「与 anchor_text 逐字相等」")


class RoleModelRef(BaseModel):
    """命中的内置岗位能力模型（`model=None` 表示未命中，走降级文案）。"""

    level: str = Field(description="初级 / 中级 / 高级 / 专家")
    label: str = Field(description="如「前端工程师 · 中级」")
    direction: str | None = Field(
        default=None, description="岗位方向（如「前端」），与课程 / 题库的 direction 同一闭集"
    )


class RoleFitItem(BaseModel):
    """竞争力差距表的一行：要求 / 当前 / 差距全部可复算，AI 不参与数值。"""

    name: str
    required: int = Field(description="模型要求档位，1..4")
    user_level: int = Field(description="画像档位，0..4（规则见 `services/role_fit.py`）")
    gap: int = Field(description="max(0, required-user_level)")
    must: bool = Field(description="是否该级模型的必备技能（排序与缺失清单都用它）")


class RoleFit(BaseModel):
    """市场竞争力对标：目标岗位 + 来源 + 差距表 + 缺失必备 + 先补 1/2/3。"""

    target_role: str | None = None
    role_source: Literal["interview", "profile"] | None = Field(
        default=None, description="目标岗位来源优先级：本次面试设定 > 简历画像（AC-9）"
    )
    role_source_label: str | None = Field(default=None, description="「本次面试设定」/「简历画像」")
    model: RoleModelRef | None = Field(default=None, description="None ⇒ 无匹配模型（AC-10）")
    items: list[RoleFitItem] = Field(default_factory=list)
    missing_must: list[str] = Field(default_factory=list, description="gap>0 的必备技能（缺 ⇔ 未达标）")
    first_fix: list[str] = Field(default_factory=list, description="前 3 个 gap>0 的 name，顺序即优先级")
    conclusion: str | None = Field(default=None, description="一句话结论（AI 可替换）")
    notice: str | None = Field(default=None, description="降级原因文案（服务端定，前端只渲染）")


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
    interview_settings: InterviewSettings | None = Field(
        default=None, description="报告引用面试的设定；无面试或旧 run 时为 None"
    )
    # --- r7 三块补强（全部可选：旧报告 payload 里没有这些键，反序列化即 None）----------
    weakness_map: list[WeaknessItem] | None = Field(
        default=None, description="知识薄弱地图；None=旧报告，[]=本次无已计分题"
    )
    resume_pointers: list[ResumePointer] | None = Field(
        default=None, description="简历改进要点；None=旧报告，[]=无正文或 AI 降级（原因见 notice）"
    )
    resume_pointers_notice: str | None = Field(
        default=None, description="resume_pointers 为空时的中文原因；非空数组时为 None"
    )
    role_fit: RoleFit | None = Field(default=None, description="市场竞争力对标；None=旧报告")


class RunSummary(BaseModel):
    id: str
    kind: RunKind
    score: float | None = None
    shortfall_count: int | None = None
    created_at: str
    interview_settings: InterviewSettings | None = Field(
        default=None, description="面试 run 的设定；笔试与旧 run 为 None"
    )


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


class ResumeJobStarted(BaseModel):
    """`POST /api/resumes/images/async` 响应：识别任务已受理，凭 `job_id` 轮询（r42）。"""

    job_id: str
    status: str = "running"


class ResumeJobStatus(BaseModel):
    """`GET /api/resume-jobs/{job_id}` 响应：图片识别任务状态 + 终态 ResumeMeta（r42）。

    `completed` 时 `result` 是已入库简历的 `ResumeMeta`；`failed` 时 `error` 是可直接展示的中文原因。
    """

    job_id: str
    file_name: str
    image_count: int
    status: str
    error: str
    result: ResumeMeta | None = None
    created_at: str


class ProfileJobStarted(BaseModel):
    """`POST /api/resumes/{id}/profile/async` 响应：任务已受理，凭 `job_id` 轮询（r30）。"""

    job_id: str
    status: str = "running"


class ProfileJobStatus(BaseModel):
    """`GET /api/profile-jobs/{job_id}` 响应：任务状态 + 终态结果（r30）。

    `completed` 时 `result` 是完整 `ProfileWithMerge`（含一次性 `merge_summary`，
    后台完成也不丢「本次合并」摘要）；`failed` 时 `error` 是可直接展示的中文原因。
    """

    job_id: str
    document_id: str
    file_name: str
    chars: int
    sections: int
    status: str  # running | completed | failed
    error: str = ""
    result: ProfileWithMerge | None = None
    created_at: str


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


# --- r23 登录 / 用户 / 自带 AI Key --------------------------------------------

#: 用户 Key 的来源模式：`own` = 自己填 Key；`shared` = 管理员同意的内置 Key。
KeyMode = Literal["own", "shared"]
#: 当前用户可用的 AI 能力：`full` 全开 / `light` 仅轻量 / `none` 不可用。
AiCapability = Literal["full", "light", "none"]


class LoginRequest(BaseModel):
    email: str
    password: str = Field(min_length=1)


class MeResponse(BaseModel):
    """当前用户 + AI 状态；`ai_masked_key` 只含后 4 位，绝不含明文。"""

    id: str
    email: str
    display_name: str
    role: str
    key_mode: KeyMode
    ai_capability: AiCapability
    ai_base_url: str = ""
    ai_model: str = ""
    ai_json_mode: str = "json_object"
    ai_masked_key: str = ""
    ai_updated_at: str = ""
    #: 内置 Key 今日已用 / 每日上限；非 `shared` 恒 0（上限 0 表示不限次数）。
    ai_quota_used: int = 0
    ai_quota_limit: int = 0


class AiSettingsRequest(BaseModel):
    """保存自带 Key：`api_key` 缺省（空）表示「沿用已保存的 Key」。"""

    base_url: str
    model: str
    api_key: str = ""
    json_mode: JsonMode = "json_object"


class AiTestRequest(BaseModel):
    """测试连接：字段全可选，缺省用已保存的配置。"""

    base_url: str = ""
    model: str = ""
    api_key: str = ""
    json_mode: JsonMode = "json_object"


class AiTestResult(BaseModel):
    ok: bool
    message: str


class PasswordChangeRequest(BaseModel):
    old_password: str = Field(min_length=1)
    new_password: str = Field(min_length=1)


# --- r65 AI 学习教练（检索增强 + 引用白名单） ---------------------------------
#
# 材料由前端组装（教程正文只在 `frontend/src/lib/tutorials.ts`，后端没有语料），
# 因此这里同时是「上传上下文」与「引用白名单」的契约：`href` 必须逐字出现，
# 模型给的 href 命中不了允许集合 → 该条建议直接丢弃并计入 `dropped_citations`。


class CoachMaterial(BaseModel):
    """一条站内材料：`href` 是后续引用校验的唯一凭据。"""

    title: str = ""
    href: str = ""
    direction: str = ""
    sub_direction: str = ""
    level: str = ""
    detail: str = ""


class CoachAdviceRequest(BaseModel):
    materials: list[CoachMaterial] = Field(default_factory=list)
    focus: str = Field(default="", description="本次聚焦的方向 / 岗位，空串表示由模型自行收窄")
    goal: str = Field(default="", description="用户本次想解决的问题，空串表示按薄弱方向默认目标")


class CoachAction(BaseModel):
    """一条可执行动作：`href` 已通过白名单校验，前端可直接跳转。"""

    label: str
    href: str
    why: str = ""
    minutes: int = 30


class CoachBlock(BaseModel):
    title: str
    reason: str = ""
    actions: list[CoachAction] = Field(default_factory=list)


class CoachAdvice(BaseModel):
    summary: str = ""
    blocks: list[CoachBlock] = Field(default_factory=list)
    #: 通过清洗后真正交给模型的材料条数（0 表示未调用模型）。
    materials_used: int = 0
    #: 因 href 不在白名单被丢弃的动作条数（幻觉引用计数器）。
    dropped_citations: int = 0
    #: 空材料 / 全部引用不可核对时的中文说明；正常出建议时为空串。
    notice: str = ""


# --- r67 技术雷达（先锋 / 国子监） --------------------------------------------
#
# 技术清单 / 快照 / 评估是全局知识；只有生成任务 `radar_jobs` 按账号隔离。
# `tech_slug` 形如 `github:owner/repo`，含 `/` 与 `:`，故**一律走 body 传参**，
# 不做路径参数端点（生成入口 `POST /api/radar/generate`）。


class RadarSourceStatus(BaseModel):
    """单个采集源的本轮结果：`ok` / `degraded` / `offline`（形状同 `sources.fetch_all`）。"""

    source_key: str
    status: str = "ok"
    items: int = 0
    latency_ms: int = 0
    message: str = ""


class RadarRunRequest(BaseModel):
    """指定本轮采集范围：`direction` 走站内方向闭集，`repo` 接受 GitHub 链接或 `owner/repo`。

    两者都留空时就是原有的全源默认轮次；都填时以仓库为准（只采该仓库）。
    """

    direction: str = ""
    repo: str = ""


class RadarRunSummary(BaseModel):
    """一轮采集的结果摘要（`/runs/latest` 也返回它）。"""

    run_id: int = 0
    trigger: str = ""
    started_at: str = ""
    finished_at: str = ""
    degraded: bool = False
    techs_seen: int = 0
    sources: list[RadarSourceStatus] = Field(default_factory=list)
    notice: str = ""


class RadarTechItem(BaseModel):
    """先锋页一条技术：最新评估 + 最新快照 + 当前账号在该技术上的任务。"""

    tech_slug: str
    name: str
    direction: str
    sub_direction: str = ""
    source_key: str = ""
    url: str = ""
    summary: str = ""
    verdict: str = "skip"
    verdict_label: str = ""
    relevance: int = 1
    adoption: int = 1
    maturity: int = 1
    effort: int = 1
    reasons: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    rule_based: bool = False
    assessed_at: str = ""
    stars: int = 0
    star_delta_7d: int = 0
    suspect: bool = False
    job_id: str = ""


class RadarTechList(BaseModel):
    items: list[RadarTechItem] = Field(default_factory=list)
    total: int = 0
    #: 本轮采集的概括说明（离线 / 降级 / 丢弃引用等），空串表示无特别情况。
    notice: str = ""


class RadarManualRequest(BaseModel):
    """手工录入一条技术线索：GitHub 仓库链接会补一次公开元数据，其余直接进清单。"""

    name: str = Field(min_length=1)
    url: str = ""
    summary: str = ""
    direction: str = ""
    sub_direction: str = ""


class RadarGenerateRequest(BaseModel):
    tech_slug: str = Field(min_length=1)


class RadarJobAccepted(BaseModel):
    """生成入口响应：`reused=True` 表示命中在途任务，未重复烧 token（AC-3）。"""

    job_id: str
    tech_slug: str
    status: str = "queued"
    reused: bool = False


class RadarChapterSection(BaseModel):
    id: str
    title: str
    body: str
    bullets: list[str] = Field(default_factory=list)


class RadarChapterDraft(BaseModel):
    """章节草稿：`id` 一律 `radar-` 前缀（不占用官方 40 章的 id 命名空间）。"""

    id: str
    title: str
    direction: str = ""
    sub_direction: str = ""
    level: str = "intermediate"
    summary: str = ""
    sections: list[RadarChapterSection] = Field(default_factory=list)


class RadarQuestionOption(BaseModel):
    key: str
    text: str


class RadarQuestionSample(BaseModel):
    id: str
    direction: str = ""
    sub_direction: str = ""
    kind: str
    difficulty: str
    essentiality: str = "advanced"
    prompt: str
    options: list[RadarQuestionOption] = Field(default_factory=list)
    answer: list[str] = Field(default_factory=list)
    language: str = ""
    explanation: str = ""


class RadarJobItem(BaseModel):
    """国子监一条任务：进度 + 草稿 + 自检丢弃计数。

    `status` ∈ `queued` / `running` / `succeeded` / `adopted` / `discarded` / `failed`；
    `adopted` 与 `discarded` 是互斥终态（AC-8）。
    """

    job_id: str
    tech_slug: str
    tech_name: str = ""
    status: str = "queued"
    stage: str = "chapter"
    progress: int = 0
    chapter: RadarChapterDraft | None = None
    questions: list[RadarQuestionSample] = Field(default_factory=list)
    discarded_count: int = 0
    error_message: str = ""
    trigger: str = "manual"
    created_at: str = ""
    updated_at: str = ""


class RadarJobList(BaseModel):
    items: list[RadarJobItem] = Field(default_factory=list)
    total: int = 0
