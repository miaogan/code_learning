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

export interface ProfileSkill {
  name: string
  source_quote: string
}

export interface ProfileProject {
  name: string
  role: string
  period: string
  bullets: string[]
  source_quote: string
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
