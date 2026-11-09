/**
 * 报告页「推荐学习方向」的纯逻辑（无 DOM / 无请求，vitest 直接断言）。
 *
 * 方向只来自报告里的真实字段：`role_fit.model.direction`（后端内置岗位模型透出的方向）
 * 与 `shortfalls[].courses[].direction`（课程自身的方向）。不发明「某方向很热门」这类数据，
 * 也不把技能名猜成方向 —— 没有依据时就只给文案，不硬凑卡片。
 */
import type { Course, Report, RoleFitItem } from '../api/types'
import { practiceHref } from './studyPlan'

/** 主攻方向之外的延伸方向上限（再多会淹没主攻方向）。 */
const EXTRA_DIRECTION_LIMIT = 2
/** 每个方向最多列的课程数（与短板卡一样只给最相关的几门）。 */
const DIRECTION_COURSE_LIMIT = 3
/** 「先补什么」上限：与后端 `FIRST_FIX_LIMIT` 同口径。 */
const SKILL_LIMIT = 3

/** 旧报告（`role_fit === null`）没有目标岗位能力模型，推不出主攻方向。 */
export const GUIDANCE_LEGACY_NOTICE = '旧报告不含目标岗位能力模型，重新生成后可推荐学习方向'
/** 新报告但既没有方向模型、也没有带方向的课程。 */
export const GUIDANCE_EMPTY_NOTICE = '本次报告没有可推荐的学习方向，先完成一轮有课程推荐的测评'
/** 主攻方向能力已基本达标时的提示（不再列「先补什么」）。 */
export const GUIDANCE_MET_NOTICE = '该方向的能力已基本达标，可以把精力放到更复杂的项目或更高一级的岗位'

export type GuidanceKind = 'primary' | 'extra'

export interface GuidanceSkill {
  name: string
  gap: number
  required: number
  user_level: number
  must: boolean
}

export interface GuidanceDirection {
  /** 方向名（与题库 / 课程的 `direction` 同一闭集）。 */
  direction: string
  /** `primary` = 目标岗位方向；`extra` = 报告里其他带课程的短板方向。 */
  kind: GuidanceKind
  /** 为什么推荐这个方向（全部取自 `role_fit` / `shortfalls` 的真实文案字段）。 */
  summary: string
  /** 先补的技能，顺序 = `role_fit.first_fix` 顺序（前端不重排）。 */
  skills: GuidanceSkill[]
  courses: Course[]
  /** 该方向的专项练习入口（r50 起可带短板二级方向聚焦）。 */
  practiceLink: string
  /** r50：取自 `weakness_map` 的组内众数二级方向；空串 = 旧报告 / 无标签，按方向级回落。 */
  sub_direction: string
  /** 主攻方向已达标等补充说明；没有则为 `null`。 */
  notice: string | null
}

/** 课程按方向分组（同一门课可能挂在多条短板上，先按 `course.id` 去重）。 */
function coursesOf(report: Report): Map<string, Course[]> {
  const grouped = new Map<string, Course[]>()
  const seen = new Set<string>()
  report.shortfalls.forEach((shortfall) => {
    shortfall.courses.forEach((course) => {
      if (seen.has(course.id)) return
      seen.add(course.id)
      const list = grouped.get(course.direction) ?? []
      list.push(course)
      grouped.set(course.direction, list)
    })
  })
  return grouped
}

/** 哪些短板的推荐课程落在这个方向（用于说明推荐理由，不猜语义）。 */
function shortfallNamesOf(report: Report, direction: string): string[] {
  return report.shortfalls
    .filter((shortfall) => shortfall.courses.some((course) => course.direction === direction))
    .map((shortfall) => shortfall.name)
}

/**
 * r50：该方向的二级方向只取自报告 `weakness_map` 的组内众数（后端 r49 已算好）。
 * 按报告原始顺序取第一条非空项 —— 不重排、不发明标签；旧报告缺字段时返回空串。
 */
function subDirectionOf(report: Report, direction: string): string {
  const hit = (report.weakness_map ?? []).find(
    (item) => item.direction === direction && (item.sub_direction ?? '').trim() !== '',
  )
  return (hit?.sub_direction ?? '').trim()
}

function skillOf(item: RoleFitItem): GuidanceSkill {
  return {
    name: item.name,
    gap: item.gap,
    required: item.required,
    user_level: item.user_level,
    must: item.must,
  }
}

/** 主攻方向：只在目标岗位命中内置模型且模型带方向时给出。 */
function primaryOf(
  report: Report,
  grouped: Map<string, Course[]>,
): GuidanceDirection | null {
  const roleFit = report.role_fit
  if (roleFit === null || roleFit.model === null) return null
  const direction = roleFit.model.direction
  if (direction === null || direction.trim() === '') return null

  const skills = roleFit.first_fix
    .map((name) => roleFit.items.find((item) => item.name === name))
    .filter((item): item is RoleFitItem => item !== undefined)
    .slice(0, SKILL_LIMIT)
    .map(skillOf)

  const names = shortfallNamesOf(report, direction)
  const summary =
    names.length > 0
      ? `目标岗位「${roleFit.model.label}」属于${direction}方向；本次报告有 ${names.length} 条短板的推荐课程落在这个方向`
      : `目标岗位「${roleFit.model.label}」属于${direction}方向，先把该方向的基础补扎实`

  const sub_direction = subDirectionOf(report, direction)
  return {
    direction,
    kind: 'primary',
    summary,
    skills,
    courses: (grouped.get(direction) ?? []).slice(0, DIRECTION_COURSE_LIMIT),
    practiceLink: practiceHref({ direction, sub_direction }),
    sub_direction,
    notice: skills.length === 0 ? GUIDANCE_MET_NOTICE : null,
  }
}

/** 延伸方向：报告里其他带推荐课程的短板方向，按课程数降序、同数保持原始出现顺序。 */
function extrasOf(
  report: Report,
  grouped: Map<string, Course[]>,
  primaryDirection: string | null,
): GuidanceDirection[] {
  const entries = Array.from(grouped.entries())
    .filter(([direction]) => direction.trim() !== '' && direction !== primaryDirection)
    .map(([direction, courses], index) => ({ direction, courses, index }))
    .sort((left, right) => right.courses.length - left.courses.length || left.index - right.index)

  return entries.slice(0, EXTRA_DIRECTION_LIMIT).map(({ direction, courses }) => {
    const names = shortfallNamesOf(report, direction)
    const shown =
      names.length > 2 ? `${names.slice(0, 2).join('、')} 等` : names.join('、')
    const sub_direction = subDirectionOf(report, direction)
    return {
      direction,
      kind: 'extra',
      summary: `短板「${shown}」的推荐课程落在${direction}方向，可以作为主攻方向之外的补充`,
      skills: [],
      courses: courses.slice(0, DIRECTION_COURSE_LIMIT),
      practiceLink: practiceHref({ direction, sub_direction }),
      sub_direction,
      notice: null,
    }
  })
}

/**
 * 生成学习方向列表：主攻方向（有目标岗位模型时）排在第一位，最多再跟 2 个延伸方向。
 *
 * - `role_fit === null`（旧报告）→ `[]`，由调用方渲染 `GUIDANCE_LEGACY_NOTICE`；
 * - 有 `role_fit` 但没有方向模型、也没有带方向的课程 → `[]`，渲染 `GUIDANCE_EMPTY_NOTICE`；
 * - 有课程但没有方向模型 → 只给延伸方向（不假造主攻方向）。
 */
export function buildGuidance(report: Report): GuidanceDirection[] {
  if (report.role_fit === null) return []
  const grouped = coursesOf(report)
  const primary = primaryOf(report, grouped)
  const extras = extrasOf(report, grouped, primary?.direction ?? null)
  return primary === null ? extras : [primary, ...extras]
}
