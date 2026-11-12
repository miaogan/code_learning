import { describe, expect, it } from 'vitest'

import {
  CLEAR_LABELS,
  FORGET_LABELS,
  TAIFU_QUESTION_MAX,
  canSend,
  clampQuestion,
  paragraphsOf,
  parseReplyBlocks,
  splitBold,
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

describe('r82 回答渲染：列表与行内加粗', () => {
  it('连续无序项合并成一块', () => {
    expect(parseReplyBlocks('- 先补并发\n- 再补观测')).toEqual([
      { kind: 'list', ordered: false, items: ['先补并发', '再补观测'] },
    ])
  })

  it('有序与无序列表不混进同一块', () => {
    expect(parseReplyBlocks('1. 先补并发\n- 再补观测')).toEqual([
      { kind: 'list', ordered: true, items: ['先补并发'] },
      { kind: 'list', ordered: false, items: ['再补观测'] },
    ])
  })

  it('空行结束列表，前后段落仍是段落', () => {
    expect(parseReplyBlocks('结论：\n\n- a\n- b\n\n收尾')).toEqual([
      { kind: 'p', text: '结论：' },
      { kind: 'list', ordered: false, items: ['a', 'b'] },
      { kind: 'p', text: '收尾' },
    ])
  })

  it('不是列表的普通行原样成段（「1 小时」不是编号）', () => {
    expect(parseReplyBlocks('1 小时后再看')).toEqual([{ kind: 'p', text: '1 小时后再看' }])
    expect(parseReplyBlocks('  \n\n ')).toEqual([])
  })

  it('行内加粗：成对才生效，未闭合按普通文本', () => {
    expect(splitBold('先看 **并发** 再看观测')).toEqual([
      { text: '先看 ', bold: false },
      { text: '并发', bold: true },
      { text: ' 再看观测', bold: false },
    ])
    expect(splitBold('**没闭合')).toEqual([{ text: '**没闭合', bold: false }])
    expect(splitBold('')).toEqual([])
  })
})

describe('二次确认文案', () => {
  it('两态等长：页脚是行内按钮，字数一变就换行、面板上下跳（r83 实测位移 16px）', () => {
    expect(CLEAR_LABELS.idle).toHaveLength(CLEAR_LABELS.armed.length)
    expect(FORGET_LABELS.idle).toHaveLength(FORGET_LABELS.armed.length)
  })

  it('文案本身不含空白，不会把按钮顶成两行', () => {
    for (const label of [CLEAR_LABELS.idle, CLEAR_LABELS.armed, FORGET_LABELS.idle, FORGET_LABELS.armed]) {
      expect(label).not.toMatch(/\s/)
    }
  })
})
