/**
 * r125 镜试（反向面试）：用户作为面试官，用自己的简历向自己提问。
 *
 * 页面零编排逻辑：题目推荐、满分答案、证据闸门、数字闸门全在服务端 `services.mirror`。
 * 与「召对」的边界：这里不打分、不逐题评分、不写成长时间线，只做评题与复盘。
 * 结果按账号保存（`/api/mirror/cards`），刷新后可恢复复盘。
 */

import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'

import { ApiError, api } from '../api/client'
import type { MirrorCard, MirrorSuggestion } from '../api/types'
import { Button } from '../components/ui/Button'
import { Card } from '../components/ui/Card'
import { InlineError } from '../components/ui/InlineError'
import { PhaseLoader } from '../components/ui/PhaseLoader'
import { ResumeGate } from '../components/ui/ResumeGate'
import { useAsync } from '../lib/useAsync'
import { formatWhen } from '../lib/format'

const ASSESSMENT_LEVEL_LABEL: Record<MirrorCard['assessment']['level'], string> = {
  基础: '基础题',
  合格: '合格题',
  优秀: '优秀题',
}

function EvidenceList({ card }: { card: MirrorCard }) {
  if (card.evidence.length === 0) {
    return <p className="sc-mirror-note">AI 没有给出能命中简历原文的证据（已剔除 {card.dropped_evidence_count} 条无出处引用）。</p>
  }
  return (
    <ul className="sc-mirror-evidence">
      {card.evidence.map((item) => (
        <li key={item.quote}>
          <p className="sc-mirror-claim">{item.claim}</p>
          <p className="sc-mirror-quote">简历原文：{item.quote}</p>
        </li>
      ))}
    </ul>
  )
}

function MirrorCardBody({ card }: { card: MirrorCard }) {
  return (
    <Card className="sc-mirror-card">
      <div className="sc-mirror-card-top">
        <span className="sc-chip">
          {card.origin === 'custom' ? '自拟问题' : 'AI 推荐题'}
        </span>
        <span className={`sc-chip sc-mirror-level sc-mirror-level--${card.assessment.level}`}>
          {ASSESSMENT_LEVEL_LABEL[card.assessment.level]}
        </span>
        <span className="sc-mirror-when">{formatWhen(card.created_at)}</span>
      </div>
      <h2 className="sc-mirror-question">{card.question}</h2>

      <section className="sc-mirror-block">
        <h3 className="sc-mirror-block-title">参考满分答案</h3>
        <p className="sc-mirror-answer">{card.answer}</p>
        {card.answer_sanitized ? (
          <p className="sc-mirror-note">
            答案里简历查不到的数字已降级为〈待补充〉——请自己补真实数据，不要沿用编造的量化成果。
          </p>
        ) : null}
      </section>

      <section className="sc-mirror-block">
        <h3 className="sc-mirror-block-title">为什么这么答</h3>
        <ul className="sc-mirror-list">
          {card.rationale.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      </section>

      <section className="sc-mirror-block">
        <h3 className="sc-mirror-block-title">简历依据</h3>
        <EvidenceList card={card} />
      </section>

      {card.missing_info.length > 0 ? (
        <section className="sc-mirror-block">
          <h3 className="sc-mirror-block-title">缺失信息（待你补充，AI 不会代填）</h3>
          <ul className="sc-mirror-list sc-mirror-missing">
            {card.missing_info.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </section>
      ) : null}

      <section className="sc-mirror-block">
        <h3 className="sc-mirror-block-title">这道题出得怎么样</h3>
        {card.assessment.strengths.length > 0 ? (
          <ul className="sc-mirror-list">
            {card.assessment.strengths.map((item) => (
              <li key={item}>值得肯定：{item}</li>
            ))}
          </ul>
        ) : null}
        {card.assessment.improvements.length > 0 ? (
          <ul className="sc-mirror-list">
            {card.assessment.improvements.map((item) => (
              <li key={item}>可以更好：{item}</li>
            ))}
          </ul>
        ) : null}
      </section>

      <section className="sc-mirror-block">
        <h3 className="sc-mirror-block-title">后续追问方向</h3>
        <ul className="sc-mirror-list">
          {card.follow_ups.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      </section>
    </Card>
  )
}

function SuggestionList({
  items,
  onPick,
}: {
  items: MirrorSuggestion[]
  onPick: (question: string) => void
}) {
  return (
    <Card className="sc-mirror-suggestions">
      <h2 className="sc-mirror-subtitle">AI 推荐的自查问题</h2>
      <p className="sc-mirror-note">
        每条都锚定了简历原文片段；点一条即可生成完整复盘。已剔除无法在原文命中的推荐。
      </p>
      <ul className="sc-mirror-suggestion-list">
        {items.map((item) => (
          <li key={item.question}>
            <button
              type="button"
              className="sc-mirror-suggestion"
              onClick={() => onPick(item.question)}
            >
              <span className="sc-mirror-suggestion-q">{item.question}</span>
              <span className="sc-mirror-suggestion-why">{item.rationale}</span>
              <span className="sc-mirror-quote">简历原文：{item.quote}</span>
            </button>
          </li>
        ))}
      </ul>
    </Card>
  )
}

export default function MirrorPage() {
  const profileState = useAsync((signal) => api.latestProfile(signal), [])
  const cardsState = useAsync((signal) => api.mirrorCards(50, signal), [])
  const [resumeId, setResumeId] = useState('')
  const [question, setQuestion] = useState('')
  const [suggestions, setSuggestions] = useState<MirrorSuggestion[] | null>(null)
  const [current, setCurrent] = useState<MirrorCard | null>(null)
  const [busy, setBusy] = useState(false)
  const [busyLabel, setBusyLabel] = useState('')
  const [error, setError] = useState('')
  const abortRef = useRef<AbortController | null>(null)

  // 画像就绪后锁定简历来源（与修文同口径：只用最新画像对应的简历版本）。
  useEffect(() => {
    if (profileState.status === 'success' && profileState.data) {
      setResumeId(profileState.data.resume_id)
    }
  }, [profileState.status, profileState.data])

  // 复盘列表先到、当前还没有选中卡时，默认展开最近一条（刷新恢复）。
  useEffect(() => {
    if (cardsState.status === 'success' && cardsState.data && current === null) {
      const [latest] = cardsState.data.items
      if (latest) setCurrent(latest)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cardsState.status, cardsState.data])

  useEffect(() => {
    return () => abortRef.current?.abort()
  }, [])

  if (profileState.status === 'error' && profileState.error?.status === 404) {
    return <ResumeGate reason="镜试需要用你的简历生成自查问题" unlockLabel="回镜试向自己提问" />
  }
  if (profileState.status === 'loading' || profileState.status === 'idle') {
    return <p className="sc-boot">正在加载画像…</p>
  }
  if (!resumeId) {
    return <ResumeGate reason="镜试需要用你的简历生成自查问题" unlockLabel="回镜试向自己提问" />
  }

  const refreshCards = (): void => {
    cardsState.reload()
  }

  const runAsk = async (askQuestion: string | null, source: 'custom' | 'recommended'): Promise<void> => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    setBusy(true)
    setBusyLabel(askQuestion === null ? 'AI 正在出题并生成复盘…' : '正在生成复盘…')
    setError('')
    try {
      const card = await api.mirrorAsk({
        resume_id: resumeId,
        question: askQuestion,
      })
      if (!controller.signal.aborted) {
        setCurrent(card)
        setSuggestions(null)
        setQuestion('')
        refreshCards()
      }
    } catch (reason: unknown) {
      if (controller.signal.aborted) return
      setError(
        reason instanceof ApiError ? reason.message : '复盘生成失败，请稍后重试',
      )
      void source
    } finally {
      if (!controller.signal.aborted) setBusy(false)
    }
  }

  const loadSuggestions = async (): Promise<void> => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    setBusy(true)
    setBusyLabel('AI 正在依据简历出题…')
    setError('')
    try {
      const result = await api.mirrorSuggestions({ resume_id: resumeId, count: 4 }, controller.signal)
      if (!controller.signal.aborted) {
        setSuggestions(result.items)
        if (result.items.length === 0) {
          setError('AI 推荐的问题都没能在简历原文中找到依据，已全部剔除。请换个角度自己提问。')
        }
      }
    } catch (reason: unknown) {
      if (controller.signal.aborted) return
      setError(reason instanceof ApiError ? reason.message : '推荐问题失败，请稍后重试')
    } finally {
      if (!controller.signal.aborted) setBusy(false)
    }
  }

  const submit = (event: FormEvent<HTMLFormElement>): void => {
    event.preventDefault()
    if (question.trim() === '') {
      setError('请输入你想问自己的问题，或让 AI 推荐题目')
      return
    }
    void runAsk(question.trim(), 'custom')
  }

  const history = cardsState.data?.items ?? []

  return (
    <div className="sc-page sc-mirror">
      <header className="sc-mirror-hero">
        <p className="sc-page-kicker">逃 跑 计 划 · 镜 试</p>
        <h1 className="sc-page-title">镜试</h1>
        <p className="sc-mirror-hero-note">
          角色反转：你是面试官，用自己简历向自己提问。AI 给参考满分答案、解释答题思路、
          评价题目水准。只用于练习复盘，不打分、不进战绩。
        </p>
      </header>

      {/* 左主栏 = 提问与当前复盘；右栏 = 历史复盘（窄屏退化成上下堆叠）。 */}
      <div className="sc-mirror-layout">
        <div className="sc-mirror-main">
          <Card className="sc-mirror-form-card">
            <form onSubmit={submit}>
              <label className="sc-mirror-label" htmlFor="mirror-question">
                向自己提问（留空则让 AI 直接出题并复盘）
              </label>
              <textarea
                id="mirror-question"
                className="sc-mirror-textarea"
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                placeholder="例如：这个项目的 QPS 是怎么测出来的？如果流量翻十倍会发生什么？"
                maxLength={1000}
                rows={4}
              />
              <div className="sc-mirror-actions">
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  loading={busy && busyLabel.includes('出题')}
                  onClick={() => void loadSuggestions()}
                >
                  AI 推荐问题
                </Button>
                <Button
                  type="button"
                  variant="secondary"
                  onClick={() => void runAsk(null, 'recommended')}
                  loading={busy && busyLabel.includes('出题并生成')}
                >
                  AI 出题并复盘
                </Button>
                <Button type="submit" loading={busy && !busyLabel.includes('出题')}>
                  生成复盘
                </Button>
              </div>
            </form>
          </Card>

          {busy ? <PhaseLoader phases={['读取简历', 'AI 生成', '证据校验']} active={1} /> : null}
          {error ? <InlineError message={error} /> : null}

          {suggestions !== null && suggestions.length > 0 ? (
            <SuggestionList
              items={suggestions}
              onPick={(picked) => void runAsk(picked, 'recommended')}
            />
          ) : null}

          {current ? <MirrorCardBody card={current} /> : null}
        </div>

        <aside className="sc-mirror-side">
          <Card className="sc-mirror-side-card">
            <h2 className="sc-mirror-subtitle">历史复盘</h2>
            {history.length > 0 ? (
              <>
                <p className="sc-mirror-note">
                  {history.length} 条 · 按账号隔离保存，点一条即可回看
                </p>
                <ul className="sc-mirror-history">
                  {history.map((item) => (
                    <li key={item.id}>
                      <button
                        type="button"
                        className={`sc-mirror-history-item ${current?.id === item.id ? 'is-active' : ''}`}
                        onClick={() => setCurrent(item)}
                      >
                        <span className="sc-mirror-history-q">{item.question}</span>
                        <span className="sc-mirror-history-meta">
                          {item.origin === 'custom' ? '自拟' : 'AI 推荐'} · {formatWhen(item.created_at)}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              </>
            ) : (
              <p className="sc-mirror-note">还没有复盘记录。提一个问题或让 AI 出题，就会在这里保存。</p>
            )}
          </Card>
        </aside>
      </div>
    </div>
  )
}
