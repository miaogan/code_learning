import { useState } from 'react'
import type { Evidence } from '../../api/types'
import { evidenceSourceLine, visibleEvidence } from './evidenceModel'

export interface EvidenceListProps {
  /** 旧→新累积的证据（服务端顺序即「旧→新」；页面不重排、不二次计算）。 */
  evidence: Evidence[]
  /** 折叠条文案覆盖；缺省按条数生成「证据 N 条 · 旧→新」。 */
  label?: string
}

/**
 * 多证据折叠（AC-6 的可视证据链，DESIGN §3 `EvidenceList`）：
 * 技能与项目两处复用；**顺序与条数只取服务端**（前端禁二次排序，避免与 profile_merge 口径分叉）。
 * 不降对比度表达「历史」——历史态由调用方在条目侧用徽章区分，本组件只管证据。
 */
export function EvidenceList({ evidence, label }: EvidenceListProps) {
  const [expanded, setExpanded] = useState(false)
  const list = visibleEvidence(evidence)
  if (list.length === 0) return null

  const toggleLabel = label ?? `证据 ${list.length} 条 · 旧→新`

  return (
    <div>
      <button
        type="button"
        className={expanded ? 'sc-evidence-chip is-expanded' : 'sc-evidence-chip'}
        aria-expanded={expanded}
        onClick={() => setExpanded((current) => !current)}
      >
        <span>{toggleLabel}</span>
        <span aria-hidden="true">{expanded ? '▾' : '▸'}</span>
      </button>

      {expanded ? (
        <div className="sc-evidence-list">
          {list.map((item, index) => (
            <div key={`${item.resume_id}#${index}`} className="sc-evidence-item">
              <div className="sc-source-quote">
                <span className="sc-source-quote-label">{evidenceSourceLine(item)}</span>
                <p>{item.quote}</p>
              </div>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  )
}
