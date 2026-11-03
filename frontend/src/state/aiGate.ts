/** 403 `AI_KEY_REQUIRED` 的全局提示（r23 P2）：由 api/client 上报，壳层横幅提供「去设置」。 */

import { useSyncExternalStore } from 'react'

let message: string | null = null
const listeners = new Set<() => void>()

function emit(): void {
  listeners.forEach((listener) => listener())
}

export function reportKeyRequired(next: string): void {
  if (message === next) return
  message = next
  emit()
}

export function dismissKeyRequired(): void {
  if (message === null) return
  message = null
  emit()
}

export function getKeyRequiredMessage(): string | null {
  return message
}

export function subscribeKeyRequired(listener: () => void): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

export function useKeyRequired(): string | null {
  return useSyncExternalStore(subscribeKeyRequired, getKeyRequiredMessage, getKeyRequiredMessage)
}
