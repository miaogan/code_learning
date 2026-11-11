/**
 * r76 太傅悬浮入口的位置计算与本地记忆。
 *
 * 只做三件事，全部纯函数可单测：
 * 1. 默认位置固定在右下（右 24 / 底 88，避开右下 Toast 的 24）；
 * 2. 拖拽或窗口变化时把 56×56 的印章夹在视口内，不压系统安全区；
 * 3. 按账号读写 `sc.taifu.pos.<userId>`，损坏、旧版本、越界数据一律降级为默认位置。
 *
 * 刻意不把位置写成百分比：不同浏览器地址栏收放会改变 `innerHeight`，
 * 百分比会把印章从右下角推到页面中部；像素位置 + 每次重新夹紧更可控。
 */

export const TAIFU_SIZE = 56
export const TAIFU_EDGE = 8
export const TAIFU_DEFAULT_RIGHT = 24
export const TAIFU_DEFAULT_BOTTOM = 88
export const TAIFU_PANEL_WIDTH = 400
export const TAIFU_PANEL_HEIGHT = 600
export const TAIFU_PANEL_GAP = 12
export const TAIFU_MOBILE_BREAKPOINT = 640
export const TAIFU_STORAGE_VERSION = 1

export interface TaifuPosition {
  x: number
  y: number
}

export interface TaifuViewport {
  width: number
  height: number
}

export interface TaifuPanelLayout {
  left: number
  top: number
  width: number
  height: number
}

export function taifuStorageKey(userId: string | null): string {
  return `sc.taifu.pos.${userId ?? 'anonymous'}`
}

function safeViewport(width: number, height: number): TaifuViewport {
  return {
    width: Number.isFinite(width) ? Math.max(0, width) : 0,
    height: Number.isFinite(height) ? Math.max(0, height) : 0,
  }
}

export function clampTaifuPosition(
  position: TaifuPosition,
  width: number,
  height: number,
): TaifuPosition {
  const viewport = safeViewport(width, height)
  const maxX = Math.max(TAIFU_EDGE, viewport.width - TAIFU_SIZE - TAIFU_EDGE)
  const maxY = Math.max(TAIFU_EDGE, viewport.height - TAIFU_SIZE - TAIFU_EDGE)
  const x = Number.isFinite(position.x) ? position.x : TAIFU_EDGE
  const y = Number.isFinite(position.y) ? position.y : TAIFU_EDGE
  return {
    x: Math.min(Math.max(TAIFU_EDGE, x), maxX),
    y: Math.min(Math.max(TAIFU_EDGE, y), maxY),
  }
}

/** 默认右下：右 24、底 88；视口过小时自动压回可放下的最小位置。 */
export function defaultTaifuPosition(width: number, height: number): TaifuPosition {
  return clampTaifuPosition(
    {
      x: width - TAIFU_SIZE - TAIFU_DEFAULT_RIGHT,
      y: height - TAIFU_SIZE - TAIFU_DEFAULT_BOTTOM,
    },
    width,
    height,
  )
}

/**
 * 浮窗位置：桌面端从印章上方展开，空间不足时落到下方或贴边；
 * 窄屏返回 `null`，由 CSS 接管为底部面板（避免 inline style 压过 media query）。
 */
export function taifuPanelLayout(
  position: TaifuPosition,
  width: number,
  height: number,
): TaifuPanelLayout | null {
  const viewport = safeViewport(width, height)
  if (viewport.width <= TAIFU_MOBILE_BREAKPOINT) return null

  const panelWidth = Math.min(TAIFU_PANEL_WIDTH, Math.max(0, viewport.width - TAIFU_EDGE * 2))
  const maxPanelHeight = Math.min(
    TAIFU_PANEL_HEIGHT,
    Math.max(0, viewport.height - TAIFU_EDGE * 2),
  )
  const maxLeft = Math.max(TAIFU_EDGE, viewport.width - panelWidth - TAIFU_EDGE)

  const left = Math.min(
    Math.max(TAIFU_EDGE, position.x + TAIFU_SIZE - panelWidth),
    maxLeft,
  )

  // 先试上方、再试下方；两边都放不下整窗时，选空间更大的一侧缩高。
  // 这样印章在屏幕中部也不会被浮窗盖住，浮窗内部自行滚动。
  const spaceAbove = Math.max(0, position.y - TAIFU_PANEL_GAP - TAIFU_EDGE)
  const spaceBelow = Math.max(
    0,
    viewport.height - (position.y + TAIFU_SIZE) - TAIFU_PANEL_GAP - TAIFU_EDGE,
  )
  const putAbove = spaceAbove >= spaceBelow
  const panelHeight =
    spaceAbove >= maxPanelHeight
      ? maxPanelHeight
      : spaceBelow >= maxPanelHeight
        ? maxPanelHeight
        : spaceAbove >= spaceBelow
          ? spaceAbove
          : spaceBelow
  const top = putAbove
    ? position.y - TAIFU_PANEL_GAP - panelHeight
    : position.y + TAIFU_SIZE + TAIFU_PANEL_GAP

  return {
    left,
    top: Math.max(TAIFU_EDGE, top),
    width: panelWidth,
    height: Math.max(0, panelHeight),
  }
}

export function readStoredTaifuPosition(
  userId: string | null,
  width: number,
  height: number,
): TaifuPosition | null {
  if (userId === null) return null
  try {
    const raw = window.localStorage.getItem(taifuStorageKey(userId))
    if (raw === null) return null
    const parsed = JSON.parse(raw) as unknown
    if (typeof parsed !== 'object' || parsed === null) return null
    const record = parsed as { version?: unknown; x?: unknown; y?: unknown }
    if (record.version !== TAIFU_STORAGE_VERSION) return null
    if (typeof record.x !== 'number' || typeof record.y !== 'number') return null
    if (!Number.isFinite(record.x) || !Number.isFinite(record.y)) return null
    return clampTaifuPosition({ x: record.x, y: record.y }, width, height)
  } catch {
    return null
  }
}

export function writeStoredTaifuPosition(userId: string | null, position: TaifuPosition): boolean {
  if (userId === null) return false
  try {
    window.localStorage.setItem(
      taifuStorageKey(userId),
      JSON.stringify({
        version: TAIFU_STORAGE_VERSION,
        x: Math.round(position.x),
        y: Math.round(position.y),
      }),
    )
    return true
  } catch {
    return false
  }
}
