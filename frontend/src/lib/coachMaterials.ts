/**
 * r65 AI 学习教练的前端纯函数层：把「诊断报告 + 站内检索」组装成给模型的材料。
 *
 * 教程正文只在前端（`lib/tutorials.ts`），所以检索增强的上下文必须由这里组装后随请求上传。
 * 这一层同时决定了服务端的**引用白名单**：只有这里产出的 `href` 会被模型引用并通过校验。
 * 页面零计算，全部规则集中在此并配 vitest。
 */
import type { CoachMaterial, Report, WeaknessItem } from '../api/types'
import { ALL_TUTORIAL_CHAPTERS, chapterById } from './tutorials'
import { searchTutorials } from './tutorialSearch'

/** 最多覆盖 3 个最薄弱方向：再多材料对一次建议没有增量，只会稀释提示词。 */
export const COACH_DIRECTION_LIMIT = 3
/** 每个方向取 3 个小节（够形成「先读什么 → 再练什么」的梯度）。 */
export const COACH_PER_DIRECTION = 3
/** 材料总量上限，与后端 `policy.MATERIAL_LIMIT = 12` 留出余量。 */
export const COACH_MATERIAL_LIMIT = COACH_DIRECTION_LIMIT * COACH_PER_DIRECTION
export const COACH_DETAIL_MAX = 400
export const COACH_FOCUS_MAX = 40
export const COACH_GOAL_MAX = 160

/** 薄弱方向（已按错误率排序、按方向去重）：排序口径与报告页薄弱地图同源。 */
export function weakDirectionsOf(report: Report): WeaknessItem[] {
  const map = report.weakness_map
  if (!map || map.length === 0) return []
  const ranked = map
    .filter((item) => item.total > 0 && item.direction)
    .slice()
    .sort(
      (a, b) =>
        b.rate - a.rate ||
        b.wrong - a.wrong ||
        a.direction.localeCompare(b.direction)
    )
  const seen = new Set<string>()
  const picked: WeaknessItem[] = []
  for (const item of ranked) {
    if (seen.has(item.direction)) continue
    seen.add(item.direction)
    picked.push(item)
    if (picked.length >= COACH_DIRECTION_LIMIT) break
  }
  return picked
}

/** 压平空白并截断（材料摘要进提示词，换行只会增加 token 不增加信息）。 */
export function clampText(text: string, limit: number): string {
  const flat = String(text ?? '')
    .replace(/\s+/g, ' ')
    .trim()
  if (limit <= 0) return ''
  return flat.length <= limit ? flat : `${flat.slice(0, limit).trimEnd()}…`
}

/**
 * 组装材料：每个薄弱方向用它自己的「方向 + 二级方向」做一次教程检索。
 *
 * 二级方向检索不到时**静默回落到方向级**（与 r49/r50 的「聚焦优先、不足补位」同口径），
 * 绝不因为一个空子方向就把整个方向丢掉。
 */
export function buildCoachMaterials(report: Report): CoachMaterial[] {
  const materials: CoachMaterial[] = []
  const seen = new Set<string>()
  for (const weakness of weakDirectionsOf(report)) {
    const subDirection = weakness.sub_direction ?? ''
    const query = [weakness.direction, subDirection].filter(Boolean).join(' ')
    const search = (withSub: boolean) =>
      searchTutorials(
        query,
        withSub && subDirection
          ? { direction: weakness.direction, sub_direction: subDirection }
          : { direction: weakness.direction },
        ALL_TUTORIAL_CHAPTERS,
        COACH_PER_DIRECTION,
      )
    let citations = search(true)
    if (citations.length === 0 && subDirection) citations = search(false)

    for (const citation of citations) {
      if (seen.has(citation.href)) continue
      seen.add(citation.href)
      const chapter = chapterById(citation.chapter_id)
      materials.push({
        title: clampText(citation.title, 60),
        href: citation.href,
        direction: chapter?.direction ?? weakness.direction,
        sub_direction: chapter?.sub_direction ?? subDirection,
        level: chapter?.level ?? '',
        detail: clampText(citation.snippet, COACH_DETAIL_MAX),
      })
      if (materials.length >= COACH_MATERIAL_LIMIT) return materials
    }
  }
  return materials
}

/** 本次聚焦：优先用报告里的目标岗位（`role_fit` 已有来源优先级口径）。 */
export function coachFocusOf(report: Report): string {
  return clampText(report.role_fit?.target_role ?? '', COACH_FOCUS_MAX)
}

/** 本次目标：默认写成「优先补强最薄弱方向」，把报告的结论直接带进提示词。 */
export function coachGoalOf(report: Report): string {
  const top = weakDirectionsOf(report)[0]
  if (!top) return ''
  const where = top.sub_direction ? `${top.direction} · ${top.sub_direction}` : top.direction
  const rate = Math.round(top.rate * 100)
  return clampText(`优先补强 ${where}（该分组错误率 ${rate}%，共 ${top.total} 题）`, COACH_GOAL_MAX)
}
