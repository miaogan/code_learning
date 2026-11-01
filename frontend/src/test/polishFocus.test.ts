import { describe, expect, it } from 'vitest'
import type { PolishSection, PolishSuggestion } from '../api/types'
import {
  FOCUS_PENDING_NOTICE,
  SECTION_LABEL,
  findFocusedSuggestion,
  focusNotice,
  parseFocusParams,
} from '../lib/polishFocus'

/** 造一条建议：只有 `id` / `section` / `original_text` 参与定位，其余字段填最小合法值。 */
function makeSuggestion(id: string, section: PolishSection, originalText: string): PolishSuggestion {
  return {
    id,
    section,
    original_text: originalText,
    suggested_text: `${originalText}（改写）`,
    reason: '缺少数值结果',
    target_role: null,
    flags: [],
    start: 0,
    end: originalText.length,
  }
}

const SUGGESTIONS: PolishSuggestion[] = [
  makeSuggestion('s1', 'project', '主导了数据看板的重构'),
  makeSuggestion('s2', 'experience', '负责订单系统的日常维护'),
  makeSuggestion('s3', 'project', '带过三人小团队'),
]

describe('parseFocusParams', () => {
  it('没有 focus 参数时返回 null（页面行为完全不变）', () => {
    expect(parseFocusParams(new URLSearchParams(''))).toBeNull()
    expect(parseFocusParams(new URLSearchParams('section=project'))).toBeNull()
    expect(parseFocusParams(new URLSearchParams('focus=%20%20'))).toBeNull()
  })

  it('解析 focus / section / anchor', () => {
    const target = parseFocusParams(
      new URLSearchParams('focus=%E4%B8%BB%E5%AF%BC&section=project&anchor=%E4%B8%BB%E5%AF%BC'),
    )
    expect(target).toEqual({ focus: '主导', section: 'project', anchor: '主导' })
  })

  it('非法 section 退化为不预筛，但仍保留 focus', () => {
    const target = parseFocusParams(new URLSearchParams('focus=x&section=bogus'))
    expect(target?.section).toBeNull()
    expect(target?.focus).toBe('x')
    expect(target?.anchor).toBeNull()
  })
})

describe('findFocusedSuggestion', () => {
  it('按 anchor 与 original_text 逐字命中', () => {
    const target = parseFocusParams(new URLSearchParams('focus=any&anchor=带过三人小团队'))!
    expect(findFocusedSuggestion(SUGGESTIONS, target)?.id).toBe('s3')
  })

  it('只有 focus 时用 focus 与 original_text 全等比较', () => {
    const target = parseFocusParams(new URLSearchParams('focus=负责订单系统的日常维护'))!
    expect(findFocusedSuggestion(SUGGESTIONS, target)?.id).toBe('s2')
  })

  it('不做模糊匹配：漏字/多字都算未命中（反面目标 3）', () => {
    const partial = parseFocusParams(new URLSearchParams('focus=主导了数据看板'))!
    expect(findFocusedSuggestion(SUGGESTIONS, partial)).toBeNull()
    // anchor 落空但 focus 能命中时，仍然用 focus 兜回来
    const mixed = parseFocusParams(new URLSearchParams('focus=s1&anchor=主导了数据看板的重构'))!
    expect(findFocusedSuggestion(SUGGESTIONS, mixed)?.id).toBe('s1')
  })
})

describe('focusNotice', () => {
  it('带 section 时提示里含段落中文名', () => {
    expect(focusNotice('project')).toBe('未找到对应条目，已按「项目经历」筛选')
    expect(focusNotice('education')).toContain(SECTION_LABEL.education)
  })

  it('无 section 时退化为通用文案', () => {
    expect(focusNotice(null)).toBe('未找到对应条目，已显示全部建议')
  })
})

describe('SECTION_LABEL / 待定提示', () => {
  it('四档段落中文名齐全且与后端 coach_copy 逐字一致', () => {
    expect(SECTION_LABEL).toEqual({
      project: '项目经历',
      experience: '工作经历',
      education: '教育背景',
      summary: '个人简介',
    })
  })

  it('待定提示是中文且不含提示词痕迹', () => {
    expect(FOCUS_PENDING_NOTICE).toBe('分析完成后会自动定位到报告里指出的那一条')
    expect(FOCUS_PENDING_NOTICE).not.toMatch(/POLISH_SYSTEM|prompt/i)
  })
})
