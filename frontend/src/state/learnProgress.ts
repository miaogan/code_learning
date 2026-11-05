/**
 * 阅读进度 store（r25）：与 `state/flow.ts` 同一套模式 —— 单例 + useSyncExternalStore + localStorage。
 *
 * 两个必须守住的点：
 * 1. **按账号分区**（`sc.learn.<userId>`）：同一台机器多人用时，退出后不能把上一个人的进度留给下一个人；
 * 2. **只写不读后端**：进度是本地阅读痕迹，属于「刷新就能恢复」的体验数据，不进后端也不计入任何成绩。
 */
import { useSyncExternalStore } from 'react'
import {
  EMPTY_LEARN_PROGRESS,
  type ChapterProgress,
  type LearnProgressState,
} from '../lib/learnProgress'

const STORAGE_PREFIX = 'sc.learn'

/** 与 flow 同口径：匿名用裸前缀，登录用户各用自己的后缀。 */
function keyFor(userId: string | null): string {
  return userId === null ? STORAGE_PREFIX : `${STORAGE_PREFIX}.${userId}`
}

function normalizeChapter(value: unknown): ChapterProgress | null {
  if (value === null || typeof value !== 'object') return null
  const entry = value as Partial<ChapterProgress>
  if (!Array.isArray(entry.seen)) return null
  return {
    seen: entry.seen.filter((id): id is string => typeof id === 'string'),
    lastSectionId: typeof entry.lastSectionId === 'string' ? entry.lastSectionId : null,
    updatedAt: typeof entry.updatedAt === 'number' ? entry.updatedAt : 0,
  }
}

/** 读到损坏数据就退回空状态：进度丢了不影响用，白屏才是事故。 */
function readStorage(key: string): LearnProgressState {
  try {
    const raw = window.localStorage.getItem(key)
    if (!raw) return EMPTY_LEARN_PROGRESS
    const parsed = JSON.parse(raw) as Partial<LearnProgressState> | null
    if (parsed === null || typeof parsed !== 'object') return EMPTY_LEARN_PROGRESS

    const chapters: Record<string, ChapterProgress> = {}
    const rawChapters = parsed.chapters
    if (rawChapters !== null && typeof rawChapters === 'object') {
      for (const [id, value] of Object.entries(rawChapters as Record<string, unknown>)) {
        const chapter = normalizeChapter(value)
        if (chapter !== null) chapters[id] = chapter
      }
    }
    return {
      lastChapterId: typeof parsed.lastChapterId === 'string' ? parsed.lastChapterId : null,
      chapters,
    }
  } catch {
    return EMPTY_LEARN_PROGRESS
  }
}

let storageKey = keyFor(null)
let current: LearnProgressState = readStorage(storageKey)
const listeners = new Set<() => void>()

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

function snapshot(): LearnProgressState {
  return current
}

function commit(next: LearnProgressState): void {
  current = next
  try {
    window.localStorage.setItem(storageKey, JSON.stringify(next))
  } catch {
    /* 隐私模式 / 配额满：内存里的进度仍然生效，本次会话可用 */
  }
  listeners.forEach((listener) => listener())
}

/** 登录态变化时切到该用户自己的进度（见 `state/auth.ts` 的 emit）。 */
export function bindLearnProgressToUser(userId: string | null): void {
  const nextKey = keyFor(userId)
  if (nextKey === storageKey) return
  storageKey = nextKey
  current = readStorage(storageKey)
  listeners.forEach((listener) => listener())
}

export function getLearnProgress(): LearnProgressState {
  return current
}

/** 打开章节：只记「最近读到哪」，不影响已读小节（翻一眼就走不该算读过）。 */
export function markChapterOpened(chapterId: string, now: number = Date.now()): void {
  const prev = current.chapters[chapterId]
  if (prev === undefined) {
    commit({
      lastChapterId: chapterId,
      chapters: { ...current.chapters, [chapterId]: { seen: [], lastSectionId: null, updatedAt: now } },
    })
    return
  }
  if (current.lastChapterId === chapterId) return
  commit({ lastChapterId: chapterId, chapters: current.chapters })
}

/**
 * 记「这一节读到了」。
 *
 * 滚动时会被高频调用，所以内容没变就直接返回，不写存储也不通知订阅者；
 * 回滚到已读小节仍会更新 `lastSectionId`（续读要接着这一节）。
 */
export function markSectionSeen(
  chapterId: string,
  sectionId: string,
  now: number = Date.now(),
): void {
  const prev = current.chapters[chapterId]
  const seen = prev === undefined ? [] : prev.seen
  const alreadySeen = prev !== undefined && prev.seen.includes(sectionId)
  if (alreadySeen && prev.lastSectionId === sectionId && current.lastChapterId === chapterId) {
    return
  }
  commit({
    lastChapterId: chapterId,
    chapters: {
      ...current.chapters,
      [chapterId]: {
        seen: alreadySeen ? seen : [...seen, sectionId],
        lastSectionId: sectionId,
        updatedAt: now,
      },
    },
  })
}

export function useLearnProgress(): LearnProgressState {
  return useSyncExternalStore(subscribe, snapshot, snapshot)
}
