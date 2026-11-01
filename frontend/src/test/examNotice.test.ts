import { describe, expect, it } from 'vitest'
import { filteredNotice } from '../lib/examNotice'

/**
 * AC-12：`filtered_count` 的一行透明度文案。
 * 断言语义：正数逐字等于 AC-12 原句；其余全部静默（返回 `null` → 页面不挂载节点）。
 * 用 `toContain` 之外的全等断言，是因为这句话的措辞本身就是验收口径（不许改写/缩短）。
 */
describe('filteredNotice', () => {
  it('正数：逐字等于 AC-12 原句（含「你已熟练掌握」归因，不许弱化成「已过滤 N 题」）', () => {
    expect(filteredNotice(1)).toBe('本次已过滤 1 道你已熟练掌握的题')
    expect(filteredNotice(3)).toBe('本次已过滤 3 道你已熟练掌握的题')
    expect(filteredNotice(80)).toBe('本次已过滤 80 道你已熟练掌握的题')
  })

  it('0：静默（L6 全库兜底时不许断言「已过滤 0 道」）', () => {
    expect(filteredNotice(0)).toBeNull()
  })

  it('负数：静默，不渲染「已过滤 -3 道」', () => {
    expect(filteredNotice(-3)).toBeNull()
    expect(filteredNotice(-1)).toBeNull()
  })

  it('undefined / null：静默（旧 payload、刷新后的会话缺该字段）', () => {
    expect(filteredNotice(undefined)).toBeNull()
    expect(filteredNotice(null)).toBeNull()
  })

  it('NaN：静默，不渲染「NaN 道」', () => {
    expect(filteredNotice(Number.NaN)).toBeNull()
  })

  it('±Infinity：静默（N 只可能是有限整数）', () => {
    expect(filteredNotice(Number.POSITIVE_INFINITY)).toBeNull()
    expect(filteredNotice(Number.NEGATIVE_INFINITY)).toBeNull()
  })

  it('文案里的数字与入参同源：不同 N 只差数字，措辞恒定', () => {
    const suffix = ' 道你已熟练掌握的题'
    for (const count of [2, 7, 12]) {
      expect(filteredNotice(count)).toBe(`本次已过滤 ${count}${suffix}`)
    }
  })
})
