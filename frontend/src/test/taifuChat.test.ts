import { describe, expect, it } from 'vitest'

import {
  TAIFU_QUESTION_MAX,
  canSend,
  clampQuestion,
  paragraphsOf,
  uniqueCitations,
} from '../lib/taifuChat'

describe('r77 太傅对话纯函数', () => {
  it('压平空白并去首尾空格', () => {
    expect(clampQuestion('  我  最近\n掉分  ')).toBe('我 最近 掉分')
  })

  it('超长问句截到上限并补省略号', () => {
    const clamped = clampQuestion('问'.repeat(TAIFU_QUESTION_MAX + 80))
    expect(clamped).toHaveLength(TAIFU_QUESTION_MAX + 1)
    expect(clamped.endsWith('…')).toBe(true)
  })

  it('空问句不能发送，在途时也不能重复发送', () => {
    expect(canSend('   ', false)).toBe(false)
    expect(canSend('我先补什么', true)).toBe(false)
    expect(canSend('我先补什么', false)).toBe(true)
  })

  it('段落切分丢弃空段并兼容 CRLF', () => {
    expect(paragraphsOf('')).toEqual([])
    expect(paragraphsOf('第一段\r\n\r\n\r\n第二段\n  \n第三段')).toEqual([
      '第一段',
      '第二段',
      '第三段',
    ])
  })

  it('引用按 href 去重且丢弃空链接', () => {
    expect(
      uniqueCitations([
        { label: '最近诊断', href: '/report' },
        { label: '重复', href: '/report' },
        { label: '空', href: '  ' },
        { label: '', href: '/practice' },
      ]),
    ).toEqual([
      { label: '最近诊断', href: '/report' },
      { label: '/practice', href: '/practice' },
    ])
  })
})
