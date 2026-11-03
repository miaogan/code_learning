import { beforeEach, describe, expect, it, vi } from 'vitest'

/** r23 P2：`AI_KEY_REQUIRED` 全局提示由 client 上报、壳层横幅消费，状态机必须可预期。 */
describe('aiGate 全局提示状态', () => {
  beforeEach(() => {
    vi.resetModules()
  })

  it('上报后可见，重复上报同文案不重复通知，可消失', async () => {
    const gate = await import('../state/aiGate')
    const listener = vi.fn()
    const unsubscribe = gate.subscribeKeyRequired(listener)

    expect(gate.getKeyRequiredMessage()).toBeNull()
    gate.reportKeyRequired('未配置自己的 AI Key')
    expect(gate.getKeyRequiredMessage()).toBe('未配置自己的 AI Key')
    expect(listener).toHaveBeenCalledTimes(1)

    gate.reportKeyRequired('未配置自己的 AI Key')
    expect(listener).toHaveBeenCalledTimes(1)

    gate.dismissKeyRequired()
    expect(gate.getKeyRequiredMessage()).toBeNull()
    expect(listener).toHaveBeenCalledTimes(2)

    gate.dismissKeyRequired()
    expect(listener).toHaveBeenCalledTimes(2)

    unsubscribe()
    gate.reportKeyRequired('再次触发')
    expect(listener).toHaveBeenCalledTimes(2)
  })
})
