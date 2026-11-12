import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { TAIFU_ASK_EVENT, askTaifu, normalizeFocus, onTaifuAsk } from '../lib/taifuBridge'

/**
 * r82 唤起桥：jsdom 没开（vitest 环境是 node），用 `EventTarget` 顶替 `window`。
 * Node 22 自带 `CustomEvent`，所以桥里的实现可以原样跑。
 */
beforeEach(() => {
  vi.stubGlobal('window', new EventTarget())
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('r82 太傅唤起桥', () => {
  it('事件名固定', () => {
    expect(TAIFU_ASK_EVENT).toBe('sc:taifu-ask')
  })

  it('非法焦点不发事件：页面上点了没反应，好过让服务端静默忽略', () => {
    const handler = vi.fn()
    const stop = onTaifuAsk(handler)

    expect(
      askTaifu({ question: '这条怎么补', focus: { kind: 'weakness', index: 0 }, label: 'x' }),
    ).toBe(false)
    expect(
      askTaifu({ question: '这题为什么错', focus: { kind: 'attempt', question_id: '  ' }, label: 'x' }),
    ).toBe(false)
    expect(askTaifu({ question: '  ', focus: { kind: 'weakness', index: 1 }, label: 'x' })).toBe(
      false,
    )
    expect(handler).not.toHaveBeenCalled()
    stop()
  })

  it('合法焦点带上问题与标签送达', () => {
    const handler = vi.fn()
    const stop = onTaifuAsk(handler)

    const sent = askTaifu({
      question: ' 这题\n为什么错 ',
      focus: { kind: 'attempt', question_id: ' q-1 ' },
      label: ' 错题 ',
    })

    expect(sent).toBe(true)
    expect(handler).toHaveBeenCalledWith({
      question: '这题 为什么错',
      focus: { kind: 'attempt', question_id: 'q-1' },
      label: '错题',
    })
    stop()
  })

  it('取消订阅后不再收到事件', () => {
    const handler = vi.fn()
    const stop = onTaifuAsk(handler)
    stop()

    askTaifu({ question: '这条怎么补', focus: { kind: 'weakness', index: 2 }, label: '' })

    expect(handler).not.toHaveBeenCalled()
  })

  it('normalizeFocus 压平原句、拒绝空值与小数序号', () => {
    expect(normalizeFocus({ kind: 'resume', anchor: ' 负责\n接口开发 ' })).toEqual({
      kind: 'resume',
      anchor: '负责 接口开发',
    })
    expect(normalizeFocus({ kind: 'resume', anchor: '   ' })).toBeNull()
    expect(normalizeFocus({ kind: 'weakness', index: 1.5 })).toBeNull()
    expect(normalizeFocus({ kind: 'weakness', index: 3 })).toEqual({ kind: 'weakness', index: 3 })
  })
})
