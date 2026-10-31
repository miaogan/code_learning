import type { ButtonHTMLAttributes, ReactNode } from 'react'

type Variant = 'primary' | 'secondary' | 'ghost'
type Size = 'sm' | 'md' | 'hero'

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  size?: Size
  loading?: boolean
  children: ReactNode
}

/** 主/次/幽灵按钮，高 40（DESIGN §0.5 / §0.7 第 5 条），焦点环不渐入。 */
export function Button({
  variant = 'primary',
  size = 'md',
  loading = false,
  className,
  children,
  disabled,
  ...rest
}: ButtonProps) {
  const classes = ['sc-btn', `sc-btn--${variant}`]
  if (size === 'sm') classes.push('is-sm')
  if (size === 'hero') classes.push('is-hero')
  if (loading) classes.push('is-loading')
  if (className) classes.push(className)

  return (
    <button
      {...rest}
      className={classes.join(' ')}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
    >
      {loading ? <span className="sc-spinner" aria-hidden="true" /> : null}
      {children}
    </button>
  )
}
