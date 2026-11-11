import type { ExamRun } from '../api/types'

/**
 * r75 未提交笔试草稿：保存本机卷面快照、已答内容和作答起点。
 * 服务端仍是判分真源；本地草稿只负责让刷新、站内离开和重新登录不再丢卷。
 */
export interface ExamDraft {
  version: 1
  run_id: string
  run: ExamRun
  answers: Record<string, string[] | string>
  started_at: string
  saved_at: string
}

export type ExamDraftRead =
  | { status: 'none' }
  | { status: 'ok'; draft: ExamDraft; elapsedS: number }
  | { status: 'expired' }
  | { status: 'invalid' }

export const EXAM_DRAFT_TTL_MS = 24 * 60 * 60 * 1000
const CLOCK_SKEW_TOLERANCE_MS = 5 * 60 * 1000

export function examDraftKey(userId: string | null): string {
  return `sc.exam.${userId ?? 'anon'}`
}

function validTime(value: unknown, nowMs: number): boolean {
  if (typeof value !== 'string' || Number.isNaN(Date.parse(value))) return false
  return Date.parse(value) <= nowMs + CLOCK_SKEW_TOLERANCE_MS
}

function parseDraft(raw: string, nowMs: number): ExamDraft | null {
  try {
    const value = JSON.parse(raw) as Partial<ExamDraft> | null
    if (value === null || typeof value !== 'object' || value.version !== 1) return null
    const run = value.run
    if (
      typeof value.run_id !== 'string' ||
      value.run_id === '' ||
      run === undefined ||
      run === null ||
      run.run_id !== value.run_id ||
      !Array.isArray(run.questions) ||
      run.questions.length === 0 ||
      run.questions.some((question) => typeof question.id !== 'string' || question.id === '')
    ) {
      return null
    }
    if (value.answers === null || typeof value.answers !== 'object' || Array.isArray(value.answers)) {
      return null
    }
    const questionIds = new Set(run.questions.map((question) => question.id))
    for (const [questionId, answer] of Object.entries(value.answers)) {
      if (!questionIds.has(questionId)) return null
      if (
        typeof answer !== 'string' &&
        (!Array.isArray(answer) || answer.some((item) => typeof item !== 'string'))
      ) {
        return null
      }
    }
    if (!validTime(value.started_at, nowMs) || !validTime(value.saved_at, nowMs)) return null
    return value as ExamDraft
  } catch {
    return null
  }
}

/** 纯读：不清键，保证 StrictMode 两次初始化读取到同一结果。 */
export function readExamDraft(
  userId: string | null,
  nowMs: number = Date.now(),
): ExamDraftRead {
  if (userId === null) return { status: 'none' }
  try {
    const raw = window.localStorage.getItem(examDraftKey(userId))
    if (raw === null) return { status: 'none' }
    const draft = parseDraft(raw, nowMs)
    if (draft === null) return { status: 'invalid' }
    if (nowMs - Date.parse(draft.saved_at) > EXAM_DRAFT_TTL_MS) return { status: 'expired' }
    const elapsedS = Math.max(0, Math.floor((nowMs - Date.parse(draft.started_at)) / 1000))
    return { status: 'ok', draft, elapsedS }
  } catch {
    return { status: 'none' }
  }
}

export function writeExamDraft(
  userId: string | null,
  input: { run: ExamRun; answers: Record<string, string[] | string>; startedAt: string },
): boolean {
  if (userId === null) return false
  const draft: ExamDraft = {
    version: 1,
    run_id: input.run.run_id,
    run: input.run,
    answers: input.answers,
    started_at: input.startedAt,
    saved_at: new Date().toISOString(),
  }
  try {
    window.localStorage.setItem(examDraftKey(userId), JSON.stringify(draft))
    return true
  } catch {
    return false
  }
}

export function clearExamDraft(userId: string | null): void {
  if (userId === null) return
  try {
    window.localStorage.removeItem(examDraftKey(userId))
  } catch {
    /* 清理失败不阻塞新卷或提交；旧草稿仍受 TTL 约束。 */
  }
}
