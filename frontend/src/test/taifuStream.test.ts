import { describe, expect, it } from 'vitest'

import {
  argsLine,
  cappedOf,
  doneOf,
  noticeOf,
  partsToView,
  rowKeysOf,
  textOf,
} from '../lib/taifuStream'

describe('partsToView', () => {
  it('把正文、工具卡、元信息按出现顺序摊平', () => {
    const view = partsToView([
      { type: 'data-meta', data: { materials: 8, memoriesUsed: 2 } },
      { type: 'tool-read_weakness_detail', state: 'input-available', input: { label: '薄弱明细', arguments: { point: '事件循环' } } },
      { type: 'tool-read_weakness_detail', state: 'output-available', input: { label: '薄弱明细' }, output: { ok: true, label: '薄弱明细 · 事件循环', summary: '错误率 75%' } },
      { type: 'text', text: '先补事件循环。' },
    ])

    expect(view.map((item) => item.kind)).toEqual(['meta', 'tool', 'tool', 'text'])
    expect(view[0]).toMatchObject({ materials: 8, memoriesUsed: 2 })
    expect(view[1]).toMatchObject({ state: 'running', args: { point: '事件循环' } })
    // 结果里的标签更具体，优先于入参里的通用名。
    expect(view[2]).toMatchObject({ state: 'done', ok: true, label: '薄弱明细 · 事件循环', summary: '错误率 75%' })
  })

  it('读不到的工具如实标成 done + 不 ok', () => {
    const [tool] = partsToView([
      { type: 'tool-read_question_detail', state: 'output-available', output: { ok: false, label: '错题明细', summary: '没有作答记录' } },
    ])

    expect(tool).toMatchObject({ kind: 'tool', state: 'done', ok: false, summary: '没有作答记录' })
  })

  it('未知工具退回英文名，不猜中文含义', () => {
    const [tool] = partsToView([{ type: 'tool-list_calendar', state: 'input-available' }])

    expect(tool).toMatchObject({ kind: 'tool', label: 'list_calendar' })
  })

  it('认识之外的 part 一律跳过（协议加字段不该让面板白屏）', () => {
    const view = partsToView([
      { type: 'reasoning', text: '不该显示' },
      { type: 'step-start' },
      { type: 'data-capped', data: { capped: true } },
      { type: 'source-url', url: '/x' },
      { type: 'text', text: '能显示' },
    ])

    expect(view).toEqual([{ kind: 'text', key: 'text-4', text: '能显示' }])
  })

  it('空 data-citations 不产生空的依据行', () => {
    expect(partsToView([{ type: 'data-citations', data: { items: [] } }])).toEqual([])
  })

  it('异常输入不抛错', () => {
    expect(partsToView([null, undefined, 42, {}, { type: 1 }])).toEqual([])
  })
})

describe('textOf / noticeOf / cappedOf', () => {
  it('textOf 拼接全部正文段，忽略工具与 data part', () => {
    const text = textOf([
      { type: 'text', text: '第一段' },
      { type: 'tool-read_weakness_detail', state: 'input-available' },
      { type: 'text', text: '第二段' },
    ])

    expect(text).toBe('第一段第二段')
  })

  it('noticeOf 取 done 里的提示，没有就空串', () => {
    expect(noticeOf([{ type: 'data-done', data: { notice: '站内记录还是空的' } }])).toBe('站内记录还是空的')
    expect(noticeOf([{ type: 'text', text: '正常回答' }])).toBe('')
  })

  it('cappedOf 只在真的撞到上限时为真', () => {
    expect(cappedOf([{ type: 'data-capped', data: { capped: true } }])).toBe(true)
    expect(cappedOf([{ type: 'text', text: '正常回答' }])).toBe(false)
  })
})

describe('argsLine', () => {
  it('按 key: value 拼接，只列有值的', () => {
    expect(argsLine({ point: '事件循环', question_id: 'q-1' })).toBe('point: 事件循环 · question_id: q-1')
    expect(argsLine({})).toBe('')
  })
})

describe('rowKeysOf', () => {
  it('id 唯一时原样用作 key', () => {
    expect(rowKeysOf([{ id: 'a' }, { id: 'b' }])).toEqual(['a', 'b'])
  })

  it('重复 id 追加序号，保证同一列里没有两个相同的 key', () => {
    // 服务端 id 撞车时（r83 交付初版每条回答都是 msg_taifu），React key 会重复、
    // 「已复制」会串台；追加序号让两条都还在，且各自独立。
    const keys = rowKeysOf([{ id: 'msg' }, { id: 'msg' }, { id: 'other' }, { id: 'msg' }])

    expect(keys).toEqual(['msg', 'msg#2', 'other', 'msg#3'])
    expect(new Set(keys).size).toBe(keys.length)
  })

  it('空列表给空数组（空态不渲染任何行）', () => {
    expect(rowKeysOf([])).toEqual([])
  })
})

describe('doneOf', () => {
  it('读出提示、机器可读原因与本轮记忆条数', () => {
    const done = doneOf([
      { type: 'data-done', data: { notice: '站内记录还是空的', reason: 'no_records', memoriesAdded: 1 } },
    ])

    expect(done).toEqual({ notice: '站内记录还是空的', reason: 'no_records', memoriesAdded: 1 })
  })

  it('缺字段一律按空值兜底（旧服务端没有 reason 时不能崩）', () => {
    expect(doneOf([{ type: 'data-done', data: {} }])).toEqual({
      notice: '',
      reason: '',
      memoriesAdded: 0,
    })
    expect(doneOf([{ type: 'text', text: '正常回答' }])).toBe(null)
    expect(doneOf([])).toBe(null)
  })

  it('noticeOf 与 done.notice 同源（空回答的提示只从 data-done 来）', () => {
    expect(noticeOf([{ type: 'data-done', data: { notice: '这次没生成出来' } }])).toBe(
      '这次没生成出来',
    )
    expect(noticeOf([{ type: 'text', text: '正常回答' }])).toBe('')
  })
})
