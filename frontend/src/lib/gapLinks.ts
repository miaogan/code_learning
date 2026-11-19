/**
 * r132 缺口 → 行动的深链层（纯函数）：把站内已有的「缺口证据」转成目标工具的预填链接。
 *
 * 口径：
 * 1. **只做深链，不重算缺口**——`first_fix` 顺序即后端口径（前端绝不重排，AC-20 继承），
 *    演武/学堂的方向筛选参数与题库 / 课程 direction 同一闭集（`questionDirections.DIRECTIONS`）；
 * 2. 召对预设解析器（`setupModel.presetFromParams`）天然支持 `?focus=`（≤3），与 JD 对位
 *    （`jdMatch.ts`）同一通道——缺口从 JD 或报告进来，召对侧零改动；
 * 3. 推不出链接时返回空串，调用方**不渲染入口**（宁可没有，不给死链）。
 */

import type { RoleFit } from '../api/types'
import { DIRECTIONS } from './questionDirections'
import { practiceHref } from './studyPlan'

const FOCUS_LIMIT = 3
const CHUNK = 40

/**
 * 报告 / 跃迁的 `role_fit` → 定向召对链接：
 * `first_fix`（≤3）作 focus 缺口，`target_role` 与 `model.direction` 一并预填。
 * 没有 `first_fix`（没有差距可补）时返回空串。
 */
export function roleFitInterviewHref(roleFit: RoleFit): string {
  const seen: string[] = []
  for (const raw of roleFit.first_fix) {
    const gap = raw.trim().slice(0, CHUNK)
    if (gap !== '' && !seen.includes(gap)) seen.push(gap)
    if (seen.length === FOCUS_LIMIT) break
  }
  if (seen.length === 0) return ''
  const params = new URLSearchParams()
  const role = (roleFit.target_role ?? '').trim()
  if (role !== '') params.set('target_role', role.slice(0, CHUNK))
  const direction = roleFit.model?.direction ?? ''
  if (DIRECTIONS.includes(direction)) params.set('direction', direction)
  seen.forEach((gap) => params.append('focus', gap))
  return `/interview?${params.toString()}`
}

/** 一道错题 → 演武定向重练链接（同方向 + 同难度聚焦）。 */
export function wrongItemPracticeHref(direction: string, difficulty: string | null): string {
  const dir = direction.trim()
  if (!DIRECTIONS.includes(dir)) return ''
  return practiceHref({ direction: dir, difficulty: difficulty ?? null })
}

/** 一道错题 → 学堂补课链接（目录页按方向预筛）。 */
export function wrongItemLearnHref(direction: string): string {
  const dir = direction.trim()
  if (!DIRECTIONS.includes(dir)) return ''
  const params = new URLSearchParams()
  params.set('direction', dir)
  return `/learn?${params.toString()}`
}

/** 当前错题列表涉及的去重方向（保持首次出现顺序）；推不出方向返回空数组。 */
export function wrongDirectionsOf(directions: readonly string[]): string[] {
  const seen: string[] = []
  for (const raw of directions) {
    const dir = raw.trim()
    if (dir !== '' && DIRECTIONS.includes(dir) && !seen.includes(dir)) seen.push(dir)
  }
  return seen
}
