import { describe, expect, it } from 'vitest'
import {
  backfillNotice,
  filteredNotice,
  proficiencyRuleHint,
  subDirectionNotice,
} from '../lib/examNotice'

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
 * r6 D-7 / D-9：过滤规则说明（r19；r43 合并「L2 兜底回流」）。
 * 断言语义：文案必须同时回答「怎样才算熟练 / 怎样回流」「为什么卷面里仍会出现熟练题」
 * 与「另有 N 道因保持卷面结构被重新纳入」，全部拼成**一处**说明，不拆成三个标签。
 * 阈值文案带「默认」限定：真实阈值住在后端 `config.Settings`，可被环境变量覆盖。
 */
describe('proficiencyRuleHint', () => {
  it('正数：返回规则说明，含熟练条件、回流条件与「默认」限定', () => {
    const hint = proficiencyRuleHint(3)
    expect(hint).toBe(
      '默认 30 天内答对 2 次及以上、且最近一次答对才计为熟练；超过 30 天或最近一次答错会自动回流到题池',
    )
    expect(hint).toContain('默认')
    expect(hint).toContain('回流')
  })

  it('兜底回流数并进同一句：含「另有 N 道因保持卷面结构被重新纳入」', () => {
    const hint = proficiencyRuleHint(3, 2)
    expect(hint).toContain('另有 2 道因保持卷面结构被重新纳入')
    expect(hint).toContain('默认 30 天')
  })

  it('净过滤为 0 但确有兜底回流时仍给说明（L2 放回全部熟练题）', () => {
    expect(proficiencyRuleHint(0, 4)).toContain('另有 4 道因保持卷面结构被重新纳入')
    expect(proficiencyRuleHint(undefined, 1)).not.toBeNull()
  })

  it('两个计数都为 0 / 负数 / 缺失 / 非有限数时一律 null（零占位）', () => {
    expect(proficiencyRuleHint(0)).toBeNull()
    expect(proficiencyRuleHint(0, 0)).toBeNull()
    expect(proficiencyRuleHint(-3, -1)).toBeNull()
    expect(proficiencyRuleHint(null)).toBeNull()
    expect(proficiencyRuleHint(undefined)).toBeNull()
    expect(proficiencyRuleHint(Number.NaN)).toBeNull()
    expect(proficiencyRuleHint(Number.POSITIVE_INFINITY)).toBeNull()
  })
})

describe('backfillNotice', () => {
  it('正数：逐字给出兜底回流事实', () => {
    expect(backfillNotice(2)).toBe('另有 2 道因保持卷面结构被重新纳入')
  })

  it('0 / 负数 / 缺失 / 非有限数：静默（不渲染「另有 0 道」）', () => {
    expect(backfillNotice(0)).toBeNull()
    expect(backfillNotice(-1)).toBeNull()
    expect(backfillNotice(null)).toBeNull()
    expect(backfillNotice(undefined)).toBeNull()
    expect(backfillNotice(Number.NaN)).toBeNull()
  })
})

/**
 * r46：子方向聚焦的透明度文案。
 * 断言语义：事实（补位题数 / 卷题数）由服务端给，前端只读成一句话 ——
 * 未选子方向或全部命中时静默，部分补位与「一道都没命中」各有一句，措辞不许改写。
 */
describe('subDirectionNotice', () => {
  it('未选子方向 / 空白：静默（不挂「方向聚焦」行）', () => {
    expect(subDirectionNotice('', 3, 10)).toBeNull()
    expect(subDirectionNotice('   ', 3, 10)).toBeNull()
    expect(subDirectionNotice(null, 3, 10)).toBeNull()
    expect(subDirectionNotice(undefined, 3, 10)).toBeNull()
  })

  it('全部命中（backfill 0 / 负数 / 缺失 / 非有限数）：静默', () => {
    expect(subDirectionNotice('动态规划', 0, 10)).toBeNull()
    expect(subDirectionNotice('动态规划', -2, 10)).toBeNull()
    expect(subDirectionNotice('动态规划', null, 10)).toBeNull()
    expect(subDirectionNotice('动态规划', undefined, 10)).toBeNull()
    expect(subDirectionNotice('动态规划', Number.NaN, 10)).toBeNull()
    expect(subDirectionNotice('动态规划', Number.POSITIVE_INFINITY, 10)).toBeNull()
  })

  it('部分补位：逐字给出「题目不足以单独成卷，已补充 N 道同方向题」', () => {
    expect(subDirectionNotice('哈希', 4, 10)).toBe('「哈希」题目不足以单独成卷，已补充 4 道同方向题')
  })

  it('一道都没命中（backfill >= 卷题数）：明说「暂无可用题目，本卷已改按同方向出题」', () => {
    expect(subDirectionNotice('NoSQL', 10, 10)).toBe('「NoSQL」暂无可用题目，本卷已改按同方向出题')
    expect(subDirectionNotice('NoSQL', 12, 10)).toBe('「NoSQL」暂无可用题目，本卷已改按同方向出题')
  })

  it('卷题数缺失 / 非正数时退化为「已补充 N 道」句（不误判成零题子方向）', () => {
    expect(subDirectionNotice('图', 3, 0)).toBe('「图」题目不足以单独成卷，已补充 3 道同方向题')
    expect(subDirectionNotice('图', 3, undefined)).toBe('「图」题目不足以单独成卷，已补充 3 道同方向题')
    expect(subDirectionNotice('图', 3, Number.NaN)).toBe('「图」题目不足以单独成卷，已补充 3 道同方向题')
  })

  it('文案里的数字与入参同源：不同补位量只差数字，措辞恒定', () => {
    for (const count of [1, 6, 9]) {
      expect(subDirectionNotice('排序', count, 12)).toBe(
        `「排序」题目不足以单独成卷，已补充 ${count} 道同方向题`,
      )
    }
  })
})
