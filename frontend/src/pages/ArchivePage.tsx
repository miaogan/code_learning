import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import { api, ApiError } from '../api/client'
import type { Profile, Report, ResumeVersionSummary, RunSummary, PlanState } from '../api/types'
import { Button } from '../components/ui/Button'
import { Card } from '../components/ui/Card'
import { EmptyState } from '../components/ui/EmptyState'
import { InlineError } from '../components/ui/InlineError'
import { PhaseLoader } from '../components/ui/PhaseLoader'
import { Toast } from '../components/ui/Toast'
import {
  archiveFileName,
  archiveMarkdown,
  buildArchiveSnapshot,
  DEFAULT_ARCHIVE_MINUTES,
  evidenceCoverage,
  isEmptyArchive,
  type ArchiveSnapshot,
} from '../lib/archive'
import { formatChars, formatScore, formatWhen } from '../lib/format'
import { buildStudyPlan, PLAN_MINUTES } from '../lib/studyPlan'
import { useAsync } from '../lib/useAsync'
import { useLearnProgress } from '../state/learnProgress'

/** 404 = 「该账号还没有这条记录」；其它错误照常上抛（不能把断网渲染成空态）。 */
async function optional<T>(promise: Promise<T>): Promise<T | null> {
  try {
    return await promise
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null
    throw error
  }
}

interface ArchiveData {
  profile: Profile | null
  versions: ResumeVersionSummary[]
  runs: RunSummary[]
  report: Report | null
  planState: PlanState | null
}

function Kv({ label, value }: { label: string; value: string }) {
  return (
    <div className="sc-archive-kv">
      <span className="sc-archive-kv-label">{label}</span>
      <span className="sc-archive-kv-value">{value}</span>
    </div>
  )
}

function Bar({ percent }: { percent: number }) {
  const width = Math.min(100, Math.max(0, percent))
  return (
    <div className="sc-archive-bar" role="img" aria-label={`完成 ${width}%`}>
      <div className="sc-archive-bar-fill" style={{ width: `${width}%` }} />
    </div>
  )
}

function ScoreText({ value, scale }: { value: number | null; scale: 10 | 100 }) {
  if (value === null) return <span className="sc-archive-muted">暂无记录</span>
  const text = scale === 10 ? formatScore(value) : Number.isInteger(value) ? String(value) : value.toFixed(1)
  return <span>{text} / {scale}</span>
}

/** 顶部读数条的一格：大数字 + 单位 + 一行口径说明。 */
function Stat({
  label,
  value,
  unit,
  hint,
  accent = false,
}: {
  label: string
  value: string
  unit?: string
  hint: string
  accent?: boolean
}) {
  return (
    <div className={accent ? 'sc-archive-stat is-accent' : 'sc-archive-stat'}>
      <span className="sc-archive-stat-label">{label}</span>
      <span className="sc-archive-stat-value">
        {value}
        {unit === undefined ? null : <span className="sc-archive-stat-unit">{unit}</span>}
      </span>
      <span className="sc-archive-stat-hint">{hint}</span>
    </div>
  )
}

/** 卡标题带编号（等宽序号 + 发丝线），六块卡一眼能数清。 */
function CardTitle({ index, title }: { index: string; title: string }) {
  return (
    <h3 className="sc-coach-blocktitle sc-archive-cardtitle">
      <span className="sc-archive-index">{index}</span>
      {title}
    </h3>
  )
}

function planValue(snapshot: ArchiveSnapshot): string {
  if (snapshot.plan === null || snapshot.plan.total === 0) return '—'
  return `${snapshot.plan.completed}/${snapshot.plan.total}`
}

/** 学习档案（r63）：一份跨模块的只读汇总 + Markdown 导出/复制；读数全部由 `lib/archive` 单点计算。 */
export default function ArchivePage() {
  const progress = useLearnProgress()
  const [toast, setToast] = useState<string | null>(null)
  const [toastSeq, setToastSeq] = useState(0)

  const dataAsync = useAsync<ArchiveData>(async (signal) => {
    const [profile, versions, runs, report] = await Promise.all([
      optional(api.latestProfile(signal)),
      api.listResumeVersions(20, signal),
      api.history(20),
      optional(api.latestReport(signal)),
    ])
    const planState = report === null ? null : await optional(api.planState(report.id, signal))
    return { profile, versions, runs, report, planState }
  }, [])

  const data = dataAsync.status === 'success' ? dataAsync.data : null

  const dailyMinutes = useMemo(() => {
    const remote = data?.planState?.daily_minutes
    if (remote !== undefined && PLAN_MINUTES.includes(remote)) return remote
    return DEFAULT_ARCHIVE_MINUTES
  }, [data])

  const plan = useMemo(() => {
    if (data === null || data.report === null) return null
    return buildStudyPlan(data.report, { dailyMinutes, learned: progress })
  }, [data, dailyMinutes, progress])

  const planDone = useMemo<Record<string, true>>(() => {
    const done: Record<string, true> = {}
    for (const [taskId, flag] of Object.entries(data?.planState?.done ?? {})) {
      if (flag === true) done[taskId] = true
    }
    return done
  }, [data])

  const snapshot = useMemo(
    () =>
      data === null
        ? null
        : buildArchiveSnapshot({
            profile: data.profile,
            versions: data.versions,
            runs: data.runs,
            report: data.report,
            progress,
            plan,
            planDone,
          }),
    [data, progress, plan, planDone],
  )

  const coverage = useMemo(() => (snapshot === null ? null : evidenceCoverage(snapshot)), [snapshot])

  const exportArchive = () => {
    if (snapshot === null) return
    const text = archiveMarkdown(snapshot)
    const blob = new Blob([text], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = archiveFileName()
    document.body.appendChild(anchor)
    anchor.click()
    document.body.removeChild(anchor)
    window.setTimeout(() => URL.revokeObjectURL(url), 0)
  }

  const copyArchive = async () => {
    if (snapshot === null) return
    try {
      await navigator.clipboard.writeText(archiveMarkdown(snapshot))
      setToast('已复制 Markdown，可直接粘进笔记')
      setToastSeq((seq) => seq + 1)
    } catch {
      setToast('复制失败：浏览器没给剪贴板权限，可改用「导出 Markdown」')
      setToastSeq((seq) => seq + 1)
    }
  }

  return (
    <div className="sc-page sc-archive">
      <header className="sc-archive-hero">
        <p className="sc-archive-kicker">EVIDENCE ARCHIVE</p>
        <h1 className="sc-page-title">学习档案</h1>
        <p className="sc-page-sub">
          把画像、成绩、薄弱方向、学习进度与计划打卡汇总到一处，可一键导出或复制 Markdown。
          只汇总你在本站的记录，不代表能力评级，也不承诺求职结果。
        </p>
        {snapshot !== null && coverage !== null && !isEmptyArchive(snapshot) && (
          <div className="sc-archive-stats">
            <Stat
              label="档案齐备度"
              value={String(coverage.percent)}
              unit="%"
              hint={`已齐备 ${coverage.covered} / ${coverage.total} 项痕迹`}
              accent
            />
            <Stat
              label="计分测评"
              value={String(snapshot.scores.judgedCount)}
              unit="场"
              hint={`面试 ${snapshot.scores.interviewCount} · 笔试 ${snapshot.scores.examCount}`}
            />
            <Stat
              label="读完章节"
              value={String(snapshot.learn.done)}
              unit="章"
              hint={`小节进度 ${snapshot.learn.percent}%`}
            />
            <Stat
              label="计划打卡"
              value={planValue(snapshot)}
              unit="个"
              hint={snapshot.plan === null ? '生成报告后才有计划' : `完成 ${snapshot.plan.percent}%`}
            />
          </div>
        )}
      </header>

      {dataAsync.status === 'loading' && data === null && (
        <PhaseLoader title="正在汇总你的记录" phases={['读取画像、版本与成绩']} active={0} />
      )}
      {dataAsync.status === 'error' && dataAsync.error !== null && (
        <InlineError message={dataAsync.error.message} onRetry={dataAsync.reload} />
      )}

      {snapshot !== null && isEmptyArchive(snapshot) && (
        <EmptyState
          reason="还没有可汇总的记录：先上传简历生成画像，再做一场模拟面试或笔试，这里就会有内容。"
          actionLabel="去上传简历"
          actionTo="/"
        />
      )}

      {snapshot !== null && coverage !== null && !isEmptyArchive(snapshot) && (
        <>
          <div className="sc-btn-row sc-archive-actions">
            <Button variant="secondary" onClick={exportArchive}>
              导出 Markdown
            </Button>
            <Button variant="ghost" onClick={() => void copyArchive()}>
              复制 Markdown
            </Button>
            <span className="sc-archive-hint">导出与复制同源，文件名带当天日期。</span>
          </div>

          <Card className="sc-archive-span">
            <div className="sc-archive-coverage-head">
              <div>
                <h3 className="sc-coach-blocktitle">证据齐备度</h3>
                <p className="sc-archive-hint">
                  只判六类痕迹「有没有留下记录」，不判好坏；点「去补齐」可直接到对应入口。
                </p>
              </div>
              <div className="sc-archive-coverage-meter">
                <span className="sc-archive-coverage-num">
                  {coverage.percent}
                  <span className="sc-archive-coverage-unit">%</span>
                </span>
                <span className="sc-archive-muted">
                  已齐备 {coverage.covered} / {coverage.total} 项
                </span>
              </div>
            </div>
            <Bar percent={coverage.percent} />
            <ul className="sc-archive-coverage-list">
              {coverage.items.map((item) => (
                <li
                  key={item.key}
                  className={item.covered ? 'sc-archive-coverage-item is-covered' : 'sc-archive-coverage-item'}
                >
                  <span className="sc-archive-coverage-flag" aria-hidden="true">
                    {item.covered ? '✓' : '○'}
                  </span>
                  <span className="sc-archive-coverage-label">{item.label}</span>
                  <span className="sc-archive-coverage-hint">
                    {item.covered ? '已留下记录' : item.hint}
                  </span>
                  {item.covered ? null : (
                    <Link className="sc-archive-link" to={item.to}>
                      去补齐
                    </Link>
                  )}
                </li>
              ))}
            </ul>
          </Card>

          <div className="sc-archive-grid">
            <Card>
              <CardTitle index="01" title="目标与画像" />
              {snapshot.profile === null ? (
                <p className="sc-coach-note">
                  还没有技术画像：上传简历并生成画像后，这里会给出证据盘点的摘要。
                  <Link className="sc-archive-link" to="/">
                    去上传简历
                  </Link>
                </p>
              ) : (
                <>
                  <Kv label="目标岗位" value={snapshot.profile.targetRole ?? '未填写'} />
                  <Kv
                    label="工作年限"
                    value={snapshot.profile.years === null ? '未填写' : `${snapshot.profile.years} 年`}
                  />
                  <Kv label="项目" value={`${snapshot.profile.projects} 个`} />
                  <div className="sc-archive-chips">
                    {snapshot.profile.skills.length === 0 ? (
                      <span className="sc-archive-muted">暂无能力项</span>
                    ) : (
                      snapshot.profile.skills.slice(0, 8).map((name) => (
                        <span key={name} className="sc-chip">
                          {name}
                        </span>
                      ))
                    )}
                    {snapshot.profile.skills.length > 8 && (
                      <span className="sc-archive-muted">+{snapshot.profile.skills.length - 8}</span>
                    )}
                  </div>
                  {snapshot.profile.tech.length > 0 && (
                    <div className="sc-archive-chips">
                      {snapshot.profile.tech.slice(0, 8).map((name) => (
                        <span key={name} className="sc-chip">
                          {name}
                        </span>
                      ))}
                      {snapshot.profile.tech.length > 8 && (
                        <span className="sc-archive-muted">+{snapshot.profile.tech.length - 8}</span>
                      )}
                    </div>
                  )}
                </>
              )}
            </Card>

            <Card>
              <CardTitle index="02" title="测评成绩" />
              {snapshot.scores.judgedCount === 0 ? (
                <p className="sc-coach-note">
                  还没有已计分的测评记录：完成一场模拟面试或模拟笔试后会出现在这里。
                  <Link className="sc-archive-link" to="/interview">
                    去面试
                  </Link>
                </p>
              ) : (
                <>
                  <Kv
                    label="已完成计分"
                    value={`${snapshot.scores.judgedCount} 场（面试 ${snapshot.scores.interviewCount} / 笔试 ${snapshot.scores.examCount}）`}
                  />
                  <div className="sc-archive-kv">
                    <span className="sc-archive-kv-label">面试最近一次</span>
                    <span className="sc-archive-kv-value">
                      <ScoreText value={snapshot.scores.latestInterview} scale={10} />
                    </span>
                  </div>
                  <div className="sc-archive-kv">
                    <span className="sc-archive-kv-label">笔试最近一次</span>
                    <span className="sc-archive-kv-value">
                      <ScoreText value={snapshot.scores.latestExam} scale={100} />
                    </span>
                  </div>
                  <Link className="sc-archive-link" to="/history">
                    去看成绩趋势
                  </Link>
                </>
              )}
            </Card>

            <Card>
              <CardTitle index="03" title="简历版本" />
              {snapshot.versions.latest === null ? (
                <p className="sc-coach-note">
                  还没有简历版本：上传第一份简历即开始存档。
                  <Link className="sc-archive-link" to="/">
                    去上传简历
                  </Link>
                </p>
              ) : (
                <>
                  <Kv label="版本数" value={`${snapshot.versions.count} 个`} />
                  <Kv label="最新版本" value={snapshot.versions.latest.file_name} />
                  <Kv label="上传时间" value={formatWhen(snapshot.versions.latest.created_at)} />
                  <Kv
                    label="正文"
                    value={`${formatChars(snapshot.versions.latest.chars)} · ${snapshot.versions.latest.sections} 个分区`}
                  />
                  {snapshot.versions.count > 1 && (
                    <Link className="sc-archive-link" to="/versions">
                      对比两个版本
                    </Link>
                  )}
                </>
              )}
            </Card>

            <Card>
              <CardTitle index="04" title="薄弱方向" />
              {!snapshot.weaknessesAvailable ? (
                <p className="sc-coach-note">
                  还没有诊断报告：完成一次有计分的测评并生成报告后，薄弱方向才会出现在这里。
                  <Link className="sc-archive-link" to="/report">
                    去看诊断报告
                  </Link>
                </p>
              ) : snapshot.weaknesses.length === 0 ? (
                <p className="sc-coach-note">本次报告里没有形成薄弱方向（没有可计分的客观题）。</p>
              ) : (
                <ul className="sc-archive-weak">
                  {snapshot.weaknesses.map((item) => (
                    <li key={`${item.direction}|${item.subDirection}`} className="sc-archive-weak-row">
                      <span className="sc-archive-weak-name">
                        {item.direction}
                        {item.subDirection === '' ? '' : ` · ${item.subDirection}`}
                      </span>
                      <span className="sc-archive-weak-rate">
                        错 {item.wrong} / {item.total}
                      </span>
                      <Bar percent={Math.round(item.rate * 100)} />
                    </li>
                  ))}
                </ul>
              )}
              {snapshot.weaknessesAvailable && snapshot.weaknesses.length > 0 && (
                <Link className="sc-archive-link" to="/report">
                  去看完整报告
                </Link>
              )}
            </Card>

            <Card>
              <CardTitle index="05" title="学习进度" />
              <Kv label="已读完" value={`${snapshot.learn.done} 章`} />
              <Kv label="读到一半" value={`${snapshot.learn.reading} 章`} />
              <Kv label="参与统计" value={`${snapshot.learn.chapters} 章`} />
              <div className="sc-archive-kv">
                <span className="sc-archive-kv-label">小节进度</span>
                <span className="sc-archive-kv-value">{snapshot.learn.percent}%</span>
              </div>
              <Bar percent={snapshot.learn.percent} />
              <Link className="sc-archive-link" to="/learn">
                继续学习
              </Link>
            </Card>

            <Card>
              <CardTitle index="06" title="7 天计划" />
              {snapshot.plan === null ? (
                <p className="sc-coach-note">
                  还没有可用的 7 天计划：生成诊断报告后，报告页会按短板排出计划。
                  <Link className="sc-archive-link" to="/report">
                    去看诊断报告
                  </Link>
                </p>
              ) : snapshot.plan.total === 0 ? (
                <p className="sc-coach-note">本次报告的短板没有可排入计划的条目。</p>
              ) : (
                <>
                  <Kv
                    label="打卡"
                    value={`${snapshot.plan.completed} / ${snapshot.plan.total} 个任务（${snapshot.plan.percent}%）`}
                  />
                  <Bar percent={snapshot.plan.percent} />
                  <p className="sc-archive-hint">打卡只记「做完」，不计入熟练度或成绩。</p>
                  <Link className="sc-archive-link" to="/report">
                    去报告页打卡
                  </Link>
                </>
              )}
            </Card>
          </div>

          <p className="sc-archive-note">
            本页只读、不修改任何记录；学习进度与计划打卡换设备登录同一账号可接着看。
          </p>
        </>
      )}

      {toast === null ? null : (
        <Toast message={toast} seq={toastSeq} onClose={() => setToast(null)} />
      )}
    </div>
  )
}
