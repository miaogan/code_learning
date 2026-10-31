import { Button } from './Button'

export interface InlineErrorProps {
  message: string
  onRetry?: () => void
  retryLabel?: string
}

/** 页内错误条：左 2px 危险色 + 中文原因 + 重试（DESIGN §0.6，禁止整页白屏 / 只用 Toast）。 */
export function InlineError({ message, onRetry, retryLabel = '重试' }: InlineErrorProps) {
  return (
    <div className="sc-inline-error" role="alert">
      <span aria-hidden="true">!</span>
      <span className="sc-inline-error-msg">{message}</span>
      {onRetry ? (
        <Button variant="secondary" size="sm" onClick={onRetry}>
          {retryLabel}
        </Button>
      ) : null}
    </div>
  )
}
