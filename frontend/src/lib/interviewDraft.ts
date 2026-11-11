/** r75 面试当前题未提交草稿：每账号、每场一条，24 小时失效。 */
import { MAX_ANSWER_CHARS } from '../components/interview/Composer'

export interface InterviewDraft {
  version: 1
  run_id: string
  question_id: string
  text: string
  saved_at: string
}

export type InterviewDraftRead =
  | { status: 'none' | 'expired' | 'invalid' }
  | { status: 'ok'; text: string; savedAt: string }

export const INTERVIEW_DRAFT_TTL_MS = 24 * 60 * 60 * 1000

export function interviewDraftKey(userId: string | null, runId: string): string {
  return `sc.interview.draft.${userId ?? 'anon'}.${runId}`
}

export function readInterviewDraft(
  userId: string | null,
  runId: string,
  questionId: string,
  nowMs: number = Date.now(),
): InterviewDraftRead {
  if (userId === null) return { status: 'none' }
  try {
    const raw = window.localStorage.getItem(interviewDraftKey(userId, runId))
    if (raw === null) return { status: 'none' }
    const draft = JSON.parse(raw) as Partial<InterviewDraft> | null
    if (
      draft === null ||
      typeof draft !== 'object' ||
      draft.version !== 1 ||
      typeof draft.text !== 'string' ||
      typeof draft.saved_at !== 'string' ||
      Number.isNaN(Date.parse(draft.saved_at)) ||
      Date.parse(draft.saved_at) > nowMs + 5 * 60 * 1000
    ) {
      return { status: 'invalid' }
    }
    if (nowMs - Date.parse(draft.saved_at) > INTERVIEW_DRAFT_TTL_MS) return { status: 'expired' }
    if (draft.run_id !== runId || draft.question_id !== questionId) return { status: 'none' }
    return {
      status: 'ok',
      text: draft.text.slice(0, MAX_ANSWER_CHARS),
      savedAt: draft.saved_at,
    }
  } catch {
    return { status: 'invalid' }
  }
}

export function writeInterviewDraft(
  userId: string | null,
  input: { runId: string; questionId: string; text: string },
): boolean {
  if (userId === null) return false
  if (input.text === '') {
    clearInterviewDraft(userId, input.runId)
    return true
  }
  const draft: InterviewDraft = {
    version: 1,
    run_id: input.runId,
    question_id: input.questionId,
    text: input.text,
    saved_at: new Date().toISOString(),
  }
  try {
    window.localStorage.setItem(interviewDraftKey(userId, input.runId), JSON.stringify(draft))
    return true
  } catch {
    return false
  }
}

export function clearInterviewDraft(userId: string | null, runId: string): void {
  if (userId === null) return
  try {
    window.localStorage.removeItem(interviewDraftKey(userId, runId))
  } catch {
    /* 清理失败不影响已提交的服务端会话。 */
  }
}
