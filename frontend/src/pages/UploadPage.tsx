import { useEffect, useRef, useState } from 'react'
import type { ChangeEvent, DragEvent } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { ApiError, api } from '../api/client'
import type { ProfileMergeSummary, ResumeMeta } from '../api/types'
import { mergeSummaryText } from '../components/profile/mergeModel'
import { Button } from '../components/ui/Button'
import { Chip } from '../components/ui/Chip'
import { ConfirmModal } from '../components/ui/ConfirmModal'
import { InlineError } from '../components/ui/InlineError'
import { PhaseLoader } from '../components/ui/PhaseLoader'
import { RingProgress } from '../components/ui/RingProgress'
import { formatChars } from '../lib/format'
import {
  PROFILE_JOB_POLL_MS,
  isJobRunning,
  jobElapsedSec,
  jobFailureNotice,
  jobToResumeMeta,
  shouldReattach,
  shouldSurfaceFailure,
} from '../lib/profileJob'
import { useAsync } from '../lib/useAsync'
import { setFlow, useFlowState } from '../state/flow'

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
  const flow = useFlowState()
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
  // completed 的历史任务不重放（shouldReattach 只认 running），
  // 完成态走 savedProfile 读路径呈现「已有画像」摘要卡。
  // r32：最近一次任务是 failed 时必须明示原因 —— 否则「离开后任务在后台失败」
  // 回来毫无痕迹，正是「上传失败却没报错」的主因；重试走 job.document_id。
  useEffect(() => {
    if (reattachRef.current) return
    reattachRef.current = true
    api
      .latestProfileJob()
      .then((job) => {
        if (phaseRef.current !== 'idle') return
        if (shouldReattach(job)) {
          const resumed = jobToResumeMeta(job)
          setPicked(null)
          setMeta(resumed)
          metaRef.current = resumed
          setPhase('profiling')
          setJobId(job.job_id)
          // r35：秒数从任务真实起点起算，不从 0 重计（不然刚回来就「已用 1s」）。
          setProfileSec(jobElapsedSec(job))
          return
        }
        if (shouldSurfaceFailure(job)) {
          const resumed = jobToResumeMeta(job)
          setMeta(resumed)
          metaRef.current = resumed
          setFailure({
            message: jobFailureNotice(job),
            stage: 'profile',
            retryable: true,
          })
          setPhase('error')
        }
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
          setFailure({ message: jobFailureNotice(job), stage: 'profile', retryable: true })
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

  /** 简历 / 画像里的证据条数：优先累计证据，没有时用兼容字段记 1 条。 */
  const evidenceCount = (item: { source_quote?: string; source_quotes?: unknown[] }) =>
    Math.max(item.source_quotes?.length ?? 0, item.source_quote ? 1 : 0)

  const activeFile = picked?.name ?? meta?.file_name ?? null
  const parseState = busy
    ? phase === 'uploading'
      ? `UPLOADING ${uploadSec}s`
      : `PROFILING ${profileSec}s`
    : saved !== null
      ? 'READY'
      : 'IDLE'

  /** 五步管线：本机记录与页内阶段合并成「已完成 / 进行中 / 待做」。 */
  const pipeline = [
    {
      num: '01',
      title: '上传简历',
      desc: '解析正文与章节，不保存原文件',
      state: flow.hasResume ? 'done' : phase === 'uploading' ? 'now' : 'todo',
    },
    {
      num: '02',
      title: '建立画像',
      desc: '技能 / 项目 / 证据逐条可溯源',
      state: flow.hasProfile ? 'done' : phase === 'profiling' ? 'now' : 'todo',
    },
    {
      num: '03',
      title: '模拟面试',
      desc: '按画像出题，作答即时评分',
      state: flow.hasInterview ? 'done' : 'todo',
    },
    {
      num: '04',
      title: '模拟笔试',
      desc: '客观题定位知识盲区',
      state: flow.hasExam ? 'done' : 'todo',
    },
    {
      num: '05',
      title: '诊断报告',
      desc: '短板按证据排序，直连精选课程',
      state: flow.hasReport ? 'done' : 'todo',
    },
  ] as const

  return (
    <section className="sc-lab-home">
      <header className="sc-lab-hero">
        <div className="sc-lab-hero-copy">
          <p className="sc-lab-kicker sc-lab-rise">
            <span className="sc-lab-kicker-idx">01</span> COMPILE PROFILE
          </p>
          <h1 className="sc-lab-hero-title sc-lab-rise is-d1">
            {saved === null ? (
              <>
                上传简历，
                <br />
                建立<span className="sc-lab-hl">可溯源</span>
                <br />
                的技术画像
              </>
            ) : (
              <>
                继续你的
                <br />
                <span className="sc-lab-hl">技术画像</span>
              </>
            )}
          </h1>
          <p className="sc-lab-lead sc-lab-rise is-d2">
            {saved === null
              ? '从一份简历出发：抽取技能与项目，把每条结论都钉回原文，再用面试与笔试定位真实的短板。'
              : '你的画像已经就绪。可以直接开始面试或笔试，也可以上传新版简历让它继续长大。'}
          </p>
          <div className="sc-lab-cta sc-lab-rise is-d3">
            <button
              type="button"
              className="sc-btn sc-btn--primary sc-lab-cta-btn"
              onClick={() => inputRef.current?.click()}
              disabled={busy}
            >
              选择简历文件
              <span className="sc-lab-arrow" aria-hidden="true">
                ↗
              </span>
            </button>
            <Link className="sc-lab-ghost" to={saved === null ? '/learn' : '/profile'}>
              {saved === null ? '先看站内教程 →' : '查看我的画像 →'}
            </Link>
          </div>
          {saved === null && savedError === null && phase === 'idle' ? (
            <p className="sc-lab-note sc-lab-rise is-d4">
              暂时没有简历？<Link to="/practice">在线练习</Link>和
              <Link to="/learn">站内教程</Link>不需要简历，现在就能用。
            </p>
          ) : saved !== null ? (
            <p className="sc-lab-note sc-lab-rise is-d4">
              重新上传会自动合并：原有能力与证据不会被覆盖，逐条仍可核溯源。
            </p>
          ) : null}
        </div>

        {/* 解析仪器：把「简历 → 画像」的过程做成一台看得见的读数面板 */}
        <aside className="sc-lab-parse sc-lab-rise is-d2" aria-label="画像解析面板">
          <div className="sc-lab-parse-head">
            <span>PARSE STREAM</span>
            <span className={busy ? 'sc-lab-parse-live is-busy' : 'sc-lab-parse-live'}>
              <i aria-hidden="true" />
              {parseState}
            </span>
          </div>

          {saved !== null && !busy ? (
            <>
              <div className="sc-lab-parse-file">
                <span className="sc-lab-parse-name">{saved.target_role ?? '目标岗位未填写'}</span>
                <span className="sc-lab-parse-meta">
                  {`技能 ${saved.skills.length} 项 · 项目 ${saved.projects.length} 个 · 证据 ${saved.skills.reduce(
                    (sum, skill) => sum + evidenceCount(skill),
                    0,
                  ) + saved.projects.reduce((sum, project) => sum + evidenceCount(project), 0)} 条`}
                </span>
                <div className="sc-lab-scan">
                  <span className="sc-lab-scan-fill" style={{ width: '100%' }} />
                </div>
              </div>
              <div className="sc-lab-toks">
                {saved.skills.slice(0, 4).map((skill) => (
                  <div className="sc-lab-tok" key={`skill-${skill.name}`}>
                    <span className="sc-lab-tok-k">SKILL</span>
                    <span className="sc-lab-tok-v">{skill.name}</span>
                    <span className="sc-lab-bars" aria-hidden="true">
                      {[0, 1, 2, 3, 4].map((index) => (
                        <i
                          key={index}
                          className={index < Math.min(5, evidenceCount(skill)) ? 'is-on' : undefined}
                        />
                      ))}
                    </span>
                    <span className="sc-lab-tok-s">{evidenceCount(skill)} 证</span>
                  </div>
                ))}
                {saved.projects.slice(0, 2).map((project) => (
                  <div className="sc-lab-tok" key={`project-${project.name}`}>
                    <span className="sc-lab-tok-k">PROJECT</span>
                    <span className="sc-lab-tok-v">{project.name}</span>
                    <span className="sc-lab-bars" aria-hidden="true">
                      {[0, 1, 2, 3, 4].map((index) => (
                        <i
                          key={index}
                          className={index < Math.min(5, evidenceCount(project)) ? 'is-on' : undefined}
                        />
                      ))}
                    </span>
                    <span className="sc-lab-tok-s">{evidenceCount(project)} 证</span>
                  </div>
                ))}
              </div>
              <div className="sc-lab-parse-foot">
                <span>
                  证据 <b>{saved.tech_stack.length}</b> 项技术栈
                </span>
                <span>原文未保存</span>
              </div>
            </>
          ) : (
            <>
              <div className="sc-lab-parse-file">
                <span className="sc-lab-parse-name">{activeFile ?? '等待简历文件'}</span>
                <span className="sc-lab-parse-meta">
                  {busy ? '解析正文 → 抽取能力 → 合并画像' : 'PDF / DOCX / TXT · ≤10MB · 解析约 30 秒'}
                </span>
                <div className="sc-lab-scan">
                  {busy ? <span className="sc-lab-scan-echo" /> : null}
                </div>
              </div>
              <ul className="sc-lab-stages">
                <li>
                  <span>01</span> 解析正文与章节
                </li>
                <li>
                  <span>02</span> 抽取技能 / 项目 / 证据
                </li>
                <li>
                  <span>03</span> 合并成可溯源画像
                </li>
              </ul>
              <div className="sc-lab-parse-foot">
                <span>不保存原文件</span>
                <span>只存抽取正文</span>
              </div>
            </>
          )}
        </aside>
      </header>

      {/* 非 404 的画像读取失败：显式报错 + 重试，不当作「新用户」。 */}
      {savedError !== null ? (
        <InlineError message={savedError} onRetry={savedProfileAsync.reload} />
      ) : null}

      <button
        type="button"
        className={dragOver ? 'sc-lab-dropband is-dragover' : 'sc-lab-dropband'}
        onClick={() => inputRef.current?.click()}
        onDragOver={(event) => {
          event.preventDefault()
          setDragOver(true)
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
        disabled={busy}
      >
        <span className="sc-lab-drop-kicker">DROP</span>
        <span className="sc-lab-drop-main">拖入或点击选择文件</span>
        <span className="sc-lab-drop-meta">PDF / DOCX / TXT · 单文件 ≤10MB</span>
        <span className="sc-lab-drop-cta">选择文件 ↗</span>
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

      {phase === 'idle' && saved !== null ? (
        <div className="sc-lab-existing">
          <span className="sc-lab-tag">已有画像 · 回访</span>
          <span className="sc-lab-existing-text">
            {`目标岗位 ${saved.target_role ?? '未填写'} · 技能 ${saved.skills.length} 项 · 项目 ${saved.projects.length} 个`}
          </span>
          <span className="sc-lab-existing-links">
            <Link className="sc-lab-ghost" to="/profile">
              查看画像 →
            </Link>
            <Link className="sc-lab-ghost" to="/interview">
              模拟面试 →
            </Link>
            <Link className="sc-lab-ghost" to="/report">
              诊断报告 →
            </Link>
          </span>
        </div>
      ) : null}

      {failure !== null && phase === 'error' ? (
        <div className="sc-lab-panel">
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
        <div className="sc-lab-panel">
          <div className="sc-upload-progress">
            <RingProgress size={56} state="indeterminate" ariaLabel="解析中" />
            <PhaseLoader
              phases={['上传简历', '解析简历 → 提取正文', 'AI 生成并合并画像']}
              active={0}
              elapsedSec={uploadSec}
              title={picked ? picked.name : undefined}
            />
          </div>
          <div className="sc-actions">
            <Button variant="ghost" size="sm" onClick={cancel}>
              取消
            </Button>
          </div>
        </div>
      ) : null}

      {phase === 'profiling' ? (
        <div className="sc-lab-panel">
          <div className="sc-upload-progress">
            <RingProgress size={56} state="indeterminate" ariaLabel="生成画像" />
            <PhaseLoader
              phases={['上传简历', '解析简历 → 提取正文', 'AI 生成并合并画像']}
              active={2}
              elapsedSec={profileSec}
              title={meta ? `${meta.file_name} · 正在生成可溯源画像` : undefined}
            />
          </div>
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
      ) : null}

      {phase === 'done' && meta ? (
        <div className="sc-lab-panel">
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
      ) : null}

      <section className="sc-lab-pipeline" aria-label="五步闭环">
        <div className="sc-lab-pipeline-head">
          <h2>一次闭环，五步</h2>
          <p>UPLOAD → PROFILE → MEASURE → REPAIR</p>
        </div>
        <div className="sc-lab-pipe-grid">
          {pipeline.map((step) => (
            <article
              className={
                step.state === 'done'
                  ? 'sc-lab-pipe is-done'
                  : step.state === 'now'
                    ? 'sc-lab-pipe is-now'
                    : 'sc-lab-pipe'
              }
              key={step.num}
            >
              <span className="sc-lab-pipe-num">{step.num}</span>
              <h3>{step.title}</h3>
              <p>{step.desc}</p>
              <span className="sc-lab-pipe-state">
                {step.state === 'done' ? 'DONE' : step.state === 'now' ? 'RUNNING' : 'TODO'}
              </span>
            </article>
          ))}
        </div>
      </section>

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
