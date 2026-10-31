import type { ReactNode } from 'react'

export interface CardProps {
  children: ReactNode
  interactive?: boolean
  active?: boolean
  className?: string
}

/** 卡片：圆角 12 / padding 20 / 1px 边框 + 内嵌高光（DESIGN §0.2 禁纯平方砖）。 */
export function Card({ children, interactive = false, active = false, className }: CardProps) {
  const classes = ['sc-card']
  if (interactive) classes.push('is-interactive')
  if (active) classes.push('is-active')
  if (className) classes.push(className)
  return <div className={classes.join(' ')}>{children}</div>
}
