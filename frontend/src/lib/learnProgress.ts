/**
 * 阅读进度的纯逻辑（无 DOM、无存储），目录页 / 文章页 / 测试共用。
 *
 * 存储与订阅在 `state/learnProgress.ts`；本文件只负责「原始记录 → 可展示的状态」，
 * 所以同一份记录在卡片、文章页、继续学习入口三处的口径完全一致。
 *
 * 进度的定义取窄口径：某小节只要真正滚进过视口就算「读到」，
 * 全部小节都读到才算「已读完」。它衡量的是「读过」而不是「掌握」，文案也照此写。
 */
import type { TutorialChapter } from './tutorialTypes'
import { ALL_TUTORIAL_CHAPTERS } from './tutorials'

/** 单章进度：以小节为最小粒度，`seen` 用集合语义（顺序无意义）。 */
export interface ChapterProgress {
  /** 已经滚进过视口的小节 id。 */
  seen: string[]
  /** 最后一次看到的小节 id：续读从这一节接着往下。 */
  lastSectionId: string | null
  /** 最后活跃时间（epoch ms）。 */
  updatedAt: number
}

export interface LearnProgressState {
  /** 最后打开过的章节：没有任何记录时为 `null`。 */
  lastChapterId: string | null
  chapters: Record<string, ChapterProgress>
}

export const EMPTY_LEARN_PROGRESS: LearnProgressState = { lastChapterId: null, chapters: {} }

/** 三态：没读过 / 读到一半 / 读完。 */
export type ChapterReadStatus = 'unread' | 'reading' | 'done'

export interface ChapterProgressView {
  status: ChapterReadStatus
  /** 有效已读小节数（已按当前章节结构过滤掉改名/删除的小节）。 */
  seen: number
  total: number
  /** 0–100 的整数，直接给进度条宽度用。 */
  percent: number
  lastSectionId: string | null
  updatedAt: number | null
  /** 一句话状态，卡片与文章页共用。 */
  label: string
  /** 卡片底部的动作文案。 */
  cta: string
}

/**
 * 把原始记录换算成某一章的可展示状态。
 *
 * `seen` 会与当前章节的小节 id 求交集：内容改版后旧记录里的失效 id 自动失配，
 * 不会把「2/4」错算成「3/4」，也不需要迁移脚本。
 */
export function progressView(
  progress: ChapterProgress | undefined,
  chapter: TutorialChapter,
): ChapterProgressView {
  const total = chapter.sections.length
  const validIds = new Set(chapter.sections.map((section) => section.id))
  const seenIds = progress === undefined ? [] : progress.seen.filter((id) => validIds.has(id))
  const seen = seenIds.length
  const lastSectionId =
    progress !== undefined &&
    progress.lastSectionId !== null &&
    validIds.has(progress.lastSectionId)
      ? progress.lastSectionId
      : null

  const status: ChapterReadStatus =
    seen === 0 || total === 0 ? 'unread' : seen >= total ? 'done' : 'reading'

  return {
    status,
    seen,
    total,
    percent: total === 0 ? 0 : Math.round((seen / total) * 100),
    lastSectionId,
    updatedAt: progress === undefined ? null : progress.updatedAt,
    label:
      status === 'done'
        ? '已读完'
        : status === 'reading'
          ? `读到 ${seen}/${total} 节`
          : '未开始',
    cta: status === 'done' ? '再读一遍' : status === 'reading' ? '继续阅读' : '开始阅读',
  }
}

export interface ResumeTarget {
  chapter: TutorialChapter
  /** 续读锚点小节：`null` 表示从章首开始。 */
  sectionId: string | null
  /** 锚点小节在章内的序号（从 1 开始），无锚点为 `null`。 */
  sectionIndex: number | null
  view: ChapterProgressView
}

function buildTarget(chapter: TutorialChapter, view: ChapterProgressView): ResumeTarget {
  const index =
    view.lastSectionId === null
      ? -1
      : chapter.sections.findIndex((section) => section.id === view.lastSectionId)
  return {
    chapter,
    sectionId: index === -1 ? null : chapter.sections[index].id,
    sectionIndex: index === -1 ? null : index + 1,
    view,
  }
}

/**
 * 「继续学习」该去哪一章。
 *
 * 1. 上次打开的章节还没读完 → 回到那一章，并带上上次看到的小节；
 * 2. 上次那章已读完 → 沿目录往后找第一本没读完的（到末尾再从头找）；
 * 3. 全读完了 → `null`，调用方据此不渲染入口。
 */
export function resumeTarget(state: LearnProgressState): ResumeTarget | null {
  const lastIndex =
    state.lastChapterId === null
      ? -1
      : ALL_TUTORIAL_CHAPTERS.findIndex((chapter) => chapter.id === state.lastChapterId)

  if (lastIndex !== -1) {
    const chapter = ALL_TUTORIAL_CHAPTERS[lastIndex]
    const view = progressView(state.chapters[chapter.id], chapter)
    if (view.status !== 'done') return buildTarget(chapter, view)
  }

  const start = Math.max(lastIndex, 0)
  const ordered = [
    ...ALL_TUTORIAL_CHAPTERS.slice(start),
    ...ALL_TUTORIAL_CHAPTERS.slice(0, start),
  ]
  for (const chapter of ordered) {
    const view = progressView(state.chapters[chapter.id], chapter)
    if (view.status !== 'done') return buildTarget(chapter, view)
  }
  return null
}

/** 续读链接：有锚点就带 `#tutorial-<sectionId>`，文章页据此滚到该小节。 */
export function resumeHref(target: ResumeTarget): string {
  const base = `/learn/${target.chapter.id}`
  return target.sectionId === null ? base : `${base}#tutorial-${target.sectionId}`
}

export interface LearnProgressSummary {
  /** 已读完章数。 */
  done: number
  /** 读到一半的章数。 */
  reading: number
  /** 参与统计的章数。 */
  chapters: number
  /** 按小节加权的总进度（0–100）。 */
  percent: number
}

/** 页头统计：按小节加权比「读完章数 / 总章数」更贴近实际投入。 */
export function summarizeProgress(
  state: LearnProgressState,
  chapters: TutorialChapter[],
): LearnProgressSummary {
  let done = 0
  let reading = 0
  let seen = 0
  let total = 0
  for (const chapter of chapters) {
    const view = progressView(state.chapters[chapter.id], chapter)
    if (view.status === 'done') done += 1
    else if (view.status === 'reading') reading += 1
    seen += view.seen
    total += view.total
  }
  return {
    done,
    reading,
    chapters: chapters.length,
    percent: total === 0 ? 0 : Math.round((seen / total) * 100),
  }
}
