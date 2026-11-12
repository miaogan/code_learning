import { describe, expect, it } from 'vitest'
import {
  NEWCOMER_GUIDE,
  STEP_HINTS,
  STEP_HREFS,
  firstOpenStepIndex,
} from '../lib/onboarding'

describe('r86 新用户指引：五步闭环的入口与术语对照', () => {
  it('五步各有站内入口，顺序与首页 pipeline 一一对应', () => {
    expect(STEP_HREFS).toEqual(['/', '/profile', '/interview', '/exam', '/report'])
    expect(STEP_HINTS).toHaveLength(5)
  })

  it('术语对照把侧栏叫法讲清楚：召对 = 面试、科考 = 笔试、医案 = 报告', () => {
    expect(STEP_HINTS[2]).toContain('召对')
    expect(STEP_HINTS[3]).toContain('科考')
    expect(STEP_HINTS[4]).toContain('医案')
  })

  it('新手上路说明给完整路径，并给免简历出口', () => {
    expect(NEWCOMER_GUIDE).toContain('01')
    expect(NEWCOMER_GUIDE).toContain('05')
    expect(NEWCOMER_GUIDE).toContain('演武')
    expect(NEWCOMER_GUIDE).toContain('学堂')
  })
})

describe('firstOpenStepIndex 当前步判定', () => {
  it('全新用户：第一步就是当前步', () => {
    expect(firstOpenStepIndex(['todo', 'todo', 'todo', 'todo', 'todo'])).toBe(0)
  })

  it('走到一半：第一个未完成步骤是当前步（now / todo 都算未完成）', () => {
    expect(firstOpenStepIndex(['done', 'done', 'todo', 'todo', 'todo'])).toBe(2)
    expect(firstOpenStepIndex(['done', 'now', 'todo', 'todo', 'todo'])).toBe(1)
  })

  it('全部完成：不再指路（-1）', () => {
    expect(firstOpenStepIndex(['done', 'done', 'done', 'done', 'done'])).toBe(-1)
  })

  it('空列表与未知状态按「未完成」处理，不抛错', () => {
    expect(firstOpenStepIndex([])).toBe(-1)
    expect(firstOpenStepIndex(['weird'])).toBe(0)
  })
})
