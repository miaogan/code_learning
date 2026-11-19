import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import type { RadarRunRequest, RadarTechItem } from '../api/types'
import { MultiChipRow, type ChipOption } from '../components/ui/ChipRow'
import { Button } from '../components/ui/Button'
import { Card } from '../components/ui/Card'
import { EmptyState } from '../components/ui/EmptyState'
import { InlineError } from '../components/ui/InlineError'
import { Pagination } from '../components/ui/Pagination'
import { PhaseLoader } from '../components/ui/PhaseLoader'
import { Select } from '../components/ui/Select'
import { Toast } from '../components/ui/Toast'
import { DIRECTIONS } from '../lib/questionDirections'
import {
  assessedTimeText,
  dimensionText,
  formatCount,
  groupTechsByDay,
  listCountText,
  matchesTechQuery,
  needsTranslation,
  safeRepoUrl,
  starDeltaText,
  summaryText,
  techTagList,
  VERDICT_ORDER,
  verdictChipLabel,
  whyText,
} from '../lib/radar'
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

/** 每页条数：与后端 `/api/radar/techs` 的 `limit` 同一口径（上限 100）。 */
const PAGE_SIZE_OPTIONS = [10, 20, 50, 100] as const
// 默认 10：折叠后一行约 90px，10 条恰好接近一屏；默认 20 会让清单必然滚两三屏。
const DEFAULT_PAGE_SIZE = 10

/** 结论筛选多选：与后端 `rules.VERDICT_LABELS` 同一套措辞（「全部」是折叠后的哨兵）。 */
const VERDICT_BASE_OPTIONS: ChipOption<string>[] = [
  { value: 'all', label: '全部' },
  { value: 'must_learn', label: '必学' },
  { value: 'worth_knowing', label: '选学' },
  { value: 'watch', label: '观望' },
  { value: 'skip', label: '跳过' },
]

/**
 * r146：给结论 chip 挂分面计数（`必学 8`）。
 *
 * 计数由服务端按**方向**过滤后统计、刻意不看结论筛选——否则点开「必学」后其余三档
 * 全变 0，用户会以为别的档空了。`counts` 未就绪（首屏）时退回纯文案，不显示误导性的 0。
 */
function verdictOptions(counts: Record<string, number> | undefined): ChipOption<string>[] {
  if (counts === undefined) return VERDICT_BASE_OPTIONS
  const all = VERDICT_ORDER.reduce((sum, verdict) => sum + (counts[verdict] ?? 0), 0)
  return VERDICT_BASE_OPTIONS.map((option) => ({
    ...option,
    label: verdictChipLabel(
      option.label,
      option.value === 'all' ? all : (counts[option.value] ?? 0),
    ),
  }))
}

/** 方向筛选多选：与题库 / 学馆同一份闭集，勾满全部具体方向自动折叠回「全部」。 */
const DIRECTION_OPTIONS: ChipOption<string>[] = [
  { value: 'all', label: '全部' },
  ...DIRECTIONS.map((item) => ({ value: item, label: item })),
]

/**
 * r144 信息流单条（aihot 式）：左侧编号时间线 rail + 右侧紧凑信息卡。
 * meta 行放「结论徽章 · 时间 · 来源 · star」，标题单独一行，标签行收方向与状态词，
 * 「生成样例」与「展开详情」仍是显式按钮（不做整卡点击，避免误触）。
 */
function TechRow({
  item,
  rank,
  busy,
  expanded,
  hit,
  onToggle,
  onGenerate,
}: {
  item: RadarTechItem
  /** 页内全局序号（跨日期分组连续编号，aihot 同款）。 */
  rank: number
  busy: boolean
  expanded: boolean
  /** r87：从国子监深链定位到的条目，短暂高亮便于一眼找到。 */
  hit: boolean
  onToggle: () => void
  onGenerate: (item: RadarTechItem) => void
}) {
  const detailId = `radar-tech-detail-${item.tech_slug}`
  // 中文优先：有译文展示译文；原文始终留着，展开态里可回看。
  const summaryToShow = summaryText(item)
  const hasOriginal = item.summary_zh !== '' && item.summary !== ''
  const link = safeRepoUrl(item.url)
  const time = assessedTimeText(item.assessed_at)
  const tags = techTagList(item)
  // r146：折叠态也给「凭什么」——四档结论原来只有结果，用户只能展开才知道依据。
  const why = whyText(item)
  return (
    <li
      className={hit ? 'sc-radar-slot is-hit' : 'sc-radar-slot'}
      id={`radar-tech-${item.tech_slug}`}
    >
      <div className="sc-radar-rail" aria-hidden="true">
        <span className="sc-radar-rank">{rank}</span>
        <span className="sc-radar-node" />
      </div>
      <div className="sc-radar-slotcard">
        <div className="sc-radar-slotmeta">
          <span className={`sc-radar-verdict ${VERDICT_CLASS[item.verdict] ?? 'is-skip'}`}>
            {item.verdict_label}
          </span>
          <span className="sc-radar-slotsrc">
            {time !== '' ? `${time} · ` : ''}
            {item.source_key}
          </span>
          <span className="sc-radar-slotstars">
            {`star ${formatCount(item.stars)}（7 日 ${starDeltaText(item.star_delta_7d)}）`}
          </span>
          <div className="sc-radar-slotact">
            <Button variant="secondary" size="sm" loading={busy} onClick={() => onGenerate(item)}>
              {item.job_id !== '' ? '查看样例' : '生成样例'}
            </Button>
          </div>
        </div>
        <div className="sc-radar-slothead">
          {link !== '' ? (
            <a
              className="sc-radar-name sc-radar-name--link"
              href={link}
              target="_blank"
              rel="noopener noreferrer"
              title="在新标签打开仓库"
            >
              {item.name}
              <span className="sc-radar-ext" aria-hidden="true">
                ↗
              </span>
            </a>
          ) : (
            <span className="sc-radar-name">{item.name}</span>
          )}
        </div>
        {!expanded && summaryToShow !== '' && <p className="sc-radar-brief">{summaryToShow}</p>}
        {!expanded && why !== '' && (
          <p className="sc-radar-why">
            <span className="sc-radar-whylabel">依据</span>
            {why}
          </p>
        )}
        <div className="sc-radar-tagrow">
          {tags.map((tag) => (
            <span key={tag} className="sc-radar-tag">
              {`#${tag}`}
            </span>
          ))}
          <button
            type="button"
            className="sc-radar-expand"
            aria-expanded={expanded}
            aria-controls={detailId}
            onClick={onToggle}
          >
            {expanded ? '收起详情 ▴' : '展开详情 ▾'}
          </button>
        </div>
        {expanded && (
          <div className="sc-radar-rowdetail" id={detailId}>
            {summaryToShow !== '' && <p className="sc-radar-summary">{summaryToShow}</p>}
            {hasOriginal && (
              <details className="sc-radar-origin">
                <summary>查看英文原文</summary>
                <p>{item.summary}</p>
              </details>
            )}
            {item.reasons.length > 0 && <p className="sc-radar-reasons">{item.reasons.join('；')}</p>}
            <p className="sc-radar-dims">{dimensionText(item)}</p>
          </div>
        )}
      </div>
    </li>
  )
}

export default function PioneerPage() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  // r87：国子监「在先锋看这项技术」带回的深链 —— `tech` 定位某项技术，`direction` 落为方向筛选。
  const linkTech = searchParams.get('tech') ?? ''
  const linkDirection = searchParams.get('direction') ?? ''
  const [page, setPage] = useState(1)
  // 每页条数由用户选（后端 `limit` 上限 100），改动同样回到第 1 页。
  const [pageSize, setPageSize] = useState<number>(DEFAULT_PAGE_SIZE)
  // r144：当前页关键词过滤（服务端分页是权威口径，这里只帮用户在已取回的一页里快速扫）。
  const [techQuery, setTechQuery] = useState('')
  // r146：「怎么评的」说明面板默认收起——它是一次性的心智建设，不该长期占屏。
  const [howtoOpen, setHowtoOpen] = useState(false)
  // 清单筛选（服务端过滤）：结论与方向都是多选，`['all']` = 不筛选；筛选值变化一律回到第 1 页。
  const [verdictFilters, setVerdictFilters] = useState<string[]>(['all'])
  const [directionFilters, setDirectionFilters] = useState<string[]>(['all'])
  const pickedVerdicts = verdictFilters.filter((item) => item !== 'all')
  const pickedDirections = directionFilters.filter((item) => item !== 'all')
  const listAsync = useAsync(
    (signal) =>
      api.radarTechs({
        limit: pageSize,
        page,
        direction: pickedDirections,
        verdict: pickedVerdicts,
        signal,
      }),
    [page, pageSize, verdictFilters, directionFilters],
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
  // 补翻：录入时已在服务端翻好，这里只兜住历史遗留 / 当时没配模型的英文摘要。
  const [translating, setTranslating] = useState(false)
  // 条目的详情默认折叠：按 tech_slug 记住哪些被展开，翻页后状态天然跟着条目走。
  const [expandedSlugs, setExpandedSlugs] = useState<string[]>([])
  // 深链命中的高亮：只标从国子监带回来的那一条，手动展开不触发。
  const [hitSlug, setHitSlug] = useState('')
  // 深链未命中：目标技术在当前页找不到（在后面的分页里），给一句不催不挡的提示。
  const [missName, setMissName] = useState('')
  const toggleExpanded = (slug: string): void => {
    setExpandedSlugs((prev) => (prev.includes(slug) ? prev.filter((item) => item !== slug) : [...prev, slug]))
  }

  // r87 深链消费之一：`direction` 合法时直接落为方向筛选（服务端过滤后第一页大概率就有目标技术）。
  // 只在参数变化时执行；随后技术定位成功/失败都会清掉 URL 参数，不会反复触发。
  useEffect(() => {
    if (linkDirection === '' || !DIRECTIONS.includes(linkDirection)) return
    setDirectionFilters([linkDirection])
    setPage(1)
  }, [linkDirection])

  // r87 深链消费之二：清单加载后定位 `tech` —— 命中就展开 + 高亮 + 滚过去，
  // 未命中（在后面的分页里）给一句不催不挡的提示；消费完清掉 URL 参数（replace，不留历史记录）。
  useEffect(() => {
    if (linkTech === '' || listAsync.status !== 'success') return
    const linkName = searchParams.get('name') ?? ''
    const hit = (listAsync.data?.items ?? []).find((item) => item.tech_slug === linkTech)
    if (hit !== undefined) {
      setExpandedSlugs((prev) => (prev.includes(hit.tech_slug) ? prev : [...prev, hit.tech_slug]))
      setHitSlug(hit.tech_slug)
      setMissName('')
      window.requestAnimationFrame(() => {
        document.getElementById(`radar-tech-${hit.tech_slug}`)?.scrollIntoView({ block: 'center' })
      })
    } else {
      setHitSlug('')
      setMissName(linkName !== '' ? linkName : linkTech)
    }
    setSearchParams({}, { replace: true })
  }, [linkTech, listAsync.status, listAsync.data, searchParams, setSearchParams])

  // 翻页 / 改每页条数后，未命中提示不再有意义（用户已经在主动找了），静默清掉。
  useEffect(() => {
    setMissName('')
  }, [page, pageSize])
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
  const filtering = pickedVerdicts.length > 0 || pickedDirections.length > 0
  // 当前页还有「英文且没译文」的条目时才显示补翻按钮：没待翻内容就不占位置。
  const pendingTranslation = (techs?.items ?? []).some(
    (item) => item.summary_zh === '' && needsTranslation(item.summary),
  )

  // r144 信息流：当前页过滤 → 按本地日分组 → 跨组连续编号（aihot 同款）。
  const visibleItems = (techs?.items ?? []).filter((item) => matchesTechQuery(item, techQuery))
  const dayGroups = groupTechsByDay(visibleItems)
  const rankBySlug = new Map<string, number>()
  {
    let rank = 0
    for (const group of dayGroups) {
      for (const item of group.items) {
        rank += 1
        rankBySlug.set(item.tech_slug, rank)
      }
    }
  }

  // reload 引用稳定（useAsync 内部 useCallback），补翻函数才能安全地进 effect 依赖。
  const listReload = listAsync.reload
  const runReload = runAsync.reload
  const translateBacklog = useCallback(async (): Promise<void> => {
    setTranslating(true)
    try {
      // 一批按当前页大小翻：翻完刷一次清单，译文直接替换成中文。
      const result = await api.radarTranslate({ limit: pageSize })
      listReload()
      runReload()
      setToast({ message: result.notice, seq: Date.now() })
    } catch (error) {
      setToast({
        message: error instanceof Error ? error.message : '翻译失败，请稍后重试',
        seq: Date.now(),
      })
    } finally {
      setTranslating(false)
    }
  }, [pageSize, listReload, runReload])

  const changeVerdicts = (next: string[]): void => {
    setVerdictFilters(next)
    setPage(1)
  }

  const changeDirections = (next: string[]): void => {
    setDirectionFilters(next)
    setPage(1)
  }

  const changePageSize = (value: string): void => {
    const size = Number(value)
    setPageSize(
      PAGE_SIZE_OPTIONS.includes(size as (typeof PAGE_SIZE_OPTIONS)[number])
        ? size
        : DEFAULT_PAGE_SIZE,
    )
    setPage(1)
  }

  const resetFilters = (): void => {
    setVerdictFilters(['all'])
    setDirectionFilters(['all'])
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
          新技术动态流：按评估日期分组、按时间倒序编号；服务端按「岗位相关度 / 行业采用度 / 成熟度 /
          学习成本」四个粗档评估，结论是 1–5 的规则档位，不是精确评分。生成样例在后台跑，进度统一到「国子监」看。
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
            <Select
              value={direction}
              options={[
                { value: '', label: '全部方向' },
                ...DIRECTIONS.map((item) => ({ value: item, label: item })),
              ]}
              onChange={setDirection}
            />
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
            <div className="sc-radar-listmeta">
              <span className="sc-radar-count">
                {listCountText({
                  total: techs.total,
                  pageCount: visibleItems.length,
                  allCount: VERDICT_ORDER.reduce(
                    (sum, verdict) => sum + (techs.counts?.[verdict] ?? 0),
                    0,
                  ),
                  searching: techQuery.trim() !== '',
                  filtering,
                  counts: techs.counts,
                })}
              </span>
              <button
                type="button"
                className="sc-radar-howto"
                aria-expanded={howtoOpen}
                aria-controls="radar-howto"
                onClick={() => setHowtoOpen((prev) => !prev)}
              >
                {howtoOpen ? '收起评分说明 ▴' : '怎么评的 ▾'}
              </button>
            </div>
          </div>
          {howtoOpen && (
            <div className="sc-radar-howto-panel" id="radar-howto">
              <p className="sc-radar-howto-lead">
                四维都是 1–5 的粗档，用来排序和分流，不是精确评分；结论只看前两维——
                岗位相关度与行业采用度，另外两维也照实记录，但不改变结论。
              </p>
              <dl className="sc-radar-howto-list">
                <div>
                  <dt>必学</dt>
                  <dd>岗位相关度 ≥ 4 且 行业采用度 ≥ 3</dd>
                </div>
                <div>
                  <dt>选学</dt>
                  <dd>岗位相关度 ≥ 3（采用度不一定高，但和你当前方向相关）</dd>
                </div>
                <div>
                  <dt>观望</dt>
                  <dd>行业采用度 ≥ 3（够热，但与你当前方向关系弱）</dd>
                </div>
                <div>
                  <dt>跳过</dt>
                  <dd>其余：既不相关，也还没被行业验证</dd>
                </div>
              </dl>
              <dl className="sc-radar-howto-list">
                <div>
                  <dt>岗位相关度</dt>
                  <dd>属站内 8 个方向 +1；命中画像里的薄弱方向 +2；命中目标岗位关键词 +1</dd>
                </div>
                <div>
                  <dt>行业采用度</dt>
                  <dd>star 每 100 倍 +1；7 日涨 50 star +1；多源同时出现（≥2）+1</dd>
                </div>
                <div>
                  <dt>成熟度</dt>
                  <dd>仓库满 180 天 +1；近 30 天仍有推送 +1；来自 GitHub +1；多源出现 +1</dd>
                </div>
                <div>
                  <dt>学习成本</dt>
                  <dd>论文 2、新仓库 3、成熟且活跃 5、其余 4；数值越大越省力（5 = 一个下午能上手）</dd>
                </div>
              </dl>
              <p className="sc-radar-howto-note">
                疑似刷 star（新建即巨量）会把结论降一档，例如「必学」降成「选学」。
              </p>
              <p className="sc-radar-howto-note">
                条目上标「规则评估」= 纯规则打分，零模型参与、可复算；没有这个标 = 模型按同一套四维与四档给分，
                越界值会被夹到 1–5。
              </p>
            </div>
          )}
          {missName !== '' && (
            <p className="sc-coach-note">
              从国子监带来的「{missName}」不在当前页：它可能在后面的分页里，翻页或换个方向筛选找找。
            </p>
          )}
          {/* r144：aihot 式搜索条放在筛选之上——先扫词，再用结论 / 方向收窄。 */}
          <div className="sc-radar-searchrow">
            <input
              type="text"
              className="sc-radar-searchinput"
              value={techQuery}
              onChange={(event) => setTechQuery(event.target.value)}
              placeholder="搜索标题和摘要（当前页）"
              aria-label="过滤当前页技术条目"
            />
            {techQuery !== '' && (
              <Button variant="ghost" size="sm" onClick={() => setTechQuery('')}>
                清空
              </Button>
            )}
          </div>
          {techQuery.trim() !== '' && (
            <p className="sc-coach-note">
              搜索只过滤当前已取回的 {techs.items.length} 条；更早的条目请翻页后再搜。
            </p>
          )}
          {/* 筛选放在清单卡内：筛到 0 条时卡片仍在，筛选器不会跟着消失。 */}
          <div className="sc-radar-filters">
            <div className="sc-radar-filtergroups">
              <div className="sc-lab-filter-row">
                <span className="sc-lab-filter-label">结论</span>
                <div className="sc-lab-filter-body">
                  <MultiChipRow
                    groupLabel="技术结论筛选"
                    options={verdictOptions(techs.counts)}
                    values={verdictFilters}
                    allValue="all"
                    onChange={changeVerdicts}
                  />
                </div>
              </div>
              <div className="sc-lab-filter-row">
                <span className="sc-lab-filter-label">方向</span>
                <div className="sc-lab-filter-body">
                  <MultiChipRow
                    groupLabel="按方向筛选"
                    options={DIRECTION_OPTIONS}
                    values={directionFilters}
                    allValue="all"
                    onChange={changeDirections}
                  />
                </div>
              </div>
            </div>
            <div className="sc-radar-filterright">
              <Select
                variant="compact"
                ariaLabel="每页条数"
                value={String(pageSize)}
                options={PAGE_SIZE_OPTIONS.map((size) => ({
                  value: String(size),
                  label: `每页 ${size} 条`,
                }))}
                onChange={changePageSize}
              />
              {/* r133：翻页与每页条数同处筛选条右侧，找页码不用再滚到清单底部。 */}
              <Pagination
                page={page}
                pageSize={pageSize}
                total={techs.total}
                onChange={setPage}
                label="技术清单分页"
              />
              {pendingTranslation && (
                <Button
                  variant="ghost"
                  size="sm"
                  loading={translating}
                  onClick={() => void translateBacklog()}
                >
                  翻译英文简介
                </Button>
              )}
              {filtering && (
                <Button variant="ghost" size="sm" onClick={resetFilters}>
                  清除筛选
                </Button>
              )}
            </div>
          </div>
          {techs.notice !== '' && <p className="sc-coach-note">{techs.notice}</p>}
          {techs.items.length === 0 ? (
            <p className="sc-radar-filtered-empty">
              当前筛选下没有条目：换个方向或结论，或点「清除筛选」看全量清单。
            </p>
          ) : visibleItems.length === 0 ? (
            <p className="sc-radar-filtered-empty">
              {`当前页没有匹配「${techQuery.trim()}」的条目：换个词，或清空搜索看整页。`}
            </p>
          ) : (
            <div className="sc-radar-feed">
              {dayGroups.map((group) => (
                <section className="sc-radar-day" key={group.key}>
                  <header className="sc-radar-dayhead">
                    <h4 className="sc-radar-daylabel">{group.label}</h4>
                    <span className="sc-radar-daycount">{`${group.items.length} 条`}</span>
                  </header>
                  <ol className="sc-radar-timeline">
                    {group.items.map((item) => (
                      <TechRow
                        key={item.tech_slug}
                        item={item}
                        rank={rankBySlug.get(item.tech_slug) ?? 0}
                        busy={generating === item.tech_slug}
                        expanded={expandedSlugs.includes(item.tech_slug)}
                        hit={hitSlug === item.tech_slug}
                        onToggle={() => toggleExpanded(item.tech_slug)}
                        onGenerate={(row) => void generate(row)}
                      />
                    ))}
                  </ol>
                </section>
              ))}
            </div>
          )}
          <p className="sc-coach-note">
            清单是全局知识库，不按账号隔离；生成的任务按账号隔离，别人在途的任务不会占用你的额度。
          </p>
        </Card>
      )}
    </div>
  )
}
