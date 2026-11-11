import { beforeEach, describe, expect, it, vi } from 'vitest'
import { markSessionExpired, resetAuthNoticeForTest, takeAuthNotice } from '../state/authNotice'

const NOW = Date.parse('2026-11-11T10:00:00Z')
const store = new Map<string, string>()

beforeEach(() => {
  store.clear()
  resetAuthNoticeForTest()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  vi.spyOn(Date, 'now').mockReturnValue(NOW)
  vi.setSystemTime(new Date(NOW))
  vi.stubGlobal('window', {
    setTimeout: (callback: () => void, delay?: number) => globalThis.setTimeout(callback, delay),
    sessionStorage: {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => store.set(key, value),
      removeItem: (key: string) => store.delete(key),
    },
  })
})

describe('r75 登录过期一次性提示', () => {
  it('读取一次后消费，StrictMode 同页初始化仍取得相同结果', async () => {
    markSessionExpired(NOW)
    expect(takeAuthNotice(NOW)).toBe('登录已过期，请重新登录')
    expect(takeAuthNotice(NOW)).toBe('登录已过期，请重新登录')
    expect(store.has('sc.auth.notice')).toBe(true)
    await new Promise((resolve) => window.setTimeout(resolve, 0))
    expect(store.size).toBe(0)
    resetAuthNoticeForTest()
    expect(takeAuthNotice(NOW)).toBeNull()
  })

  it('没有标记时返回 null', () => {
    expect(takeAuthNotice(NOW)).toBeNull()
  })

  it('超过 10 分钟与未来时间戳均失效', () => {
    store.set('sc.auth.notice', JSON.stringify({ version: 1, at: new Date(NOW - 10 * 60_000 - 1).toISOString() }))
    expect(takeAuthNotice(NOW)).toBeNull()
    resetAuthNoticeForTest()
    store.set('sc.auth.notice', JSON.stringify({ version: 1, at: new Date(NOW + 1).toISOString() }))
    expect(takeAuthNotice(NOW)).toBeNull()
  })

  it('损坏 JSON 不抛出且不提示', () => {
    store.set('sc.auth.notice', '{bad')
    expect(takeAuthNotice(NOW)).toBeNull()
  })

  it('存储不可用不阻塞', () => {
    vi.stubGlobal('window', { sessionStorage: { setItem: () => { throw new Error('blocked') }, getItem: () => { throw new Error('blocked') }, removeItem: () => { throw new Error('blocked') } } })
    expect(() => markSessionExpired(NOW)).not.toThrow()
    expect(takeAuthNotice(NOW)).toBeNull()
  })
})
