/**
 * r102 最小 SSE 客户端：fetch + ReadableStream 解析 `event:` / `data:` 帧。
 *
 * 为什么不用 EventSource：面试回合流是 POST（带 JSON 体），EventSource 只支持 GET；
 * fetch 流还能复用既有的 Cookie 会话与错误 envelope 解析。
 *
 * 本模块**不依赖 `api/client`**（client 要 import 它来发流，反向 import 会成环）：
 * 错误统一抛 `SseError`，由调用方决定映射成 `ApiError` 还是回落轮询。
 */

export interface SseFrame {
  event: string
  data: string
}

/** 流断开 / 非 2xx：字段与后端错误 envelope 对齐，方便上层直接映射。 */
export class SseError extends Error {
  readonly code: string
  readonly status: number
  readonly retryable: boolean

  constructor(code: string, message: string, status: number, retryable: boolean) {
    super(message)
    this.name = 'SseError'
    this.code = code
    this.status = status
    this.retryable = retryable
  }
}

/** 逐帧解析：空行分帧，`:` 开头是注释（心跳），忽略。 */
export function parseSseChunk(buffer: string, onFrame: (frame: SseFrame) => void): string {
  let rest = buffer
  let index = rest.indexOf('\n\n')
  while (index >= 0) {
    const raw = rest.slice(0, index)
    rest = rest.slice(index + 2)
    let event = 'message'
    const dataLines: string[] = []
    for (const line of raw.split('\n')) {
      if (line.startsWith(':')) continue
      if (line.startsWith('event:')) event = line.slice(6).trim()
      else if (line.startsWith('data:')) dataLines.push(line.slice(5).replace(/^ /, ''))
    }
    if (dataLines.length > 0) onFrame({ event, data: dataLines.join('\n') })
    index = rest.indexOf('\n\n')
  }
  return rest
}

/**
 * 打开一条 SSE 流并逐帧回调；返回时流已结束（正常收尾或中途断开）。
 * 非 2xx 按既有错误 envelope 抛 `ApiError`，调用方据此决定是否回落轮询。
 */
export async function streamSse(
  base: string,
  path: string,
  init: RequestInit,
  onFrame: (frame: SseFrame) => void,
  signal?: AbortSignal,
): Promise<void> {
  const headers = new Headers(init.headers)
  headers.set('Accept', 'text/event-stream')
  const response = await fetch(`${base}${path}`, { ...init, headers, signal })
  if (!response.ok) {
    let code = 'HTTP_ERROR'
    let message = `服务返回异常（HTTP ${response.status}）`
    let retryable = true
    try {
      const body = (await response.json()) as {
        error?: { code?: string; message?: string; retryable?: boolean }
      }
      if (body.error?.code) {
        code = body.error.code
        message = body.error.message ?? message
        retryable = body.error.retryable ?? retryable
      }
    } catch {
      /* 非 JSON 错误体：用默认文案 */
    }
    throw new SseError(code, message, response.status, retryable)
  }
  if (response.body === null) return
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buffer = parseSseChunk(buffer + decoder.decode(value, { stream: true }), onFrame)
    }
    // 收尾：最后一段可能不带结尾空行
    buffer += decoder.decode()
    if (buffer.trim() !== '') parseSseChunk(buffer + '\n\n', onFrame)
  } finally {
    reader.releaseLock()
  }
}
