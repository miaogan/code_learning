import { useId, useState } from 'react'
import type { KeyboardEvent } from 'react'
import { Button } from '../ui/Button'
import { InlineError } from '../ui/InlineError'

/** 行内编辑的字段类型：单行文本 / 数字 / 多行文本。 */
export type EditorFieldKind = 'text' | 'number' | 'textarea'

export interface EditorField {
  /** 与 `ProfilePatch` 的字段名同名，保存时直接映射回 patch（不做二次改名）。 */
  key: string
  label: string
  kind: EditorFieldKind
  value: string
  placeholder?: string
}

export interface ProfileEditorProps {
  fields: EditorField[]
  /** 保存中：按钮 disabled + 主按钮内嵌 spinner。 */
  saving: boolean
  /** 保存失败：错误条留在编辑态里，草稿不清空（可原地重试）。 */
  error?: string | null
  onSave: (values: Record<string, string>) => void
  onCancel: () => void
  saveLabel?: string
}

function initialDraft(fields: EditorField[]): Record<string, string> {
  const draft: Record<string, string> = {}
  for (const field of fields) draft[field.key] = field.value
  return draft
}

/** 数字字段只放行数字与小数点，避免「12abc」这种值把页码/年限写成 null。 */
function sanitizeNumber(input: string): string {
  return input.replace(/[^0-9.]/g, '').replace(/(.*\..*)\./g, '$1')
}

/**
 * 行内编辑器（DESIGN §2.2「点字段 → 原地输入 → Enter 保存」，TECHNICAL §3.2 的 textarea + 保存/取消）。
 * 纯受控组件：只收 props 与回调，不 import api（硬规则 §3.2-1）。
 * 保存语义由调用方决定：本组件只负责草稿与快捷键，草稿在失败时保留。
 */
export function ProfileEditor({
  fields,
  saving,
  error = null,
  onSave,
  onCancel,
  saveLabel = '保存',
}: ProfileEditorProps) {
  const baseId = useId()
  const [draft, setDraft] = useState<Record<string, string>>(() => initialDraft(fields))

  const update = (key: string, kind: EditorFieldKind, raw: string) => {
    setDraft((current) => ({ ...current, [key]: kind === 'number' ? sanitizeNumber(raw) : raw }))
  }

  const submit = () => {
    if (saving) return
    onSave(draft)
  }

  const handleKeyDown = (event: KeyboardEvent<HTMLInputElement | HTMLTextAreaElement>, kind: EditorFieldKind) => {
    if (event.key === 'Escape') {
      event.preventDefault()
      if (!saving) onCancel()
      return
    }
    if (event.key !== 'Enter') return
    // 多行字段的 Enter 是换行；Ctrl/Cmd+Enter 才保存（避免长文本误提交）。
    if (kind === 'textarea' && !(event.metaKey || event.ctrlKey)) return
    event.preventDefault()
    submit()
  }

  return (
    <div className="sc-edit-row">
      {fields.map((field, index) => {
        const fieldId = `${baseId}-${index}`
        const value = draft[field.key] ?? ''
        return (
          <div key={field.key}>
            <label className="sc-meta-line" htmlFor={fieldId}>
              {field.label}
            </label>
            {field.kind === 'textarea' ? (
              <textarea
                id={fieldId}
                value={value}
                placeholder={field.placeholder}
                disabled={saving}
                aria-busy={saving}
                onChange={(event) => update(field.key, field.kind, event.target.value)}
                onKeyDown={(event) => handleKeyDown(event, field.kind)}
              />
            ) : (
              <input
                id={fieldId}
                type="text"
                inputMode={field.kind === 'number' ? 'decimal' : undefined}
                value={value}
                placeholder={field.placeholder}
                disabled={saving}
                aria-busy={saving}
                onChange={(event) => update(field.key, field.kind, event.target.value)}
                onKeyDown={(event) => handleKeyDown(event, field.kind)}
              />
            )}
          </div>
        )
      })}

      {error ? <InlineError message={error} /> : null}

      <div className="sc-btn-row">
        <Button onClick={submit} loading={saving} disabled={saving}>
          {saveLabel}
        </Button>
        <Button variant="secondary" onClick={onCancel} disabled={saving}>
          取消
        </Button>
      </div>
    </div>
  )
}
