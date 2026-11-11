import { useEffect, useState } from 'react'
import { useLocation } from 'react-router-dom'
import type { WeaknessItem } from '../../api/types'
import {
  COACH_COPY,
  WEAKNESS_FOLD_LIMIT,
  WEAKNESS_SORT_NOTE,
  blockStateOf,
  difficultyLabel,
  essentialityLabel,
  foldWeakness,
  weaknessCountLabel,
  weaknessAnchorIndex,
  weaknessRateLabel,
  weaknessRatePercent,
  weaknessSubDirectionLabel,
} from '../../lib/coach'
import { Card } from '../ui/Card'

export interface WeaknessMapProps {
  /** `null` = 旧报告（字段未落库）｜`[]` = 本次没有已计分题｜非空 = 正常渲染（三态**不可合并**）。 */
  items: WeaknessItem[] | null
}

/**
 * 区块 A · 知识薄弱地图（DESIGN r7 §2.1）。
 *
 * - 只投影后端算好的分组（前端零除法、零排序：`rate`/`avg` 与服务端 `.md` 同源，AC-12）；
 * - **错误率与「错 x / 共 y 题」永远同屏**：单独一个 62% 会被读成「整体水平」（反面目标 2 的防线）；
 * - 折叠是纯前端行为（后端不截断），默认 8 条，`aria-expanded` 与文案同步（AC-19）。
 */
export function WeaknessMap({ items }: WeaknessMapProps) {
  const [expanded, setExpanded] = useState(false)
  const [anchored, setAnchored] = useState<number | null>(null)
  const location = useLocation()
  const state = blockStateOf(items)

  // r79：太傅的引用可以带 `#weakness-N` 直接指到某一行。
  // 被引用的行可能落在折叠区，所以先展开再滚动 —— 否则「点进来什么都没有」。
  // 高亮用显式状态而不是只靠 `:target`：站内跳转是 pushState，浏览器不会重算 `:target`。
  useEffect(() => {
    const target = weaknessAnchorIndex(location.hash)
    setAnchored(target)
    if (target === null || items === null) return
    if (!expanded && target > WEAKNESS_FOLD_LIMIT) {
      setExpanded(true)
      return
    }
    const timer = window.setTimeout(() => {
      document.getElementById(`weakness-${target}`)?.scrollIntoView({ block: 'center' })
    }, 0)
    return () => window.clearTimeout(timer)
  }, [expanded, items, location.hash])

  if (state !== 'ready' || items === null) {
    return (
      <Card className="sc-coach-block">
        <div className="sc-coach-blockhead">
          <h3 className="sc-coach-blocktitle">知识薄弱地图</h3>
        </div>
        <p className="sc-coach-note">
          {state === 'legacy' ? COACH_COPY.legacy : COACH_COPY.weaknessEmpty}
        </p>
      </Card>
    )
  }

  const { visible, hiddenCount } = foldWeakness(items, expanded)
  const foldable = items.length > WEAKNESS_FOLD_LIMIT

  return (
    <Card className="sc-coach-block">
      <div className="sc-coach-blockhead">
        <h3 className="sc-coach-blocktitle">知识薄弱地图</h3>
        <p className="sc-coach-meta">{WEAKNESS_SORT_NOTE}</p>
      </div>

      <table className="sc-trend-table sc-weak-table" aria-label="知识薄弱地图">
        <thead>
          <tr>
            <th scope="col">#</th>
            <th scope="col">薄弱方向</th>
            <th scope="col">错误率</th>
          </tr>
        </thead>
        <tbody>
          {visible.map((item, index) => {
            const scopeLabel = weaknessSubDirectionLabel(item)
            return (
              <tr
                key={item.key}
                id={`weakness-${index + 1}`}
                className={anchored === index + 1 ? 'is-anchored' : undefined}
              >
                <td className="sc-mono">{index + 1}</td>
                <td>
                  <p className="sc-weak-name">{item.point}</p>
                  <p className="sc-weak-summary">{item.summary}</p>
                  <div className="sc-weak-line">
                    {scopeLabel !== null ? (
                      <span className="sc-chip" key="sub-direction">
                        {scopeLabel}
                      </span>
                    ) : null}
                    {item.difficulty.map((value) => (
                      <span className="sc-chip" key={`difficulty-${value}`}>
                        {difficultyLabel(value)}
                      </span>
                    ))}
                    {item.essentiality.map((value) => (
                      <span className="sc-chip" key={`essentiality-${value}`}>
                        {essentialityLabel(value)}
                      </span>
                    ))}
                  </div>
                  {item.samples.length > 0 ? (
                    <div className="sc-weak-line">
                      {item.samples.map((sample) => (
                        <span className="sc-chip" key={sample.question_id}>
                          {sample.evidence}
                        </span>
                      ))}
                    </div>
                  ) : null}
                  <p className="sc-weak-count sc-mono">
                    {weaknessCountLabel(item.wrong, item.total)}
                  </p>
                </td>
                <td>
                  {/* 横条只是错误率的可视化通道：读数（% 与「错 x / 共 y 题」）仍在同一行，不与数字脱钩。 */}
                  <div className="sc-weak-ratecell">
                    <span className="sc-weak-rate sc-mono">{weaknessRateLabel(item.rate)}</span>
                    <span className="sc-weak-bar" aria-hidden="true">
                      <span
                        className="sc-weak-bar-fill"
                        style={{ width: `${weaknessRatePercent(item.rate)}%` }}
                      />
                    </span>
                  </div>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>

      {foldable ? (
        <div className="sc-weak-line">
          <button
            type="button"
            className="sc-fold-toggle"
            aria-expanded={expanded}
            onClick={() => setExpanded((value) => !value)}
          >
            {expanded ? '收起' : `其余 ${hiddenCount} 条已折叠`}
          </button>
        </div>
      ) : null}
    </Card>
  )
}
