import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import type { RadarJobItem } from '../api/types'
import { Button } from '../components/ui/Button'
import { Card } from '../components/ui/Card'
import { EmptyState } from '../components/ui/EmptyState'
import { InlineError } from '../components/ui/InlineError'
import { PhaseLoader } from '../components/ui/PhaseLoader'
import { Toast } from '../components/ui/Toast'
import { formatWhen } from '../lib/format'
import {
  canAdopt,
  canDiscard,
  discardedNotice,
  isActiveJob,
  progressText,
  statusLabel,
} from '../lib/radar'
import { useAsync } from '../lib/useAsync'

/** 轮询间隔：一次生成约几十秒，2s 足够跟手又不打爆接口。 */
const POLL_MS = 2000

const STATUS_CLASS: Record<string, string> = {
  queued: 'is-queued',
  running: 'is-running',
  succeeded: 'is-succeeded',
  adopted: 'is-adopted',
  discarded: 'is-discarded',
  failed: 'is-failed',
}

const KIND_LABELS: Record<string, string> = {
  single: '单选',
  multiple: '多选',
  judge: '判断',
}

const DIFFICULTY_LABELS: Record<string, string> = {
  basic: '基础',
  intermediate: '进阶',
  challenge: '高级',
}

function JobRow({
  job,
  active,
  onClick,
}: {
  job: RadarJobItem
  active: boolean
  onClick: () => void
}) {
  return (
    <li>
      <button
        type="button"
        className={active ? 'sc-radar-jobrow is-active' : 'sc-radar-jobrow'}
        onClick={onClick}
        aria-pressed={active}
      >
        <span className="sc-radar-jobrowtitle">
          <span className={`sc-radar-jobstatus ${STATUS_CLASS[job.status] ?? 'is-failed'}`}>
            {statusLabel(job.status)}
          </span>
          <span className="sc-radar-name">{job.tech_name || job.tech_slug}</span>
        </span>
        <span className="sc-radar-jobmeta">
          {progressText(job)} · {formatWhen(job.created_at)}
        </span>
      </button>
    </li>
  )
}

function JobDetail({
  job,
  acting,
  onAdopt,
  onDiscard,
}: {
  job: RadarJobItem
  acting: boolean
  onAdopt: () => void
  onDiscard: () => void
}) {
  const percent = Math.max(0, Math.min(100, Math.floor(job.progress)))
  return (
    <Card>
      <div className="sc-radar-detailhead">
        <h3 className="sc-coach-blocktitle">{job.tech_name || job.tech_slug}</h3>
        <span className={`sc-radar-jobstatus ${STATUS_CLASS[job.status] ?? 'is-failed'}`}>
          {statusLabel(job.status)}
        </span>
      </div>

      <div
        className="sc-radar-progress"
        role="progressbar"
        aria-valuenow={percent}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <span className="sc-radar-progressfill" style={{ width: `${percent}%` }} />
      </div>
      <p className="sc-radar-meta">{progressText(job)}</p>

      {job.status === 'failed' && job.error_message !== '' && (
        <InlineError message={job.error_message} />
      )}

      {job.chapter !== null && (
        <div className="sc-radar-chapter">
          <h4 className="sc-coach-blocktitle">
            学习章节草稿（{DIFFICULTY_LABELS[job.chapter.level] ?? job.chapter.level}）
          </h4>
          <p className="sc-radar-meta">
            {job.chapter.direction}
            {job.chapter.sub_direction !== '' ? ` · ${job.chapter.sub_direction}` : ''}
          </p>
          <p className="sc-radar-summary">{job.chapter.summary}</p>
          <ul className="sc-radar-sections">
            {job.chapter.sections.map((section) => (
              <li key={section.id} className="sc-radar-section">
                <strong className="sc-radar-sectitle">{section.title}</strong>
                <p className="sc-radar-summary">{section.body}</p>
                {section.bullets.length > 0 && (
                  <ul className="sc-radar-bullets">
                    {section.bullets.map((bullet) => (
                      <li key={bullet}>{bullet}</li>
                    ))}
                  </ul>
                )}
              </li>
            ))}
          </ul>
          <p className="sc-coach-note">
            章节草稿留档在任务里，不会并入站内教程；扩充入库只把题目写进练习池。
          </p>
        </div>
      )}

      {job.questions.length > 0 && (
        <div className="sc-radar-questions">
          <h4 className="sc-coach-blocktitle">练习题样例（{job.questions.length} 条）</h4>
          <ul className="sc-radar-qlist">
            {job.questions.map((question) => (
              <li key={question.id} className="sc-radar-q">
                <p className="sc-radar-qprompt">
                  <span className="sc-radar-qtag">
                    {KIND_LABELS[question.kind] ?? question.kind} ·{' '}
                    {DIFFICULTY_LABELS[question.difficulty] ?? question.difficulty}
                  </span>
                  {question.prompt}
                </p>
                <ul className="sc-radar-options">
                  {question.options.map((option) => (
                    <li
                      key={option.key}
                      className={
                        question.answer.includes(option.key)
                          ? 'sc-radar-option is-answer'
                          : 'sc-radar-option'
                      }
                    >
                      <span className="sc-radar-okey">{option.key}</span>
                      {option.text}
                    </li>
                  ))}
                </ul>
                {question.explanation !== '' && (
                  <p className="sc-coach-note">解析：{question.explanation}</p>
                )}
              </li>
            ))}
          </ul>
          {discardedNotice(job) !== '' && <p className="sc-coach-note">{discardedNotice(job)}</p>}
        </div>
      )}

      <div className="sc-btn-row sc-radar-actions">
        <Button
          variant="primary"
          size="sm"
          loading={acting}
          disabled={!canAdopt(job)}
          onClick={onAdopt}
        >
          扩充入库
        </Button>
        <Button variant="ghost" size="sm" disabled={!canDiscard(job)} onClick={onDiscard}>
          废弃
        </Button>
      </div>
      {job.status === 'succeeded' && job.questions.length === 0 && (
        <p className="sc-coach-note">这份草稿没有题目通过自检，只能废弃。</p>
      )}
      {job.status === 'adopted' && (
        <p className="sc-coach-note">
          已扩充入库：{job.questions.length} 条题已进入练习池（不进入科考卷）。
        </p>
      )}
      {job.status === 'discarded' && <p className="sc-coach-note">这份草稿已废弃，题目未入库。</p>}
    </Card>
  )
}

export default function GuozijianPage() {
  const [params] = useSearchParams()
  const jobParam = params.get('job') ?? ''
  const jobsAsync = useAsync((signal) => api.radarJobs(20, signal), [])

  const [selectedId, setSelectedId] = useState(jobParam)
  const [acting, setActing] = useState('')
  const [actionError, setActionError] = useState('')
  const [toast, setToast] = useState<{ message: string; seq: number } | null>(null)

  useEffect(() => {
    if (jobParam !== '') setSelectedId(jobParam)
  }, [jobParam])

  const jobs = jobsAsync.status === 'success' && jobsAsync.data !== null ? jobsAsync.data.items : []
  const hasActive = jobs.some((job) => isActiveJob(job.status))
  const reload = jobsAsync.reload

  // 轮询：只有存在在途任务时继续拉，终态后自然停下（离开页面由 useAsync 的 cleanup 中止）。
  // 依赖 `data` 而不是派生出来的 `jobs` 数组：后者每次渲染都是新引用，会让计时器反复重建。
  useEffect(() => {
    if (!hasActive) return undefined
    const timer = setTimeout(reload, POLL_MS)
    return () => clearTimeout(timer)
  }, [hasActive, jobsAsync.data, reload])

  const selected = jobs.find((job) => job.job_id === selectedId) ?? (jobs.length > 0 ? jobs[0] : null)

  const act = async (kind: 'adopt' | 'discard', job: RadarJobItem): Promise<void> => {
    setActing(job.job_id)
    setActionError('')
    try {
      const result =
        kind === 'adopt' ? await api.radarAdopt(job.job_id) : await api.radarDiscard(job.job_id)
      jobsAsync.reload()
      setToast({
        message:
          kind === 'adopt'
            ? `已扩充入库：${result.questions.length} 条题进入练习池`
            : '已废弃这份样例草稿，题目未入库',
        seq: Date.now(),
      })
    } catch (error) {
      setActionError(error instanceof Error ? error.message : '操作失败，请稍后重试')
    } finally {
      setActing('')
    }
  }

  return (
    <div className="sc-page">
      <header className="sc-page-header">
        <h1 className="sc-page-title">国子监</h1>
        <p className="sc-page-sub">
          这里统一观察样例生成进度：生成在服务端后台跑，离开页面也不会中断，回来按任务接上。
          完成后只有两个出口 —— 扩充入库（题目进练习池）或废弃（整份草稿作废），二者互斥。
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

      {jobsAsync.status === 'loading' && jobs.length === 0 && (
        <PhaseLoader title="正在读取样例任务" phases={['读取任务列表']} active={0} />
      )}
      {jobsAsync.status === 'error' && jobsAsync.error !== null && (
        <InlineError message={jobsAsync.error.message} onRetry={jobsAsync.reload} />
      )}

      {jobsAsync.status === 'success' && jobs.length === 0 && (
        <EmptyState
          reason="还没有样例任务：去「先锋」挑一项技术，点右侧的「生成样例」即可。"
          actionLabel="去先锋挑技术"
          actionTo="/pioneer"
        />
      )}

      {jobs.length > 0 && (
        <div className="sc-radar-workspace">
          <Card>
            <div className="sc-radar-listhead">
              <h3 className="sc-coach-blocktitle">样例任务</h3>
              <span className="sc-radar-count">{jobs.length} 条</span>
            </div>
            <ul className="sc-radar-joblist">
              {jobs.map((job) => (
                <JobRow
                  key={job.job_id}
                  job={job}
                  active={selected !== null && selected.job_id === job.job_id}
                  onClick={() => setSelectedId(job.job_id)}
                />
              ))}
            </ul>
            {hasActive && <p className="sc-coach-note">有任务正在生成，列表每 2 秒自动刷新。</p>}
          </Card>

          {selected !== null && (
            <div className="sc-radar-detail">
              {actionError !== '' && <InlineError message={actionError} />}
              <JobDetail
                job={selected}
                acting={acting === selected.job_id}
                onAdopt={() => void act('adopt', selected)}
                onDiscard={() => void act('discard', selected)}
              />
              <p className="sc-coach-note">
                雷达生成的题只进练习池、不进科考卷；章节草稿不并入官方教程。
                扩充入库后可到练习页按方向练习。
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
