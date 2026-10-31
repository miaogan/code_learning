import type { MouseEventHandler, ReactNode } from 'react'

export interface ChipProps {
  label: ReactNode
  tone?: 'default' | 'direction'
  onClick?: MouseEventHandler<HTMLButtonElement>
}

/** 标签 chip：高 24 / 圆角 4 / 12-16 500。可点击时用按钮元素以保留键盘可达。 */
export function Chip({ label, tone = 'default', onClick }: ChipProps) {
  const classes = ['sc-chip']
  if (tone === 'direction') classes.push('sc-chip--direction')

  if (onClick) {
    classes.push('is-clickable')
    return (
      <button type="button" className={classes.join(' ')} onClick={onClick}>
        {label}
      </button>
    )
  }
  return <span className={classes.join(' ')}>{label}</span>
}
