/**
 * 面试会话本地锚点（断页恢复用）。
 *
 * 服务端 `runs` 才是真源，但恢复入口只有一个：URL 的 `?run_id=`。站内导航（顶栏 /
 * 报告页 / 画像页）都指向裸 `/interview`，一离开 query 就没了 —— 会话还在服务端跑着，
 * 页面上却只剩「本场尚未开始」。这里把最近一场未完成的 run_id 记在本机，进入面试页
 * 时若 URL 没带 run_id 就自动接上（与 r42 上传会话同一套「本地锚点」思路）。
 *
 * 存储按账号隔离（`sc.interview.<userId>`），24 小时后自动失效；正常结束 / 主动重开
 * 时由调用方清空 —— 已完成的历史场次不该在回访时被反复接回来。
 */

export interface InterviewSession {
  version: 1
  run_id: string
  saved_at: string
}

/** 本地锚点有效期：跨过「关掉页面第二天再来」，但不过度久远。 */
export const INTERVIEW_SESSION_TTL_MS = 24 * 60 * 60 * 1000

const KEY_PREFIX = 'sc.interview'

export function interviewSessionKey(userId: string | null): string {
  return `${KEY_PREFIX}.${userId ?? 'anon'}`
}

function safeGetItem(key: string): string | null {
  try {
    return window.localStorage.getItem(key)
  } catch {
    return null
  }
}

function safeSetItem(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value)
  } catch {
    /* 隐私模式 / 配额满：恢复尽力而为，不影响面试主流程 */
  }
}

function safeRemoveItem(key: string): void {
  try {
    window.localStorage.removeItem(key)
  } catch {
    /* 同上 */
  }
}

/** 读取本账号的未完成会话 run_id；过期 / 结构不合法一律返回 null（并顺手清掉脏数据）。 */
export function readInterviewSession(
  userId: string | null,
  nowMs: number = Date.now(),
): string | null {
  const key = interviewSessionKey(userId)
  const raw = safeGetItem(key)
  if (raw === null) return null
  let session: InterviewSession | null = null
  try {
    const parsed = JSON.parse(raw) as Partial<InterviewSession> | null
    if (parsed !== null && typeof parsed === 'object') {
      if (parsed.version === 1 && typeof parsed.run_id === 'string' && parsed.run_id !== '') {
        if (typeof parsed.saved_at === 'string' && !Number.isNaN(Date.parse(parsed.saved_at))) {
          session = parsed as InterviewSession
        }
      }
    }
  } catch {
    session = null
  }
  if (session === null) {
    safeRemoveItem(key)
    return null
  }
  if (nowMs - Date.parse(session.saved_at) > INTERVIEW_SESSION_TTL_MS) {
    safeRemoveItem(key)
    return null
  }
  return session.run_id
}

/**
 * 记下「这场还没答完」。`userId` 为空（登录态未就绪 / 已登出）时不写：否则会落到
 * `sc.interview.anon` 这个跨账号共享的键上，变成别人也能读到的脏数据。
 */
export function writeInterviewSession(userId: string | null, runId: string): void {
  if (userId === null || runId === '') return
  const next: InterviewSession = {
    version: 1,
    run_id: runId,
    saved_at: new Date().toISOString(),
  }
  safeSetItem(interviewSessionKey(userId), JSON.stringify(next))
}

export function clearInterviewSession(userId: string | null): void {
  safeRemoveItem(interviewSessionKey(userId))
}
