import type {
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
  Profile,
  ProfilePatch,
  ProfileWithMerge,
  PolishFullRequest,
  PolishFullResponse,
  PolishRequest,
  PolishResponse,
  Report,
  ReportGenerateRequest,
  ResumeMeta,
  RunSummary,
  TimelineEvent,
} from './types'

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
    if (isErrorBody(body)) {
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

export const api = {
  health: (): Promise<Health> => request<Health>('/health'),

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
}
