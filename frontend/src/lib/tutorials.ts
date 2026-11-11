/**
 * 站内教程的纯逻辑（无 DOM），目录页 / 文章页 / 报告页入口共用。
 *
 * 内容在 `content/tutorials/`，本文件只做索引、两级筛选与链接拼接；
 * 章节 ID 是全局唯一 ASCII slug（URL 直接用），方向与难度只进查询参数。
 */
import { TUTORIAL_CHAPTERS } from '../content/tutorials'
import { subDirectionsOf } from './questionDirections'
import type { TutorialChapter, TutorialDirection, TutorialLevel } from './tutorialTypes'

/** 目录页方向筛选的展示顺序：与内容聚合顺序一致，读起来是一条线。 */
export const TUTORIAL_DIRECTIONS: TutorialDirection[] = [
  '前端',
  '后端',
  'SQL 与数据库',
  '中间件与运维',
  '算法与数据结构',
  '计算机基础',
  'AI 工程',
  '研发工程实践',
]

/** 难度档位由易到难：二级筛选的按钮顺序与「只列真实存在的档位」都依赖这个顺序。 */
export const TUTORIAL_LEVELS: TutorialLevel[] = ['基础', '进阶', '高级']

/** 方向筛选取值：`all` 表示不过滤。 */
export type TutorialDirectionFilter = TutorialDirection | 'all'
/** 难度筛选取值：`all` 表示不过滤。 */
export type TutorialLevelFilter = TutorialLevel | 'all'
/** 子方向筛选取值：`all` 表示不过滤（子方向是自由字符串，闭集由 `questionDirections` 提供）。 */
export type TutorialSubDirectionFilter = string | 'all'

/** 难度由易到难的比较序号：目录排序与「三档齐全」的判定都用它。 */
const LEVEL_ORDER: Record<TutorialLevel, number> = { 基础: 0, 进阶: 1, 高级: 2 }

/**
 * 全量章节，按「方向顺序 × 难度档位」排好序后再对外暴露。
 *
 * 内容文件追加章节时只需写对 `direction` 与 `level`，不必关心自己插在数组哪个位置：
 * 目录页、上一章/下一章、报告页入口都只认这一份顺序。
 */
export const ALL_TUTORIAL_CHAPTERS: TutorialChapter[] = [...TUTORIAL_CHAPTERS].sort(
  (a, b) =>
    TUTORIAL_DIRECTIONS.indexOf(a.direction) - TUTORIAL_DIRECTIONS.indexOf(b.direction) ||
    LEVEL_ORDER[a.level] - LEVEL_ORDER[b.level],
)

/** 按 ID 取章节：未知 ID 返回 `undefined`，由页面渲染 404 态而不是抛错。 */
export function chapterById(id: string): TutorialChapter | undefined {
  return ALL_TUTORIAL_CHAPTERS.find((chapter) => chapter.id === id)
}

/**
 * 某方向下的章节。
 * 入参放宽为字符串：报告页的短板方向可能超出教程覆盖范围（如题库里的新方向），
 * 此时返回空数组，调用方据此不渲染入口。
 */
export function chaptersInDirection(direction: string): TutorialChapter[] {
  return ALL_TUTORIAL_CHAPTERS.filter((chapter) => chapter.direction === direction)
}

/** 第一级筛选：`all` 取全量，其余按方向取。 */
export function chaptersInScope(direction: TutorialDirectionFilter): TutorialChapter[] {
  return direction === 'all' ? ALL_TUTORIAL_CHAPTERS : chaptersInDirection(direction)
}

/**
 * 一组章节里真实存在的难度档位，按由易到难排序。
 * 二级筛选只列这些值——选了方向就不会出现「有按钮但一定查不到东西」的档位。
 */
export function levelsInChapters(chapters: TutorialChapter[]): TutorialLevel[] {
  const present = new Set(chapters.map((chapter) => chapter.level))
  return TUTORIAL_LEVELS.filter((level) => present.has(level))
}

/** 第二级筛选：`all` 原样返回（只读，不复制数组）。 */
export function filterChaptersByLevel(
  chapters: TutorialChapter[],
  level: TutorialLevelFilter,
): TutorialChapter[] {
  return level === 'all' ? chapters : chapters.filter((chapter) => chapter.level === level)
}

/**
 * 一组章节里真实存在的子方向，按该方向闭集顺序排（闭集外的历史值追加在后）。
 * 与难度同理：只列有内容的子方向，避免点了必然空结果。
 */
export function subDirectionsInChapters(chapters: TutorialChapter[]): string[] {
  const direction = chapters[0]?.direction
  const present = new Set(chapters.map((chapter) => chapter.sub_direction))
  const ordered = direction ? subDirectionsOf(direction).filter((sub) => present.has(sub)) : []
  const extra = [...present].filter((sub) => !ordered.includes(sub))
  return [...ordered, ...extra]
}

/** 第三级筛选：`all` 原样返回。 */
export function filterChaptersBySubDirection(
  chapters: TutorialChapter[],
  sub: TutorialSubDirectionFilter,
): TutorialChapter[] {
  return sub === 'all' ? chapters : chapters.filter((chapter) => chapter.sub_direction === sub)
}

/** 章节在全量顺序里的前后邻居：末章 `next` 为 `null`，首章 `prev` 为 `null`。 */
export function chapterNeighbors(id: string): {
  prev: TutorialChapter | null
  next: TutorialChapter | null
} {
  const index = ALL_TUTORIAL_CHAPTERS.findIndex((chapter) => chapter.id === id)
  if (index === -1) return { prev: null, next: null }
  return {
    prev: index > 0 ? ALL_TUTORIAL_CHAPTERS[index - 1] : null,
    next: index < ALL_TUTORIAL_CHAPTERS.length - 1 ? ALL_TUTORIAL_CHAPTERS[index + 1] : null,
  }
}

/**
 * 当前正在读的小节下标：最后一个「顶边已越过判定线」的小节。
 *
 * 判定线一般取视口高度的 40%（页面坐标）。规则是「谁开始了就算谁」：
 * 滚到第 3 节时，第 1、2 节的顶边都越过了线，但取最后一个 —— 正在读的就是它。
 * 一节都没越过线（小节被页头压得很靠下）时回落到第 0 节，目录不至于全灰。
 */
export function activeSectionIndex(tops: number[], line: number): number {
  let active = 0
  for (let index = 0; index < tops.length; index += 1) {
    if (tops[index] <= line) active = index
    else break
  }
  return active
}

/**
 * 解析 `/learn` 的 `?direction=`：只接受闭集内取值，
 * 未知 / 缺省 / 空串一律回落 `all`，坏链接不让页面白屏。
 */
export function parseLearnDirection(search: string): TutorialDirectionFilter {
  const value = new URLSearchParams(search).get('direction')
  if (value !== null && (TUTORIAL_DIRECTIONS as string[]).includes(value)) {
    return value as TutorialDirection
  }
  return 'all'
}

/** 解析 `/learn` 的 `?level=`：口径与方向一致，非法值回落 `all`。 */
export function parseLearnLevel(search: string): TutorialLevelFilter {
  const value = new URLSearchParams(search).get('level')
  if (value !== null && (TUTORIAL_LEVELS as string[]).includes(value)) {
    return value as TutorialLevel
  }
  return 'all'
}

/**
 * 解析 `/learn` 的 `?sub=`：子方向必须属于当前方向的闭集，
 * 「方向不限」或越界值一律回落 `all`（子方向只在选定方向后才有意义）。
 */
export function parseLearnSubDirection(
  search: string,
  direction: TutorialDirectionFilter,
): TutorialSubDirectionFilter {
  if (direction === 'all') return 'all'
  const value = new URLSearchParams(search).get('sub')
  if (value === null) return 'all'
  return subDirectionsOf(direction).includes(value) ? value : 'all'
}

/** 多选筛选的统一判定：空数组或含 `all` 都表示不过滤（与 `MultiChipRow` 的折叠语义一致）。 */
function isAllChoices(values: readonly string[]): boolean {
  return values.length === 0 || values.includes('all')
}

/** 解析重复键 / 逗号并列的取值：闭集外的值静默丢弃，勾满全部具体项折叠回「全部」（空数组）。 */
function readChoices<T extends string>(search: string, key: string, allowed: readonly T[]): T[] {
  const picked = new URLSearchParams(search)
    .getAll(key)
    .flatMap((raw) => raw.split(','))
    .filter((value): value is T => (allowed as readonly string[]).includes(value))
  if (picked.length === 0 || picked.includes('all' as T)) return []
  if (allowed.every((value) => picked.includes(value))) return []
  return allowed.filter((value) => picked.includes(value))
}

/** `/learn` 的 `?direction=` 多选：空数组 = 全部方向。 */
export function parseLearnDirections(search: string): TutorialDirection[] {
  return readChoices(search, 'direction', TUTORIAL_DIRECTIONS)
}

/** `/learn` 的 `?sub=` 多选：子方向只在选定方向后才有意义，方向不限或越界值一律回空数组。 */
export function parseLearnSubDirections(
  search: string,
  directions: readonly TutorialDirection[],
): string[] {
  if (isAllChoices(directions)) return []
  const allowed = Array.from(new Set(directions.flatMap((direction) => subDirectionsOf(direction))))
  return readChoices(search, 'sub', allowed)
}

/** `/learn` 的 `?level=` 多选：空数组 = 全部难度档。 */
export function parseLearnLevels(search: string): TutorialLevel[] {
  return readChoices(search, 'level', TUTORIAL_LEVELS)
}

/** 多方向并集：空数组（不过滤）返回全量，否则只保留命中方向的章节。 */
export function chaptersInDirections(directions: readonly string[]): TutorialChapter[] {
  if (isAllChoices(directions)) return ALL_TUTORIAL_CHAPTERS
  return ALL_TUTORIAL_CHAPTERS.filter((chapter) => directions.includes(chapter.direction))
}

/** 多子方向并集：空数组原样返回。 */
export function filterChaptersBySubDirections(
  chapters: TutorialChapter[],
  subs: readonly string[],
): TutorialChapter[] {
  if (isAllChoices(subs)) return chapters
  return chapters.filter((chapter) => subs.includes(chapter.sub_direction))
}

/** 多难度档并集：空数组原样返回。 */
export function filterChaptersByLevels(
  chapters: TutorialChapter[],
  levels: readonly TutorialLevel[],
): TutorialChapter[] {
  if (isAllChoices(levels)) return chapters
  return chapters.filter((chapter) => levels.includes(chapter.level))
}

/**
 * 目录页多选链接：`all` / 空数组都不写参数，链接更短也更好读。
 * 子方向只在选定方向后写入（与解析口径一致）。
 */
export function learnHref(
  directions: readonly string[] = [],
  levels: readonly string[] = [],
  subs: readonly string[] = [],
): string {
  const params = new URLSearchParams()
  if (!isAllChoices(directions)) {
    directions.forEach((direction) => params.append('direction', direction))
    if (!isAllChoices(subs)) subs.forEach((sub) => params.append('sub', sub))
  }
  if (!isAllChoices(levels)) levels.forEach((level) => params.append('level', level))
  const suffix = params.toString()
  return suffix === '' ? '/learn' : `/learn?${suffix}`
}

/**
 * 目录页链接：默认值不写参数，链接更短也更好读。
 * 入参放宽为字符串：报告页方向可能不在教程覆盖范围内，调用方先按 `chaptersInDirection` 判空。
 */
export function tutorialHref(
  direction?: string | null,
  level?: TutorialLevelFilter | null,
  sub?: TutorialSubDirectionFilter | null,
): string {
  const params = new URLSearchParams()
  const hasDirection = direction !== null && direction !== undefined && direction !== 'all'
  if (hasDirection) {
    params.set('direction', direction)
  }
  if (level !== null && level !== undefined && level !== 'all') {
    params.set('level', level)
  }
  if (hasDirection && sub !== null && sub !== undefined && sub !== 'all') {
    params.set('sub', sub)
  }
  const suffix = params.toString()
  return suffix === '' ? '/learn' : `/learn?${suffix}`
}

/** 文章页链接：章节 ID 已是 ASCII slug，无需转义。 */
export function chapterHref(id: string): string {
  return `/learn/${id}`
}
