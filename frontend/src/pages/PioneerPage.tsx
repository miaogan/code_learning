import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import type { RadarTechItem } from '../api/types'
import { Button } from '../components/ui/Button'
import { Card } from '../components/ui/Card'
import { EmptyState } from '../components/ui/EmptyState'
import { InlineError } from '../components/ui/InlineError'
import { PhaseLoader } from '../components/ui/PhaseLoader'
import { Toast } from '../components/ui/Toast'
import { dimensionText, techMetaText } from '../lib/radar'
import { useAsync } from '../lib/useAsync'

/**
 * r67「先锋」：新技术 / 热门技术清单。
 *
 * 采集与评估全在服务端（离线模式下只读内置样本、不出网），页面只负责三件事：
 * 触发一轮采集、手工补一条线索、行内「生成样例」受理后跳「国子监」看进度。
 */

const VERDICT_CLASS: Record<string, string> = {
  must_learn: 'is-must',
  worth_knowing: 'is-worth',
  watch: 'is-watch',
  skip: 'is-skip',
}

function TechRow({
  item,
  busy,
  onGenerate,
}: {
  item: RadarTechItem
  busy: boolean
  onGenerate: (item: RadarTechItem) => void
}) {
  return (
    <li className="sc-radar-techrow">
      <div className="sc-radar-rowmain">
        <div className="sc-radar-rowtitle">
          <span className={`sc-radar-verdict ${VERDICT_CLASS[item.verdict] ?? 'is-skip'}`}>
            {item.verdict_label}
          </span>
          <span className="sc-radar-name">{item.name}</span>
          <span className="sc-radar-source">{item.source_key}</span>
        </div>
        <p className="sc-radar-meta">{techMetaText(item)}</p>
        {item.summary !== '' && <p className="sc-radar-summary">{item.summary}</p>}
        {item.reasons.length > 0 && <p className="sc-radar-reasons">{item.reasons.join('；')}</p>}
        <p className="sc-radar-dims">{dimensionText(item)}</p>
      </div>
      <div className="sc-radar-rowact">
        <Button variant="secondary" size="sm" loading={busy} onClick={() => onGenerate(item)}>
          {item.job_id !== '' ? '查看样例' : '生成样例'}
        </Button>
      </div>
    </li>
  )
}

export default function PioneerPage() {
  const navigate = useNavigate()
  const listAsync = useAsync((signal) => api.radarTechs(50, signal), [])
  const runAsync = useAsync((signal) => api.radarLatestRun(signal), [])

  const [name, setName] = useState('')
  const [url, setUrl] = useState('')
  const [summary, setSummary] = useState('')
  const [manualBusy, setManualBusy] = useState(false)
  const [manualError, setManualError] = useState('')
  const [toast, setToast] = useState<{ message: string; seq: number } | null>(null)
  const [collecting, setCollecting] = useState(false)
  const [collectError, setCollectError] = useState('')
  const [generating, setGenerating] = useState('')

  const techs = listAsync.status === 'success' ? listAsync.data : null
  const lastRun = runAsync.status === 'success' ? runAsync.data : null

  const refresh = (): void => {
    listAsync.reload()
    runAsync.reload()
  }

  const collect = async (): Promise<void> => {
    setCollecting(true)
    setCollectError('')
    try {
      const result = await api.radarRun()
      refresh()
      setToast({
        message: result.notice !== '' ? result.notice : `采集完成：本轮看到 ${result.techs_seen} 项技术`,
        seq: Date.now(),
      })
    } catch (error) {
      setCollectError(error instanceof Error ? error.message : '采集失败，请稍后重试')
    } finally {
      setCollecting(false)
    }
  }

  const submitManual = async (): Promise<void> => {
    if (name.trim() === '') {
      setManualError('请先填写技术名称')
      return
    }
    setManualBusy(true)
    setManualError('')
    try {
      const item = await api.radarManual({
        name: name.trim(),
        url: url.trim(),
        summary: summary.trim(),
      })
      setName('')
      setUrl('')
      setSummary('')
      refresh()
      setToast({ message: `已加入清单：${item.name}（${item.verdict_label}）`, seq: Date.now() })
    } catch (error) {
      setManualError(error instanceof Error ? error.message : '录入失败，请稍后重试')
    } finally {
      setManualBusy(false)
    }
  }

  const generate = async (item: RadarTechItem): Promise<void> => {
    if (item.job_id !== '') {
      navigate(`/guozijian?job=${encodeURIComponent(item.job_id)}`)
      return
    }
    setGenerating(item.tech_slug)
    try {
      const accepted = await api.radarGenerate({ tech_slug: item.tech_slug })
      navigate(`/guozijian?job=${encodeURIComponent(accepted.job_id)}`)
    } catch (error) {
      setToast({ message: error instanceof Error ? error.message : '生成受理失败', seq: Date.now() })
      setGenerating('')
    }
  }

  return (
    <div className="sc-page">
      <header className="sc-page-header">
        <h1 className="sc-page-title">先锋</h1>
        <p className="sc-page-sub">
          新技术与热门技术清单：服务端按「岗位相关度 / 行业采用度 / 成熟度 / 学习成本」四个粗档评估，
          结论是 1–5 的规则档位，不是精确评分。生成样例在后台跑，进度统一到「国子监」看。
        </p>
      </header>

      {toast !== null && (
        <Toast
          message={toast.message}
          seq={toast.seq}
          durationMs={2600}
          onClose={() => setToast(null)}
        />
      )}

      <Card>
        <div className="sc-radar-toolbar">
          <div className="sc-radar-toolbarleft">
            <span className="sc-radar-recent">
              {lastRun === null || lastRun.run_id === 0
                ? '还没有采集记录：点「立即采集一轮」开始。'
                : `最近采集：${lastRun.finished_at || lastRun.started_at} · 看到 ${lastRun.techs_seen} 项技术`}
            </span>
            {lastRun !== null && lastRun.notice !== '' && (
              <span className="sc-radar-notice">{lastRun.notice}</span>
            )}
          </div>
          <div className="sc-btn-row">
            <Button variant="ghost" size="sm" onClick={refresh}>
              刷新清单
            </Button>
            <Button variant="secondary" size="sm" loading={collecting} onClick={() => void collect()}>
              立即采集一轮
            </Button>
          </div>
        </div>
        {collectError !== '' && <p className="sc-radar-error">{collectError}</p>}
      </Card>

      <Card>
        <h3 className="sc-coach-blocktitle">手工录入线索</h3>
        <p className="sc-coach-note">
          自动采集只读公开清单，没覆盖到的技术可以手动补一条：不联网，按通用规则评估后即可生成样例。
        </p>
        <div className="sc-radar-manual">
          <label className="sc-field">
            <span className="sc-field-label">技术名称（必填）</span>
            <input
              type="text"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="例如：vLLM / PagedAttention"
            />
          </label>
          <label className="sc-field">
            <span className="sc-field-label">链接（选填）</span>
            <input
              type="text"
              value={url}
              onChange={(event) => setUrl(event.target.value)}
              placeholder="https://github.com/…"
            />
          </label>
          <label className="sc-field">
            <span className="sc-field-label">一句话说明（选填）</span>
            <input
              type="text"
              value={summary}
              onChange={(event) => setSummary(event.target.value)}
              placeholder="它解决什么问题"
            />
          </label>
          <div className="sc-btn-row">
            <Button variant="secondary" size="sm" loading={manualBusy} onClick={() => void submitManual()}>
              加入清单
            </Button>
          </div>
        </div>
        {manualError !== '' && <p className="sc-radar-error">{manualError}</p>}
      </Card>

      {listAsync.status === 'loading' && techs === null && (
        <PhaseLoader title="正在读取技术清单" phases={['读取评估结果']} active={0} />
      )}
      {listAsync.status === 'error' && listAsync.error !== null && (
        <InlineError message={listAsync.error.message} onRetry={listAsync.reload} />
      )}

      {techs !== null && techs.items.length === 0 && (
        <EmptyState
          reason="清单还是空的：点「立即采集一轮」拉一轮公开信号，或在上方手工录入一条线索。"
          actionLabel="立即采集一轮"
          onAction={() => void collect()}
        />
      )}

      {techs !== null && techs.items.length > 0 && (
        <Card>
          <div className="sc-radar-listhead">
            <h3 className="sc-coach-blocktitle">技术清单</h3>
            <span className="sc-radar-count">共 {techs.items.length} 项</span>
          </div>
          {techs.notice !== '' && <p className="sc-coach-note">{techs.notice}</p>}
          <ul className="sc-radar-list">
            {techs.items.map((item) => (
              <TechRow
                key={item.tech_slug}
                item={item}
                busy={generating === item.tech_slug}
                onGenerate={(row) => void generate(row)}
              />
            ))}
          </ul>
          <p className="sc-coach-note">
            清单是全局知识库，不按账号隔离；生成的任务按账号隔离，别人在途的任务不会占用你的额度。
          </p>
        </Card>
      )}
    </div>
  )
}
