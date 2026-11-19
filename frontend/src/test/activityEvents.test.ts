import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  ACTIVITY_CHANGED_EVENT,
  notifyActivityChanged,
  onActivityChanged,
} from '../lib/activityEvents'

const globals = globalThis as unknown as { window?: EventTarget }
const originalWindow = globals.window

afterEach(() => {
  if (originalWindow === undefined) delete globals.window
  else globals.window = originalWindow
})

describe('activityEvents', () => {
  it('写侧通知能触发徽章刷新，退订后不再触发', () => {
    globals.window = new EventTarget()
    const listener = vi.fn()
    const off = onActivityChanged(listener)

    notifyActivityChanged()
    expect(listener).toHaveBeenCalledTimes(1)

    off()
    notifyActivityChanged()
    expect(listener).toHaveBeenCalledTimes(1)
  })

  it('窗口重新聚焦也会触发刷新', () => {
    globals.window = new EventTarget()
    const listener = vi.fn()
    const off = onActivityChanged(listener)

    globals.window.dispatchEvent(new Event('focus'))
    expect(listener).toHaveBeenCalledTimes(1)
    off()
  })

  it('事件名稳定，便于跨模块对齐', () => {
    expect(ACTIVITY_CHANGED_EVENT).toBe('skillcoach:activity-changed')
  })
})
