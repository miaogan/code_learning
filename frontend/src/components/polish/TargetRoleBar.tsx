import { Button } from '../ui/Button'

export interface TargetRoleBarProps {
  value: string
  defaultRole: string | null
  busy: boolean
  onChange: (value: string) => void
  onApply: () => void
  onReset: () => void
}

const MAX_ROLE_LEN = 40

/** 目标岗位条：行高 40。临时岗位只用于本次调用，画像 `target_role` 全程不变（AC-12）。 */
export function TargetRoleBar({
  value,
  defaultRole,
  busy,
  onChange,
  onApply,
  onReset,
}: TargetRoleBarProps) {
  const trimmed = value.trim()
  const isTemporary = trimmed !== '' && trimmed !== (defaultRole ?? '').trim()
  const inputId = 'sc-target-role-input'

  return (
    <div className="sc-target-role">
      <div className="sc-target-role-main">
        <label className="sc-target-role-label" htmlFor={inputId}>
          目标岗位
        </label>
        <input
          id={inputId}
          className="sc-target-role-input"
          type="text"
          value={value}
          maxLength={MAX_ROLE_LEN}
          disabled={busy}
          placeholder={defaultRole ?? '例如：前端工程师'}
          aria-describedby="sc-target-role-hint"
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !busy) {
              event.preventDefault()
              onApply()
            }
          }}
        />
        {isTemporary ? (
          <span className="sc-chip sc-target-role-chip is-temp">临时</span>
        ) : trimmed !== '' ? (
          <span className="sc-chip sc-target-role-chip">默认</span>
        ) : null}
        <Button variant="secondary" onClick={onApply} disabled={busy}>
          按此岗位重跑
        </Button>
        <Button variant="ghost" onClick={onReset} disabled={busy || defaultRole === null}>
          恢复默认
        </Button>
      </div>
      <p className="sc-target-role-hint" id="sc-target-role-hint">
        {busy
          ? '正在按该岗位重跑建议，画像里的目标岗位不会被改动'
          : '临时岗位只用于本次，画像里的目标岗位不会被改动'}
      </p>
    </div>
  )
}
