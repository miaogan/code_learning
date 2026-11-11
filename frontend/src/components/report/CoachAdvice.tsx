import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, api } from '../../api/client'
import type { CoachAdvice as CoachAdviceData, Report } from '../../api/types'
import { buildCoachMaterials, coachFocusOf, coachGoalOf } from '../../lib/coachMaterials'
import { Button } from '../ui/Button'
import { Card } from '../ui/Card'
import { InlineError } from '../ui/InlineError'

/** 一次建议要花一次 AI 调用：按报告缓存到会话里，来回翻页不重复付费。 */
const CACHE_PREFIX = 'coach:advice:'

function readCache(reportId: string): CoachAdviceData | null {
  try {
    const raw = window.sessionStorage.getItem(`${CACHE_PREFIX}${reportId}`)
    if (!raw) return null
    const parsed = JSON.parse(raw) as CoachAdviceData
    return Array.isArray(parsed?.blocks) ? parsed : null
  } catch {
    return null
  }
}

function writeCache(reportId: string, advice: CoachAdviceData): void {
  try {
    window.sessionStorage.setItem(`${CACHE_PREFIX}${reportId}`, JSON.stringify(advice))
  } catch {
    // 缓存失败不影响已展示的建议：下一次生成会重新调用模型。
  }
}

export interface CoachAdviceProps {
  report: Report
}

/**
 * r65「AI 学习教练」（检索增强 + 引用白名单）。
 *
 * 材料来自报告薄弱方向 + 站内教程检索（`lib/coachMaterials.ts`）；服务端会把模型给出的
 * href 与材料逐字比对，不可核对的建议直接丢弃并计数——所以这里能诚实地展示
 * 「材料 N 条 / 丢弃 M 条无依据引用」，而不是把幻觉链接当教程入口渲染出来。
 */
export function CoachAdvice({ report }: CoachAdviceProps) {
  const materials = useMemo(() => buildCoachMaterials(report), [report])
  const focus = useMemo(() => coachFocusOf(report), [report])
  const goal = useMemo(() => coachGoalOf(report), [report])
  const [advice, setAdvice] = useState<CoachAdviceData | null>(() => readCache(report.id))
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  async function generate(): Promise<void> {
    setLoading(true)
    setError('')
    try {
      const result = await api.coachAdvice({ materials, focus, goal })
      setAdvice(result)
      // 只有真的产出可核对建议才缓存：空建议不值得占一格会话存储。
      if (result.blocks.length > 0) writeCache(report.id, result)
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : '生成学习建议失败，请稍后重试'
      )
    } finally {
      setLoading(false)
    }
  }

  const noMaterials = materials.length === 0

  return (
    <Card className="sc-coach">
      <div className="sc-coach-head">
        <div>
          <p className="sc-coach-kicker">AI COACH</p>
          <h3 className="sc-coach-title">学习教练</h3>
        </div>
        <p className="sc-coach-note">
          {noMaterials
            ? '需要一份含薄弱方向的医案，才能检索出可引用的站内材料。'
            : `本次上传 ${materials.length} 条站内材料；建议里的链接必须逐字来自这些材料，服务端会逐条校验。`}
        </p>
      </div>

      {noMaterials ? (
        <p className="sc-coach-hint">
          先去科考或召对拿到计分结果，报告里有了薄弱方向后再回来。
        </p>
      ) : (
        <>
          {error ? (
            <InlineError message={error} onRetry={() => void generate()} retryLabel="重新生成" />
          ) : null}

          {advice ? (
            <div className="sc-coach-result" aria-live="polite">
              {advice.summary ? <p className="sc-coach-summary">{advice.summary}</p> : null}
              {advice.blocks.length > 0 ? (
                <ol className="sc-coach-blocks">
                  {advice.blocks.map((block) => (
                    <li className="sc-coach-block" key={block.title}>
                      <p className="sc-coach-block-title">{block.title}</p>
                      {block.reason ? (
                        <p className="sc-coach-block-reason">{block.reason}</p>
                      ) : null}
                      <ul className="sc-coach-actions">
                        {block.actions.map((action) => (
                          <li className="sc-coach-action" key={`${block.title}-${action.href}`}>
                            <Link className="sc-coach-action-link" to={action.href}>
                              {action.label}
                            </Link>
                            <span className="sc-coach-minutes">{action.minutes} 分钟</span>
                            {action.why ? (
                              <span className="sc-coach-why">{action.why}</span>
                            ) : null}
                          </li>
                        ))}
                      </ul>
                    </li>
                  ))}
                </ol>
              ) : null}
              {advice.notice ? <p className="sc-coach-hint">{advice.notice}</p> : null}
              <p className="sc-coach-trace">
                材料 {advice.materials_used} 条
                {advice.dropped_citations > 0
                  ? ` · 已丢弃 ${advice.dropped_citations} 条无依据引用`
                  : ' · 所有引用都可核对'}
                ；建议只基于站内教程与题干，不代表能力评级。
              </p>
              <Button variant="secondary" size="sm" loading={loading} onClick={() => void generate()}>
                重新生成
              </Button>
            </div>
          ) : (
            <div className="sc-coach-actions-bar">
              <Button loading={loading} onClick={() => void generate()}>
                生成学习建议
              </Button>
              <span className="sc-coach-cost">会发起一次 AI 调用，按你的模型额度计费。</span>
            </div>
          )}
        </>
      )}
    </Card>
  )
}
