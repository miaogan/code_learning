import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  TAIFU_SIZE,
  clampTaifuPosition,
  defaultTaifuPosition,
  readStoredTaifuPosition,
  taifuPanelLayout,
  taifuStorageKey,
  writeStoredTaifuPosition,
} from '../lib/taifuPosition'

const store = new Map<string, string>()
let failWrite = false

function installWindow(): void {
  vi.stubGlobal('window', {
    localStorage: {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => {
        if (failWrite) throw new Error('quota')
        store.set(key, value)
      },
      removeItem: (key: string) => store.delete(key),
    },
  })
}

beforeEach(() => {
  store.clear()
  failWrite = false
  vi.unstubAllGlobals()
  installWindow()
})

describe('r76 太傅悬浮位置', () => {
  it('默认贴右下，并避开右下 Toast', () => {
    const position = defaultTaifuPosition(1440, 900)
    expect(position).toEqual({ x: 1440 - TAIFU_SIZE - 24, y: 900 - TAIFU_SIZE - 88 })
  })

  it('拖出四边时夹回视口，视口过小仍保证 8 的内边距', () => {
    expect(clampTaifuPosition({ x: -100, y: -100 }, 1440, 900)).toEqual({ x: 8, y: 8 })
    expect(clampTaifuPosition({ x: 9999, y: 9999 }, 1440, 900)).toEqual({
      x: 1440 - TAIFU_SIZE - 8,
      y: 900 - TAIFU_SIZE - 8,
    })
    expect(clampTaifuPosition({ x: 20, y: 20 }, 40, 40)).toEqual({ x: 8, y: 8 })
  })

  it('浮窗优先在印章上方展开，上方空间不足时翻到下方', () => {
    const above = taifuPanelLayout({ x: 1360, y: 756 }, 1440, 900)
    expect(above).not.toBeNull()
    expect(above?.height).toBe(600)
    expect(above?.top).toBe(144)

    const below = taifuPanelLayout({ x: 1360, y: 20 }, 1440, 900)
    expect(below?.top).toBe(88)
  })

  it('上下都放不下 600 时按较大空间缩高，不盖住印章', () => {
    const middle = taifuPanelLayout({ x: 400, y: 300 }, 1440, 900)
    expect(middle?.height).toBe(524)
    expect(middle?.top).toBe(368)
    expect((middle?.top ?? 0) + (middle?.height ?? 0)).toBeLessThanOrEqual(900 - 8)
  })

  it('窄屏交给 CSS 底部面板，不返回 inline 布局', () => {
    expect(taifuPanelLayout({ x: 300, y: 600 }, 640, 800)).toBeNull()
  })

  it('位置按账号隔离，读写往返且越界值读取时重新夹紧', () => {
    expect(writeStoredTaifuPosition('u1', { x: 100, y: 200 })).toBe(true)
    expect(readStoredTaifuPosition('u1', 800, 600)).toEqual({ x: 100, y: 200 })
    expect(readStoredTaifuPosition('u2', 800, 600)).toBeNull()

    store.set(taifuStorageKey('u1'), JSON.stringify({ version: 1, x: 9999, y: -20 }))
    expect(readStoredTaifuPosition('u1', 800, 600)).toEqual({ x: 736, y: 8 })
  })

  it('损坏 JSON、旧版本与非法数值一律降级为无记忆', () => {
    store.set(taifuStorageKey('u1'), '{bad')
    expect(readStoredTaifuPosition('u1', 800, 600)).toBeNull()
    store.set(taifuStorageKey('u1'), JSON.stringify({ version: 2, x: 10, y: 20 }))
    expect(readStoredTaifuPosition('u1', 800, 600)).toBeNull()
    store.set(taifuStorageKey('u1'), JSON.stringify({ version: 1, x: '10', y: 20 }))
    expect(readStoredTaifuPosition('u1', 800, 600)).toBeNull()
    store.set(taifuStorageKey('u1'), JSON.stringify({ version: 1, x: Number.NaN, y: 20 }))
    expect(readStoredTaifuPosition('u1', 800, 600)).toBeNull()
  })

  it('隐私模式写盘失败只返回 false，不抛错', () => {
    failWrite = true
    expect(writeStoredTaifuPosition('u1', { x: 10, y: 20 })).toBe(false)
  })

  it('匿名用户不读写位置', () => {
    expect(writeStoredTaifuPosition(null, { x: 10, y: 20 })).toBe(false)
    expect(readStoredTaifuPosition(null, 800, 600)).toBeNull()
  })
})
