import { useState } from 'react'

export interface EvidenceChipProps {
  /** 后端给出的证据文案，已含题号与得分（如「Q3 · 4/10」） */
  evidence: string
  /** 该证据指向的题目 id；null 表示未能定位到具体题目 */
  questionRef: string | null
}

/**
 * 证据 chip（高 24、等宽、tabular）：短板唯一展示证据的位置（AC-5「题目 id 可溯源」）。
 * 报告契约只携带 `evidence` + `question_ref`（不含题干正文），所以点开给的是「出处」而不是复核气泡；
 * 题号与得分一律以文字呈现，颜色永不单独承载信息（DESIGN §0.8）。
 */
export function EvidenceChip({ evidence, questionRef }: EvidenceChipProps) {
  const [expanded, setExpanded] = useState(false)

  // 无出处时不做成按钮：没有可展开内容，按钮只会让键盘用户空转
  if (questionRef === null) {
    return (
      <span className="sc-evidence-chip" title="未能定位到具体题目，仅保留得分证据">
        {evidence}
      </span>
    )
  }

  const classes = ['sc-evidence-chip']
  if (expanded) classes.push('is-expanded')

  return (
    <button
      type="button"
      className={classes.join(' ')}
      title={`来源题目 ${questionRef}`}
      aria-expanded={expanded}
      onClick={() => setExpanded((value) => !value)}
    >
      {evidence}
      <span>{expanded ? `题目 ${questionRef}` : '出处'}</span>
    </button>
  )
}
