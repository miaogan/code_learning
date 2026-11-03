import { beforeEach, describe, expect, it, vi } from 'vitest'

/** r23：进度标记必须按账号隔离，否则同机多人会看到上一个人的对勾。 */
const store = new Map<string, string>()

function installWindow(): void {
  vi.stubGlobal('window', {
    localStorage: {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => {
        store.set(key, value)
      },
    },
  })
}

describe('flow 存储按账号分区', () => {
  beforeEach(() => {
    store.clear()
    vi.resetModules()
    vi.unstubAllGlobals()
    installWindow()
  })

  it('未登录写匿名键，绑定账号后读写各自独立', async () => {
    const flow = await import('../state/flow')

    flow.setFlow({ hasResume: true })
    expect(store.get('sc.flow')).toContain('"hasResume":true')

    flow.bindFlowToUser('user-a')
    expect(flow.getFlowState()).toEqual({
      hasResume: false,
      hasProfile: false,
      hasReport: false,
    })
    flow.setFlow({ hasProfile: true })
    expect(store.get('sc.flow.user-a')).toContain('"hasProfile":true')

    flow.bindFlowToUser('user-b')
    expect(flow.getFlowState().hasProfile).toBe(false)
    flow.setFlow({ hasReport: true })

    flow.bindFlowToUser('user-a')
    expect(flow.getFlowState().hasProfile).toBe(true)
    expect(flow.getFlowState().hasReport).toBe(false)

    flow.bindFlowToUser(null)
    expect(flow.getFlowState().hasResume).toBe(true)
    expect(flow.getFlowState().hasProfile).toBe(false)
  })

  it('损坏的存储值降级为空状态', async () => {
    store.set('sc.flow.user-a', '{oops')
    const flow = await import('../state/flow')
    flow.bindFlowToUser('user-a')
    expect(flow.getFlowState()).toEqual({
      hasResume: false,
      hasProfile: false,
      hasReport: false,
    })
  })
})
