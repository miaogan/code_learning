import { useEffect, useRef, useState } from 'react'
import type { ChangeEvent, DragEvent } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { ApiError, api } from '../api/client'
import type { ProfileMergeSummary, ResumeMeta } from '../api/types'
import { mergeSummaryText } from '../components/profile/mergeModel'
import { Button } from '../components/ui/Button'
import { Card } from '../components/ui/Card'
import { Chip } from '../components/ui/Chip'
import { ConfirmModal } from '../components/ui/ConfirmModal'
import { InlineError } from '../components/ui/InlineError'
import { PhaseLoader } from '../components/ui/PhaseLoader'
import { RingProgress } from '../components/ui/RingProgress'
import { formatChars } from '../lib/format'
import {
  PROFILE_JOB_POLL_MS,
  isJobRunning,
  jobFailureMessage,
  jobToResumeMeta,
  shouldReattach,
} from '../lib/profileJob'
import { useAsync } from '../lib/useAsync'
import { setFlow } from '../state/flow'

const MAX_BYTES = 10 * 1024 * 1024
const ACCEPTED = ['.pdf', '.docx', '.txt']

/**
 * 页面阶段（r30 行为变更）：idle →（上传解析，仍同步等待）→ profiling（服务端后台任务，
 * 本页只轮询，可随时离开）→ done；任一步失败进 error 并记住失败在哪一步（重试只重跑那一步）。
 * 旧版 profiling 阶段的 paused（取消后可续）随同步等待一起移除：后台任务没有「取消」，
 * 离开不丢进度，回来自动接上。
 */
type Phase = 'idle' | 'uploading' | 'profiling' | 'done' | 'error'

interface Failure {
  message: string
  /** 失败发生在哪一步：上传解析 / 画像生成合并（决定「重试」重跑哪一段）。 */
  stage: 'upload' | 'profile'
  /** 本地校验失败（格式/大小/空文件）重跑同一文件毫无意义，直接不给重试入口。 */
  retryable: boolean
}

/** 与后端一致的中文错误文案（AC-1：空文件 / 加密 PDF / 超限都要给出具体原因）。 */
function validateLocally(file: File): string | null {
  const name = file.name.toLowerCase()
  if (!ACCEPTED.some((suffix) => name.endsWith(suffix))) {
    return '仅支持 PDF / DOCX / TXT 文件'
  }
  if (file.size === 0) {
    return '文件内容为空，请换一份'
  }
  if (file.size > MAX_BYTES) {
    return '文件超过 10MB，请压缩或分卷'
  }
  return null
}

/**
 * 上传页。r3：上传成功后立即生成/合并画像；r30：画像生成改为服务端后台任务 ——
 * 受理即返回 `job_id`，本页每 2 秒轮询，生成期间离开页面任务照跑，回来自动接上。
 * 因此离开保护只保留在「文件上传中」这个秒级窗口；画像生成阶段不再拦截导航。
 */
export default function UploadPage() {
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const inputRef = useRef<HTMLInputElement>(null)
  /** 只保护文件上传这一段在途请求；画像任务在服务端，卸载不需要（也不应该）中止它。 */
  const abortRef = useRef<AbortController | null>(null)
  const [phase, setPhase] = useState<Phase>('idle')
  const [dragOver, setDragOver] = useState(false)
  const [picked, setPicked] = useState<File | null>(null)
  const [meta, setMeta] = useState<ResumeMeta | null>(null)
  /** meta 的镜像：失败重试时取 resume_id 重新受理画像任务。 */
  const metaRef = useRef<ResumeMeta | null>(null)
  const [jobId, setJobId] = useState<string | null>(null)
  const [merge, setMerge] = useState<ProfileMergeSummary | null>(null)
  const [failure, setFailure] = useState<Failure | null>(null)
  const [uploadSec, setUploadSec] = useState(0)
  const [profileSec, setProfileSec] = useState(0)
  /** 上传中点了站内链接：先确认再跳（画像生成阶段不拦截，任务在服务端跑）。 */
  const [pendingLeave, setPendingLeave] = useState<string | null>(null)
  /** 重接入只跑一次（StrictMode 双跑会被 ref 挡住，避免重复请求与状态踩踏）。 */
  const reattachRef = useRef(false)
  /** phase 的镜像：重接入的异步回调里判断「用户是否已经又开始了新动作」。 */
  const phaseRef = useRef<Phase>(phase)
  phaseRef.current = phase

  // 回访识别：已有画像的用户（换设备/重新登录后）不必再传一份简历，首页给「继续」入口。
  // 没有画像时接口报 PROFILE_MISSING，这里按「新用户」处理，不显示任何错误。
  const savedProfileAsync = useAsync((signal) => api.latestProfile(signal), [])
  // data 是「最近一次成功值」（重载期间保留）：生成成功后再 reload，页头与回访摘要卡不闪空。
  const saved = savedProfileAsync.data
  const reloadSavedProfile = savedProfileAsync.reload
  // 只有「没有画像」（404）才按新用户处理；其它错误必须显式报错并给重试，不能假装是新用户。
  const savedError =
    savedProfileAsync.status === 'error' && savedProfileAsync.error?.status !== 404
      ? (savedProfileAsync.error?.message ?? '画像读取失败，请稍后重试')
      : null

  // 服务端已有画像 → 把步骤条对勾补齐（对勾原本只来自本机 localStorage）。
  useEffect(() => {
    if (saved === null) return
    setFlow({ hasResume: true, hasProfile: true })
  }, [saved])

  useEffect(() => {
    if (phase !== 'uploading' && phase !== 'profiling') return
    const bump = phase === 'uploading' ? setUploadSec : setProfileSec
    const timer = window.setInterval(() => bump((value) => value + 1), 1000)
    return () => window.clearInterval(timer)
  }, [phase])

  const busy = phase === 'uploading' || phase === 'profiling'

  // 文件上传中（秒级窗口）离开会丢进度：刷新/关闭走浏览器原生提示，站内链接先确认 ——
  // 与笔试页（作答中离开）、润色页（生成中离开）同一套写法。
  // 画像生成阶段**不拦截**：那是服务端后台任务（r30），离开照跑，回来自动接上。
  useEffect(() => {
    if (phase !== 'uploading') {
      setPendingLeave(null)
      return
    }
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault()
      event.returnValue = ''
    }
    const onClickCapture = (event: MouseEvent) => {
      const target = event.target instanceof Element ? event.target.closest('a[href]') : null
      if (!target) return
      const href = target.getAttribute('href')
      if (!href || href.startsWith('#') || /^[a-z]+:/i.test(href) || href === pathname) return
      event.preventDefault()
      event.stopPropagation()
      setPendingLeave(href)
    }
    window.addEventListener('beforeunload', onBeforeUnload)
    document.addEventListener('click', onClickCapture, true)
    return () => {
      window.removeEventListener('beforeunload', onBeforeUnload)
      document.removeEventListener('click', onClickCapture, true)
    }
  }, [phase, pathname])

  // 兜底：卸载时文件上传仍在途（确认离开后的跳转、登出）一律中止；
  // 画像后台任务不在中止范围 —— 它就是要活在页面之外。
  useEffect(() => () => abortRef.current?.abort(), [])

  // r30 重接入：回到上传页时若还有在后台跑的画像任务，直接接上轮询。
  // completed/failed 的历史任务不重放（shouldReattach 只认 running），
  // 完成态走 savedProfile 读路径呈现「已有画像」摘要卡。
  useEffect(() => {
    if (reattachRef.current) return
    reattachRef.current = true
    api
      .latestProfileJob()
      .then((job) => {
        if (!shouldReattach(job) || phaseRef.current !== 'idle') return
        const resumed = jobToResumeMeta(job)
        setPicked(null)
        setMeta(resumed)
        metaRef.current = resumed
        setPhase('profiling')
        setJobId(job.job_id)
      })
      .catch(() => {
        /* 404 = 没有任务，正常新用户路径；其它错误也静默 —— 生成不是本页必现状态 */
      })
  }, [])

  // r30 轮询：每 2 秒查一次任务状态。网络抖动继续轮（不轻易判死）；
  // 404 说明任务行没了，如实报错。轮询随卸载/终态自动停止，任务本身在服务端照跑。
  useEffect(() => {
    if (jobId === null) return
    let stopped = false
    let timer = 0
    const poll = async () => {
      try {
        const job = await api.getProfileJob(jobId)
        if (stopped) return
        if (isJobRunning(job)) {
          timer = window.setTimeout(() => void poll(), PROFILE_JOB_POLL_MS)
          return
        }
        setJobId(null)
        if (job.status === 'completed' && job.result !== null) {
          // 后台完成也带一次性 merge_summary（r3 的「本次合并」摘要不因异步而丢）。
          setMerge(job.result.merge_summary ?? null)
          setFlow({ hasResume: true, hasProfile: true })
          setPhase('done')
          void reloadSavedProfile()
        } else {
          setFailure({ message: jobFailureMessage(job), stage: 'profile', retryable: true })
          setPhase('error')
        }
      } catch (err) {
        if (stopped) return
        if (err instanceof ApiError && err.status === 404) {
          setJobId(null)
          setFailure({
            message: '后台任务已不存在，请重新生成画像',
            stage: 'profile',
            retryable: true,
          })
          setPhase('error')
          return
        }
        timer = window.setTimeout(() => void poll(), PROFILE_JOB_POLL_MS)
      }
    }
    timer = window.setTimeout(() => void poll(), PROFILE_JOB_POLL_MS)
    return () => {
      stopped = true
      window.clearTimeout(timer)
    }
  }, [jobId, reloadSavedProfile])

  /** 画像生成（r30 起为后台任务）：受理即返回，状态由轮询 effect 接管。 */
  const startProfileJob = (resumeId: string) => {
    setFailure(null)
    setMerge(null)
    setProfileSec(0)
    setPhase('profiling')
    api
      .generateProfileAsync(resumeId)
      .then((started) => setJobId(started.job_id))
      .catch((err: unknown) => {
        setFailure({
          message: err instanceof ApiError ? err.message : '画像生成受理失败，请稍后重试',
          stage: 'profile',
          retryable: true,
        })
        setPhase('error')
      })
  }

  const upload = async (file: File) => {
    const localError = validateLocally(file)
    if (localError) {
      setFailure({ message: localError, stage: 'upload', retryable: false })
      setPhase('error')
      return
    }
    setPicked(file)
    setFailure(null)
    setMeta(null)
    metaRef.current = null
    setMerge(null)
    setUploadSec(0)
    setProfileSec(0)
    setPhase('uploading')

    const controller = new AbortController()
    abortRef.current = controller
    try {
      const result = await api.uploadResume(file, controller.signal)
      setMeta(result)
      metaRef.current = result
      setFlow({ hasResume: true })
      // 解析完成后画像在服务端后台生成，这里不再同步等待（r30）。
      startProfileJob(result.resume_id)
    } catch (err) {
      if (controller.signal.aborted) {
        // 上传被打断 = 简历没入库，直接回 idle，用户重选文件即可。
        setPhase('idle')
        return
      }
      setFailure({
        message: err instanceof ApiError ? err.message : '解析失败，请稍后重试',
        stage: 'upload',
        retryable: true,
      })
      setPhase('error')
    }
  }

  const retry = () => {
    if (failure === null) return
    if (failure.stage === 'upload') {
      if (picked) void upload(picked)
      return
    }
    const current = metaRef.current
    if (current === null) {
      setPhase('idle')
      return
    }
    startProfileJob(current.resume_id)
  }

  /** 取消（仅文件上传窗口）：中止在途请求，简历未入库，回到 idle 重选文件即可。 */
  const cancel = () => {
    abortRef.current?.abort()
    setUploadSec(0)
  }

  /** 确认离开：中止在途上传再跳转；简历未入库则重传，已入库则重新上传会走合并，不重复计费。 */
  const confirmLeave = () => {
    const href = pendingLeave
    setPendingLeave(null)
    abortRef.current?.abort()
    if (href !== null) navigate(href)
  }

  const reset = () => {
    metaRef.current = null
    abortRef.current?.abort()
    setPicked(null)
    setMeta(null)
    setMerge(null)
    setJobId(null)
    setFailure(null)
    setPhase('idle')
  }

  const handleFiles = (files: FileList | null) => {
    const first = files && files.length > 0 ? files[0] : null
    if (first) void upload(first)
  }

  const onDrop = (event: DragEvent<HTMLButtonElement>) => {
    event.preventDefault()
    setDragOver(false)
    handleFiles(event.dataTransfer.files)
  }

  const onInputChange = (event: ChangeEvent<HTMLInputElement>) => {
    handleFiles(event.target.files)
    event.target.value = ''
  }

  /** 进画像页时只在真的合并过时带 state（「本次合并」语义，刷新即消失）。 */
  const toProfile = () => {
    navigate('/profile', merge === null ? undefined : { state: { merge } })
  }

  /** 进润色页只带「刚上传」标记：润色页据此改引导文案，绝不据此自动调 AI。 */
  const toPolish = () => {
    navigate('/polish', { state: { fromUpload: true } })
  }

  return (
    <section>
      <header className="sc-page-header">
        <h1 className="sc-page-title">
          {saved === null ? '上传简历，建立你的技术画像' : '继续你的技术画像'}
        </h1>
        <p className="sc-page-sub">
          {saved === null
            ? '一次闭环：画像 → 面试 / 笔试 → 短板报告 → 课程'
            : '也可以上传新版简历：自动合并，保留原有能力与证据'}
        </p>
      </header>

      {/* 非 404 的画像读取失败：显式报错 + 重试，不当作「新用户」。 */}
      {savedError !== null ? (
        <InlineError message={savedError} onRetry={savedProfileAsync.reload} />
      ) : null}

      {phase === 'idle' && saved !== null ? (
        <Card>
          <div className="sc-upload-summary">
            <p className="sc-meta-line">你已有一份技术画像</p>
            <p className="sc-summary-meta">
              {`目标岗位 ${saved.target_role ?? '未填写'} · 技能 ${saved.skills.length} 项 · 项目 ${saved.projects.length} 个`}
            </p>
            <div className="sc-btn-row">
              <Link className="sc-btn sc-btn--primary" to="/profile">
                查看画像
              </Link>
              <Link className="sc-btn sc-btn--secondary" to="/interview">
                模拟面试
              </Link>
              <Link className="sc-btn sc-btn--secondary" to="/report">
                诊断报告
              </Link>
            </div>
          </div>
        </Card>
      ) : null}

      <button
        type="button"
        className={dragOver ? 'sc-dropzone is-dragover' : 'sc-dropzone'}
        onClick={() => inputRef.current?.click()}
        onDragOver={(event) => {
          event.preventDefault()
          setDragOver(true)
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
        disabled={busy}
      >
        <span className="sc-dropzone-inner">
          <span className="sc-dropzone-text">拖入或点击选择文件</span>
          <span className="sc-dropzone-hint">支持 PDF / DOCX / TXT · 单文件 ≤10MB</span>
        </span>
      </button>
      <input
        ref={inputRef}
        type="file"
        accept=".pdf,.docx,.txt"
        onChange={onInputChange}
        hidden
        aria-hidden="true"
        tabIndex={-1}
      />

      <div className="sc-chips">
        <Chip label="PDF / DOCX / TXT" />
        <Chip label="≤10MB" />
        <Chip label="解析约 30 秒 · 生成在后台进行" />
      </div>

      {/* 新用户引导（r27）：练习与教程不依赖画像，先把这两个免简历入口摆在首屏，
          否则不想 / 不能立刻传简历的用户在首页找不到任何可做的事。 */}
      {saved === null && savedError === null && phase === 'idle' ? (
        <p className="sc-meta-line">
          暂时没有简历？<Link to="/practice">在线练习</Link>和<Link to="/learn">站内教程</Link>
          不需要简历，现在就能用。
        </p>
      ) : null}

      {failure !== null && phase === 'error' ? (
        <div className="sc-actions">
          <InlineError
            message={failure.message}
            onRetry={failure.retryable ? retry : undefined}
          />
          {failure.stage === 'profile' && meta !== null ? (
            <div className="sc-btn-row">
              <Button variant="secondary" onClick={toProfile}>
                先去画像页
              </Button>
            </div>
          ) : null}
        </div>
      ) : null}

      {phase === 'uploading' ? (
        <div className="sc-actions">
          <Card>
            <div className="sc-upload-summary">
              <RingProgress size={56} state="indeterminate" ariaLabel="解析中" />
              <PhaseLoader
                phases={['上传简历', '解析简历 → 提取正文', 'AI 生成并合并画像']}
                active={1}
                elapsedSec={uploadSec}
                title={picked ? picked.name : undefined}
              />
              <div className="sc-actions">
                <Button variant="ghost" size="sm" onClick={cancel}>
                  取消
                </Button>
              </div>
            </div>
          </Card>
        </div>
      ) : null}

      {phase === 'profiling' ? (
        <div className="sc-actions">
          <Card>
            <div className="sc-upload-summary">
              <RingProgress size={56} state="indeterminate" ariaLabel="生成画像" />
              <PhaseLoader
                phases={['上传简历', '解析简历 → 提取正文', 'AI 生成并合并画像']}
                active={2}
                elapsedSec={profileSec}
                title={meta ? `${meta.file_name} · 正在生成可溯源画像` : undefined}
              />
              {/* r30：任务在服务端跑，离开本页不会中断 —— 给出口而不是给拦截。 */}
              <p className="sc-meta-line">
                画像在后台生成，离开本页不会中断，回来后会自动接上进度。
              </p>
              <div className="sc-btn-row">
                <Link className="sc-btn sc-btn--secondary" to="/practice">
                  先去练习
                </Link>
                <Link className="sc-btn sc-btn--secondary" to="/learn">
                  看站内教程
                </Link>
              </div>
            </div>
          </Card>
        </div>
      ) : null}

      {phase === 'done' && meta ? (
        <div className="sc-actions">
          <Card>
            <div className="sc-upload-summary">
              <p className="sc-file-name">{meta.file_name}</p>
              <p className="sc-summary-meta">
                抽取 {formatChars(meta.chars)} · {meta.sections} 章节
              </p>

              {merge !== null ? (
                <>
                  <p className={merge.duplicate ? 'sc-meta-line' : 'sc-summary-meta'}>
                    {`本次合并 · ${mergeSummaryText(merge)}`}
                  </p>
                  <p className="sc-meta-line">原有能力与证据不会被覆盖，可在画像页逐条核溯源</p>
                  {merge.duplicate ? (
                    <div className="sc-chips">
                      <Chip label="同一份简历 · 仍记为一次成长事件" />
                    </div>
                  ) : null}
                </>
              ) : null}

              <div className="sc-actions">
                <Button onClick={toProfile}>查看画像</Button>
                <Button variant="secondary" onClick={toPolish}>
                  继续润色这份简历
                </Button>
                <Button variant="ghost" onClick={reset}>
                  重新上传
                </Button>
              </div>
            </div>
          </Card>
        </div>
      ) : null}
      <ConfirmModal
        open={pendingLeave !== null}
        title="简历还在上传，离开会中断"
        message="上传中断后需要重新选择文件再传一次。刷新或关闭页面同样会中断。"
        confirmLabel="仍然离开"
        cancelLabel="留在本页"
        onConfirm={confirmLeave}
        onCancel={() => setPendingLeave(null)}
      />
    </section>
  )
}
