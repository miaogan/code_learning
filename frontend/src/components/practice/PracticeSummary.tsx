import { accuracyText } from '../../lib/practice'
import { Button } from '../ui/Button'
import { Card } from '../ui/Card'

export interface PracticeSummaryProps {
  /** 本轮题数 */
  total: number
  /** 本轮答对数 */
  correct: number
  /** 全库错题数（tab 角标与「去错题本 N」同源，来自服务端统计） */
  wrongCount: number
  /** 本次筛选的可读描述（由 `lib/practice.ts:filtersLabel` 产出，组件不拼文案） */
  filtersLabel: string
  onWrongBook: () => void
  onAgain: () => void
  onReset: () => void
}

/**
 * 完成态（r11 · DESIGN §2.4）：正确率大数 + 一句说明 + 三个出口。
 *
 * 正确率用等宽 32/40 的数字（换轮次不跳动）；0 题时显示「—」而不是 `NaN%`。
 * 三个出口的语义固定：去错题本（secondary）/ 再来一轮（primary，沿用当前筛选）/ 回到筛选（ghost）。
 */
export function PracticeSummary({
  total,
  correct,
  wrongCount,
  filtersLabel,
  onWrongBook,
  onAgain,
  onReset,
}: PracticeSummaryProps) {
  const rate = accuracyText(correct, total)
  const hasRate = rate !== '—'

  return (
    <Card className="sc-qa-summary">
      <h2 className="sc-qa-summary-title">本轮完成</h2>
      <p className="sc-qa-rate">
        {hasRate ? (
          <>
            {rate.replace('%', '')}
            <span className="sc-qa-rate-unit">%</span>
          </>
        ) : (
          '—'
        )}
      </p>
      <p className="sc-qa-summary-line">
        {total > 0
          ? `本轮 ${total} 题，答对 ${correct} 道 · 本次筛选：${filtersLabel}`
          : '本轮没有作答记录'}
      </p>
      <div className="sc-qa-split" />
      <div className="sc-qa-summary-actions">
        <Button variant="secondary" onClick={onWrongBook}>
          {`去错题本 ${wrongCount}`}
        </Button>
        <Button variant="primary" onClick={onAgain}>
          再来一轮
        </Button>
        <Button variant="ghost" onClick={onReset}>
          回到筛选
        </Button>
      </div>
    </Card>
  )
}
