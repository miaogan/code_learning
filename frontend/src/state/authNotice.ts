/** r75 非主动登出的会话过期提示：sessionStorage 只跨本次标签页，登录页读取一次即消费。 */
const KEY = 'sc.auth.notice'
const NOTICE_TTL_MS = 10 * 60 * 1000
let taken: string | null | undefined
let consumedNotice: string | null = null

export function markSessionExpired(nowMs: number = Date.now()): void {
  taken = undefined
  try {
    window.sessionStorage.setItem(KEY, JSON.stringify({ version: 1, at: new Date(nowMs).toISOString() }))
  } catch {
    /* 无法存储时只降级提示，不影响回登录页。 */
  }
}

export function takeAuthNotice(nowMs: number = Date.now()): string | null {
  if (taken !== undefined) return taken
  taken = null
  try {
    const raw = window.sessionStorage.getItem(KEY)
    // StrictMode 会在 effect 之间短暂切到 authed；只在真正卸载登录页时清一次性提示。
    window.setTimeout(() => {
      if (taken === consumedNotice) {
        try {
          window.sessionStorage.removeItem(KEY)
        } catch {
          /* 存储不可用时提示仍按本页生命周期消费。 */
        }
      }
    }, 0)
    if (raw === null) return null
    const value = JSON.parse(raw) as { version?: number; at?: string } | null
    if (
      value === null ||
      value.version !== 1 ||
      typeof value.at !== 'string' ||
      Number.isNaN(Date.parse(value.at)) ||
      nowMs - Date.parse(value.at) > NOTICE_TTL_MS ||
      nowMs - Date.parse(value.at) < 0
    ) {
      return null
    }
    taken = '登录已过期，请重新登录'
    consumedNotice = taken
  } catch {
    return null
  }
  return taken
}

/** 仅供测试清理本页面生命周期内的一次性缓存。 */
export function resetAuthNoticeForTest(): void {
  taken = undefined
}
