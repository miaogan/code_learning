import type { Profile } from '../api/types'
import type { ProfileDimensionKey } from '../components/profile/ProfileDimension'
import { DIMENSIONS, dimensionEntries } from './profileEdit'

/**
 * 画像雷达图的**纯函数层**（五维填充度 + 坐标投影），无 DOM、无请求，vitest 可直接测。
 *
 * 口径（必须与页面文案一致）：雷达图画的是**简历信息填充度 / 证据覆盖**，
 * 不是能力评分、不是熟练度。产品明确不承诺能力评级，参考上限只是「画图归一化用的分母」，
 * 不能反过来读成「达到 x 就算合格」。
 */
export const RADAR_REFERENCE: Record<ProfileDimensionKey, number> = {
  skills: 8,
  tech_stack: 8,
  years_experience: 5,
  projects: 3,
  target_role: 1,
}

/** 雷达图轴标签只放序号，避免长中文文字在 SVG 边缘被裁（标题与读数在右侧图例里给全）。 */
export const RADAR_SHORT_TITLE: Record<ProfileDimensionKey, string> = {
  skills: '技能',
  tech_stack: '技术栈',
  years_experience: '年限',
  projects: '项目',
  target_role: '岗位',
}

export interface RadarAxis {
  key: ProfileDimensionKey
  /** 与 `DIMENSIONS` 同一份标题，不另写一套文案。 */
  title: string
  /** 归一化填充度 0–1（只用于画图，不参与任何评分）。 */
  ratio: number
  /** 图例读数（真实计数，可人工核对；这才是「事实」，ratio 只是它的投影）。 */
  reading: string
  /** 该维度是否已有内容：历史条目不算（与主卡片、`confirmedDimensions` 同一口径）。 */
  filled: boolean
}

function ratioOf(count: number, reference: number): number {
  if (!Number.isFinite(count) || count <= 0 || reference <= 0) return 0
  return Math.min(1, count / reference)
}

/** 画像 → 5 条轴（顺序即 `DIMENSIONS` 顺序：技能 → 技术栈 → 年限 → 项目 → 目标岗位）。 */
export function radarAxes(profile: Profile): RadarAxis[] {
  const entries = dimensionEntries(profile)
  const years = profile.years_experience
  const role = typeof profile.target_role === 'string' ? profile.target_role.trim() : ''
  const skillCount = entries.skills.length
  const techCount = entries.tech_stack.length
  const projectCount = entries.projects.length
  const yearsValue = years === null || years === undefined || !Number.isFinite(years) ? null : Math.max(0, years)

  return DIMENSIONS.map(({ key, title }) => {
    if (key === 'skills') {
      return {
        key,
        title,
        ratio: ratioOf(skillCount, RADAR_REFERENCE.skills),
        reading: `${skillCount} 个技能`,
        filled: skillCount > 0,
      }
    }
    if (key === 'tech_stack') {
      return {
        key,
        title,
        ratio: ratioOf(techCount, RADAR_REFERENCE.tech_stack),
        reading: `${techCount} 项技术栈`,
        filled: techCount > 0,
      }
    }
    if (key === 'years_experience') {
      return {
        key,
        title,
        ratio: yearsValue === null ? 0 : ratioOf(yearsValue, RADAR_REFERENCE.years_experience),
        reading: yearsValue === null ? '未填写' : `${yearsValue} 年`,
        filled: yearsValue !== null,
      }
    }
    if (key === 'projects') {
      return {
        key,
        title,
        ratio: ratioOf(projectCount, RADAR_REFERENCE.projects),
        reading: `${projectCount} 段项目`,
        filled: projectCount > 0,
      }
    }
    return {
      key,
      title,
      ratio: role === '' ? 0 : 1,
      reading: role === '' ? '未填写' : role,
      filled: role !== '',
    }
  })
}

/** 已填写维度数（与侧栏「N/5 维度已确认」同口径，但这里只用于雷达图副标题）。 */
export function radarCoverage(axes: RadarAxis[]): number {
  return axes.filter((axis) => axis.filled).length
}

export interface RadarPoint {
  x: number
  y: number
}

/**
 * 把 0–1 的填充度投影成多边形顶点：第一条轴在正上方（−90°），顺时针均分 360°。
 * `ratio` 越界按 0/1 夹取（防御脏数据，不抛错）。
 */
export function radarPoints(ratios: number[], cx: number, cy: number, radius: number): RadarPoint[] {
  const count = ratios.length
  if (count === 0 || radius <= 0) return []
  return ratios.map((ratio, index) => {
    const value = Number.isFinite(ratio) ? Math.min(1, Math.max(0, ratio)) : 0
    const angle = -Math.PI / 2 + (index * 2 * Math.PI) / count
    return {
      x: cx + Math.cos(angle) * radius * value,
      y: cy + Math.sin(angle) * radius * value,
    }
  })
}

/** 顶点 → 闭合多边形路径；不足 3 个点返回空串（组件据此不画填充区）。 */
export function radarPath(points: RadarPoint[]): string {
  if (points.length < 3) return ''
  const body = points.map((point) => `${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(' ')
  return `M ${body} Z`
}
