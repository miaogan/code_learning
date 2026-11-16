/**
 * r110 岗位对位：粘贴 JD → 服务端字面对照 → 证据清单 / 缺口 / 召对预设。
 *
 * 页面零匹配逻辑：分组、摘要、链接都在 lib/jdMatch.ts，数值与证据唯一真源是后端响应。
 * 所有「未找到证据」都只是画像里没查到可复算的引用，绝不表述为能力不足或生产经验。
 */

import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { Link } from 'react-router-dom'

import { ApiError, api } from '../api/client'
import type { JdGapItem, JdKeywordItem, JdMatchResult } from '../api/types'
import { RoleFitCard } from '../components/report/RoleFitCard'
import { Button } from '../components/ui/Button'
import { Card } from '../components/ui/Card'
import { EmptyState } from '../components/ui/EmptyState'
import { InlineError } from '../components/ui/InlineError'
import { formatWhen } from '../lib/format'
import {
  GAP_ORIGIN_LABEL,
  KEYWORD_STATUS_LABEL,
  gapGroups,
  interviewHref,
  isJdEmpty,
  jdSummary,
  keywordGroups,
} from '../lib/jdMatch'

const SAMPLE_JD = `招聘后端工程师。
职责：设计 Python 后端服务，维护 Redis 缓存与消息队列。
要求：熟悉 Docker 基础、Kubernetes 运维，有事务与锁经验；了解 React。`

function KeywordRow({ item }: { item: JdKeywordItem }) {
  return (
    <li className="sc-jd-keyword">
      <div className="sc-jd-keyword-top">
        <span className="sc-jd-keyword-name">{item.name}</span>
        <span className={`sc-chip ${item.status === 'missing' ? 'is-muted' : ''}`}>
          {KEYWORD_STATUS_LABEL[item.status]}
        </span>
      </div>
      <p className="sc-jd-keyword-quote">JD：{item.source_quote}</p>
      {item.evidence.length > 0 ? (
        <ul className="sc-jd-evidence">
          {item.evidence.map((quote) => (
            <li key={quote}>画像证据：{quote}</li>
          ))}
        </ul>
      ) : (
        <p className="sc-jd-keyword-hint">
          {item.status === 'mentioned'
            ? '只在技术栈里出现，还没有可引用的简历原句。'
            : '画像里没有可复算的证据；不等于能力不足。'}
        </p>
      )}
      <p className="sc-jd-keyword-meta">
        画像档位 {item.user_level}/4 · 引用 {item.evidence_count} 条
        {item.role_required ? ' · 岗位模型要求' : ''}
      </p>
    </li>
  )
}

function GapList({ items, title, note }: { items: JdGapItem[]; title: string; note: string }) {
  if (items.length === 0) return null
  return (
    <section className="sc-jd-block">
      <h2 className="sc-jd-subtitle">{title}</h2>
      <p className="sc-jd-note">{note}</p>
      <ul className="sc-jd-gaps">
        {items.map((item) => (
          <li className="sc-jd-gap" key={`${item.origin}-${item.name}`}>
            <span className="sc-chip">{GAP_ORIGIN_LABEL[item.origin]}</span>
            <span className="sc-jd-gap-name">{item.name}</span>
            <p className="sc-jd-gap-reason">{item.reason}</p>
            {item.source_quote ? <p className="sc-jd-keyword-quote">原句：{item.source_quote}</p> : null}
          </li>
        ))}
      </ul>
    </section>
  )
}

function JdBody({ result }: { result: JdMatchResult }) {
  if (isJdEmpty(result)) {
    return (
      <EmptyState
        reason="这段 JD 里没检出可对照的技术词，也没有可推断的目标岗位。"
        actionLabel="去投卷补画像"
        actionTo="/"
        altLabel="去看跃迁档案"
        altTo="/leap"
        hints={['补上「技能要求 / 岗位职责」再对位', '显式填写目标岗位可跳过自动识别']}
      />
    )
  }

  const groups = keywordGroups(result.keywords)
  const gaps = gapGroups(result.gaps)

  return (
    <div className="sc-jd-result">
      <Card className="sc-jd-summary-card">
        <p className="sc-jd-summary">{jdSummary(result)}</p>
        {result.notice ? <p className="sc-jd-notice">{result.notice}</p> : null}
        <p className="sc-jd-stamp">对照于 {formatWhen(result.generated_at)}</p>
        {result.preset ? (
          <div className="sc-jd-preset">
            <div>
              <p className="sc-jd-preset-title">
                已备好召对预设：{result.preset.target_role}
                {result.preset.direction ? ` · ${result.preset.direction}` : ''}
                {result.preset.sub_direction ? ` · ${result.preset.sub_direction}` : ''}
              </p>
              <p className="sc-jd-note">{result.preset.reason}</p>
              {result.preset.focus_gaps.length > 0 ? (
                <p className="sc-jd-note">
                  将优先追问：{result.preset.focus_gaps.join(' / ')}（仍不虚构候选人经历）
                </p>
              ) : null}
            </div>
            <Link className="sc-btn sc-btn--primary" to={interviewHref(result.preset)}>
              带配置去召对 →
            </Link>
          </div>
        ) : null}
      </Card>

      {result.role_fit ? (
        <section className="sc-jd-block">
          <h2 className="sc-jd-subtitle">目标岗位差距</h2>
          <p className="sc-jd-note">
            按本次 JD 识别的岗位现场对标；与医案里已写入的报告互不影响。
          </p>
          <RoleFitCard roleFit={result.role_fit} />
        </section>
      ) : null}

      <section className="sc-jd-block">
        <h2 className="sc-jd-subtitle">JD 技术词与画像证据</h2>
        <p className="sc-jd-note">
          命中短语与原句都来自你粘贴的 JD；画像证据逐条引用简历记录，页面不做二次匹配。
        </p>
        {result.keywords.length === 0 ? (
          <Card className="sc-jd-card">
            <p className="sc-jd-note">没有可展示的技术词。</p>
          </Card>
        ) : (
          <ul className="sc-jd-keywords">
            {[...groups.evidence, ...groups.mentioned, ...groups.missing].map((item) => (
              <KeywordRow key={`${item.name}-${item.matched_alias}`} item={item} />
            ))}
          </ul>
        )}
      </section>

      <GapList
        items={gaps.jd}
        title="JD 写到，但画像没找到证据"
        note="只表示这段文本里没有可复算的引用；请自己判断是否真的缺。"
      />
      <GapList
        items={gaps.roleModel}
        title="岗位模型要求，但这段 JD 没直接写"
        note="来自内置岗位模型的「先补 1/2/3」，不是 JD 硬性要求。"
      />
    </div>
  )
}

export default function JdPage() {
  const [jdText, setJdText] = useState('')
  const [targetRole, setTargetRole] = useState('')
  const [result, setResult] = useState<JdMatchResult | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    return () => abortRef.current?.abort()
  }, [])

  const submit = async (event: FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault()
    if (jdText.trim() === '') {
      setError('请先粘贴岗位 JD')
      return
    }
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    setBusy(true)
    setError('')
    try {
      const next = await api.matchJd(
        { jd_text: jdText, target_role: targetRole.trim() || null },
        controller.signal,
      )
      if (!controller.signal.aborted) setResult(next)
    } catch (reason: unknown) {
      if (controller.signal.aborted) return
      setError(
        reason instanceof ApiError
          ? reason.message
          : '岗位对位失败，请稍后重试',
      )
    } finally {
      if (!controller.signal.aborted) setBusy(false)
    }
  }

  return (
    <div className="sc-page sc-jd">
      <header className="sc-jd-hero">
        <p className="sc-page-kicker">逃 跑 计 划 · 岗 位 对 位</p>
        <h1 className="sc-page-title">岗位对位</h1>
        <p className="sc-jd-hero-note">
          把 JD 里的技术词和简历画像里的真实证据放在一起看。这里不打分，
          也不把模拟练习包装成生产经验。
        </p>
      </header>

      <Card className="sc-jd-form-card">
        <form onSubmit={(event) => void submit(event)}>
          <label className="sc-jd-label" htmlFor="jd-text">岗位 JD</label>
          <textarea
            id="jd-text"
            className="sc-jd-textarea"
            value={jdText}
            onChange={(event) => setJdText(event.target.value)}
            placeholder={SAMPLE_JD}
            maxLength={12000}
            rows={8}
          />
          <div className="sc-jd-form-row">
            <label className="sc-jd-label" htmlFor="jd-role">
              目标岗位（可选，填了就跳过自动识别）
              <input
                id="jd-role"
                className="sc-jd-input"
                value={targetRole}
                onChange={(event) => setTargetRole(event.target.value)}
                placeholder="例如：后端工程师"
                maxLength={40}
              />
            </label>
            <div className="sc-jd-actions">
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => {
                  setJdText(SAMPLE_JD)
                  setError('')
                }}
              >
                填入示例
              </Button>
              <Button type="submit" loading={busy}>
                {busy ? '正在对照…' : '开始对位'}
              </Button>
            </div>
          </div>
        </form>
      </Card>

      {error ? <InlineError message={error} /> : null}
      {result ? <JdBody result={result} /> : null}
    </div>
  )
}
