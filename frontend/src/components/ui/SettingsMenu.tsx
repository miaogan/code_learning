import { useEffect, useRef, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { isRouteActive } from '../../lib/navGroups'
import type { ToolNavItem } from './ToolNav'

export interface SettingsMenuProps {
  items: ToolNavItem[]
}

/**
 * 顶栏「设置」下拉（r127）：全站唯一一个下拉菜单——设置组只有 3 项，
 * 平铺进顶栏会挤占工具导航的宽度，收进下拉既省地又符合「低频项收起」惯例。
 *
 * 交互刻意保持最简（上一代级联浮层的教训）：
 * - 只有**点击**开合（不做 hover 触发）；点击条目跳转后自动收；
 * - 点击面板外 / 按 Escape 收起；当前页所在条目高亮。
 */
export function SettingsMenu({ items }: SettingsMenuProps) {
  const [open, setOpen] = useState(false)
  const wrapperRef = useRef<HTMLDivElement | null>(null)
  const { pathname } = useLocation()

  // 点击面板外 / Escape 收起（仅在展开期间挂监听）。
  useEffect(() => {
    if (!open) return
    const onDocPointerDown = (event: PointerEvent): void => {
      if (wrapperRef.current && !wrapperRef.current.contains(event.target as Node)) {
        setOpen(false)
      }
    }
    const onKeyDown = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('pointerdown', onDocPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('pointerdown', onDocPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [open])

  const active = items.some((item) => isRouteActive(pathname, item.to))

  return (
    <div className="sc-settings-menu" ref={wrapperRef}>
      <button
        type="button"
        className={active ? 'sc-settings-menu-btn is-active' : 'sc-settings-menu-btn'}
        onClick={() => setOpen((prev) => !prev)}
        aria-expanded={open}
        aria-haspopup="true"
      >
        设置
        <span aria-hidden="true">{open ? '▾' : '▸'}</span>
      </button>
      {open ? (
        <div className="sc-settings-menu-panel">
          {items.map((item) => (
            <Link
              key={item.key}
              to={item.to}
              className={isRouteActive(pathname, item.to) ? 'sc-settings-menu-item is-active' : 'sc-settings-menu-item'}
              aria-current={isRouteActive(pathname, item.to) ? 'page' : undefined}
              onClick={() => setOpen(false)}
            >
              {item.label}
            </Link>
          ))}
        </div>
      ) : null}
    </div>
  )
}
