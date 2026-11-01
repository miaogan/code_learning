import { describe, expect, it } from 'vitest'
import { joinMeta, textOrEmpty } from '../lib/profileText'

/**
 * r8 AC-5：契约可空后，`role` / `period` 是 `string | null`（存量 payload 还可能是 `undefined`）。
 * 页面渲染（`joinMeta`）与编辑框取值（`textOrEmpty`）都只能经这两个纯函数，
 * 所以「null 不当成已知信息」「不出现悬空分隔符」这两条语义在这里钉死。
 * 刻意不放 jsdom / RTL：lib 无 DOM 依赖，node 环境最稳。
 */
describe('textOrEmpty', () => {
  it('null / undefined → 空串（简历没写 = 未知，编辑框受控值只能是字符串）', () => {
    expect(textOrEmpty(null)).toBe('')
    expect(textOrEmpty(undefined)).toBe('')
  })

  it('空串保持空串', () => {
    expect(textOrEmpty('')).toBe('')
  })

  it('有值去首尾空白（回填编辑框不带上意外空格）', () => {
    expect(textOrEmpty('  后端开发  ')).toBe('后端开发')
  })

  it('纯空白视同未填写 —— 否则会渲染出一条只有空格的「已知」信息', () => {
    expect(textOrEmpty('   ')).toBe('')
    expect(textOrEmpty('\t\n')).toBe('')
  })
})

describe('joinMeta', () => {
  it('两侧皆空 → 空串（`entry.meta ? … : null` 吞掉它，不留空行）', () => {
    expect(joinMeta([null, null])).toBe('')
    expect(joinMeta([undefined, undefined])).toBe('')
    expect(joinMeta([])).toBe('')
  })

  it('仅角色有值 → 只显示角色，分隔符不悬空', () => {
    expect(joinMeta(['后端开发', null])).toBe('后端开发')
  })

  it('仅时间有值 → 只显示时间（顺序颠倒也成立）', () => {
    expect(joinMeta([null, '2024-2026'])).toBe('2024-2026')
    expect(joinMeta([undefined, ' 2024-2026 '])).toBe('2024-2026')
  })

  it('两侧都有值 → 「角色 · 时间」，与既有 meta 渲染一致', () => {
    expect(joinMeta(['后端开发', '2024-2026'])).toBe('后端开发 · 2024-2026')
  })

  it('单侧是空白（用户编辑清空未归一）→ 与 null 同口径，仍只剩一侧', () => {
    expect(joinMeta(['   ', '2024-2026'])).toBe('2024-2026')
    expect(joinMeta(['后端开发', ''])).toBe('后端开发')
    expect(joinMeta([' ', ''])).toBe('')
  })
})
