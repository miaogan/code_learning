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
  Profile,
  ProfilePatch,
  Report,
  ReportGenerateRequest,
  ResumeMeta,
  RunSummary,
  ScoreResult,
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

  generateProfile: (resumeId: string, signal?: AbortSignal): Promise<Profile> =>
    request<Profile>(`/api/resumes/${encodeURIComponent(resumeId)}/profile`, {
      method: 'POST',
      signal,
    }),

  latestProfile: (signal?: AbortSignal): Promise<Profile> =>
    request<Profile>('/api/profiles/latest', { signal }),

  patchProfile: (profileId: string, patch: ProfilePatch): Promise<Profile> =>
    request<Profile>(`/api/profiles/${encodeURIComponent(profileId)}`, jsonInit('PATCH', patch)),

  createInterview: (payload: InterviewCreateRequest): Promise<InterviewRun> =>
    request<InterviewRun>('/api/interviews', jsonInit('POST', payload)),

  scoreAnswer: (runId: string, payload: AnswerRequest): Promise<ScoreResult> =>
    request<ScoreResult>(
      `/api/interviews/${encodeURIComponent(runId)}/answers`,
      jsonInit('POST', payload),
    ),

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
