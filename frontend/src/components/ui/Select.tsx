import { useEffect, useId, useRef, useState } from 'react'

export interface SelectOption {
  /** 与原生 select 一致：value 统一是字符串，页面侧自行做数字转换。 */
  value: string
  label: string
}

export interface SelectProps {
  options: SelectOption[]
  value: string
  onChange: (value: string) => void
  disabled?: boolean
  /** 无包裹 label 时（如工具行里的紧凑下拉）提供可访问名称。 */
  ariaLabel?: string
  id?: string
  /** standard = 40px 表单/筛选触发器；compact = 32px 清单工具行触发器。 */
  variant?: 'standard' | 'compact'
}

/**
 * 窄屏与触屏判定：系统选择器在手机上是底部弹层，体验优于任何自绘弹层，
 * 也免去弹层定位问题；桌面浏览器原生弹层无法跟随深色主题，才走自绘。
 */
const NATIVE_QUERY = '(max-width: 640px), (pointer: coarse)'

function usePrefersNativeSelect(): boolean {
  const [native, setNative] = useState(() =>
    typeof window !== 'undefined' &&
    typeof window.matchMedia === 'function'
      ? window.matchMedia(NATIVE_QUERY).matches
      : false,
  )

  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return
    const media = window.matchMedia(NATIVE_QUERY)
    const listener = (event: MediaQueryListEvent): void => setNative(event.matches)
    media.addEventListener('change', listener)
    return () => media.removeEventListener('change', listener)
  }, [])

  return native
}

/**
 * 自绘单选下拉：只替换「弹层」这一层，替换原因是 Windows Chromium 的原生
 * 弹层跟随系统浅色主题，页面级 `color-scheme: dark` 与 option 上色都管不到
 * （2026-11 实测），在深色页面里是一块白底。交互契约保持与原生 select 一致：
 * value/onChange 都是字符串；键盘 ↑↓/Home/End/Enter/Space/Esc/Tab 全覆盖；
 * listbox 语义用 role + aria-activedescendant 表达，焦点始终留在触发按钮上。
 */
export function Select({
  options,
  value,
  onChange,
  disabled = false,
  ariaLabel,
  id,
  variant = 'standard',
}: SelectProps) {
  const prefersNative = usePrefersNativeSelect()
  const reactId = useId()
  const listId = `${reactId}-listbox`
  const wrapRef = useRef<HTMLDivElement | null>(null)
  const listRef = useRef<HTMLUListElement | null>(null)
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(0)
  const [dropUp, setDropUp] = useState(false)

  const selectedIndex = Math.max(
    0,
    options.findIndex((option) => option.value === value),
  )

  useEffect(() => {
    if (!open) return
    const onPointerDown = (event: PointerEvent): void => {
      if (wrapRef.current !== null && !wrapRef.current.contains(event.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('pointerdown', onPointerDown)
    return () => document.removeEventListener('pointerdown', onPointerDown)
  }, [open])

  useEffect(() => {
    if (!open) return
    const node = listRef.current?.children[active]
    if (node instanceof HTMLElement) node.scrollIntoView({ block: 'nearest' })
  }, [open, active])

  if (prefersNative) {
    return (
      <select
        id={id}
        className={variant === 'compact' ? 'sc-radar-select' : 'sc-filter-select'}
        value={value}
        disabled={disabled}
        aria-label={ariaLabel}
        onChange={(event) => onChange(event.target.value)}
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    )
  }

  const openPopup = (): void => {
    setActive(selectedIndex)
    const rect = wrapRef.current?.getBoundingClientRect()
    if (rect !== undefined) {
      const spaceBelow = window.innerHeight - rect.bottom
      setDropUp(spaceBelow < 320 && rect.top > spaceBelow)
    }
    setOpen(true)
  }

  const choose = (next: string): void => {
    onChange(next)
    setOpen(false)
  }

  const onKeyDown = (event: React.KeyboardEvent<HTMLButtonElement>): void => {
    if (!open) {
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp' || event.key === 'Enter' || event.key === ' ') {
        event.preventDefault()
        openPopup()
      }
      return
    }
    switch (event.key) {
      case 'ArrowDown':
        event.preventDefault()
        setActive((index) => Math.min(options.length - 1, index + 1))
        break
      case 'ArrowUp':
        event.preventDefault()
        setActive((index) => Math.max(0, index - 1))
        break
      case 'Home':
        event.preventDefault()
        setActive(0)
        break
      case 'End':
        event.preventDefault()
        setActive(options.length - 1)
        break
      case 'Enter':
      case ' ':
        event.preventDefault()
        choose(options[active].value)
        break
      case 'Escape':
        event.preventDefault()
        setOpen(false)
        break
      case 'Tab':
        setOpen(false)
        break
    }
  }

  const triggerClass = variant === 'compact' ? 'sc-radar-select' : 'sc-filter-select'

  return (
    <div className="sc-select" ref={wrapRef}>
      <button
        type="button"
        id={id}
        className={`sc-select-trigger ${triggerClass}`}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={ariaLabel}
        disabled={disabled}
        onClick={() => (open ? setOpen(false) : openPopup())}
        onKeyDown={onKeyDown}
      >
        <span className="sc-select-value">{options[selectedIndex]?.label ?? ''}</span>
      </button>
      {open && (
        <ul
          ref={listRef}
          id={listId}
          className={`sc-select-popup${dropUp ? ' is-up' : ''}`}
          role="listbox"
          aria-label={ariaLabel}
          tabIndex={-1}
          aria-activedescendant={`${listId}-opt-${active}`}
        >
          {options.map((option, index) => {
            const selected = option.value === value
            return (
              <li
                key={option.value}
                id={`${listId}-opt-${index}`}
                role="option"
                aria-selected={selected}
                className={`sc-select-option${index === active ? ' is-active' : ''}${selected ? ' is-selected' : ''}`}
                onPointerMove={() => setActive(index)}
                onClick={() => choose(option.value)}
              >
                <span className="sc-select-option-label">{option.label}</span>
                {selected && (
                  <span className="sc-select-option-check" aria-hidden="true">
                    ✓
                  </span>
                )}
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
