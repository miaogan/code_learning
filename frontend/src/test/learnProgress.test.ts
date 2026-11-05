import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  type ChapterProgress,
  type LearnProgressState,
  progressView,
  resumeHref,
  resumeTarget,
  summarizeProgress,
} from '../lib/learnProgress'
import type { TutorialChapter } from '../lib/tutorialTypes'
import { ALL_TUTORIAL_CHAPTERS, chapterById } from '../lib/tutorials'

function mustChapter(id: string): TutorialChapter {
  const chapter = chapterById(id)
  if (chapter === undefined) throw new Error(`测试依赖的章节不存在：${id}`)
  return chapter
}

/** 造一条「整章读完」的记录：小节全在 `seen` 里，最后停在第 `lastSectionId`。 */
function readAll(chapter: TutorialChapter): ChapterProgress {
  const ids = chapter.sections.map((section) => section.id)
  return { seen: ids, lastSectionId: ids[ids.length - 1] ?? null, updatedAt: 1000 }
}

describe('阅读进度视图', () => {
  const chapter = mustChapter('fe-event-loop')

  it('没有记录 = 未开始', () => {
    const view = progressView(undefined, chapter)
    expect(view.status).toBe('unread')
    expect(view.seen).toBe(0)
    expect(view.percent).toBe(0)
    expect(view.cta).toBe('开始阅读')
  })

  it('读到一半给出已读小节数、百分比与续读锚点', () => {
    const view = progressView(
      { seen: ['why', 'order'], lastSectionId: 'order', updatedAt: 1000 },
      chapter,
    )
    expect(view.status).toBe('reading')
    expect(view.seen).toBe(2)
    expect(view.total).toBe(chapter.sections.length)
    expect(view.percent).toBe(50)
    expect(view.lastSectionId).toBe('order')
    expect(view.label).toBe('读到 2/4 节')
    expect(view.cta).toBe('继续阅读')
  })

  it('全部小节读到 = 已读完', () => {
    const view = progressView(readAll(chapter), chapter)
    expect(view.status).toBe('done')
    expect(view.percent).toBe(100)
    expect(view.label).toBe('已读完')
    expect(view.cta).toBe('再读一遍')
  })

  it('内容改版后失效的小节 id 不计入，也不会把锚点指到不存在的小节', () => {
    const view = progressView(
      { seen: ['why', 'removed-section'], lastSectionId: 'removed-section', updatedAt: 1000 },
      chapter,
    )
    expect(view.seen).toBe(1)
    expect(view.percent).toBe(25)
    expect(view.lastSectionId).toBeNull()
  })
})

describe('继续学习目标', () => {
  const first = ALL_TUTORIAL_CHAPTERS[0]
  const second = ALL_TUTORIAL_CHAPTERS[1]

  it('没有任何进度时指向目录第一章', () => {
    const target = resumeTarget({ lastChapterId: null, chapters: {} })
    expect(target?.chapter.id).toBe(first.id)
    expect(target?.sectionId).toBeNull()
    expect(target === null ? '' : resumeHref(target)).toBe(`/learn/${first.id}`)
  })

  it('上次那章没读完 → 回到那一章上次看到的小节', () => {
    const chapter = mustChapter('fe-event-loop')
    const anchor = chapter.sections[2].id
    const state: LearnProgressState = {
      lastChapterId: chapter.id,
      chapters: { [chapter.id]: { seen: ['why', anchor], lastSectionId: anchor, updatedAt: 1000 } },
    }
    const target = resumeTarget(state)
    expect(target?.chapter.id).toBe(chapter.id)
    expect(target?.sectionId).toBe(anchor)
    expect(target?.sectionIndex).toBe(3)
    expect(target === null ? '' : resumeHref(target)).toBe(
      `/learn/${chapter.id}#tutorial-${anchor}`,
    )
  })

  it('上次那章读完了 → 顺延到目录里下一本没读完的', () => {
    const state: LearnProgressState = {
      lastChapterId: first.id,
      chapters: { [first.id]: readAll(first) },
    }
    expect(resumeTarget(state)?.chapter.id).toBe(second.id)
  })

  it('全部读完 → 没有可续读目标（入口不渲染）', () => {
    const chapters = Object.fromEntries(
      ALL_TUTORIAL_CHAPTERS.map((chapter) => [chapter.id, readAll(chapter)]),
    )
    expect(resumeTarget({ lastChapterId: first.id, chapters })).toBeNull()
  })
})

describe('页头统计', () => {
  it('按小节加权，而不是按章数', () => {
    const first = ALL_TUTORIAL_CHAPTERS[0]
    const state: LearnProgressState = {
      lastChapterId: first.id,
      chapters: { [first.id]: { seen: [first.sections[0].id], lastSectionId: null, updatedAt: 1 } },
    }
    const summary = summarizeProgress(state, [first])
    expect(summary.chapters).toBe(1)
    expect(summary.reading).toBe(1)
    expect(summary.done).toBe(0)
    expect(summary.percent).toBe(Math.round((1 / first.sections.length) * 100))
  })
})

/** r25：进度是本地痕迹，必须按账号隔离（与 flow 同一套口径）。 */
const store = new Map<string, string>()

function installWindow(): void {
  vi.stubGlobal('window', {
    localStorage: {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => {
        store.set(key, value)
      },
    },
  })
}

describe('阅读进度存储按账号分区', () => {
  beforeEach(() => {
    store.clear()
    vi.resetModules()
    vi.unstubAllGlobals()
    installWindow()
  })

  it('未登录写匿名键，绑定账号后各读各的', async () => {
    const state = await import('../state/learnProgress')

    state.markSectionSeen('fe-event-loop', 'why')
    expect(store.get('sc.learn')).toContain('why')

    state.bindLearnProgressToUser('user-a')
    expect(state.getLearnProgress().chapters['fe-event-loop']).toBeUndefined()
    state.markSectionSeen('fe-event-loop', 'order')
    expect(store.get('sc.learn.user-a')).toContain('order')
    expect(store.get('sc.learn.user-a')).not.toContain('why')

    state.bindLearnProgressToUser('user-b')
    expect(state.getLearnProgress().chapters['fe-event-loop']).toBeUndefined()

    state.bindLearnProgressToUser('user-a')
    expect(state.getLearnProgress().chapters['fe-event-loop']?.seen).toEqual(['order'])

    state.bindLearnProgressToUser(null)
    expect(state.getLearnProgress().chapters['fe-event-loop']?.seen).toEqual(['why'])
  })

  it('同一小节重复上报不重复记录，但会更新续读位置', async () => {
    const state = await import('../state/learnProgress')
    state.markSectionSeen('fe-event-loop', 'why')
    state.markSectionSeen('fe-event-loop', 'why')
    expect(state.getLearnProgress().chapters['fe-event-loop']?.seen).toEqual(['why'])

    state.markSectionSeen('fe-event-loop', 'pitfalls')
    state.markSectionSeen('fe-event-loop', 'why')
    const entry = state.getLearnProgress().chapters['fe-event-loop']
    expect(entry?.seen).toEqual(['why', 'pitfalls'])
    expect(entry?.lastSectionId).toBe('why')
    expect(state.getLearnProgress().lastChapterId).toBe('fe-event-loop')
  })

  it('打开章节只记最近在读，不刷已读小节', async () => {
    const state = await import('../state/learnProgress')
    state.markChapterOpened('fe-react-render')
    const entry = state.getLearnProgress().chapters['fe-react-render']
    expect(entry?.seen).toEqual([])
    expect(state.getLearnProgress().lastChapterId).toBe('fe-react-render')
    // 未产生已读小节 → 目录里仍显示「未开始」
    expect(progressView(entry, mustChapter('fe-react-render')).status).toBe('unread')
  })

  it('损坏的存储值降级为空状态', async () => {
    store.set('sc.learn.user-a', '{oops')
    const state = await import('../state/learnProgress')
    state.bindLearnProgressToUser('user-a')
    expect(state.getLearnProgress()).toEqual({ lastChapterId: null, chapters: {} })

    // 结构对但字段类型不对：能救的字段救回来，坏字段丢掉
    store.set('sc.learn.user-b', JSON.stringify({
      lastChapterId: 42,
      chapters: { 'fe-event-loop': { seen: 'why', lastSectionId: 7 } },
    }))
    state.bindLearnProgressToUser('user-b')
    expect(state.getLearnProgress()).toEqual({ lastChapterId: null, chapters: {} })
  })
})
