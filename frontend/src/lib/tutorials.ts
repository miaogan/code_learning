/**
 * 站内教程的纯逻辑（无 DOM），目录页 / 文章页 / 报告页入口共用。
 *
 * 内容在 `content/tutorials/`，本文件只做索引、筛选与链接拼接；
 * 章节 ID 是全局唯一 ASCII slug（URL 直接用），方向只进查询参数。
 */
import { TUTORIAL_CHAPTERS } from '../content/tutorials'
import type { TutorialChapter, TutorialDirection } from './tutorialTypes'

/** 目录页方向筛选的展示顺序：与内容聚合顺序一致，读起来是一条线。 */
export const TUTORIAL_DIRECTIONS: TutorialDirection[] = [
  '前端',
  '后端',
  '算法与数据结构',
  '计算机基础',
  'AI 工程',
]

/** 方向筛选取值：`all` 表示不过滤。 */
export type TutorialDirectionFilter = TutorialDirection | 'all'

export const ALL_TUTORIAL_CHAPTERS = TUTORIAL_CHAPTERS

/** 按 ID 取章节：未知 ID 返回 `undefined`，由页面渲染 404 态而不是抛错。 */
export function chapterById(id: string): TutorialChapter | undefined {
  return TUTORIAL_CHAPTERS.find((chapter) => chapter.id === id)
}

/**
 * 某方向下的章节。
 * 入参放宽为字符串：报告页的短板方向可能超出教程覆盖范围（如「中间件与运维」），
 * 此时返回空数组，调用方据此不渲染入口。
 */
export function chaptersInDirection(direction: string): TutorialChapter[] {
  return TUTORIAL_CHAPTERS.filter((chapter) => chapter.direction === direction)
}

/** 章节在全量顺序里的前后邻居：末章 `next` 为 `null`，首章 `prev` 为 `null`。 */
export function chapterNeighbors(id: string): {
  prev: TutorialChapter | null
  next: TutorialChapter | null
} {
  const index = TUTORIAL_CHAPTERS.findIndex((chapter) => chapter.id === id)
  if (index === -1) return { prev: null, next: null }
  return {
    prev: index > 0 ? TUTORIAL_CHAPTERS[index - 1] : null,
    next: index < TUTORIAL_CHAPTERS.length - 1 ? TUTORIAL_CHAPTERS[index + 1] : null,
  }
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

/**
 * 目录页链接：`all` 不写参数，链接更短也更好读。
 * 入参放宽为字符串：报告页方向可能不在教程覆盖范围内，调用方先按 `chaptersInDirection` 判空。
 */
export function tutorialHref(direction?: string | null): string {
  if (direction === null || direction === undefined || direction === 'all') return '/learn'
  return `/learn?direction=${encodeURIComponent(direction)}`
}

/** 文章页链接：章节 ID 已是 ASCII slug，无需转义。 */
export function chapterHref(id: string): string {
  return `/learn/${id}`
}
