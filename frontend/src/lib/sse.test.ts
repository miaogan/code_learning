import { describe, expect, it } from 'vitest'
import { parseSseChunk, type SseFrame } from './sse'

/**
 * r102 SSE 解析器：帧可能被任意切块（网络分片），必须按空行归并；
 * 心跳是 `:` 注释行（不产生帧），data 可多行。
 */

function collect(chunks: string[]): SseFrame[] {
  const frames: SseFrame[] = []
  let buffer = ''
  for (const chunk of chunks) {
    buffer = parseSseChunk(buffer + chunk, (frame) => frames.push(frame))
  }
  return frames
}

describe('parseSseChunk', () => {
  it('解析单帧事件与 JSON data', () => {
    const frames = collect(['event: status\ndata: {"status":"running"}\n\n'])
    expect(frames).toEqual([{ event: 'status', data: '{"status":"running"}' }])
  })

  it('帧被网络切块时按空行归并（不留残帧）', () => {
    const frames = collect(['event: tur', 'n\ndata: {"score":6}', '\n\n'])
    expect(frames).toEqual([{ event: 'turn', data: '{"score":6}' }])
  })

  it('心跳注释行不产生帧', () => {
    const frames = collect([': ping\n\n', 'event: done\ndata: {}\n\n'])
    expect(frames.map((frame) => frame.event)).toEqual(['done'])
  })

  it('data 多行按换行拼接，缺省事件名为 message', () => {
    const frames = collect(['data: line1\ndata: line2\n\n'])
    expect(frames).toEqual([{ event: 'message', data: 'line1\nline2' }])
  })

  it('半帧留在缓冲区，不提前触发回调', () => {
    const frames: SseFrame[] = []
    const rest = parseSseChunk('event: status\ndata: {"a":1}', (frame) => frames.push(frame))
    expect(frames).toEqual([])
    expect(rest).toContain('event: status')
  })
})
