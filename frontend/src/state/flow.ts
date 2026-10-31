/** 步骤门禁标记：仅用于侧栏对勾与提示，刷新后的真实数据以后端为准（ARCHITECTURE §3.7）。 */
import { useSyncExternalStore } from 'react'

export interface FlowState {
  hasResume: boolean
  hasProfile: boolean
  hasReport: boolean
}

const STORAGE_KEY = 'sc.flow'
const EMPTY: FlowState = { hasResume: false, hasProfile: false, hasReport: false }

function load(): FlowState {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
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

let current: FlowState = load()
const listeners = new Set<() => void>()

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

function snapshot(): FlowState {
  return current
}

export function getFlowState(): FlowState {
  return current
}

export function setFlow(patch: Partial<FlowState>): void {
  current = { ...current, ...patch }
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(current))
  } catch {
    /* 存储不可用时静默降级，后端数据仍是权威 */
  }
  listeners.forEach((listener) => listener())
}

export function useFlowState(): FlowState {
  return useSyncExternalStore(subscribe, snapshot, snapshot)
}
