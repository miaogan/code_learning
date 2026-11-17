import { API_BASE } from '../api/client'
import { streamSse } from './sse'

/**
 * r102 任务进度监听：优先 SSE 推送，**任何环节失败自动回落轮询**（旧后端 / 代理缓冲 / 断网）。
 *
 * 分工：流只负责「有变化了」这个信号，真正的状态与结果仍由调用方的 `fetchOnce`
 * 走既有单查端点拿——序列化口径只有一处，流式化不引入第二份 payload。
 */

export interface WatchJobOptions {
  /** 拉一次完整状态并应用；返回 true 表示已到终态（监听停止）。 */
  fetchOnce: () => Promise<boolean>
  /** 回落轮询的间隔（毫秒），通常沿用原来的 2s。 */
  intervalMs: number
  /** 流不可用时回调（给页面一个「已切换为轮询」的机会，可不传）。 */
  onFallback?: () => void
}

/** 返回 stop：调用方在卸载/换任务时调用，负责 abort 流并清掉轮询。 */
export function watchJob(
  kind: 'profile' | 'resume',
  jobId: string,
  options: WatchJobOptions,
): () => void {
  const controller = new AbortController()
  let stopped = false
  let timer = 0

  const stop = (): void => {
    if (stopped) return
    stopped = true
    controller.abort()
    if (timer !== 0) window.clearInterval(timer)
  }

  const fallbackToPolling = (): void => {
    if (stopped || timer !== 0) return
    options.onFallback?.()
    timer = window.setInterval(() => {
      void options.fetchOnce().then((done) => {
        if (done) stop()
      })
    }, options.intervalMs)
  }

  void (async () => {
    try {
      await options.fetchOnce()
      await streamSse(
        API_BASE,
        `/api/jobs/${kind}/${encodeURIComponent(jobId)}/stream`,
        { method: 'GET' },
        (frame) => {
          if (frame.event === 'status' || frame.event === 'error') {
            void options.fetchOnce().then((done) => {
              if (done) stop()
            })
          }
          if (frame.event === 'done' || frame.event === 'timeout') stop()
        },
        controller.signal,
      )
    } catch {
      // 流打不开（旧后端 404 / 代理不支持 / 断网）：回落轮询，功能不缺失。
      fallbackToPolling()
    }
  })()

  return stop
}
