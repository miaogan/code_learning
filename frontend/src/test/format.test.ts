import { describe, expect, it } from 'vitest'
import { formatChars, formatElapsed, formatScore, severityLabel } from '../lib/format'

describe('formatScore', () => {
  it('整数不补小数位，保证得分环内 ≤3 字符', () => {
    expect(formatScore(8)).toBe('8')
    expect(formatScore(10)).toBe('10')
  })

  it('保留一位小数', () => {
    expect(formatScore(8.5)).toBe('8.5')
    expect(formatScore(7.24)).toBe('7.2')
  })

  it('夹紧到 0–10，非法值降级为短横', () => {
    expect(formatScore(-1)).toBe('0')
    expect(formatScore(12)).toBe('10')
    expect(formatScore(Number.NaN)).toBe('—')
  })
})

describe('formatElapsed', () => {
  it('mm:ss 且补零', () => {
    expect(formatElapsed(12)).toBe('00:12')
    expect(formatElapsed(3661)).toBe('61:01')
  })

  it('上限 99:59，与计时环内文本宽度推导一致', () => {
    expect(formatElapsed(9999)).toBe('99:59')
    expect(formatElapsed(-3)).toBe('00:00')
  })
})

describe('formatChars', () => {
  it('千分位与单位', () => {
    expect(formatChars(12340)).toBe('12,340 字')
    expect(formatChars(0)).toBe('0 字')
  })
})

describe('severityLabel', () => {
  it('严重度永远有文字，不靠颜色单独承载', () => {
    expect(severityLabel('high')).toBe('高')
    expect(severityLabel('medium')).toBe('中')
    expect(severityLabel('low')).toBe('低')
  })
})
