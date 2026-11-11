import { useEffect, useId, useRef, useState } from 'react'
import type { MouseEvent } from 'react'
import type {
  TimelineComparison,
  TimelineEvent as TimelineEventData,
  TimelineType,
} from '../../api/types'

export interface TimelineEventProps {
  /** 服务端返回的单条事件（快照已定格，组件内**零减法、零重算**：`comparison` 直接渲染）。 */
  event: TimelineEventData
  /** 列表首条（服务端 `occurred_at` 倒序的第一条）：全屏仅此一处 accent 强调（DESIGN §0.3）。 */
  latest?: boolean
  /**
   * 面试事件卡第三行「本场设定」（AC-11 / DESIGN §2.5）：`岗位 · 经验 · 市场 · 规模`，
   * 旧记录（`null` 设定）为「未记录设定」。由 `TimelineSection` 用既有 `ref_id ↔ runRows.id`
   * 关联后传入 —— 本组件只接收文本，不含任何业务判断与二次拼接。
   */
  settingsText?: string | null
}

/** 类型徽章文案：文字承载语义，颜色不单独表意（DESIGN §5 冗余编码）。 */
const KIND_LABEL: Record<TimelineType, string> = { interview: '面试', exam: '笔试', resume: '简历' }
/** 首次态文案（DESIGN §2.1「首次<类型>测评，暂无对比」）；简历事件不是测评，措辞按类型区分。 */
const FIRST_TEXT: Record<TimelineType, string> = {
  interview: '首次召对，暂无对比',
  exam: '首次科考，暂无对比',
  resume: '首次简历记录，暂无对比',
}
/** 分数量纲与 `TrendTable` 同一口径（面试均分 /10、笔试总分 /100），两种量纲永不互比。 */
const KIND_UNIT: Record<TimelineType, string> = { interview: '/10', exam: '/100', resume: '' }
const METRIC_LABEL: Record<TimelineComparison['metric'], string> = {
  interview_avg: '面试均分',
  exam_total: '笔试总分',
}
/** 短板 chip 行最多 3 项，余下折叠为「+N」可点展开（DESIGN §2.1）。 */
const MAX_CHIPS = 3
const DASH = '—'

/** 服务端存 UTC ISO8601；展示按本机时区到分钟，解析失败原样回显（与 `TrendTable` 同一规则）。 */
function formatWhen(occurredAt: string): string {
  const date = new Date(occurredAt)
  if (Number.isNaN(date.getTime())) return occurredAt
  const pad = (value: number): string => String(value).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

/** 数值口径：整数不带 `.0`，否则保留 1 位（与 `format.ts` / `markdown.py` 同一规则）。 */
function num(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return DASH
  const rounded = Math.round(value * 10) / 10
  return Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(1)
}

function Metric({ label, value, unit }: { label: string; value: string; unit?: string }) {
  return (
    <span className="sc-tl-metric">
      <span className="sc-tl-metric-label">{label}</span>
      <span className="sc-tl-metric-value">{unit ? `${value} ${unit}` : value}</span>
    </span>
  )
}

/** Δ chip：箭头 + 数字（双通道编码），`delta` 已由服务端保留 1 位小数，这里只选文案与色调。 */
function DeltaChip({ delta }: { delta: number }) {
  const rounded = Math.round(delta * 10) / 10
  if (!Number.isFinite(rounded)) {
    return <span className="sc-cmp-delta is-equal">{DASH}</span>
  }
  if (rounded === 0) {
    return <span className="sc-cmp-delta is-equal">＝ 持平</span>
  }
  const magnitude = num(Math.abs(rounded))
  return rounded > 0 ? (
    <span className="sc-cmp-delta is-up">{`↑ +${magnitude}`}</span>
  ) : (
    <span className="sc-cmp-delta is-down">{`↓ −${magnitude}`}</span>
  )
}

/**
 * 短板 chip 组（最多 `MAX_CHIPS` 项 + 「+N」展开）。
 * 「+N」是真实按钮：键盘可达、`stopPropagation` 避免触发整卡展开。
 */
function ShortfallChips({
  items,
  variant,
  prefix,
}: {
  items: string[]
  variant: 'is-added' | 'is-removed'
  prefix: string
}) {
  const [showAll, setShowAll] = useState(false)

  if (items.length === 0) return null

  const visible = showAll ? items : items.slice(0, MAX_CHIPS)
  const rest = items.length - visible.length

  return (
    <>
      {visible.map((name) => (
        <span key={`${variant}-${name}`} className={`sc-tl-chip ${variant}`}>{`${prefix}${name}`}</span>
      ))}
      {rest > 0 ? (
        <button
          type="button"
          className="sc-tl-chip is-more sc-mono"
          aria-label={`展开其余 ${rest} 项短板`}
          onClick={(clickEvent) => {
            clickEvent.stopPropagation()
            setShowAll(true)
          }}
        >
          {`+${rest}`}
        </button>
      ) : null}
    </>
  )
}

/**
 * 单条成长事件卡（可展开对比块）。
 *
 * - 布局：grid = 时间列 120 / 内容 1fr / 展开按钮（§0.5-1，88 高）；
 * - 整卡可点展开（DESIGN §0.3），键盘走展开按钮（`aria-expanded` / `aria-controls`）；
 * - 展开后焦点移到对比块标题（`tabindex="-1"`），折叠后焦点回到按钮（DESIGN §4）。
 */
export function TimelineEvent({ event, latest = false, settingsText = null }: TimelineEventProps) {
  const [expanded, setExpanded] = useState(false)
  const panelId = useId()
  const toggleRef = useRef<HTMLButtonElement>(null)
  const titleRef = useRef<HTMLParagraphElement>(null)
  /** 只有**用户主动**的展开/折叠才搬焦点（预置状态变化不抢焦点）。 */
  const pendingFocus = useRef<'open' | 'close' | null>(null)

  useEffect(() => {
    const pending = pendingFocus.current
    if (pending === null) return
    pendingFocus.current = null
    if (pending === 'open') titleRef.current?.focus()
    else toggleRef.current?.focus()
  }, [expanded])

  const toggle = (): void => {
    pendingFocus.current = expanded ? 'close' : 'open'
    setExpanded((value) => !value)
  }

  const onCardClick = (clickEvent: MouseEvent<HTMLDivElement>): void => {
    // 卡内按钮（展开按钮 / 「+N」）自己有行为，不再触发整卡切换
    if ((clickEvent.target as HTMLElement).closest('button')) return
    toggle()
  }

  const type = event.type
  const comparison = event.comparison
  const metrics = event.key_metrics
  const hasShortfallChips = event.added_shortfalls.length > 0 || event.removed_shortfalls.length > 0

  const classes = ['sc-tl-event']
  if (expanded) classes.push('is-expanded')
  if (latest) classes.push('is-latest')
  // 面试事件多一行「本场设定」：卡高走 --tl-row-h-lg 112（DESIGN §0.5-8），其余类型保持 88。
  // 只有第三行**真的要渲染**时才加 `is-interview`：趋势表未取到（runRows 为 null）时不留 24px 空槽。
  if (type === 'interview' && settingsText) classes.push('is-interview')

  return (
    <div className={classes.join(' ')} onClick={onCardClick}>
      <span className="sc-tl-time">{formatWhen(event.occurred_at)}</span>

      <div className="sc-tl-main">
        <div className="sc-tl-row1">
          <span className="sc-tl-badge">{KIND_LABEL[type]}</span>
          <span className="sc-tl-metrics">
            {type === 'interview' ? (
              <Metric label="面试均分" value={num(metrics.interview_avg)} unit={KIND_UNIT[type]} />
            ) : null}
            {type === 'exam' ? (
              <Metric label="笔试总分" value={num(metrics.exam_total)} unit={KIND_UNIT[type]} />
            ) : null}
            {type === 'interview' || type === 'exam' ? (
              <Metric
                label="短板"
                value={metrics.shortfall_count === null ? DASH : `${metrics.shortfall_count}`}
                unit={metrics.shortfall_count === null ? '' : '条'}
              />
            ) : null}
            {type === 'resume' && metrics.skill_added > 0 ? (
              <Metric label="新增能力" value={`${metrics.skill_added}`} unit="项" />
            ) : null}
            {type === 'resume' && metrics.skill_removed > 0 ? (
              <Metric label="转历史" value={`${metrics.skill_removed}`} unit="项" />
            ) : null}
          </span>
          {event.duplicate ? <span className="sc-tl-duplicate">同一份简历</span> : null}
        </div>

        {hasShortfallChips ? (
          <div className="sc-tl-chips">
            <ShortfallChips items={event.added_shortfalls} variant="is-added" prefix="+ " />
            <ShortfallChips items={event.removed_shortfalls} variant="is-removed" prefix="✓ 消失：" />
          </div>
        ) : (
          // 无短板变化（简历事件 / 短板为空）：用服务端组装的一句话占位，不留空行
          <p className="sc-tl-meta">{event.summary}</p>
        )}

        {/* 第三行「本场设定」（AC-11）：旧记录同字号同色显示「未记录设定」，不留空白、不出现 undefined */}
        {type === 'interview' && settingsText ? (
          <p className="sc-tl-settings">{settingsText}</p>
        ) : null}

        {expanded ? (
          <div id={panelId} className={comparison === null ? 'sc-cmp is-first' : 'sc-cmp'}>
            {comparison === null ? (
              <p className="sc-cmp-first" tabIndex={-1} ref={titleRef}>
                {FIRST_TEXT[type]}
              </p>
            ) : (
              <>
                <p className="sc-cmp-title" tabIndex={-1} ref={titleRef}>
                  {`与上次${KIND_LABEL[type]} · ${formatWhen(comparison.prev_occurred_at)}`}
                </p>
                <div className="sc-cmp-row">
                  <span className="sc-cmp-name">{METRIC_LABEL[comparison.metric]}</span>
                  <span className="sc-cmp-value">{num(comparison.current_value)}</span>
                  <span className="sc-cmp-chips">
                    <DeltaChip delta={comparison.delta} />
                    <span className="sc-cmp-prev">{`上次 ${num(comparison.prev_value)}`}</span>
                  </span>
                </div>
                <span className="sc-cmp-chips">
                  {comparison.repeated_shortfalls.length === 0 &&
                  comparison.disappeared_shortfalls.length === 0 ? (
                    <span className="sc-cmp-prev">短板无复现</span>
                  ) : (
                    <>
                      <ShortfallChips
                        items={comparison.repeated_shortfalls}
                        variant="is-added"
                        prefix="复现 · "
                      />
                      <ShortfallChips
                        items={comparison.disappeared_shortfalls}
                        variant="is-removed"
                        prefix="消失 · "
                      />
                    </>
                  )}
                </span>
              </>
            )}
          </div>
        ) : null}
      </div>

      <button
        type="button"
        ref={toggleRef}
        className="sc-tl-expand"
        aria-expanded={expanded}
        aria-controls={panelId}
        aria-label={`${expanded ? '收起' : '展开'}对比：${event.summary}`}
        onClick={(clickEvent) => {
          clickEvent.stopPropagation()
          toggle()
        }}
      >
        <span aria-hidden="true">{expanded ? '▾' : '▸'}</span>
        <span>{expanded ? '收起对比' : '展开对比'}</span>
      </button>
    </div>
  )
}
