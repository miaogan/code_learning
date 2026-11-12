import { useState } from 'react'
import { api } from '../api/client'
import { EmptyState } from '../components/ui/EmptyState'
import { InlineError } from '../components/ui/InlineError'
import { PhaseLoader } from '../components/ui/PhaseLoader'
import { kindRows, latencyLabel, rateLabel, summaryNotice, trendBars, trendRows } from '../lib/eval'
import { useAsync } from '../lib/useAsync'

const WINDOWS = [7, 30] as const

/**
 * r51 模型调用质量看板：只读展示 `GET /api/eval/summary` 的聚合结果。
 * 页面不做二次统计 —— 成功率分母、p50/p95 算法、失败分类口径全在后端固定；
 * 这里展示的是**真实调用元数据**，不是模型质量评分（离线回归与在线评测两条轨道分开）。
 */
export default function EvalPage() {
  const [days, setDays] = useState<number>(7)
  const state = useAsync((signal) => api.evalSummary(days, signal), [days])
  const data = state.data
  const loading = state.status === 'loading' && data === null

  return (
    <section>
      <header className="sc-page-header">
        <h1 className="sc-page-title">评鉴</h1>
        <p className="sc-page-sub">
          最近 {days} 天的模型调用元数据：成功率、延迟分位与失败分类。数据只来自本账号的真实调用，
          不含 Key、Prompt 与简历正文；这不是模型质量评分。
        </p>
      </header>

      <div className="sc-btn-row">
        {WINDOWS.map((window) => (
          <button
            key={window}
            type="button"
            className={days === window ? 'is-active' : ''}
            onClick={() => setDays(window)}
          >
            近 {window} 天
          </button>
        ))}
      </div>

      {loading ? (
        <PhaseLoader title="正在读取调用日志" phases={['聚合成功率与延迟分位']} active={0} />
      ) : null}

      {state.status === 'error' && state.error ? (
        <InlineError message={state.error.message} onRetry={state.reload} />
      ) : null}

      {data && data.total === 0 ? (
        <EmptyState
          reason={summaryNotice(data)}
          actionLabel="去练习"
          actionTo="/practice"
          hints={['做一次召对 / 科考 / 练习，调用会自动计入这里', '失败分类按次数排序，用来定位高频问题']}
        />
      ) : null}

      {data && data.total > 0 ? (
        <>
          <div className="sc-btn-row">
            <span>总调用 {data.total}</span>
            <span>成功率 {rateLabel(data.success_rate)}</span>
            <span>p50 {latencyLabel(data.p50_ms)}</span>
            <span>p95 {latencyLabel(data.p95_ms)}</span>
          </div>

          <h2>失败分类</h2>
          <table>
            <thead>
              <tr>
                <th>分类</th>
                <th>条数</th>
                <th>占比</th>
              </tr>
            </thead>
            <tbody>
              {kindRows(data).map((row) => (
                <tr key={row.kind}>
                  <td>{row.label}</td>
                  <td>{row.count}</td>
                  <td>{rateLabel(row.share)}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <h2>按模型</h2>
          <table>
            <thead>
              <tr>
                <th>模型</th>
                <th>调用数</th>
                <th>成功率</th>
                <th>p95</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(data.by_model).map(([model, stat]) => (
                <tr key={model}>
                  <td>{model}</td>
                  <td>{stat.total}</td>
                  <td>{rateLabel(stat.success_rate)}</td>
                  <td>{latencyLabel(stat.p95_ms)}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <h2>每日趋势</h2>
          {/* r84 §2：柱状速览（柱高=调用量，色深=成功率）——表格保留精确读数，柱子给形状。 */}
          <div className="sc-evbars">
            {trendBars(trendRows(data)).map((bar) => (
              <div className="sc-evbar-col" key={bar.day} title={bar.text}>
                <div className="sc-evbar-track">
                  <span
                    className="sc-evbar"
                    data-ok={bar.ok}
                    style={{ height: `${bar.height}px` }}
                  />
                </div>
                <span className="sc-evbar-label">{bar.label}</span>
              </div>
            ))}
          </div>
          <table>
            <thead>
              <tr>
                <th>日期</th>
                <th>调用数</th>
                <th>成功率</th>
              </tr>
            </thead>
            <tbody>
              {trendRows(data).map((row) => (
                <tr key={row.day}>
                  <td>{row.label}</td>
                  <td>{row.total}</td>
                  <td>{rateLabel(row.rate)}</td>
                </tr>
              ))}
            </tbody>
          </table>

          {data.notice ? <p>{data.notice}</p> : null}
          <p>
            指标口径：成功率 = 成功调用数 / 窗口内全部调用数；p50/p95 由窗口内耗时排序取值。
            离线评测门禁衡量的是解析与校验管线回归，不等同于模型质量提升。
          </p>
        </>
      ) : null}
    </section>
  )
}
