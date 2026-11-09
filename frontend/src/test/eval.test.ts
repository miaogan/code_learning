import { describe, expect, it } from 'vitest'
import type { EvalSummary } from '../api/types'
import { kindLabel, kindRows, latencyLabel, rateLabel, summaryNotice, trendRows } from '../lib/eval'

function summary(overrides: Partial<EvalSummary> = {}): EvalSummary {
  return {
    window_days: 7,
    total: 10,
    success_rate: 0.8,
    p50_ms: 320,
    p95_ms: 2100,
    by_kind: {},
    by_model: {},
    trend: [],
    notice: '',
    ...overrides,
  }
}

describe('eval 看板纯函数', () => {
  it('比例与延迟格式化有边界保护', () => {
    expect(rateLabel(0.834)).toBe('83.4%')
    expect(rateLabel(1.8)).toBe('100.0%')
    expect(rateLabel(Number.NaN)).toBe('—')
    expect(latencyLabel(320)).toBe('320 ms')
    expect(latencyLabel(2100)).toBe('2.10 s')
    expect(latencyLabel(-1)).toBe('—')
  })

  it('失败分类标签已知值中文、未知值原样回落', () => {
    expect(kindLabel('timeout')).toBe('超时')
    expect(kindLabel('schema_invalid')).toBe('结构校验失败')
    expect(kindLabel('future_kind')).toBe('future_kind')
  })

  it('失败分类按条数降序，平局按 kind 字典序，share 分母是 total', () => {
    const rows = kindRows(
      summary({ total: 10, by_kind: { connect: 2, timeout: 2, success: 6 } }),
    )
    expect(rows.map((row) => row.kind)).toEqual(['success', 'connect', 'timeout'])
    expect(rows[0].share).toBe(0.6)
    expect(rows[1].share).toBe(0.2)
    expect(kindRows(summary({ total: 0, by_kind: { timeout: 1 } }))[0].share).toBe(0)
  })

  it('趋势行只切日期，不重排服务端顺序', () => {
    const rows = trendRows(
      summary({
        trend: [
          { day: '2026-11-08', total: 3, success_rate: 1 },
          { day: '2026-11-09', total: 5, success_rate: 0.6 },
        ],
      }),
    )
    expect(rows.map((row) => row.label)).toEqual(['11-08', '11-09'])
    expect(rows[1].rate).toBe(0.6)
  })

  it('空窗口给中文提示，非空窗口沿用服务端 notice', () => {
    expect(summaryNotice(summary({ total: 0, notice: '' }))).toBe('暂无模型调用记录')
    expect(summaryNotice(summary({ total: 0, notice: '自定义提示' }))).toBe('自定义提示')
    expect(summaryNotice(summary({ total: 4, notice: '降级说明' }))).toBe('降级说明')
  })
})
