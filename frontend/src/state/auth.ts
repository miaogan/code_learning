/** r23 登录态 store：唯一会话真源（HttpOnly Cookie 由浏览器持有，前端只存 `Me`）。 */
import { useSyncExternalStore } from 'react'
import { api, setUnauthorizedHandler } from '../api/client'
import type { Me } from '../api/types'
import { bindFlowToUser } from './flow'
import { bindLearnProgressToUser } from './learnProgress'

export type AuthStatus = 'loading' | 'authed' | 'anonymous'

export interface AuthState {
  status: AuthStatus
  me: Me | null
}

let current: AuthState = { status: 'loading', me: null }
let started = false
const listeners = new Set<() => void>()

function emit(next: AuthState): void {
  current = next
  // 本地痕迹跟随账号：登录切换用户、登出回匿名，都要重读各自的 localStorage。
  const userId = next.me === null ? null : next.me.id
  bindFlowToUser(userId)
  bindLearnProgressToUser(userId)
  listeners.forEach((listener) => listener())
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

function snapshot(): AuthState {
  return current
}

export function useAuth(): AuthState {
  return useSyncExternalStore(subscribe, snapshot, snapshot)
}

export function getAuthState(): AuthState {
  return current
}

/** 会话失效（401）时回登录页；只对已登录态生效，登录页自身的 401 不重复触发。 */
setUnauthorizedHandler(() => {
  if (current.status === 'authed') emit({ status: 'anonymous', me: null })
})

/**
 * 启动时拉一次 `/api/me`。React StrictMode 会双执行副作用，
 * 用 `started` 守卫避免两次并发请求与重复状态通知。
 */
export async function startAuth(): Promise<void> {
  if (started) return
  started = true
  try {
    const me = await api.me()
    emit({ status: 'authed', me })
  } catch {
    // 401 = 未登录；网络失败也先落到登录页（登录页会给出「连接不到服务」的具体文案）。
    emit({ status: 'anonymous', me: null })
  }
}

export async function login(email: string, password: string): Promise<void> {
  const me = await api.login({ email, password })
  emit({ status: 'authed', me })
}

export async function logout(): Promise<void> {
  try {
    await api.logout()
  } catch {
    /* 会话已过期也要回到登录页，登出失败不阻塞本地状态切换 */
  }
  emit({ status: 'anonymous', me: null })
}

/** 后端返回的最新 `Me` 直接回写（保存 Key 的响应已带全量字段，免一次额外 GET）。 */
export function applyMe(me: Me): void {
  emit({ status: 'authed', me })
}
