/**
 * 站内教程的纯逻辑（无 DOM），目录页 / 文章页 / 报告页入口共用。
 *
 * 内容在 `content/tutorials/`，本文件只做索引、两级筛选与链接拼接；
 * 章节 ID 是全局唯一 ASCII slug（URL 直接用），方向与难度只进查询参数。
 */
import { TUTORIAL_CHAPTERS } from '../content/tutorials'
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
 * 目录页链接：默认值不写参数，链接更短也更好读。
 * 入参放宽为字符串：报告页方向可能不在教程覆盖范围内，调用方先按 `chaptersInDirection` 判空。
 */
export function tutorialHref(
  direction?: string | null,
  level?: TutorialLevelFilter | null,
): string {
  const params = new URLSearchParams()
  if (direction !== null && direction !== undefined && direction !== 'all') {
    params.set('direction', direction)
  }
  if (level !== null && level !== undefined && level !== 'all') {
    params.set('level', level)
  }
  const suffix = params.toString()
  return suffix === '' ? '/learn' : `/learn?${suffix}`
}

/** 文章页链接：章节 ID 已是 ASCII slug，无需转义。 */
export function chapterHref(id: string): string {
  return `/learn/${id}`
}
