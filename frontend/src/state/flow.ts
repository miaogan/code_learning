/** 步骤门禁标记：仅用于侧栏对勾与提示，刷新后的真实数据以后端为准（ARCHITECTURE §3.7）。 */
import { useSyncExternalStore } from 'react'

export interface FlowState {
  hasResume: boolean
  hasProfile: boolean
  hasReport: boolean
}

const STORAGE_PREFIX = 'sc.flow'
const EMPTY: FlowState = { hasResume: false, hasProfile: false, hasReport: false }

/** r23：同一台机器多人用时，进度必须按账号分开存，否则退出后下一个人看到上一个人的对勾。 */
function keyFor(userId: string | null): string {
  return userId === null ? STORAGE_PREFIX : `${STORAGE_PREFIX}.${userId}`
}

function readStorage(key: string): FlowState {
  try {
    const raw = window.localStorage.getItem(key)
    if (!raw) return EMPTY
    const parsed = JSON.parse(raw) as Partial<FlowState>
    return {
      hasResume: Boolean(parsed.hasResume),
      hasProfile: Boolean(parsed.hasProfile),
      hasReport: Boolean(parsed.hasReport),
    }
  } catch {
    return EMPTY
  }
}

let storageKey = keyFor(null)
let current: FlowState = readStorage(storageKey)
const listeners = new Set<() => void>()

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

function snapshot(): FlowState {
  return current
}

/**
 * 登录态变化时调用（r23）：切到该用户自己的进度键并通知订阅者。
 * 登出传 `null` 回到匿名基线；同一用户重复调用直接返回，不发多余通知。
 */
export function bindFlowToUser(userId: string | null): void {
  const nextKey = keyFor(userId)
  if (nextKey === storageKey) return
  storageKey = nextKey
  current = readStorage(storageKey)
  listeners.forEach((listener) => listener())
}

export function getFlowState(): FlowState {
  return current
}

export function setFlow(patch: Partial<FlowState>): void {
  current = { ...current, ...patch }
  try {
    window.localStorage.setItem(storageKey, JSON.stringify(current))
  } catch {
    /* 存储不可用时静默降级，后端数据仍是权威 */
  }
  listeners.forEach((listener) => listener())
}

export function useFlowState(): FlowState {
  return useSyncExternalStore(subscribe, snapshot, snapshot)
}
