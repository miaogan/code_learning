import { describe, expect, it } from 'vitest'
import { TOOL_GROUPS, TOOL_ITEMS } from '../lib/navGroups'

/** r126 侧栏多级菜单：分组数据是侧栏（折叠）与顶部横条（平铺）的唯一入口真源。 */
describe('navGroups', () => {
  it('分组互不重叠且条目路由唯一', () => {
    const all = TOOL_GROUPS.flatMap((group) => group.items)
    const keys = all.map((item) => item.key)
    const routes = all.map((item) => item.to)
    expect(new Set(keys).size).toBe(keys.length)
    expect(new Set(routes).size).toBe(routes.length)
  })

  it('平铺清单与分组条目完全同源（顺序一致、无遗漏）', () => {
    const expected = TOOL_GROUPS.flatMap((group) => [...group.items])
    expect(TOOL_ITEMS).toEqual(expected)
  })

  it('路由一律以 / 开头且不带尾斜杠（Link 契约）', () => {
    for (const item of TOOL_ITEMS) {
      expect(item.to.startsWith('/')).toBe(true)
      expect(item.to.endsWith('/') || item.to === '/').toBe(false)
    }
  })

  it('每个分组至少 2 条且组 key 唯一（组头折叠有折叠的意义）', () => {
    const groupKeys = TOOL_GROUPS.map((group) => group.key)
    expect(new Set(groupKeys).size).toBe(groupKeys.length)
    for (const group of TOOL_GROUPS) {
      expect(group.items.length).toBeGreaterThanOrEqual(2)
    }
  })

  it('镜试（r125 新页）在分组里且路由仍是 /mirror', () => {
    const mirror = TOOL_ITEMS.find((item) => item.key === 'mirror')
    expect(mirror?.to).toBe('/mirror')
  })
})
