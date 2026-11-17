import { describe, expect, it } from 'vitest'
import type { JdKeywordItem, JdMatchResult } from '../api/types'
import {
  GAP_ORIGIN_LABEL,
  KEYWORD_STATUS_LABEL,
  gapGroups,
  interviewHref,
  isJdEmpty,
  jdSummary,
  keywordGroups,
} from '../lib/jdMatch'

function keyword(status: JdKeywordItem['status'], name = 'Python 后端服务'): JdKeywordItem {
  return {
    name,
    matched_alias: 'Python',
    source_quote: '设计 Python 后端服务',
    user_level: status === 'missing' ? 0 : 3,
    evidence_count: status === 'evidence' ? 2 : 0,
    evidence: status === 'evidence' ? ['负责 Python 服务'] : [],
    status,
    role_required: true,
  }
}

function result(patch: Partial<JdMatchResult> = {}): JdMatchResult {
  return {
    target_role: '后端工程师',
    role_fit: null,
    keywords: [],
    gaps: [],
    preset: null,
    notice: '字面对照不是能力评分。',
    source_chars: 24,
    matched_count: 0,
    missing_count: 0,
    generated_at: '2026-11-16T00:00:00+00:00',
    ...patch,
  }
}

describe('keywordGroups / gapGroups', () => {
  it('按服务端给的 status 与 source 分组，不改顺序', () => {
    const rows = [keyword('missing', 'Redis'), keyword('evidence'), keyword('mentioned', 'Docker')]
    const groups = keywordGroups(rows)
    expect(groups.evidence.map((row) => row.name)).toEqual(['Python 后端服务'])
    expect(groups.mentioned.map((row) => row.name)).toEqual(['Docker'])
    expect(groups.missing.map((row) => row.name)).toEqual(['Redis'])
    expect(KEYWORD_STATUS_LABEL.missing).toBe('未找到证据')

    const gaps = gapGroups([
      { name: 'Redis', origin: 'jd', reason: 'JD 写到', source_quote: 'Redis 缓存' },
      { name: 'Python', origin: 'role_model', reason: '模型要求', source_quote: '' },
    ])
    expect(gaps.jd).toHaveLength(1)
    expect(gaps.roleModel).toHaveLength(1)
    expect(GAP_ORIGIN_LABEL.role_model).toBe('岗位模型要求')
  })
})

describe('jdSummary', () => {
  it('只报服务端数量，且明说不是能力评分', () => {
    expect(jdSummary(result())).toContain('没检出')
    expect(
      jdSummary(result({ keywords: [keyword('evidence')], matched_count: 1 })),
    ).toContain('字面对照不是能力评分')
  })
})

describe('interviewHref', () => {
  it('只带三项预填，方向与子方向按闭集收敛', () => {
    const href = interviewHref({
      target_role: '后端工程师',
      direction: '后端',
      sub_direction: 'python',
      focus_gaps: ['Redis', 'RAG'],
      reason: '',
    })
    expect(href).toContain('target_role=')
    expect(href).toContain('direction=')
    expect(href).toContain('sub_direction=python')
    expect(href).toContain('focus=Redis')
    expect(href).toContain('focus=RAG')

    const dirty = interviewHref({
      target_role: '后端工程师',
      direction: '不存在',
      sub_direction: 'react',
      focus_gaps: [],
      reason: '',
    })
    expect(dirty).not.toContain('direction=')
    expect(dirty).not.toContain('sub_direction=')
    expect(interviewHref(null)).toBe('/interview')
  })
})

describe('isJdEmpty', () => {
  it('三者皆空才为空；只有预设也不是空态', () => {
    expect(isJdEmpty(null)).toBe(true)
    expect(isJdEmpty(result())).toBe(true)
    expect(
      isJdEmpty(
        result({
          preset: {
            target_role: '后端工程师',
            direction: '',
            sub_direction: '',
            focus_gaps: [],
            reason: '',
          },
        }),
      ),
    ).toBe(false)
  })
})
