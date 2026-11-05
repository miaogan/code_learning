import type {
  AiSettingsRequest,
  AiTestRequest,
  AiTestResult,
  AnswerRequest,
  ApiErrorBody,
  Course,
  ExamAnswers,
  ExamCreateRequest,
  ExamResult,
  ExamRun,
  Health,
  InterviewCreateRequest,
  InterviewRun,
  InterviewSession,
  InterviewTurn,
  LoginRequest,
  Me,
  PasswordChangeRequest,
  Profile,
  ProfileJobStarted,
  ProfileJobStatus,
  ProfilePatch,
  ProfileWithMerge,
  PolishFullRequest,
  PolishFullResponse,
  PolishRequest,
  PolishResponse,
  PracticeAnswerRequest,
  PracticeAnswerResult,
  PracticeLanguageFilter,
  PracticePaper,
  PracticePaperRequest,
  PracticeStats,
  PracticeWrongBook,
  Report,
  ReportGenerateRequest,
  ResumeMeta,
  RunSummary,
  TimelineEvent,
} from './types'
import { reportKeyRequired } from '../state/aiGate'

/** 练习统计查询参数（r11）：与题单同口径，但**不带 limit**（命中数不受题量截断）。 */
export type PracticeStatsParams = Pick<
  PracticePaperRequest,
  'language' | 'direction' | 'difficulty' | 'essentiality' | 'scope'
>

/** 前端唯一 HTTP 出口：页面不得直接 fetch。 */
const BASE = (import.meta.env.VITE_API_BASE ?? '').replace(/\/$/, '')

export class ApiError extends Error {
  readonly code: string
  readonly status: number
  readonly retryable: boolean

  constructor(code: string, message: string, status: number, retryable: boolean) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.status = status
    this.retryable = retryable
  }
}

function isErrorBody(value: unknown): value is ApiErrorBody {
  if (typeof value !== 'object' || value === null) return false
  const body = (value as Record<string, unknown>).error
  return typeof body === 'object' && body !== null && typeof (body as Record<string, unknown>).code === 'string'
}

type UnauthorizedHandler = () => void

/** 登录态 store 注册的唯一钩子：任何请求拿到 401 即通知（会话过期/被停用后立刻回登录页）。 */
let unauthorizedHandler: UnauthorizedHandler | null = null

export function setUnauthorizedHandler(handler: UnauthorizedHandler | null): void {
  unauthorizedHandler = handler
}

async function rawRequest(path: string, init: RequestInit = {}): Promise<Response> {
  let response: Response
  try {
    response = await fetch(`${BASE}${path}`, init)
  } catch (error) {
    if ((error as { name?: string }).name === 'AbortError') {
      throw new ApiError('ABORTED', '已取消本次请求', 0, false)
    }
    throw new ApiError('NETWORK', '连接不到本地服务，请确认后端已在 8000 端口启动', 0, true)
  }

  if (!response.ok) {
    let body: unknown = null
    try {
      body = await response.json()
    } catch {
      body = null
    }
    // 401 先通知登录态再抛错：页面层不必各自判断「我是不是被踢下线了」。
    if (response.status === 401) unauthorizedHandler?.()
    if (isErrorBody(body)) {
      // AI 能力不足（403）由壳层统一给「去设置」入口，页面无需逐处实现。
      if (body.error.code === 'AI_KEY_REQUIRED') reportKeyRequired(body.error.message)
      throw new ApiError(body.error.code, body.error.message, response.status, body.error.retryable)
    }
    throw new ApiError('HTTP_ERROR', `服务返回异常（HTTP ${response.status}）`, response.status, true)
  }

  return response
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await rawRequest(path, init)
  return (await response.json()) as T
}

/** 204 无正文（登出 / 改密）：与 request 共用错误映射，成功时不解析 JSON。 */
async function requestEmpty(path: string, init: RequestInit = {}): Promise<void> {
  await rawRequest(path, init)
}

/** 非 JSON 响应（Markdown 导出）：与 request 共用错误映射，成功时返回原始文本。 */
async function requestText(path: string, init: RequestInit = {}): Promise<string> {
  const response = await rawRequest(path, init)
  return await response.text()
}

function jsonInit(method: string, body: unknown, signal?: AbortSignal): RequestInit {
  return {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  }
}

/** 查询串：只拼有值的键（中文筛选值如「后端」由 URLSearchParams 负责编码，页面不手拼）。 */
function queryString(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined) search.set(key, String(value))
  })
  return search.toString()
}

export const api = {
  health: (): Promise<Health> => request<Health>('/health'),

  /* ---------- r23 登录态与个人设置 ---------- */

  /** 当前用户：未登录时后端回 401（由 setUnauthorizedHandler 统一处理）。 */
  me: (signal?: AbortSignal): Promise<Me> => request<Me>('/api/me', { signal }),

  /** 登录：成功后服务端种 HttpOnly 会话 Cookie，前端拿不到 token（也不该拿）。 */
  login: (payload: LoginRequest): Promise<Me> =>
    request<Me>('/api/auth/login', jsonInit('POST', payload)),

  logout: (): Promise<void> => requestEmpty('/api/auth/logout', { method: 'POST' }),

  /** 保存自带 Key：`api_key` 为空表示沿用已存密文，响应只回 `****后4位`。 */
  saveAiSettings: (payload: AiSettingsRequest): Promise<Me> =>
    request<Me>('/api/me/ai', jsonInit('PUT', payload)),

  /** 清除已保存的 Key（保留 Base URL / 模型）：此后高消耗场景不可用。 */
  clearAiSettings: (): Promise<Me> =>
    request<Me>('/api/me/ai', { method: 'DELETE' }),

  /** 测试连接：优先用本表单填写的 Key，留空则回落到已存密文。 */
  testAiSettings: (payload: AiTestRequest): Promise<AiTestResult> =>
    request<AiTestResult>('/api/me/ai/test', jsonInit('POST', payload)),

  changePassword: (payload: PasswordChangeRequest): Promise<void> =>
    requestEmpty('/api/me/password', jsonInit('PATCH', payload)),

  uploadResume: async (file: File, signal?: AbortSignal): Promise<ResumeMeta> => {
    const form = new FormData()
    form.append('file', file)
    return request<ResumeMeta>('/api/resumes', { method: 'POST', body: form, signal })
  },

  /** 生成 / 增量合并画像（r3 行为变更：同一 profile_id 累积证据，返回带 `merge_summary`）。 */
  generateProfile: (resumeId: string, signal?: AbortSignal): Promise<ProfileWithMerge> =>
    request<ProfileWithMerge>(`/api/resumes/${encodeURIComponent(resumeId)}/profile`, {
      method: 'POST',
      signal,
    }),

  /** r30：同一条链路的异步版 —— 只受理，立即返回 `job_id`，真正的生成在服务端后台跑。 */
  generateProfileAsync: (resumeId: string): Promise<ProfileJobStarted> =>
    request<ProfileJobStarted>(`/api/resumes/${encodeURIComponent(resumeId)}/profile/async`, {
      method: 'POST',
    }),

  /** r30：轮询画像任务状态；`completed` 时 `result` 带一次性合并摘要。 */
  getProfileJob: (jobId: string, signal?: AbortSignal): Promise<ProfileJobStatus> =>
    request<ProfileJobStatus>(`/api/profile-jobs/${encodeURIComponent(jobId)}`, { signal }),

  /** r30：最近一次画像任务（回上传页自动接上进度）；没有任务时 404。 */
  latestProfileJob: (signal?: AbortSignal): Promise<ProfileJobStatus> =>
    request<ProfileJobStatus>('/api/profile-jobs/latest', { signal }),

  /** 成长时间线（r3）：服务端已按 `occurred_at` 倒序 + 已算好 `comparison`。 */
  timeline: (limit = 20, signal?: AbortSignal): Promise<TimelineEvent[]> =>
    request<TimelineEvent[]>(`/api/timeline?limit=${encodeURIComponent(String(limit))}`, { signal }),

  /** 简历逐条润色建议（r3）：单入口 service 产出，页面零提示词。 */
  polishSuggestions: (resumeId: string, payload: PolishRequest): Promise<PolishResponse> =>
    request<PolishResponse>(
      `/api/resumes/${encodeURIComponent(resumeId)}/polish`,
      jsonInit('POST', payload),
    ),

  /** 一键成稿（r3）：`markdown` 是唯一成稿真源（导出/复制只取它）。 */
  polishFull: (resumeId: string, payload: PolishFullRequest): Promise<PolishFullResponse> =>
    request<PolishFullResponse>(
      `/api/resumes/${encodeURIComponent(resumeId)}/polish/full`,
      jsonInit('POST', payload),
    ),

  latestProfile: (signal?: AbortSignal): Promise<Profile> =>
    request<Profile>('/api/profiles/latest', { signal }),

  patchProfile: (profileId: string, patch: ProfilePatch): Promise<Profile> =>
    request<Profile>(`/api/profiles/${encodeURIComponent(profileId)}`, jsonInit('PATCH', patch)),

  createInterview: (payload: InterviewCreateRequest): Promise<InterviewRun> =>
    request<InterviewRun>('/api/interviews', jsonInit('POST', payload)),

  scoreAnswer: (runId: string, payload: AnswerRequest): Promise<InterviewTurn> =>
    request<InterviewTurn>(
      `/api/interviews/${encodeURIComponent(runId)}/answers`,
      jsonInit('POST', payload),
    ),

  /** 会话回溯（r5）：刷新 / 重进 ?run_id= 时恢复整场对话与设定。 */
  getInterview: (runId: string, signal?: AbortSignal): Promise<InterviewSession> =>
    request<InterviewSession>(`/api/interviews/${encodeURIComponent(runId)}`, { signal }),

  createExam: (payload: ExamCreateRequest): Promise<ExamRun> =>
    request<ExamRun>('/api/exams', jsonInit('POST', payload)),

  submitExam: (runId: string, answers: ExamAnswers): Promise<ExamResult> =>
    request<ExamResult>(`/api/exams/${encodeURIComponent(runId)}/submit`, jsonInit('POST', answers)),

  generateReport: (payload: ReportGenerateRequest): Promise<Report> =>
    request<Report>('/api/reports/generate', jsonInit('POST', payload)),

  latestReport: (signal?: AbortSignal): Promise<Report> =>
    request<Report>('/api/reports/latest', { signal }),

  reportMarkdown: (reportId: string): Promise<string> =>
    requestText(`/api/reports/${encodeURIComponent(reportId)}/markdown`),

  history: (limit = 10): Promise<RunSummary[]> =>
    request<RunSummary[]>(`/api/history?limit=${encodeURIComponent(String(limit))}`),

  listCourses: (): Promise<Course[]> => request<Course[]>('/api/courses'),

  /* ---------- r11 练习四端点（纯本地、零 AI；空结果是 200 + 空列表，不是错误） ---------- */

  /** 题单：`hit_count` 是全部筛选后的命中总数（不受 `limit` 截断），题单内**不含** answer。 */
  practicePaper: (body: PracticePaperRequest): Promise<PracticePaper> =>
    request<PracticePaper>('/api/practice/paper', jsonInit('POST', body)),

  /** 单题判分：服务端复用 `exam.grade_objective` 并写 `question_attempts`，前端不做任何判分。 */
  practiceAnswer: (body: PracticeAnswerRequest): Promise<PracticeAnswerResult> =>
    request<PracticeAnswerResult>('/api/practice/answer', jsonInit('POST', body)),

  /** 统计：`hit` 与题单 `hit_count` 同源同值。 */
  practiceStats: (params: PracticeStatsParams, signal?: AbortSignal): Promise<PracticeStats> =>
    request<PracticeStats>(`/api/practice/stats?${queryString(params)}`, { signal }),

  /** 错题本：服务端已按最近答错时间倒序，前端不二次排序。 */
  practiceWrongBook: (
    language: PracticeLanguageFilter,
    signal?: AbortSignal,
  ): Promise<PracticeWrongBook> =>
    request<PracticeWrongBook>(`/api/practice/wrong-book?${queryString({ language })}`, { signal }),
}
