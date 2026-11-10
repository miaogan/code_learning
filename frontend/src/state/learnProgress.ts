/**
 * 阅读进度 store（r25 起本地、r61 起上云）：与 `state/flow.ts` 同一套模式 —— 单例 + useSyncExternalStore。
 *
 * 三个必须守住的点：
 * 1. **按账号分区**（`sc.learn.<userId>`）：同一台机器多人用时，退出后不能把上一个人的进度留给下一个人；
 * 2. **服务端权威、本地缓存**（r61）：登录后先拉服务端并合并本地旧记录（首次上云＝把本地推上去），
 *    之后每次改动防抖整份 PUT；请求失败静默保留本地，下次改动再试，绝不因网络把页面卡住；
 * 3. **只记「读过」不记「掌握」**：进度不进任何成绩与熟练度口径，界面文案照此写。
 */
import { useSyncExternalStore } from 'react'
import { api } from '../api/client'
import {
  EMPTY_LEARN_PROGRESS,
  learnProgressFromWire,
  learnProgressToWire,
  mergeLearnProgress,
  sameLearnProgress,
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

/** 当前绑定的账号：`null` 时不发任何请求（登录页尚未知道身份）。 */
let syncUserId: string | null = null
/** 防抖句柄：滚动会高频触发已读，整份 PUT 只按最后一次状态发一次。 */
let pushTimer: ReturnType<typeof setTimeout> | null = null
const PUSH_DELAY_MS = 800

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

function snapshot(): LearnProgressState {
  return current
}

function persist(): void {
  try {
    window.localStorage.setItem(storageKey, JSON.stringify(current))
  } catch {
    /* 隐私模式 / 配额满：内存里的进度仍然生效，本次会话可用 */
  }
}

function commit(next: LearnProgressState, scheduleSync = true): void {
  current = next
  persist()
  listeners.forEach((listener) => listener())
  if (scheduleSync) schedulePush()
}

function schedulePush(): void {
  if (syncUserId === null) return
  if (pushTimer !== null) clearTimeout(pushTimer)
  pushTimer = setTimeout(() => {
    pushTimer = null
    void pushProgress()
  }, PUSH_DELAY_MS)
}

async function pushProgress(): Promise<void> {
  if (syncUserId === null) return
  try {
    await api.saveLearnProgress(learnProgressToWire(current))
  } catch {
    /* 离线 / 服务端 5xx：本地照常用，下一次改动会再推一次（不弹框、不重试风暴） */
  }
}

/**
 * 登录后对齐服务端：远端为空（首次上云）直接把本地推上去；
 * 否则按小节并集合并，再把差异回写，保证下一次进来看到的是合并结果。
 */
async function hydrate(userId: string): Promise<void> {
  let remote: LearnProgressState
  try {
    remote = learnProgressFromWire(await api.learnProgress())
  } catch {
    return
  }
  if (syncUserId !== userId) return

  const merged = mergeLearnProgress(current, remote)
  commit(merged, false)
  if (sameLearnProgress(merged, remote)) return
  if (pushTimer !== null) {
    clearTimeout(pushTimer)
    pushTimer = null
  }
  void pushProgress()
}

/** 登录态变化时切到该用户自己的进度并做一次云端对齐（见 `state/auth.ts` 的 emit）。 */
export function bindLearnProgressToUser(userId: string | null): void {
  const nextKey = keyFor(userId)
  syncUserId = userId
  if (pushTimer !== null) {
    clearTimeout(pushTimer)
    pushTimer = null
  }
  if (nextKey === storageKey) {
    if (userId !== null) void hydrate(userId)
    return
  }
  storageKey = nextKey
  current = readStorage(storageKey)
  listeners.forEach((listener) => listener())
  if (userId !== null) void hydrate(userId)
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
