import { describe, expect, it } from 'vitest'
import { filteredNotice, proficiencyRuleHint } from '../lib/examNotice'

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

/**
 * r6 D-7 / D-9：过滤规则说明（r19）。
 * 断言语义：只在信息行已挂载（N>0）时给出；文案必须同时回答「为什么被过滤 / 怎样回流」
 * 与「为什么卷面里仍会出现熟练题」，且**不得写死阈值**（阈值只住后端 `config.Settings`）。
 */
describe('proficiencyRuleHint', () => {
  it('正数：返回规则说明，含「回流」与「卷面结构」两个归因', () => {
    const hint = proficiencyRuleHint(3)
    expect(hint).toBe(
      '近期多次答对的题会暂时跳过，不再算作熟练后自动回流；个别熟练题可能因卷面结构重新出现',
    )
    expect(hint).toContain('回流')
    expect(hint).toContain('卷面结构')
  })

  it('与 filteredNotice 同一静默口径：0 / 负数 / 缺失 / 非有限数一律 null', () => {
    expect(proficiencyRuleHint(0)).toBeNull()
    expect(proficiencyRuleHint(-3)).toBeNull()
    expect(proficiencyRuleHint(null)).toBeNull()
    expect(proficiencyRuleHint(undefined)).toBeNull()
    expect(proficiencyRuleHint(Number.NaN)).toBeNull()
    expect(proficiencyRuleHint(Number.POSITIVE_INFINITY)).toBeNull()
  })

  it('不写死阈值（不含数字）：避免前端副本与后端可调配置漂移', () => {
    expect(proficiencyRuleHint(80)).not.toMatch(/\d/)
  })
})
