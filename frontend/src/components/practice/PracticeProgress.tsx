import { accuracyText } from '../../lib/practice'

export interface PracticeProgressProps {
  /** 当前第几题（1 基；0 表示尚未开题，仅空态会出现） */
  index: number
  /** 本轮题数 N */
  total: number
  /** 本轮答对数 */
  correct: number
  /** 本轮已答数（进度轨分子，不是题号） */
  answered: number
}

/**
 * 本次进度（r11 · AC-18）：`第 i / N 题` + `正确 n · 正确率 p%` + 6px 进度轨。
 *
 * 三条几何/语义约束（DESIGN §0.7-2、§0.2）：
 * 1. 进度轨内**不承载任何文字**（6px 形体内塞字必然溢出）；
 * 2. 正确率分母是「已答数」而非总题数，0 已答时只显示「正确 0」；
 * 3. 数字全走等宽 + `tabular-nums`（换题不跳列）。
 */
export function PracticeProgress({ index, total, correct, answered }: PracticeProgressProps) {
  const safeTotal = Math.max(0, total)
  const done = Math.min(Math.max(0, answered), safeTotal)
  const percent = safeTotal > 0 ? Math.round((done / safeTotal) * 100) : 0
  const scoreText =
    done > 0 ? `正确 ${correct} · 正确率 ${accuracyText(correct, done)}` : `正确 ${correct}`

  return (
    <div className="sc-qa-progress-block">
      <div className="sc-qa-progress">
        <span className="sc-mono sc-qa-pos">{`第 ${index} / ${total} 题`}</span>
        <span className="sc-mono sc-qa-score">{scoreText}</span>
      </div>
      <div
        className="sc-qa-track"
        role="progressbar"
        aria-label="本轮进度"
        aria-valuemin={0}
        aria-valuemax={safeTotal}
        aria-valuenow={done}
        // QA D4：`valuenow/valuemax` 单独朗读会被读成「4」（而非 40%），补一句人人可读的进度文案。
        aria-valuetext={`已完成 ${done} / ${safeTotal} 题（${percent}%）`}
      >
        <div className="sc-qa-track-fill" style={{ width: `${percent}%` }} />
      </div>
    </div>
  )
}
