import { Link } from 'react-router-dom'
import { Button } from './Button'

export interface EmptyStateProps {
  /** 空态必须带原因句（DESIGN §0.6：禁止只写「暂无数据」） */
  reason: string
  actionLabel: string
  actionTo?: string
  onAction?: () => void
}

/** 空态：图标 + 原因句 + 一个主按钮。用 Link 复用按钮样式，避免按钮嵌套按钮。 */
export function EmptyState({ reason, actionLabel, actionTo, onAction }: EmptyStateProps) {
  return (
    <div className="sc-empty">
      <span className="sc-empty-icon" aria-hidden="true">
        ◇
      </span>
      <p className="sc-empty-reason">{reason}</p>
      <div className="sc-empty-action">
        {actionTo ? (
          <Link className="sc-btn sc-btn--primary" to={actionTo}>
            {actionLabel}
          </Link>
        ) : (
          <Button onClick={onAction}>{actionLabel}</Button>
        )}
      </div>
    </div>
  )
}
