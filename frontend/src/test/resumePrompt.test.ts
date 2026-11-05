import { beforeEach, describe, expect, it, vi } from 'vitest'

/** r27：会话标记落到 sessionStorage —— 刷新不复位，关标签页才清空。 */
const store = new Map<string, string>()

function installWindow(): void {
  vi.stubGlobal('window', {
    sessionStorage: {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => {
        store.set(key, value)
      },
      removeItem: (key: string) => {
        store.delete(key)
      },
    },
  })
}

describe('resumePrompt', () => {
  beforeEach(() => {
    store.clear()
    vi.resetModules()
    vi.unstubAllGlobals()
    installWindow()
  })

  it('同一会话只弹一次', async () => {
    const { consumeResumePrompt: consume } = await import('../lib/resumePrompt')
    expect(consume()).toBe(true)
    expect(consume()).toBe(false)
    expect(consume()).toBe(false)
  })

  it('刷新（模块重新加载）后不再重弹：标记在 sessionStorage 里存活', async () => {
    const first = await import('../lib/resumePrompt')
    expect(first.consumeResumePrompt()).toBe(true)

    // 模拟整页刷新：模块状态归零，sessionStorage 保留
    vi.resetModules()
    const second = await import('../lib/resumePrompt')
    expect(second.consumeResumePrompt()).toBe(false)
  })

  it('登出重置后下一位用户仍会看到一次引导', async () => {
    const { consumeResumePrompt: consume, resetResumePrompt: reset } = await import(
      '../lib/resumePrompt'
    )
    consume()
    reset()
    expect(consume()).toBe(true)
  })

  it('sessionStorage 不可用时静默放弃引导，不抛错', async () => {
    vi.unstubAllGlobals()
    vi.stubGlobal('window', {})
    const { consumeResumePrompt: consume } = await import('../lib/resumePrompt')
    expect(consume()).toBe(false)
  })
})
