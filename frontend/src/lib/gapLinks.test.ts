import { describe, expect, it } from 'vitest'

import type { RoleFit } from '../api/types'
import {
  roleFitInterviewHref,
  wrongDirectionsOf,
  wrongItemLearnHref,
  wrongItemPracticeHref,
} from './gapLinks'

function roleFit(overrides: Partial<RoleFit> = {}): RoleFit {
  return {
    target_role: 'AI 应用工程师',
    role_source: 'profile',
    role_source_label: '简历画像',
    model: { level: '中级', label: 'AI 应用工程师 · 中级', direction: 'AI 工程' },
    items: [],
    missing_must: [],
    first_fix: ['RAG 检索链路', 'Agent 编排', 'Python 工程化'],
    conclusion: null,
    notice: null,
    ...overrides,
  }
}

describe('roleFitInterviewHref', () => {
  it('first_fix 前 3 个作 focus，岗位与方向一并预填', () => {
    const href = roleFitInterviewHref(roleFit())
    expect(href).toContain('/interview?')
    expect(href).toContain('target_role=AI+%E5%BA%94%E7%94%A8%E5%B7%A5%E7%A8%8B%E5%B8%88')
    expect(href).toContain('direction=AI+%E5%B7%A5%E7%A8%8B')
    expect(href.match(/focus=/g)).toHaveLength(3)
    expect(href).toContain('focus=RAG+%E6%A3%80%E7%B4%A2%E9%93%BE%E8%B7%AF')
  })

  it('first_fix 超 3 个只取前 3（顺序 = 后端口径，不重排）；重复与空白去重', () => {
    const href = roleFitInterviewHref(
      roleFit({ first_fix: [' RAG 检索链路 ', '', 'Agent 编排', 'RAG 检索链路', '第四个'] }),
    )
    // 「 RAG 检索链路 」与重复项合并成 1 条，因此「第四个」补位为第 3 个（上限内）。
    expect(href.match(/focus=/g)).toHaveLength(3)
  })

  it('first_fix 超过 3 个不重复项时截断到前 3', () => {
    const href = roleFitInterviewHref(
      roleFit({ first_fix: ['缺口甲', '缺口乙', '缺口丙', '缺口丁'] }),
    )
    expect(href.match(/focus=/g)).toHaveLength(3)
    expect(href).not.toContain(encodeURIComponent('缺口丁'))
  })

  it('方向不在闭集 / 缺失时不写 direction；没有 first_fix 返回空串（不渲染死链）', () => {
    const noDirection = roleFitInterviewHref(
      roleFit({ model: { level: '中级', label: 'x', direction: '非闭集方向' } }),
    )
    expect(noDirection).not.toContain('direction=')
    expect(roleFitInterviewHref(roleFit({ first_fix: [] }))).toBe('')
    expect(roleFitInterviewHref(roleFit({ first_fix: ['  '] }))).toBe('')
  })
})

describe('wrong item links', () => {
  it('错题 → 演武重练：同方向同难度；方向不在闭集返回空串', () => {
    const href = wrongItemPracticeHref('前端', 'advanced')
    expect(href).toContain('direction=%E5%89%8D%E7%AB%AF')
    expect(href).toContain('difficulty=advanced')
    expect(wrongItemPracticeHref('非闭集方向', 'advanced')).toBe('')
    expect(wrongItemPracticeHref('  ', null)).toBe('')
  })

  it('错题 → 学堂补课：目录页方向预筛', () => {
    expect(wrongItemLearnHref('后端')).toBe('/learn?direction=%E5%90%8E%E7%AB%AF')
    expect(wrongItemLearnHref('非闭集方向')).toBe('')
  })

  it('wrongDirectionsOf 去重并过滤闭集外方向，保持首次出现顺序', () => {
    expect(
      wrongDirectionsOf(['前端', '后端', '前端', '', '非闭集方向', '后端']),
    ).toEqual(['前端', '后端'])
  })
})
