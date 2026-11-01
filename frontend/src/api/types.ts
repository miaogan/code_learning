// 与 backend/app/schemas.py 同构的契约类型。字段名沿用 snake_case，避免两侧映射出错。

export type CourseLevel = '入门' | '进阶'
export type Severity = 'high' | 'medium' | 'low'
export type RunKind = 'interview' | 'exam'

export interface Health {
  status: string
  version: string
  ai_configured: boolean
  db: string
}

export interface ResumeMeta {
  resume_id: string
  file_name: string
  chars: number
  sections: number
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
  role: string
  period: string
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

export interface InterviewCreateRequest {
  profile_id: string
}

export interface InterviewQuestion {
  id: string
  kind: 'technical' | 'project' | 'challenge'
  prompt: string
  hint: string
}

export interface InterviewRun {
  run_id: string
  questions: InterviewQuestion[]
}

export interface AnswerRequest {
  question_id: string
  answer: string
}

export interface ScoreResult {
  score: number
  comment: string
}

export interface ExamOption {
  key: string
  text: string
}

export interface ExamCreateRequest {
  profile_id: string
}

export interface ExamQuestion {
  id: string
  kind: 'single' | 'multiple' | 'text'
  direction: string
  prompt: string
  options: ExamOption[]
}

export interface ExamRun {
  run_id: string
  questions: ExamQuestion[]
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

export interface Course {
  id: string
  title: string
  direction: string
  level: CourseLevel
  url: string | null
  why: string
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
}

export interface RunSummary {
  id: string
  kind: RunKind
  score: number | null
  shortfall_count: number | null
  created_at: string
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
