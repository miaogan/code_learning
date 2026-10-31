/**
 * 页面数据获取状态机（TECHNICAL §4）：AbortController 防竞态 + AbortError 静默 + reload。
 *
 * 约定：`status` 是唯一真值来源，`data` 只是「最近一次成功值」（重载期间保留，避免内容闪空）；
 * 取消/被取代的请求一律不写 `error`（避免把「已取消」渲染成红色错误条）。
 * loader 用 ref 保存最新引用，**不进 deps**：调用方只声明真正决定请求的参数。
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError } from '../api/client'

export interface AsyncState<T> {
  status: 'idle' | 'loading' | 'success' | 'error'
  data: T | null
  error: ApiError | null
}

export interface AsyncResult<T> extends AsyncState<T> {
  reload: () => void
}

const UNKNOWN_MESSAGE = '请求失败，请稍后重试'

/** 取消有两种形态：裸 DOMException（name=AbortError）与 client.ts 归一后的 ApiError(code=ABORTED)。 */
function isAbortLike(error: unknown): boolean {
  if (typeof error !== 'object' || error === null) return false
  const candidate = error as { name?: unknown; code?: unknown }
  return candidate.name === 'AbortError' || candidate.code === 'ABORTED'
}

/** 非 ApiError 的异常也归一成 ApiError，页面只需要处理一种错误形状（错误 envelope 见 ARCHITECTURE §3.3）。 */
function toApiError(error: unknown): ApiError {
  if (error instanceof ApiError) return error
  if (typeof error === 'object' && error !== null) {
    const candidate = error as {
      message?: unknown
      code?: unknown
      status?: unknown
      retryable?: unknown
    }
    const message =
      typeof candidate.message === 'string' && candidate.message.trim() !== ''
        ? candidate.message
        : UNKNOWN_MESSAGE
    const code = typeof candidate.code === 'string' && candidate.code !== '' ? candidate.code : 'UNKNOWN'
    const status = typeof candidate.status === 'number' ? candidate.status : 0
    const retryable = typeof candidate.retryable === 'boolean' ? candidate.retryable : true
    return new ApiError(code, message, status, retryable)
  }
  return new ApiError('UNKNOWN', UNKNOWN_MESSAGE, 0, true)
}

export function useAsync<T>(
  loader: (signal: AbortSignal) => Promise<T>,
  deps: readonly unknown[],
): AsyncResult<T> {
  const [state, setState] = useState<AsyncState<T>>({ status: 'idle', data: null, error: null })
  const [tick, setTick] = useState(0)
  const loaderRef = useRef(loader)
  loaderRef.current = loader

  useEffect(() => {
    const controller = new AbortController()
    let active = true

    setState((prev) => ({ status: 'loading', data: prev.data, error: null }))

    const onSuccess = (value: T): void => {
      if (!active || controller.signal.aborted) return
      setState({ status: 'success', data: value, error: null })
    }

    const onFailure = (error: unknown): void => {
      if (!active || controller.signal.aborted || isAbortLike(error)) return
      setState({ status: 'error', data: null, error: toApiError(error) })
    }

    try {
      loaderRef.current(controller.signal).then(onSuccess, onFailure)
    } catch (error) {
      // loader 同步抛错（例如参数校验）也要落到 error 态，不能炸掉整页
      onFailure(error)
    }

    return () => {
      active = false
      controller.abort()
    }
    // loader 走 ref（最新引用），deps 由调用方声明，tick 承载 reload()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick])

  const reload = useCallback(() => {
    setTick((value) => value + 1)
  }, [])

  return { ...state, reload }
}
