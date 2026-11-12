import { Link } from 'react-router-dom'
import { Button } from './Button'

export interface EmptyStateProps {
  /** 空态必须带原因句（DESIGN §0.6：禁止只写「暂无数据」） */
  reason: string
  actionLabel: string
  actionTo?: string
  onAction?: () => void
  /** r84 §1：可选的 1–3 条「现在能做什么」步骤，把大空白变成引导卡。 */
  hints?: readonly string[]
  /** r84 §1：可选的次级入口（Link 文案 + 路由），与主按钮并列。 */
  altLabel?: string
  altTo?: string
}

/** 空态：图标 + 原因句 + 主按钮（+ 次级入口 / 步骤提示）。用 Link 复用按钮样式，避免按钮嵌套按钮。 */
export function EmptyState({ reason, actionLabel, actionTo, onAction, hints, altLabel, altTo }: EmptyStateProps) {
  const hasHints = hints !== undefined && hints.length > 0
  return (
    <div className="sc-empty">
      <span className="sc-empty-icon" aria-hidden="true">
        ◇
      </span>
      <p className="sc-empty-reason">{reason}</p>
      {hasHints ? (
        <ul className="sc-empty-hints">
          {hints.map((hint) => (
            <li key={hint}>{`▸ ${hint}`}</li>
          ))}
        </ul>
      ) : null}
      <div className="sc-empty-action">
        {actionTo ? (
          <Link className="sc-btn sc-btn--primary" to={actionTo}>
            {actionLabel}
          </Link>
        ) : (
          <Button onClick={onAction}>{actionLabel}</Button>
        )}
        {altLabel !== undefined && altTo !== undefined ? (
          <Link className="sc-btn sc-btn--ghost" to={altTo}>
            {altLabel}
          </Link>
        ) : null}
      </div>
    </div>
  )
}
