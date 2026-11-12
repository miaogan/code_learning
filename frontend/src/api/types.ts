// 与 backend/app/schemas.py 同构的契约类型。字段名沿用 snake_case，避免两侧映射出错。

export type CourseLevel = '入门' | '进阶'
export type Severity = 'high' | 'medium' | 'low'
export type RunKind = 'interview' | 'exam'

export interface Health {
  status: string
  version: string
  ai_configured: boolean
  db: string
  // r9 运维白名单三字段（与 /health 逐字镜像，永不携带 Key 片段）。
  // 标可选是为了旧后端 / 旧构建产物仍类型安全；本轮不渲染它们。
  ai_provider?: string
  ai_model?: string
  ai_json_mode?: string
}

export interface ResumeMeta {
  resume_id: string
  file_name: string
  chars: number
  sections: number
  /** r41：来源类型；存量后端默认返回 `pdf`，旧客户端按 `pdf` 处理即可。 */
  source_type: 'pdf' | 'docx' | 'txt' | 'image'
  /** 仅 `source_type=image` 时大于 1（同一次上传的多张照片拼成一份简历）。 */
  image_count: number
}

/**
 * r60 简历版本摘要：上传展示元信息 + 该版本最近一次测评成绩。
 * `interview_avg` / `exam_total` 与历史页同源（后端 `history.score_of`），页面零换算；
 * 两者为 `null` 表示「该版本还没有这一类的有分记录」——不是 0 分。
 */
export interface ResumeVersionSummary {
  resume_id: string
  file_name: string
  source_type: 'pdf' | 'docx' | 'txt' | 'image'
  chars: number
  sections: number
  created_at: string
  has_profile: boolean
  interview_avg: number | null
  exam_total: number | null
  /** 该版本下已完成的测评场数（面试 + 笔试）。 */
  judged_count: number
}

/** r60 单版详情：摘要 + 画像；未生成画像时 `profile` 为 `null`。 */
export interface ResumeVersionDetail extends ResumeVersionSummary {
  profile: Profile | null
}

/**
 * 一条来源证据（r3：旧→新累积）。`quote` 必须在来源简历正文里**逐字命中**（AC-6 的可溯源真源）；
 * `resume_id`/`file_name`/`captured_at` 由服务端回填，缺失时前端原样展示「来源未记录」而不猜。
 */
export interface Evidence {
  quote: string
  resume_id: string
  file_name: string
  captured_at: string
}

/**
 * 能力项 / 项目在增量合并后的状态（r3）：
 * `active` = 最新简历仍出现（进画像主卡、进画出题与诊断）；
 * `historical` = 本次简历未出现（证据保留、不删，但不进主卡与策划素材）。
 * 兼容回填（PRD R1）：缺此字段的旧 payload 视作 `active`。
 */
export type ProfileEntryStatus = 'active' | 'historical'

export interface ProfileSkill {
  name: string
  /** 兼容字段：与 `source_quotes[0].quote` 同源，保留给旧调用方 / 旧 payload。 */
  source_quote: string
  /** r3 累积证据（旧→新）；缺省时前端用 `source_quote` 回填首条（不伪造日期/文件名）。 */
  source_quotes?: Evidence[]
  status?: ProfileEntryStatus
}

export interface ProfileProject {
  name: string
  /**
   * r8：与 `backend/app/schemas.py` 的 `ProfileProject.role: str | None = None` 逐字段对齐。
   * 提示词明确允许模型对「简历没写」的项填 `null`，故契约必须接受 `null`；
   * `null` 表示**未知**，不要用 `''` 伪装成已知（渲染前经 `lib/profileText.ts` 的 `textOrEmpty` 归一）。
   */
  role: string | null
  /** r8：同 `role`，`None` 表示简历里没有时间信息。 */
  period: string | null
  bullets: string[]
  source_quote: string
  source_quotes?: Evidence[]
  status?: ProfileEntryStatus
}

export interface ProfileDraft {
  skills: ProfileSkill[]
  tech_stack: string[]
  years_experience: number | null
  projects: ProfileProject[]
  target_role: string | null
}

export interface Profile extends ProfileDraft {
  id: string
  resume_id: string
  updated_at: string
}

export interface ProfilePatch {
  skills?: ProfileSkill[]
  tech_stack?: string[]
  years_experience?: number | null
  projects?: ProfileProject[]
  target_role?: string | null
}

/* ------------------------------------------------------------------ *
 * r5 契约 · 面试会话与四项配置（TECHNICAL §2.6；与 backend/app/schemas.py 逐字段镜像）
 * ------------------------------------------------------------------ */

export type ExperienceBand = '应届' | '1-3年' | '3-5年' | '5-10年' | '10年以上'
export type InterviewMarket = '国内' | '北美' | '欧洲' | '其他'
export type CompanySize = '大厂' | '中型' | '初创'

export interface InterviewSettings {
  target_role: string
  years_experience: ExperienceBand
  market: InterviewMarket
  company_size: CompanySize
  /** 可选方向聚焦：空串 / 缺省 = 不限（老 run 没有这两键）。取值见 lib/questionDirections。 */
  direction?: string
  sub_direction?: string
}

export interface InterviewSettingsPatch {
  target_role?: string
  years_experience?: ExperienceBand
  market?: InterviewMarket
  company_size?: CompanySize
  direction?: string
  sub_direction?: string
}

export interface InterviewCreateRequest {
  profile_id: string
  settings?: InterviewSettingsPatch
}

export interface InterviewQuestion {
  id: string
  kind: 'technical' | 'project' | 'challenge'
  prompt: string
  hint: string
  parent_id: string | null
}

/** 开局响应：只投放第 1 条发言（计划正文在服务端 payload.plan，不外泄）。 */
export interface InterviewRun {
  run_id: string
  settings: InterviewSettings
  question: InterviewQuestion
  total: number
}

export interface AnswerRequest {
  question_id: string
  answer: string
}

export interface ScoreResult {
  score: number
  comment: string
}

/** 单轮响应：本轮评分 + 下一条发言（ScoreResult 超集）。 */
export interface InterviewTurn extends ScoreResult {
  next_question: InterviewQuestion | null
  run_status: 'running' | 'completed'
  answered_count: number
  total: number
  interview_avg: number | null
}

export interface InterviewSessionQuestion {
  id: string
  kind: 'technical' | 'project' | 'challenge'
  prompt: string
  hint: string
  parent_id: string | null
  answer: string | null
  score: number | null
  comment: string | null
}

/** GET /api/interviews/{run_id}：刷新/重进后的完整会话镜像。 */
export interface InterviewSession {
  run_id: string
  status: 'running' | 'completed'
  settings: InterviewSettings | null
  questions: InterviewSessionQuestion[]
  answered_count: number
  total: number
  current_id: string | null
  interview_avg: number | null
}

/**
 * r62 历史面试列表行（`GET /api/interviews`）：在途场次也会返回，
 * 读数是 `/api/interviews/{run_id}` 同一套投影（`total` / `answered_count` / `interview_avg`）。
 */
export interface InterviewSessionSummary {
  run_id: string
  status: 'running' | 'completed'
  created_at: string
  settings: InterviewSettings | null
  total: number
  answered_count: number
  interview_avg: number | null
}

/* ------------------------------------------------------------------ *
 * r6 契约 · 题目四维标签（与 backend/app/schemas.py 的 ExamDifficulty /
 * QuestionEssentiality 逐字镜像；闭集单一出处在 backend/app/services/rules.py）
 * ------------------------------------------------------------------ */

/** 难度三档：基础 / 中级（r6 新增）/ 挑战。 */
export type ExamDifficulty = 'basic' | 'intermediate' | 'challenge'
/** 必备度三档：必备 / 进阶 / 加分项。 */
export type QuestionEssentiality = 'must_know' | 'advanced' | 'nice_to_know'
/**
 * 题型闭集（r11 扩 `judge` 判断题）：与 `backend/app/schemas.py:ExamKind` 逐字一致，
 * 单一出处在 `backend/app/services/rules.py:OBJECTIVE_KINDS`。`text` 是简答题（不判分）。
 */
export type ExamKind = 'single' | 'multiple' | 'judge' | 'text'

/**
 * 题干语言闭集（r11）。**`''` 是闭集成员**（通用 / 算法题），不是「全部」——
 * 筛选里的「全部」是 `'all'`（`rules.FILTER_ANY`），两条语义不得混用。
 */
export type QuestionLanguage =
  | ''
  | 'python'
  | 'java'
  | 'go'
  | 'html'
  | 'css'
  | 'js'
  | 'ts'
  | 'vue3'
  | 'react'

export interface ExamOption {
  key: string
  text: string
}

export interface ExamCreateRequest {
  profile_id: string
  /** 指定方向（如 ["前端", "后端"]），空数组 / 不传 = 按画像智能组卷 */
  direction?: string[] | null
  /** 指定二级方向（如 ["python", "react"]），空数组 / 不传 = 不过滤；未传一级方向时后端按子方向自动补归属方向 */
  sub_direction?: string[] | null
  /** 指定难度档（如 ["basic", "intermediate"]），空数组 / 不传 = 不过滤 */
  difficulty?: string[] | null
  /** 目标题量，不传则默认 10–12，下限 10、上限 20 */
  question_count?: number | null
}

export interface ExamQuestion {
  id: string
  kind: ExamKind
  direction: string
  prompt: string
  options: ExamOption[]
}

export interface ExamRun {
  run_id: string
  questions: ExamQuestion[]
  /**
   * 本次**净过滤**掉的熟练题数（r6 AC-12）＝ `|熟练 ∩ 可用| − |熟练 ∩ 本卷|`，恒 `>= 0`。
   * 服务端恒返回（`Field(default=0)`）；读侧仍交给 `lib/examNotice` 的 `filteredNotice()` 解释，
   * 旧 payload 缺该字段时按 0 静默处理（页面不挂载任何断言性文案）。
   */
  filtered_count: number
  /**
   * r43：本卷里**已熟练但被兜底放回**的题数（= `|熟练 ∩ 本卷|`）。
   * 与 `filtered_count` 互补，用于「另有 N 道因保持卷面结构被重新纳入」；
   * 旧 payload 缺该字段时按 0 静默处理。
   */
  reintroduced_count: number
  /**
   * r46：实际生效的子方向（闭集内取值）；未指定 / 闭集外脏参数时为空串（= 未聚焦）。
   * 与服务端 `ExamRun.sub_direction` 逐字对齐。
   */
  sub_direction: string
  /**
   * r46：本卷中**不属于所选子方向**、因该子方向题量不足而补齐的题数（0 = 全部命中）。
   * 由 `lib/examNotice` 的 `subDirectionNotice()` 解释成一句透明文案。
   */
  sub_direction_backfill: number
}

export interface ExamAnswers {
  answers: Record<string, string[] | string>
}

export interface PerQuestionResult {
  question_id: string
  correct: boolean | null
  your_answer: string[] | string | null
  correct_answer: string[] | string | null
}

export interface ExamResult {
  total: number
  correct_count: number
  objective_total: number
  elapsed_s: number
  per_question: PerQuestionResult[]
}

/** r51 模型调用质量看板：单个模型聚合行。 */
export interface EvalModelStat {
  total: number
  success_rate: number
  p95_ms: number
}

export interface EvalTrendPoint {
  day: string
  total: number
  success_rate: number
}

/** 只读聚合：分母与分位算法固定在后端，前端只做展示（零二次统计）。 */
export interface EvalSummary {
  window_days: number
  total: number
  success_rate: number
  p50_ms: number
  p95_ms: number
  by_kind: Record<string, number>
  by_model: Record<string, EvalModelStat>
  trend: EvalTrendPoint[]
  notice: string
}

/** r51 题目全文检索请求：方向 / 子方向可选，闭集外脏值由服务端静默忽略。 */
export interface QuestionSearchRequest {
  query: string
  /** 方向多选；空数组 / 不传 = 全部方向（后端兼容旧的单值字符串）。 */
  direction?: string[]
  sub_direction?: string
  /** 每页条数 */
  limit?: number
  /** 页码，从 1 起（`total` 是命中总数） */
  page?: number
}

export interface QuestionSearchItem {
  question_id: string
  prompt: string
  direction: string
  sub_direction: string
  score: number
}

/** mode = fts5 | like（降级）；响应永不含 answer。 */
export interface QuestionSearchResponse {
  items: QuestionSearchItem[]
  total: number
  mode: string
  notice: string
}

export interface Course {
  id: string
  title: string
  direction: string
  level: CourseLevel
  url: string | null
  why: string
}

/* ---------- r61 学习进度与 7 天计划打卡（服务端权威副本，本地只做缓存） ---------- */

export interface LearnChapterProgress {
  seen: string[]
  last_section_id: string | null
  updated_at: number
}

export interface LearnProgress {
  last_chapter_id: string | null
  chapters: Record<string, LearnChapterProgress>
}

export interface PlanStatePayload {
  daily_minutes: 15 | 30 | 60
  /** task_id → 是否已打卡；服务端只保留 `true` 条目。 */
  done: Record<string, boolean>
  /** r95 计划起始日（本机日历日 `YYYY-MM-DD`）；空串 = 还没开始计时。 */
  started_on: string
}

export interface PlanState extends PlanStatePayload {
  report_id: string
  /** 空串表示该报告还没有任何打卡记录（前端据此把本地记录回推上去）。 */
  updated_at: string
}

export interface Shortfall {
  name: string
  severity: Severity
  evidence: string
  diagnosis: string
  actions: string[]
  courses: Course[]
  question_ref: string | null
}

/* ------------------------------------------------------------------ *
 * r7 契约 · 诊断报告三块补强（与 backend/app/schemas.py 逐字镜像）
 *
 * 三态语义（**禁止用 `?? []` 兜底**，否则旧报告会被误报成「没有计分题」）：
 * `null` = 旧报告（字段未落库）→ 「旧报告不含该区块，重新生成可补全」；
 * `[]`   = 新报告但本块无内容 → 各块自己的中文空态；
 * 非空   = 正常渲染。三态判定集中在 `lib/coach.ts` 的 `blockStateOf()`。
 * ------------------------------------------------------------------ */

/** 薄弱分组里的单条证据：题目 id + 得分（与短板主轴同一口径）。 */
export interface WeaknessSample {
  question_id: string
  score: number
  /** 如「Q3 · 4/10」，服务端用 `markdown.format_score` 生成。 */
  evidence: string
}

/** 知识薄弱地图的一条：方向 × 难度 × 必备级别 的分组聚合。 */
export interface WeaknessItem {
  /** 分组键 `方向|难度,|必备度,`（React key / AI 合并键）。 */
  key: string
  /** 展示名，来自 `diagnosis._bucket_name`。 */
  point: string
  direction: string
  /** r49 纯附加字段：组内题目众数二级方向。旧报告缺该键，学习计划按空串回落方向级选章。 */
  sub_direction?: string
  wrong: number
  total: number
  /** 错误率 = round(wrong/total, 3)，服务端算好，前端零除法。 */
  rate: number
  avg: number
  difficulty: string[]
  essentiality: string[]
  samples: WeaknessSample[]
  /** 一句话薄弱描述（模板文案；AI 可替换）。 */
  summary: string
}

/** 简历改进要点的一条：锚点是简历正文里的逐字切片，点跳 `/polish` 靠它定位。 */
export interface ResumePointer {
  section: PolishSection
  /** 如「项目经历 · 第 12 行」。 */
  location: string
  /** 正文逐字切片（≤40 字）。 */
  anchor_text: string
  /** 一句话问题（≤60 字）。 */
  issue: string
  /** 定位键，当前语义即「与 anchor_text 逐字相等」。 */
  focus_key: string
}

/** 命中的内置岗位能力模型（`role_fit.model === null` 表示未命中）。 */
export interface RoleModelRef {
  level: string
  /** 如「前端工程师 · 中级」。 */
  label: string
  /** 岗位方向（如「前端」），与课程 / 题库的 direction 同一闭集；旧报告为 null。 */
  direction: string | null
}

/** 竞争力差距表的一行：要求 / 当前 / 差距全部可复算。 */
export interface RoleFitItem {
  name: string
  required: number
  user_level: number
  gap: number
  must: boolean
}

/** 市场竞争力对标：目标岗位 + 来源 + 差距表 + 缺失必备 + 先补 1/2/3。 */
export interface RoleFit {
  target_role: string | null
  /** 来源优先级：本次面试设定 > 简历画像（AC-9）。 */
  role_source: 'interview' | 'profile' | null
  /** 「本次面试设定」/「简历画像」。 */
  role_source_label: string | null
  model: RoleModelRef | null
  items: RoleFitItem[]
  /** gap>0 的必备技能（缺 ⇔ 未达标）。 */
  missing_must: string[]
  /** 前 3 个 gap>0 的 name，顺序即优先级（前端不得重排）。 */
  first_fix: string[]
  conclusion: string | null
  /** 降级原因文案（服务端定，前端只渲染）。 */
  notice: string | null
}

export interface ReportGenerateRequest {
  run_ids?: string[]
}

export interface Report {
  id: string
  run_ids: string[]
  interview_avg: number | null
  exam_total: number | null
  shortfalls: Shortfall[]
  generated_at: string
  interview_settings: InterviewSettings | null
  /** 知识薄弱地图；`null` = 旧报告，`[]` = 本次无已计分题。 */
  weakness_map: WeaknessItem[] | null
  /** 简历改进要点；`null` = 旧报告，`[]` = 无正文 / AI 降级（原因见 `resume_pointers_notice`）。 */
  resume_pointers: ResumePointer[] | null
  /** `resume_pointers` 为空时的中文原因；非空数组时为 `null`。 */
  resume_pointers_notice: string | null
  /** 市场竞争力对标；`null` = 旧报告。 */
  role_fit: RoleFit | null
}

export interface RunSummary {
  id: string
  kind: RunKind
  score: number | null
  shortfall_count: number | null
  created_at: string
  interview_settings: InterviewSettings | null
  /** 上一条同类型记录的分数；分页后可能落在上一页，故由服务端算好 */
  prev_score: number | null
  /** 是否存在上一条同类型记录（区分「暂无对比」与「未计分」） */
  has_prev: boolean
}

/** 历史分页结果：`items` 是本页条目，`total` 是命中总数（与列表同一过滤口径）。 */
export interface HistoryList {
  items: RunSummary[]
  total: number
  /** 面试 / 笔试各自的历史总数（筛选标签的统计口径） */
  interview_total: number
  exam_total: number
}

export interface ApiErrorBody {
  error: {
    code: string
    message: string
    retryable: boolean
  }
}

/* ------------------------------------------------------------------ *
 * r3 契约 · 成长时间线（TECHNICAL §3；与 backend/app/schemas.py 逐字段镜像）
 * ------------------------------------------------------------------ */

export type TimelineType = 'interview' | 'exam' | 'resume'

/** 与单次运行等价的指标快照（写入即定格；分数/短板口径只在服务端算一次）。 */
export interface TimelineMetrics {
  /** 面试均分，与 `history.score_of` 同源。 */
  interview_avg: number | null
  /** 笔试总分，与 `ExamResult.total` 同源。 */
  exam_total: number | null
  /** 短板条数，与 `len(build_shortfalls([run]))` 同源。 */
  shortfall_count: number | null
  /** 简历事件：本次新增能力项数。 */
  skill_added: number
  /** 简历事件：本次转为历史的能力项数。 */
  skill_removed: number
}

/**
 * 本次 vs 上次同类事件（服务端算好，前端**零减法**：只渲染）。
 * `metric` 指明比较的是哪个指标；`delta` 已由服务端保留 1 位小数。
 */
export interface TimelineComparison {
  prev_event_id: string
  prev_occurred_at: string
  metric: 'interview_avg' | 'exam_total'
  prev_value: number
  current_value: number
  delta: number
  /** 两次都在 = 复现/持续。 */
  repeated_shortfalls: string[]
  /** 上次有、本次无。 */
  disappeared_shortfalls: string[]
}

export interface TimelineEvent {
  id: string
  type: TimelineType
  ref_id: string
  occurred_at: string
  key_metrics: TimelineMetrics
  shortfall_names: string[]
  /** 本次有、上次无（无上次则 = 全部）。 */
  added_shortfalls: string[]
  /** 上次有、本次无。 */
  removed_shortfalls: string[]
  /** 服务端组装的中文一句话。 */
  summary: string
  /** 同一份简历重复上传仍记事件，但弱化展示（不弹错误、不隐藏）。 */
  duplicate: boolean
  /** 无同类上一条时为 `null`（前端渲染「首次…，暂无对比」，不外显 0.0 / NaN）。 */
  comparison: TimelineComparison | null
}

/** 一次上传后增量合并的结果摘要（一次性会话态，不落 `GET /profiles/latest` 契约）。 */
export interface ProfileMergeSummary {
  added: number
  historical: number
  evidence_added: number
  duplicate: boolean
}

/** `POST /api/resumes/{id}/profile` 的响应：画像 + 本次合并摘要。 */
export interface ProfileWithMerge extends Profile {
  merge_summary: ProfileMergeSummary | null
}

/* ------------------------------------------------------------------ *
 * r30 契约 · 异步画像任务（后台生成 + 前端轮询）
 * ------------------------------------------------------------------ */

/** `POST /api/resumes/{id}/profile/async` 的响应：任务已受理，凭 `job_id` 轮询。 */
export interface ProfileJobStarted {
  job_id: string
  status: 'running'
}

/** 画像生成任务状态：`completed` 时 `result` 是完整 `ProfileWithMerge`（含一次性合并摘要）。 */
export interface ProfileJobStatus {
  job_id: string
  document_id: string
  file_name: string
  chars: number
  sections: number
  status: 'running' | 'completed' | 'failed'
  error: string
  result: ProfileWithMerge | null
  created_at: string
}

/* ------------------------------------------------------------------ *
 * r42 契约 · 图片识别异步任务（后台识别 + 前端轮询，与画像任务同构）
 * ------------------------------------------------------------------ */

/** `POST /api/resumes/images/async` 的响应：识别任务已受理，凭 `job_id` 轮询。 */
export interface ResumeJobStarted {
  job_id: string
  status: 'running'
}

/** 图片识别任务状态：`completed` 时 `result` 是已入库简历的 `ResumeMeta`。 */
export interface ResumeJobStatus {
  job_id: string
  file_name: string
  image_count: number
  status: 'running' | 'completed' | 'failed'
  error: string
  result: ResumeMeta | null
  created_at: string
}

/* ------------------------------------------------------------------ *
 * r3 契约 · 简历 AI 润色（TECHNICAL §3）
 * ------------------------------------------------------------------ */

export type PolishSection = 'project' | 'experience' | 'education' | 'summary'

export interface PolishSuggestion {
  id: string
  section: PolishSection
  /** 与简历正文**逐字相等**（服务端保证；前端只切片，不 trim、不 replace）。 */
  original_text: string
  /** 已通过反幻觉校验；缺数值处含「〈待补充〉」占位。 */
  suggested_text: string
  reason: string
  target_role: string | null
  /** 如 `numeric_added`（该条被降级）。 */
  flags: string[]
  /** 原句在正文中的起止偏移（服务端算，供前端本地切片预览）。 */
  start: number
  end: number
}

export interface PolishRequest {
  target_role?: string | null
}

export interface PolishResponse {
  polish_id: string
  resume_id: string
  target_role: string | null
  /**
   * 简历正文，与 `documents.text` **逐字相等**（字节级，服务端不 trim 不归一）。
   * 「原版」Tab 的唯一真源（r4 AC-1/AC-2/AC-5）：前端只渲染，不切片、不拼接、不参与成稿拼装。
   */
  resume_text: string
  /** 来源文件名（`documents.file_name`），导出命名用；存量数据可能为空串（AC-7/AC-8，空则回退日期）。 */
  file_name: string
  suggestions: PolishSuggestion[]
  dropped_count: number
  /** 条目不足时的中文说明（不造假条目）。 */
  insufficient_reason: string | null
}

export interface PolishFullRequest {
  polish_id?: string | null
  target_role?: string | null
  /** `null`/缺省 = 全部采纳。 */
  suggestion_ids?: string[] | null
}

export interface PolishFullResponse {
  id: string
  /** 唯一成稿真源：导出/复制只取这份文本。 */
  markdown: string
  dropped_count: number
  /** true = 进程内缓存失效后重跑了一套建议。 */
  regenerated: boolean
}

/* ------------------------------------------------------------------
 * r11 练习四端点（/api/practice/paper|answer|stats|wrong-book）
 * 与 `backend/app/schemas.py` 的 `Practice*` 逐字镜像（字段名 snake_case，零转换），
 * 闭集单一出处在 `backend/app/services/rules.py`。改字段必须两侧同时改。
 * ------------------------------------------------------------------ */

/** 语言筛选 = 闭集 + 「全部」（`'all'` 与通用题的 `''` 并存，两条语义不同）。 */
export type PracticeLanguageFilter = 'all' | QuestionLanguage
/** 方向筛选 = 四方向 + 「全部」。 */
export type PracticeDirectionFilter = 'all' | '前端' | '后端' | '算法与数据结构' | '计算机基础' | 'AI 工程' | '中间件与运维' | 'SQL 与数据库' | '研发工程实践'
/** 难度筛选 = 三档 + 「全部」。 */
export type PracticeDifficultyFilter = 'all' | ExamDifficulty
/** 必备度筛选 = 三档 + 「全部」。 */
export type PracticeEssentialityFilter = 'all' | QuestionEssentiality
/** 练习范围：全部 / 未做过（含笔试）/ 最近一次答错。 */
export type PracticeScope = 'all' | 'unseen' | 'wrong'
/** 练习题量：`0` = 本次全部命中。 */
export type PracticeLimit = 10 | 20 | 0

/** 二级方向筛选（r50）：空串 = 不聚焦；闭集由 `subDirectionsOf(direction)` 派生。 */
export type PracticeSubDirectionFilter = string

/** 组卷请求体。七项都有服务端默认值；筛选维度是多选数组，题量仍是单选。 */
export interface PracticePaperRequest {
  language?: PracticeLanguageFilter[]
  direction?: PracticeDirectionFilter[]
  difficulty?: PracticeDifficultyFilter[]
  essentiality?: PracticeEssentialityFilter[]
  scope?: PracticeScope[]
  limit?: PracticeLimit
  sub_direction?: PracticeSubDirectionFilter[]
}

/** 题单里的一道题：**不含** `answer`（答案只在判分响应里回显）。 */
export interface PracticeQuestion {
  id: string
  kind: ExamKind
  language: QuestionLanguage
  direction: string
  difficulty: ExamDifficulty
  essentiality: QuestionEssentiality
  prompt: string
  options: ExamOption[]
}

export interface PracticePaper {
  session_id: string
  questions: PracticeQuestion[]
  /** 全部筛选后的命中总数（不受 `limit` 截断），与 `PracticeStats.hit` 同源同值。 */
  hit_count: number
  /** 空结果 / 截断 / 题库未就绪的中文提示；正常满额时为空串。 */
  notice: string
  /** r50：实际生效的二级方向；未聚焦为空串。 */
  sub_direction: string
  /** r50：聚焦池不足题量时补齐的同方向题数（0 = 全部命中）。 */
  sub_direction_backfill: number
  /** r52：本次被熟练度过滤跳过的题数（与笔试同一份 30 天 / 答对 2 次判定；0 = 未过滤）。 */
  filtered_count: number
}

export interface PracticeAnswerRequest {
  session_id: string
  question_id: string
  answer?: string[] | string | null
}

export interface PracticeAnswerResult {
  question_id: string
  correct: boolean
  correct_answer: string[] | string | null
  /** 解析恒为字符串；空串时页面显示「本题暂无解析」。 */
  explanation: string
}

export interface PracticeStats {
  total: number
  practiced: number
  wrong_total: number
  hit: number
}

/** 错题本一行：该题**最近一次作答为错误**。 */
export interface PracticeWrongItem {
  question_id: string
  prompt: string
  /** 题型：`single` / `multiple` / `judge`（展开时只读回显）。 */
  kind: ExamKind
  /** 选项原文（只读回显，正确项按 `correct_answer` 高亮）。 */
  options: ExamOption[]
  /** 正确选项键：`["A"]` / `["A","C"]`；服务端可能给字符串（判断题旧数据）。 */
  correct_answer: string[] | string | null
  /** 逐题解析（题库保证非空 ≥10 字）。 */
  explanation: string
  language: QuestionLanguage
  direction: string
  difficulty: ExamDifficulty
  /** 最近一次答错时间（UTC ISO8601），展示时格式化为 `MM-dd HH:mm`。 */
  last_wrong_at: string
  wrong_count: number
}

export interface PracticeWrongBook {
  items: PracticeWrongItem[]
  total: number
}

// ===== r23 登录 / 多用户 / 用户自带 AI Key（与 backend/app/schemas.py 逐字段一致）=====

/** Key 来源：`own` = 用户自己在设置页填的（全能力）；`shared` = 管理员同意的内置 Key（仅轻量 + 每日配额）。 */
export type KeyMode = 'own' | 'shared'
/** 当前用户可用的 AI 档位：`full` 全能力 / `light` 仅轻量能力 / `none` 不可用。 */
export type AiCapability = 'full' | 'light' | 'none'
/** JSON 模式闭集（与后端同名字段一致）。 */
export type JsonMode = 'json_object' | 'none'

export interface Me {
  id: string
  email: string
  display_name: string
  role: string
  key_mode: KeyMode
  ai_capability: AiCapability
  ai_base_url: string
  ai_model: string
  ai_json_mode: JsonMode
  /** 只回显后 4 位；空串表示未配置。 */
  ai_masked_key: string
  ai_updated_at: string
  /** 内置 Key 今日已用 / 每日上限；非 `shared` 恒 0（上限 0 表示不限次数）。 */
  ai_quota_used: number
  ai_quota_limit: number
}

export interface LoginRequest {
  email: string
  password: string
}

export interface AiSettingsRequest {
  base_url: string
  model: string
  /** 空串 = 保留已存 Key（不改动）。 */
  api_key: string
  json_mode: JsonMode
}

export interface AiTestRequest {
  base_url: string
  model: string
  api_key: string
  json_mode: JsonMode
}

export interface AiTestResult {
  ok: boolean
  message: string
}

export interface PasswordChangeRequest {
  old_password: string
  new_password: string
}

/* ------------------------------------------------------------------ *
 * r65 AI 学习教练（检索增强 + 引用白名单，与 backend/app/schemas.py 逐字镜像）
 *
 * `CoachMaterial.href` 是双份契约：既是上传给模型的上下文，也是服务端校验引用
 * 的**允许集合**——模型给出的 href 只要不是材料里的原文就会被丢弃并计数。
 * ------------------------------------------------------------------ */

export interface CoachMaterial {
  title: string
  /** 站内路径（教程小节锚点 / 站内页面）；非 `/` 开头的会被服务端丢弃。 */
  href: string
  direction?: string
  sub_direction?: string
  level?: string
  /** 交给了模型的小节摘要（截断后的纯文本）。 */
  detail?: string
}

export interface CoachAdviceRequest {
  materials: CoachMaterial[]
  focus?: string
  goal?: string
}

export interface CoachAction {
  label: string
  href: string
  why: string
  minutes: number
}

export interface CoachBlock {
  title: string
  reason: string
  actions: CoachAction[]
}

export interface CoachAdvice {
  summary: string
  blocks: CoachBlock[]
  /** 真正交给模型的材料条数；0 表示没有调用模型。 */
  materials_used: number
  /** 因 href 不在白名单被丢弃的动作条数（幻觉引用计数器）。 */
  dropped_citations: number
  /** 空材料 / 引用全不可核对时的中文说明；正常出建议时为空串。 */
  notice: string
}

/* ------------------------------------------------------------------ *
 * r67 技术雷达（与 backend/app/schemas.py 逐字镜像）
 *
 * 技术清单 / 快照 / 评估是**全局知识**，只有生成任务 `radar_jobs` 按账号隔离。
 * `tech_slug` 形如 `github:owner/repo`，含 `/` 与 `:` → 生成入口走 body 传参。
 * ------------------------------------------------------------------ */

export interface RadarSourceStatus {
  source_key: string
  status: string
  items: number
  latency_ms: number
  message: string
}

export interface RadarRunRequest {
  /** 站内方向闭集（见 `lib/questionDirections.ts`）；空串 = 全方向。 */
  direction?: string
  /** GitHub 仓库链接或 `owner/repo`；填了只采这一个仓库。 */
  repo?: string
}

export interface RadarRunSummary {
  run_id: number
  trigger: string
  started_at: string
  finished_at: string
  degraded: boolean
  techs_seen: number
  sources: RadarSourceStatus[]
  notice: string
}

export interface RadarTechItem {
  tech_slug: string
  name: string
  direction: string
  sub_direction: string
  source_key: string
  url: string
  summary: string
  /** 中文摘要：采集时用 light 模型翻译并落库；空串表示还没翻（界面回退显示英文原文）。 */
  summary_zh: string
  verdict: string
  verdict_label: string
  relevance: number
  adoption: number
  maturity: number
  effort: number
  reasons: string[]
  evidence: string[]
  rule_based: boolean
  assessed_at: string
  stars: number
  star_delta_7d: number
  suspect: boolean
  job_id: string
}

export interface RadarTechList {
  items: RadarTechItem[]
  total: number
  notice: string
}

export interface RadarTranslateRequest {
  /** 本次最多翻几条（后端上限 50，缺省走后端配置）。 */
  limit?: number
}

export interface RadarTranslateResult {
  translated: number
  remaining: number
  notice: string
}

export interface RadarManualRequest {
  name: string
  url?: string
  summary?: string
  direction?: string
  sub_direction?: string
}

export interface RadarGenerateRequest {
  tech_slug: string
}

export interface RadarJobAccepted {
  job_id: string
  tech_slug: string
  status: string
  /** true = 命中在途任务，没有重复烧 token。 */
  reused: boolean
}

export interface RadarChapterSection {
  id: string
  title: string
  body: string
  bullets: string[]
}

export interface RadarChapterDraft {
  id: string
  title: string
  direction: string
  sub_direction: string
  level: string
  summary: string
  sections: RadarChapterSection[]
}

export interface RadarQuestionOption {
  key: string
  text: string
}

export interface RadarQuestionSample {
  id: string
  direction: string
  sub_direction: string
  kind: string
  difficulty: string
  essentiality: string
  prompt: string
  options: RadarQuestionOption[]
  answer: string[]
  language: string
  explanation: string
}

export interface RadarJobItem {
  job_id: string
  tech_slug: string
  tech_name: string
  /** `queued` / `running` / `succeeded` / `adopted` / `discarded` / `failed`。 */
  status: string
  stage: string
  progress: number
  chapter: RadarChapterDraft | null
  questions: RadarQuestionSample[]
  /** 自检丢弃的题数（答案键不在选项、选项数不合法等）。 */
  discarded_count: number
  /** 丢弃原因计数：`options` / `answer` / `prompt` / `explanation` / `duplicate`。 */
  discarded_reasons: Record<string, number>
  error_message: string
  trigger: string
  created_at: string
  updated_at: string
}

export interface RadarJobList {
  items: RadarJobItem[]
  total: number
}



/* ---------- r77 太傅对话（只读站内档案的问答） ---------- */

/** 一条可核对的站内出处：`href` 由服务端白名单校验过，必然是真实存在的页面。 */
export interface TaifuCitation {
  label: string
  href: string
}

/**
 * r82 页面带来的焦点：用户「点了哪一条」。服务端据此再取一条明细。
 *
 * 闭集三类，字段互斥：weakness 用 index（1 起）、attempt 用 question_id、resume 用逐字原句。
 * 服务端还会再校验「这一组 / 这题 / 这句」在库里存不存在，所以这里传的值可能被静默忽略——
 * 界面以响应里的 `detail` 为准，不能假设「传了就一定读到了」。
 */
export type TaifuFocus =
  | { kind: 'weakness'; index: number }
  | { kind: 'attempt'; question_id: string }
  | { kind: 'resume'; anchor: string }

/** 本轮真的读到了哪一条明细。`detail === null` 表示没读到（没传 / 越界 / 数据不存在）。 */
export interface TaifuDetailRef {
  kind: string
  label: string
  href: string
}

export interface TaifuMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  citations: TaifuCitation[]
  created_at: string
}

export interface TaifuThread {
  messages: TaifuMessage[]
}

export interface TaifuReply {
  reply: string
  citations: TaifuCitation[]
  /** 本次真正读到的档案段数；0 表示没有任何站内记录（未调用模型）。 */
  materials_used: number
  /** 模型给出但不在白名单、被服务端丢弃的引用条数。 */
  dropped_citations: number
  /** 本轮提示词是否带了线程摘要（r80）：可观测标记，界面不展示。 */
  summary_used: boolean
  /** 本轮提示词带了几条长期记忆（r81）。 */
  memories_used: number
  /** 本轮新记住几条（r81）：界面只据此提示，具体内容在记忆列表里看。 */
  memories_added: number
  /** r82：本轮读到的明细；`null` = 没传焦点 / 焦点越界 / 该条数据不存在。 */
  detail: TaifuDetailRef | null
  /** 空档案 / 空回答 / 空问句时的中文说明；正常回答为空串。 */
  notice: string
  created_at: string
}

/** 一条长期记忆：用户口头说过、档案里没有的稳定事实或偏好（跨对话有效，可单独忘掉）。 */
export interface TaifuMemoryItem {
  id: string
  content: string
  created_at: string
}

export interface TaifuMemories {
  items: TaifuMemoryItem[]
}

export interface TaifuMemoryResult {
  /** 0 表示 id 不存在或不属于本账号（幂等：重复删不报错）。 */
  deleted: number
}

export interface TaifuClearResult {
  deleted: number
}
