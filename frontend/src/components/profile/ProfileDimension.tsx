import { useState } from 'react'
import type { ReactNode } from 'react'
import { Button } from '../ui/Button'
import { Card } from '../ui/Card'
import { Chip } from '../ui/Chip'
import { InlineError } from '../ui/InlineError'

/** 画像 5 维度（顺序与 DESIGN §2.2 一致：技能 → 技术栈 → 年限 → 项目 → 目标岗位）。 */
export type ProfileDimensionKey = 'skills' | 'tech_stack' | 'years_experience' | 'projects' | 'target_role'

/** 单卡内的一条可视条目（技能 / 技术栈项 / 项目）。 */
export interface DimensionEntry {
  key: string
  title: string
  /** 项目用：角色 · 时间（12/16 --text-tertiary）。 */
  meta?: string
  /** 项目用：要点 2–3 条。 */
  bullets?: string[]
  /** 溯源片段；空/缺失 ⇒ 显式「缺失来源」错误条（anti-goal 1 不允许静默通过）。 */
  sourceQuote?: string | null
}

export interface ProfileDimensionProps {
  dimension: ProfileDimensionKey
  title: string
  /** 列表型维度（技能 / 技术栈 / 项目）的条目。 */
  entries?: DimensionEntry[]
  /** 单值型维度（工作年限 / 目标岗位）的值；null ⇒ 未填写。 */
  value?: string | null
  emptyHint: string
  /** 整维编辑入口：技术栈 / 年限 / 目标岗位这类「一维一值」字段。 */
  editable?: boolean
  /** 当前这一维是否处于编辑态：为真时正文整体换成编辑器。 */
  editing?: boolean
  editor?: ReactNode
  saving?: boolean
  onEdit?: () => void
  onEditEntry?: (entryKey: string) => void
  onDeleteEntry?: (entryKey: string) => void
}

function hasQuote(entry: DimensionEntry): boolean {
  return typeof entry.sourceQuote === 'string' && entry.sourceQuote.trim() !== ''
}

/**
 * 画像单维度卡（AC-2）：标题 + 条目 + 溯源引用 + 行内编辑入口。
 * 只收 props、不 import api（TECHNICAL §3.2-1）；样式只取 base.css 已注册的
 * `.sc-profile-dim` / `.sc-profile-dim-head` / `.sc-source-quote` / `.sc-chips` / `.sc-btn-row` / `.sc-meta-line`。
 */
export function ProfileDimension({
  dimension,
  title,
  entries = [],
  value = null,
  emptyHint,
  editable = false,
  editing = false,
  editor = null,
  saving = false,
  onEdit,
  onEditEntry,
  onDeleteEntry,
}: ProfileDimensionProps) {
  // 溯源默认收起，点条目展开（DESIGN §2.2「点 chip 展开 sourceQuote」）。
  const [expandedKey, setExpandedKey] = useState<string | null>(null)

  const quoted = entries.filter(hasQuote).length
  const missing = entries.filter((entry) => !hasQuote(entry)).length
  const isSingle = dimension === 'years_experience' || dimension === 'target_role'
  const footer = isSingle
    ? (value === null ? '未填写' : '已确认')
    : `来源 ${quoted} 条${missing > 0 ? ` · 缺失来源 ${missing} 条` : ''}`

  const toggleEntry = (entryKey: string) => {
    setExpandedKey((current) => (current === entryKey ? null : entryKey))
  }

  /** 技能详情（简历原文 + 编辑/删除）在标签行下方独占整行，避免窄列里被挤成竖条。 */
  const expandedEntry = entries.find((entry) => entry.key === expandedKey) ?? null

  const editorIfEditing = editing ? editor : null

  return (
    <Card className="sc-profile-dim">
      <div className="sc-profile-dim-head">
        <h2>{title}</h2>
        {editable && !editing ? (
          <Button variant="ghost" onClick={onEdit} disabled={saving}>
            编辑
          </Button>
        ) : null}
      </div>

      {editorIfEditing ??
        (dimension === 'skills' ? (
          entries.length === 0 ? (
            <p className="sc-meta-line">{emptyHint}</p>
          ) : (
            <>
              <div className="sc-lab-skills" role="group" aria-label={title}>
                {entries.map((entry) => {
                  const open = expandedKey === entry.key
                  const quoted = hasQuote(entry)
                  const classes = ['sc-lab-skill']
                  if (open) classes.push('is-open')
                  if (!quoted) classes.push('is-missing')
                  return (
                    <button
                      key={entry.key}
                      type="button"
                      className={classes.join(' ')}
                      aria-expanded={open}
                      onClick={() => toggleEntry(entry.key)}
                    >
                      <span className="sc-lab-skill-mark" aria-hidden="true" />
                      <span className="sc-lab-skill-name">{entry.title}</span>
                      <span className="sc-lab-skill-cue" aria-hidden="true">
                        {open ? '−' : '+'}
                      </span>
                    </button>
                  )
                })}
              </div>

              {expandedEntry !== null ? (
                <div className="sc-source-quote sc-lab-skill-detail">
                  <span className="sc-source-quote-label">{`简历原文 · ${expandedEntry.title}`}</span>
                  {hasQuote(expandedEntry) ? (
                    <p>{expandedEntry.sourceQuote}</p>
                  ) : (
                    <InlineError message="缺失来源：该条无法溯源，建议删除或补充原文" />
                  )}
                  <div className="sc-btn-row">
                    {onEditEntry ? (
                      <Button
                        variant="ghost"
                        onClick={() => onEditEntry(expandedEntry.key)}
                        disabled={saving}
                      >
                        编辑
                      </Button>
                    ) : null}
                    {onDeleteEntry ? (
                      <Button
                        variant="ghost"
                        onClick={() => onDeleteEntry(expandedEntry.key)}
                        disabled={saving}
                      >
                        删除
                      </Button>
                    ) : null}
                  </div>
                </div>
              ) : null}
            </>
          )
        ) : dimension === 'tech_stack' ? (
          entries.length === 0 ? (
            <p className="sc-meta-line">{emptyHint}</p>
          ) : (
            <div className="sc-chips" aria-label={title}>
              {entries.map((entry) => (
                <Chip key={entry.key} label={entry.title} />
              ))}
            </div>
          )
        ) : dimension === 'projects' ? (
          entries.length === 0 ? (
            <p className="sc-meta-line">{emptyHint}</p>
          ) : (
            <div aria-label={title}>
              {entries.map((entry) => (
                <div key={entry.key}>
                  <h3>{entry.title}</h3>
                  {entry.meta ? <span className="sc-meta-line">{entry.meta}</span> : null}
                  {entry.bullets && entry.bullets.length > 0 ? (
                    <ul>
                      {entry.bullets.map((bullet, slot) => (
                        <li key={`${entry.key}-b${slot}`}>{bullet}</li>
                      ))}
                    </ul>
                  ) : null}

                  {!hasQuote(entry) ? (
                    <InlineError message="缺失来源：该条无法溯源，建议删除或补充原文" />
                  ) : null}

                  <div className="sc-btn-row">
                    {hasQuote(entry) ? (
                      <Button variant="ghost" onClick={() => toggleEntry(entry.key)}>
                        {expandedKey === entry.key ? '收起原文' : '简历原文'}
                      </Button>
                    ) : null}
                    {onEditEntry ? (
                      <Button variant="ghost" onClick={() => onEditEntry(entry.key)} disabled={saving}>
                        编辑
                      </Button>
                    ) : null}
                    {onDeleteEntry ? (
                      <Button variant="ghost" onClick={() => onDeleteEntry(entry.key)} disabled={saving}>
                        删除
                      </Button>
                    ) : null}
                  </div>

                  {hasQuote(entry) && expandedKey === entry.key ? (
                    <div className="sc-source-quote">
                      <span className="sc-source-quote-label">简历原文</span>
                      <p>{entry.sourceQuote}</p>
                    </div>
                  ) : null}
                </div>
              ))}
            </div>
          )
        ) : (
          <p className={value === null ? 'sc-meta-line' : undefined}>{value ?? emptyHint}</p>
        ))}

      {!editing ? <span className="sc-meta-line">{footer}</span> : null}
    </Card>
  )
}
