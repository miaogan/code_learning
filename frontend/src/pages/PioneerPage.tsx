import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import type { RadarRunRequest, RadarTechItem } from '../api/types'
import { Button } from '../components/ui/Button'
import { Card } from '../components/ui/Card'
import { EmptyState } from '../components/ui/EmptyState'
import { InlineError } from '../components/ui/InlineError'
import { Pagination } from '../components/ui/Pagination'
import { PhaseLoader } from '../components/ui/PhaseLoader'
import { SegTabs } from '../components/polish/SegTabs'
import { Toast } from '../components/ui/Toast'
import { DIRECTIONS } from '../lib/questionDirections'
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

/** 每页条数：与后端 `/api/radar/techs` 的 `limit` 同一口径。 */
const PAGE_SIZE = 20

type VerdictFilter = 'all' | 'must_learn' | 'worth_knowing' | 'watch' | 'skip'

const VERDICT_KEYS: VerdictFilter[] = ['all', 'must_learn', 'worth_knowing', 'watch', 'skip']

/** 结论筛选标签：与后端 `rules.VERDICT_LABELS` 同一套措辞（间隔只在「全部」与四个结论之间）。 */
const VERDICT_TABS = [
  { key: 'all', label: '全部' },
  { key: 'must_learn', label: '必学' },
  { key: 'worth_knowing', label: '值得了解' },
  { key: 'watch', label: '观望' },
  { key: 'skip', label: '跳过' },
]

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
  const [page, setPage] = useState(1)
  // 清单筛选（服务端过滤）：结论走 tab、方向走下拉；筛选值变化一律回到第 1 页。
  const [verdictFilter, setVerdictFilter] = useState<VerdictFilter>('all')
  const [directionFilter, setDirectionFilter] = useState('')
  const listAsync = useAsync(
    (signal) =>
      api.radarTechs({
        limit: PAGE_SIZE,
        page,
        direction: directionFilter,
        verdict: verdictFilter === 'all' ? undefined : verdictFilter,
        signal,
      }),
    [page, directionFilter, verdictFilter],
  )
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
  const [direction, setDirection] = useState('')
  const [repo, setRepo] = useState('')
  // 采集期间的清单轮询句柄：离开页面时要清掉，避免在别的页面继续打接口。
  const pollRef = useRef<number | null>(null)

  useEffect(() => {
    return () => {
      if (pollRef.current !== null) {
        window.clearInterval(pollRef.current)
        pollRef.current = null
      }
    }
  }, [])

  // 直接读 `data`（重载期间保留上一次成功值）：按 status 派生会在采集后刷新时清空清单、闪一帧 loader。
  const techs = listAsync.data
  const lastRun = runAsync.data
  const filtering = verdictFilter !== 'all' || directionFilter !== ''

  const changeVerdict = (key: string): void => {
    setVerdictFilter(VERDICT_KEYS.includes(key as VerdictFilter) ? (key as VerdictFilter) : 'all')
    setPage(1)
  }

  const changeDirection = (value: string): void => {
    setDirectionFilter(value)
    setPage(1)
  }

  const resetFilters = (): void => {
    setVerdictFilter('all')
    setDirectionFilter('')
    setPage(1)
  }

  const refresh = (): void => {
    listAsync.reload()
    runAsync.reload()
  }

  const collect = async (): Promise<void> => {
    setCollecting(true)
    setCollectError('')
    // 规则评估先落库、模型细化还要接着跑（单轮可能几十秒）：采集在飞时轮询清单，
    // 让新条目随写随现，不必等整轮结束或手动刷新。
    pollRef.current = window.setInterval(() => listAsync.reload(), 2000)
    try {
      const payload: RadarRunRequest = {}
      if (direction !== '') {
        payload.direction = direction
      }
      if (repo.trim() !== '') {
        payload.repo = repo.trim()
      }
      const result = await api.radarRun(payload)
      setPage(1)
      refresh()
      setToast({
        message: result.notice !== '' ? result.notice : `采集完成：本轮看到 ${result.techs_seen} 项技术`,
        seq: Date.now(),
      })
    } catch (error) {
      setCollectError(error instanceof Error ? error.message : '采集失败，请稍后重试')
    } finally {
      if (pollRef.current !== null) {
        window.clearInterval(pollRef.current)
        pollRef.current = null
      }
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
      setPage(1)
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
        <div className="sc-radar-target">
          <label className="sc-field sc-radar-targetdir">
            <span className="sc-field-label">采集方向</span>
            <select
              className="sc-filter-select"
              value={direction}
              onChange={(event) => setDirection(event.target.value)}
            >
              <option value="">全部方向</option>
              {DIRECTIONS.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </label>
          <label className="sc-field sc-radar-targetrepo">
            <span className="sc-field-label">指定仓库（选填）</span>
            <input
              type="text"
              value={repo}
              onChange={(event) => setRepo(event.target.value)}
              placeholder="https://github.com/HKUDS/LightRAG 或 HKUDS/LightRAG"
            />
          </label>
        </div>
        <p className="sc-coach-note">
          指定仓库时只采这一个仓库；只选方向时按该方向的关键词检索，并只保留该方向的条目。两者都留空就是全源默认轮次。
        </p>
        {collectError !== '' && <p className="sc-radar-error">{collectError}</p>}
      </Card>

      <Card>
        <h3 className="sc-coach-blocktitle">手工录入线索</h3>
        <p className="sc-coach-note">
          自动采集只读公开清单，没覆盖到的技术可以手动补一条：粘贴 GitHub 仓库链接会自动补上
          star / 库龄等公开数据，其余按通用规则评估后即可生成样例。
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

      {techs !== null && techs.items.length === 0 && !filtering && (
        <EmptyState
          reason="清单还是空的：点「立即采集一轮」拉一轮公开信号，或在上方手工录入一条线索。"
          actionLabel="立即采集一轮"
          onAction={() => void collect()}
        />
      )}

      {techs !== null && (techs.items.length > 0 || filtering) && (
        <Card>
          <div className="sc-radar-listhead">
            <h3 className="sc-coach-blocktitle">技术清单</h3>
            <span className="sc-radar-count">共 {techs.total} 项</span>
          </div>
          {/* 筛选放在清单卡内：筛到 0 条时卡片仍在，筛选器不会跟着消失。 */}
          <div className="sc-radar-filters">
            <SegTabs
              tabs={VERDICT_TABS}
              active={verdictFilter}
              onChange={changeVerdict}
              ariaLabel="技术结论筛选"
            />
            <label className="sc-field sc-radar-filterdir">
              <span className="sc-field-label">按方向筛选</span>
              <select
                className="sc-filter-select"
                value={directionFilter}
                onChange={(event) => changeDirection(event.target.value)}
              >
                <option value="">全部方向</option>
                {DIRECTIONS.map((item) => (
                  <option key={item} value={item}>
                    {item}
                  </option>
                ))}
              </select>
            </label>
            {filtering && (
              <Button variant="ghost" size="sm" onClick={resetFilters}>
                清除筛选
              </Button>
            )}
          </div>
          {techs.notice !== '' && <p className="sc-coach-note">{techs.notice}</p>}
          {techs.items.length === 0 ? (
            <p className="sc-radar-filtered-empty">
              当前筛选下没有条目：换个方向或结论，或点「清除筛选」看全量清单。
            </p>
          ) : (
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
          )}
          <Pagination
            page={page}
            pageSize={PAGE_SIZE}
            total={techs.total}
            onChange={setPage}
            label="技术清单分页"
          />
          <p className="sc-coach-note">
            清单是全局知识库，不按账号隔离；生成的任务按账号隔离，别人在途的任务不会占用你的额度。
          </p>
        </Card>
      )}
    </div>
  )
}
