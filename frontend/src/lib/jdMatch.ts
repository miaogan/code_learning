/**
 * r110 岗位对位的纯函数层：页面只分组与生成链接，不二次匹配、不算分。
 *
 * 服务端已经给出证据与缺口的唯一口径；这里只做展示分组与「一键带进召对」的链接拼装。
 * 方向 / 子方向按题库闭集收敛，非法值宁可不下发，避免面试页收到不认识的筛选项。
 */
import type {
  JdGapItem,
  JdInterviewPreset,
  JdKeywordItem,
  JdKeywordStatus,
  JdMatchResult,
} from '../api/types'
import { DIRECTIONS, subDirectionsOf } from './questionDirections'

export const KEYWORD_STATUS_LABEL: Record<JdKeywordStatus, string> = {
  evidence: '有证据',
  mentioned: '证据弱',
  missing: '未找到证据',
}

export const GAP_ORIGIN_LABEL: Record<JdGapItem['origin'], string> = {
  jd: 'JD 写到',
  role_model: '岗位模型要求',
}

export interface JdKeywordGroups {
  evidence: JdKeywordItem[]
  mentioned: JdKeywordItem[]
  missing: JdKeywordItem[]
}

export function keywordGroups(items: JdKeywordItem[]): JdKeywordGroups {
  return {
    evidence: items.filter((item) => item.status === 'evidence'),
    mentioned: items.filter((item) => item.status === 'mentioned'),
    missing: items.filter((item) => item.status === 'missing'),
  }
}

export function gapGroups(items: JdGapItem[]): { jd: JdGapItem[]; roleModel: JdGapItem[] } {
  return {
    jd: items.filter((item) => item.origin === 'jd'),
    roleModel: items.filter((item) => item.origin === 'role_model'),
  }
}

/** 一句话摘要：只报服务端给的数量，并明说不是能力评分。 */
export function jdSummary(result: JdMatchResult): string {
  if (result.keywords.length === 0) return '这段 JD 里没检出可对照的技术词；不是能力评分。'
  return (
    `检出 ${result.keywords.length} 个技术词：${result.matched_count} 个有画像证据，` +
    `${result.missing_count} 个未找到证据。字面对照不是能力评分。`
  )
}

/** 召对链接：只带岗位 / 方向 / 二级方向，其余四项配置仍在面试页由用户确认。 */
export function interviewHref(preset: JdInterviewPreset | null): string {
  if (preset === null) return '/interview'
  const role = preset.target_role.trim()
  if (role === '') return '/interview'
  const params = new URLSearchParams()
  params.set('target_role', role.slice(0, 40))
  const direction = DIRECTIONS.includes(preset.direction) ? preset.direction : ''
  if (direction !== '') {
    params.set('direction', direction)
    const sub = preset.sub_direction.trim()
    if (sub !== '' && subDirectionsOf(direction).includes(sub)) params.set('sub_direction', sub)
  }
  const seen: string[] = []
  for (const raw of preset.focus_gaps) {
    const gap = raw.trim().slice(0, 40)
    if (gap !== '' && !seen.includes(gap)) seen.push(gap)
    if (seen.length === 3) break
  }
  seen.forEach((gap) => params.append('focus', gap))
  return `/interview?${params.toString()}`
}

/** 是否有可展示内容：三者皆空才给空态，避免「只有预设没有关键词」时误判为空。 */
export function isJdEmpty(result: JdMatchResult | null): boolean {
  return (
    result === null ||
    (result.keywords.length === 0 && result.gaps.length === 0 && result.preset === null)
  )
}
