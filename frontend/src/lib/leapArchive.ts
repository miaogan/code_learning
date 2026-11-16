/**
 * r108 跃迁档案看板的纯函数层：页面零计算，所有展示口径在此单点。
 *
 * 三条口径（与后端 `services/leap.py`、r56 原则一致）：
 * 1. 三块数据由服务端一次聚合，前端**不重算**差距、不重排 `first_fix`、不二次统计分数；
 * 2. 项目只数服务端带回的真实证据条数，historical 项如实展示但不算当前能力；
 * 3. 面试表达的四要素自检是**关键词启发式，不是评分**——文案里必须让这一点可见，
 *    更不能把模拟面试或 dry-run 说成生产经验（不虚构跃迁）。
 */

import type {
  LeapArchive,
  LeapEngineeringItem,
  LeapExpressionItem,
  LeapExpressionStructure,
} from '../api/types'

/** 结构自检四要素的展示名，顺序固定（与后端 `_LABELS` 同源）。 */
export const STRUCTURE_PARTS = [
  { key: 'has_problem', label: '问题 / 背景' },
  { key: 'has_solution', label: '方案 / 做法' },
  { key: 'has_metric', label: '指标 / 数据' },
  { key: 'has_pitfall', label: '踩坑 / 反思' },
] as const satisfies ReadonlyArray<{ key: keyof LeapExpressionStructure; label: string }>

/** `data_scale` 的展示名（后端给的是真实行数，前端只改名不改数）。 */
const SCALE_LABELS: Record<string, string> = {
  questions: '题库',
  attempts: '作答记录',
  interview_runs: '面试场次',
  exam_runs: '笔试场次',
  documents: '简历文档',
  profiles: '画像版本',
  reports: '诊断报告',
  ai_calls: '模型调用',
}

export interface ScaleRow {
  key: string
  label: string
  count: number
}

/** 规模事实转成有序展示行：只列后端给了的 key，未出现的 key 不补 0。 */
export function scaleRows(dataScale: Record<string, number>): ScaleRow[] {
  return Object.entries(dataScale).map(([key, count]) => ({
    key,
    label: SCALE_LABELS[key] ?? key,
    count,
  }))
}

/** 当前可作为证据的项目：active 优先展示，historical 保留但标注（不丢弃、不冒充当前）。 */
export function orderedProjects(projects: LeapEngineeringItem[]): LeapEngineeringItem[] {
  return [...projects].sort((left, right) => {
    if (left.status !== right.status) return left.status === 'active' ? -1 : 1
    return right.evidence_count - left.evidence_count
  })
}

/** 结构自检的命中项 / 缺失项标签，供页面渲染 chip（不评分、不排序优先级）。 */
export function structureParts(structure: LeapExpressionStructure): {
  hits: string[]
  misses: string[]
} {
  const hits: string[] = []
  const misses: string[] = []
  for (const part of STRUCTURE_PARTS) {
    if (structure[part.key] === true) hits.push(part.label)
    else misses.push(part.label)
  }
  return { hits, misses }
}

/** 表达块的一句话摘要：统计也是「数服务端给的 items」，不做任何能力判断。 */
export function expressionSummary(items: LeapExpressionItem[]): string {
  if (items.length === 0) return '还没有已作答的面试发言'
  const scored = items.filter((item) => item.score !== null).length
  const full = items.filter((item) => item.structure.hit_count === STRUCTURE_PARTS.length).length
  return `已收录 ${items.length} 条作答（${scored} 条有评分），其中 ${full} 条四项措辞齐全；自检不是评分。`
}

/** 整份档案是否三块皆空：仅用于展示空态引导，不改变服务端数据。 */
export function isLeapEmpty(archive: LeapArchive): boolean {
  return (
    archive.role_gap.role_fit === null &&
    archive.engineering.projects.length === 0 &&
    archive.expression.items.length === 0
  )
}
