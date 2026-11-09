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
import {
  HEIC_UNSUPPORTED_HINT,
  clearUploadSession,
  elapsedSince,
  isHeifFile,
  readUploadSession,
  shouldReplayCompleted,
  writeUploadSession,
} from '../lib/uploadSession'
import { useAsync } from '../lib/useAsync'
import { setFlow, useFlowState } from '../state/flow'
import { useAuth } from '../state/auth'

const MAX_UPLOAD_MB = 10
const MAX_BYTES = MAX_UPLOAD_MB * 1024 * 1024
const ACCEPTED = ['.pdf', '.docx', '.txt']
/** r41：图片入口上限 3 张（与后端 `MAX_IMAGE_COUNT` 同口径）。 */
const MAX_IMAGES = 3
/** 预处理：最长边压到 1600（服务端还会按 ~1300 再缩，这里只为省流量与缩短上传）。 */
const IMAGE_MAX_EDGE = 1600
const IMAGE_QUALITY = 0.85

/**
 * 一张已预处理待上传的图片。`url` 是压缩后 JPEG 的 object URL（仅本页预览用，
 * 删除 / 重置 / 卸载时必须 revoke，原图字节不会随请求之外留在内存）。
 */
interface PickedImage {
  url: string
  file: File
}

function loadImageElement(url: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new window.Image()
    image.onload = () => resolve(image)
    image.onerror = () => reject(new Error('这张图片打不开，请重新拍照或改用 PDF'))
    image.src = url
  })
}

/**
 * 手机相册图 → JPEG：EXIF 方向由浏览器渲染时校正（现代 Chrome / Safari 默认 from-image），
 * canvas 等比缩放到最长边 1600 后按 0.85 质量重编码。解码失败（HEIC / 损坏）直接给中文提示。
 */
async function compressImage(file: File): Promise<File> {
  const sourceUrl = URL.createObjectURL(file)
  try {
    const image = await loadImageElement(sourceUrl)
    const scale = Math.min(1, IMAGE_MAX_EDGE / Math.max(image.naturalWidth, image.naturalHeight))
    const width = Math.max(1, Math.round(image.naturalWidth * scale))
    const height = Math.max(1, Math.round(image.naturalHeight * scale))
    const canvas = document.createElement('canvas')
    canvas.width = width
    canvas.height = height
    const context = canvas.getContext('2d')
    if (context === null) throw new Error('当前浏览器无法处理图片，请改用 PDF 上传')
    // JPEG 无透明通道：先铺白底，避免 PNG 截图透明区被压成黑色。
    context.fillStyle = '#ffffff'
    context.fillRect(0, 0, width, height)
    context.drawImage(image, 0, 0, width, height)
    const blob = await new Promise<Blob | null>((resolve) =>
      canvas.toBlob(resolve, 'image/jpeg', IMAGE_QUALITY),
    )
    if (blob === null) throw new Error('这张图片打不开，请重新拍照或改用 PDF')
    const name = `${file.name.replace(/\.[^.]+$/, '') || 'resume'}.jpg`
    return new File([blob], name, { type: 'image/jpeg' })
  } finally {
    URL.revokeObjectURL(sourceUrl)
  }
}

/**
 * 页面阶段（r42）：idle →（文档上传解析，仍同步）→ profiling（画像后台任务）→ done；
 * 图片入口是 idle → recognizing（图片识别后台任务，可离开）→ profiling → done。
 * 任一步失败进 error 并记住失败在哪一步（重试只重跑那一步）。
 * 后台任务没有「取消」：离开不丢进度，回来自动接上。
 */
type Phase = 'idle' | 'uploading' | 'recognizing' | 'profiling' | 'done' | 'error'

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
    return `文件超过 ${MAX_UPLOAD_MB}MB，请压缩或分卷`
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
  /** r41：拍照（capture=environment，单选）与相册选择（multiple，最多 3 张）两个独立入口。 */
  const captureRef = useRef<HTMLInputElement>(null)
  const pickImagesRef = useRef<HTMLInputElement>(null)
  const [images, setImages] = useState<PickedImage[]>([])
  /** images 的镜像：卸载兜底 revoke object URL 用（不随每次渲染重建 cleanup）。 */
  const imagesRef = useRef<PickedImage[]>([])
  imagesRef.current = images
  /** 图片选择 / 压缩阶段的本地错误：不打断页面，改选即可（与服务端失败的重试面板分开）。 */
  const [imageError, setImageError] = useState<string | null>(null)
  const [imageLoading, setImageLoading] = useState(false)
  /** 只保护文件上传这一段在途请求；画像任务在服务端，卸载不需要（也不应该）中止它。 */
  const abortRef = useRef<AbortController | null>(null)
  const [phase, setPhase] = useState<Phase>('idle')
  const [dragOver, setDragOver] = useState(false)
  const [picked, setPicked] = useState<File | null>(null)
  const [meta, setMeta] = useState<ResumeMeta | null>(null)
  /** meta 的镜像：失败重试时取 resume_id 重新受理画像任务。 */
  const metaRef = useRef<ResumeMeta | null>(null)
  const [jobId, setJobId] = useState<string | null>(null)
  /** r42：图片识别后台任务 id（与画像任务分开轮询，先识别后生成）。 */
  const [resumeJobId, setResumeJobId] = useState<string | null>(null)
  const [merge, setMerge] = useState<ProfileMergeSummary | null>(null)
  const [failure, setFailure] = useState<Failure | null>(null)
  const [uploadSec, setUploadSec] = useState(0)
  const [profileSec, setProfileSec] = useState(0)
  /** r42：断网 / 轮询异常的中文提示（不白屏、不误判任务失败）。 */
  const [netNotice, setNetNotice] = useState<string | null>(null)
  /** 上传中点了站内链接：先确认再跳（后台任务阶段不拦截）。 */
  const [pendingLeave, setPendingLeave] = useState<string | null>(null)
  /** r42：本地会话的账号作用域；登录态就绪后才读本地会话。 */
  const userId = useAuth().me?.id ?? null
  /** 重接入按「恢复轮次」只跑一次（StrictMode 双跑由 ref 挡住；手动重试 +1 轮）。 */
  const [recoverTick, setRecoverTick] = useState(0)
  const recoverTickRef = useRef(-1)
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
    if (phase !== 'uploading' && phase !== 'recognizing' && phase !== 'profiling') return
    // 前两段都是「解析 / 识别」计时，第三段是画像生成计时。
    const bump =
      phase === 'profiling' ? setProfileSec : setUploadSec
    const timer = window.setInterval(() => bump((value) => value + 1), 1000)
    return () => window.clearInterval(timer)
  }, [phase])

  const busy = phase === 'uploading' || phase === 'recognizing' || phase === 'profiling'
  /** 压缩 / 选图期间也锁入口，避免并发编排顺序错乱（服务端上限仍是最终闸门）。 */
  const controlsLocked = busy || imageLoading

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

  // r41：缩略图预览是 object URL，删除 / 重置之外的兜底在卸载时统一 revoke（不泄漏内存）。
  useEffect(
    () => () => imagesRef.current.forEach((image) => URL.revokeObjectURL(image.url)),
    [],
  )

  // r42 重接入（在 r30 的「服务端 running 接上」之上补本地会话）：
  // 1) 先读本机上传会话（同一台设备上的那次上传，锁屏 / 切 App / 刷新后仍是「我这次」）；
  //    running → 直接接上轮询；completed（30 分钟内）→ 回放结果，三态连续不空白；
  //    failed（24 小时内，r33 口径）→ 明示原因并重试；更早的完成 / 失败不打扰。
  // 2) 没有本地会话（换设备 / 清缓存）时回落到服务端 latest：图片识别任务 + 画像任务。
  // 3) 网络异常不能白屏：给中文提示 + 「重试接上」，任务本身仍在服务端跑。
  useEffect(() => {
    if (userId === null) return
    if (recoverTickRef.current === recoverTick) return
    recoverTickRef.current = recoverTick
    let cancelled = false

    const run = async () => {
      const session = readUploadSession(userId)
      if (session !== null && session.profile_job_id !== undefined) {
        try {
          const job = await api.getProfileJob(session.profile_job_id)
          if (cancelled) return
          if (shouldReattach(job)) {
            const resumed = jobToResumeMeta(job)
            setPicked(null)
            setMeta(resumed)
            metaRef.current = resumed
            setPhase('profiling')
            setJobId(job.job_id)
            setProfileSec(jobElapsedSec(job))
            return
          }
          if (job.status === 'completed' && job.result !== null) {
            const resumed = jobToResumeMeta(job)
            setPicked(null)
            setMeta(resumed)
            metaRef.current = resumed
            writeUploadSession(userId, {
              source: session.source,
              profile_job_id: job.job_id,
              meta: resumed,
            })
            if (shouldReplayCompleted(job.created_at)) {
              setMerge(job.result.merge_summary ?? null)
              setFlow({ hasResume: true, hasProfile: true })
              setPhase('done')
              void reloadSavedProfile()
            } else {
              // 久远的完成回放会霸占页面：清掉本地会话，回到「已有画像」读路径。
              clearUploadSession(userId)
            }
            return
          }
          if (shouldSurfaceFailure(job)) {
            const resumed = jobToResumeMeta(job)
            setMeta(resumed)
            metaRef.current = resumed
            setFailure({ message: jobFailureNotice(job), stage: 'profile', retryable: true })
            setPhase('error')
            return
          }
          clearUploadSession(userId)
          return
        } catch (err) {
          if (cancelled) return
          if (!(err instanceof ApiError && err.status === 404)) {
            setNetNotice('网络异常，暂时无法恢复上次的上传进度；恢复网络后点「重试接上」即可。')
            return
          }
          clearUploadSession(userId)
          // 404 = 任务行被清理，继续往下走服务端兜底
        }
      }

      if (session !== null && session.resume_job_id !== undefined) {
        try {
          const job = await api.getResumeJob(session.resume_job_id)
          if (cancelled) return
          if (job.status === 'running') {
            setPicked(null)
            setMeta(session.meta ?? null)
            metaRef.current = session.meta ?? null
            setPhase('recognizing')
            setResumeJobId(job.job_id)
            setUploadSec(elapsedSince(job.created_at))
            return
          }
          if (job.status === 'completed' && job.result !== null) {
            // 识别早已完成、画像还没受理（例如在受理前离开）：从已完成处继续生成画像。
            const resumed = job.result
            setPicked(null)
            setMeta(resumed)
            metaRef.current = resumed
            setFlow({ hasResume: true })
            writeUploadSession(userId, { source: 'image', resume_job_id: job.job_id, meta: resumed })
            startProfileJob(resumed.resume_id)
            return
          }
          setFailure({
            message: job.error || '图片识别失败，请重新上传图片',
            stage: 'upload',
            retryable: true,
          })
          setPhase('error')
          return
        } catch (err) {
          if (cancelled) return
          if (!(err instanceof ApiError && err.status === 404)) {
            setNetNotice('网络异常，暂时无法恢复上次的上传进度；恢复网络后点「重试接上」即可。')
            return
          }
          clearUploadSession(userId)
        }
      }

      // 服务端兜底（跨设备 / 本地会话已被清理）：先看图片识别，再看画像。
      try {
        const resumeJob = await api.latestResumeJob()
        if (cancelled) return
        if (resumeJob.status === 'running') {
          setPicked(null)
          setPhase('recognizing')
          setResumeJobId(resumeJob.job_id)
          setUploadSec(elapsedSince(resumeJob.created_at))
          return
        }
      } catch {
        /* 404 = 没有识别任务，正常路径 */
      }
      try {
        const job = await api.latestProfileJob()
        if (cancelled || phaseRef.current !== 'idle') return
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
          setFailure({ message: jobFailureNotice(job), stage: 'profile', retryable: true })
          setPhase('error')
        }
      } catch {
        /* 404 = 没有任务，正常新用户路径；其它错误也静默 —— 生成不是本页必现状态 */
      }
    }

    void run()
    return () => {
      cancelled = true
    }
    // startProfileJob 是「受理 + 写本地会话」的组件内动作，身份随渲染变化；放进依赖会导致
    // 恢复流程反复触发。它只读 ref / setState，行为等价稳定，故刻意排除。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId, recoverTick, reloadSavedProfile])

  // r30 轮询：每 2 秒查一次任务状态。网络抖动继续轮（不轻易判死）；
  // 404 说明任务行没了，如实报错。轮询随卸载/终态自动停止，任务本身在服务端照跑。
  // r42：连续两次取不到状态就给中文提示（断网 / 弱网），但仍继续重试，不误判任务失败。
  useEffect(() => {
    if (jobId === null) return
    let stopped = false
    let timer = 0
    let failures = 0
    const poll = async () => {
      try {
        const job = await api.getProfileJob(jobId)
        if (stopped) return
        failures = 0
        setNetNotice(null)
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
        failures += 1
        if (failures >= 2) {
          setNetNotice(
            typeof navigator !== 'undefined' && navigator.onLine === false
              ? '网络已断开：画像仍在服务端生成，恢复网络后会自动接上。'
              : '网络连接不稳定，正在自动重试；任务在服务端继续，不会丢失。',
          )
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

  // r42 图片识别轮询：与画像任务分开（先识别出正文入库，再受理画像任务）。
  // 识别在服务端后台跑，离开页面不中止；completed 后自动进入 profiling，三态连续。
  useEffect(() => {
    if (resumeJobId === null) return
    let stopped = false
    let timer = 0
    let failures = 0
    const poll = async () => {
      try {
        const job = await api.getResumeJob(resumeJobId)
        if (stopped) return
        failures = 0
        setNetNotice(null)
        if (job.status === 'running') {
          timer = window.setTimeout(() => void poll(), PROFILE_JOB_POLL_MS)
          return
        }
        setResumeJobId(null)
        if (job.status === 'completed' && job.result !== null) {
          const result = job.result
          setMeta(result)
          metaRef.current = result
          setFlow({ hasResume: true })
          writeUploadSession(userId, {
            source: 'image',
            resume_job_id: job.job_id,
            meta: result,
          })
          startProfileJob(result.resume_id)
        } else {
          setFailure({
            message: job.error || '图片识别失败，请重新上传图片',
            stage: 'upload',
            retryable: true,
          })
          setPhase('error')
        }
      } catch (err) {
        if (stopped) return
        if (err instanceof ApiError && err.status === 404) {
          setResumeJobId(null)
          setFailure({
            message: '图片识别任务已不存在，请重新上传图片',
            stage: 'upload',
            retryable: true,
          })
          setPhase('error')
          return
        }
        failures += 1
        if (failures >= 2) {
          setNetNotice(
            typeof navigator !== 'undefined' && navigator.onLine === false
              ? '网络已断开：图片仍在服务端识别，恢复网络后会自动接上。'
              : '网络连接不稳定，正在自动重试；识别任务在服务端继续，不会丢失。',
          )
        }
        timer = window.setTimeout(() => void poll(), PROFILE_JOB_POLL_MS)
      }
    }
    timer = window.setTimeout(() => void poll(), PROFILE_JOB_POLL_MS)
    return () => {
      stopped = true
      window.clearTimeout(timer)
    }
    // startProfileJob 同上的「行为稳定但身份易变」动作，放进依赖会重复受理，故排除。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resumeJobId, userId])

  // r42 断网事件直报：不等下一轮轮询，立刻给中文提示；联网后清掉提示、轮询自然恢复。
  useEffect(() => {
    const inFlight = () =>
      phaseRef.current === 'uploading' ||
      phaseRef.current === 'recognizing' ||
      phaseRef.current === 'profiling'
    const onOffline = () => {
      if (!inFlight()) return
      setNetNotice('网络已断开：任务仍在服务端继续，恢复网络后会自动接上。')
    }
    const onOnline = () => setNetNotice(null)
    window.addEventListener('offline', onOffline)
    window.addEventListener('online', onOnline)
    return () => {
      window.removeEventListener('offline', onOffline)
      window.removeEventListener('online', onOnline)
    }
  }, [])

  /** 画像生成（r30 起为后台任务）：受理即返回，状态由轮询 effect 接管。 */
  const startProfileJob = (resumeId: string) => {
    setFailure(null)
    setMerge(null)
    setProfileSec(0)
    setNetNotice(null)
    setPhase('profiling')
    api
      .generateProfileAsync(resumeId)
      .then((started) => {
        setJobId(started.job_id)
        const current = metaRef.current
        if (current !== null) {
          // 记下「本次上传」的画像任务，刷新 / 锁屏回来后能立即接上（r42 本地会话）。
          writeUploadSession(userId, {
            source: current.source_type === 'image' ? 'image' : 'file',
            profile_job_id: started.job_id,
            meta: current,
          })
        }
      })
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

  /**
   * r41：选择 / 拍照后先在本机预处理（EXIF 方向 + 压到最长边 1600 + JPEG 0.85），
   * 只把压缩后的 File 放进待上传队列；超过 3 张的部分直接截断并给出提示。
   * r42：先按真实字节识别 HEIC —— iOS Safari 通常会把相册选图转成 JPEG，但「文件」入口
   * 会原样送出 HEIC；本机解码失败时给出「相机格式改成兼容性最佳 / 导出 JPG」的替代路径，
   * 而不是笼统的「图片打不开」（也避免后端收到 HEIC 才报错才让用户重选）。
   */
  const addImages = async (files: FileList | null) => {
    if (controlsLocked) return
    const incoming = files ? Array.from(files) : []
    if (incoming.length === 0) return
    const room = MAX_IMAGES - images.length
    if (room <= 0) {
      setImageError(`一次最多上传 ${MAX_IMAGES} 张图片，请先删除一张`)
      return
    }
    if (incoming.length > room) {
      setImageError(`一次最多上传 ${MAX_IMAGES} 张图片，本次只保留前 ${room} 张`)
    } else {
      setImageError(null)
    }
    setImageLoading(true)
    try {
      const prepared: PickedImage[] = []
      for (const file of incoming.slice(0, room)) {
        if (file.size > MAX_BYTES) throw new Error(`图片超过 ${MAX_UPLOAD_MB}MB，请压缩后重试`)
        if (await isHeifFile(file)) throw new Error(HEIC_UNSUPPORTED_HINT)
        const compressed = await compressImage(file)
        prepared.push({ url: URL.createObjectURL(compressed), file: compressed })
      }
      setImages((prev) => [...prev, ...prepared].slice(0, MAX_IMAGES))
    } catch (err) {
      setImageError(err instanceof Error ? err.message : '图片处理失败，请重新选择')
    } finally {
      setImageLoading(false)
    }
  }

  const removeImage = (index: number) => {
    setImageError(null)
    setImages((prev) => {
      const target = prev[index]
      if (target !== undefined) URL.revokeObjectURL(target.url)
      return prev.filter((_, position) => position !== index)
    })
  }

  const clearImages = () => {
    setImageError(null)
    imagesRef.current.forEach((image) => URL.revokeObjectURL(image.url))
    setImages([])
  }

  /**
   * 图片入口上传（r42 异步）：受理即返回 `job_id`，识别在服务端后台跑；
   * 本页只轮询。离开 / 锁屏不中止任务，回来由本地会话自动接上。
   */
  const uploadImages = async () => {
    if (images.length === 0 || busy) return
    setPicked(null)
    setFailure(null)
    setImageError(null)
    setMeta(null)
    metaRef.current = null
    setMerge(null)
    setUploadSec(0)
    setProfileSec(0)
    setResumeJobId(null)
    setNetNotice(null)
    setPhase('recognizing')

    const controller = new AbortController()
    abortRef.current = controller
    try {
      const started = await api.uploadResumeImagesAsync(
        images.map((image) => image.file),
        controller.signal,
      )
      setResumeJobId(started.job_id)
      // 本地会话：识别任务在服务端跑，凭这个 id 回来接上。
      writeUploadSession(userId, { source: 'image', resume_job_id: started.job_id })
    } catch (err) {
      if (controller.signal.aborted) {
        setPhase('idle')
        return
      }
      setFailure({
        message: err instanceof ApiError ? err.message : '图片识别受理失败，请稍后重试',
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
      else if (images.length > 0) void uploadImages()
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
    clearImages()
    setPicked(null)
    setMeta(null)
    setMerge(null)
    setJobId(null)
    setResumeJobId(null)
    setFailure(null)
    setNetNotice(null)
    // 用户主动重新上传 = 这次会话结束，清掉本地恢复锚点（后台任务仍在服务端跑完）。
    clearUploadSession(userId)
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

  const onCaptureChange = (event: ChangeEvent<HTMLInputElement>) => {
    void addImages(event.target.files)
    event.target.value = ''
  }

  const onPickImagesChange = (event: ChangeEvent<HTMLInputElement>) => {
    void addImages(event.target.files)
    event.target.value = ''
  }

  /** 进画像页时只在真的合并过时带 state（「本次合并」语义，刷新即消失）。 */
  const toProfile = () => {
    // 流程走完了：清掉本地恢复锚点，下次回上传页按「已有画像」呈现，不重放旧结果。
    clearUploadSession(userId)
    navigate('/profile', merge === null ? undefined : { state: { merge } })
  }

  /** 进润色页只带「刚上传」标记：润色页据此改引导文案，绝不据此自动调 AI。 */
  const toPolish = () => {
    clearUploadSession(userId)
    navigate('/polish', { state: { fromUpload: true } })
  }

  /** 简历 / 画像里的证据条数：优先累计证据，没有时用兼容字段记 1 条。 */
  const evidenceCount = (item: { source_quote?: string; source_quotes?: unknown[] }) =>
    Math.max(item.source_quotes?.length ?? 0, item.source_quote ? 1 : 0)

  const usingImages =
    meta?.source_type === 'image' ||
    (picked === null && images.length > 0) ||
    phase === 'recognizing'
  const uploadPhases = usingImages
    ? ['上传图片', '识别图片中的文字', 'AI 生成并合并画像']
    : ['上传简历', '解析简历 → 提取正文', 'AI 生成并合并画像']
  const activeFile =
    picked?.name ??
    meta?.file_name ??
    (images.length > 0 ? `照片简历（${images.length} 张）` : null)
  const parseState = busy
    ? phase === 'uploading'
      ? `UPLOADING ${uploadSec}s`
      : phase === 'recognizing'
        ? `RECOGNIZING ${uploadSec}s`
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
      state: flow.hasResume
        ? 'done'
        : phase === 'uploading' || phase === 'recognizing'
          ? 'now'
          : 'todo',
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
            <button
              type="button"
              className="sc-btn sc-btn--secondary sc-lab-cta-btn"
              onClick={() => captureRef.current?.click()}
              disabled={controlsLocked}
            >
              拍照上传
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
                  {busy
                    ? usingImages
                      ? '上传图片 → 识别文字 → 合并画像'
                      : '解析正文 → 抽取能力 → 合并画像'
                    : usingImages
                      ? 'JPG / PNG / WEBP · 最多 3 张 · 按顺序拼成一份简历'
                      : 'PDF / DOCX / TXT · ≤10MB · 解析约 30 秒'}
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

      {/* r42：断网 / 弱网中文提示。任务仍在服务端跑，所以只提示、不判失败，也不白屏。 */}
      {netNotice !== null ? (
        <InlineError
          message={netNotice}
          onRetry={
            jobId === null && resumeJobId === null
              ? () => setRecoverTick((value) => value + 1)
              : undefined
          }
        />
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
        <span className="sc-lab-drop-main is-drag">拖入或点击选择文件</span>
        <span className="sc-lab-drop-main is-tap">点击选择文件</span>
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

      {/* r41：图片入口 —— 手机上简历常常只是一张照片 / 截图，拍照与相册是一等入口 */}
      <div className="sc-lab-image-entry">
        <div className="sc-lab-image-head">
          <span className="sc-lab-image-kicker">PHOTO / SCAN</span>
          <p className="sc-lab-image-lead">
            简历只有照片或截图？拍照 / 从相册选择，最多 {MAX_IMAGES} 张，按顺序拼成一份。
            只识别正文，不保存原图。
          </p>
        </div>
        <div className="sc-lab-image-actions">
          <Button
            variant="secondary"
            onClick={() => captureRef.current?.click()}
            disabled={controlsLocked || images.length >= MAX_IMAGES}
          >
            拍照
          </Button>
          <Button
            variant="secondary"
            onClick={() => pickImagesRef.current?.click()}
            disabled={controlsLocked || images.length >= MAX_IMAGES}
          >
            从相册选择
          </Button>
          {images.length > 0 ? (
            <Button variant="ghost" onClick={clearImages} disabled={busy}>
              清空
            </Button>
          ) : null}
        </div>
        {images.length > 0 ? (
          <>
            <ul className="sc-lab-thumbs" aria-label="待上传的简历图片">
              {images.map((image, index) => (
                <li className="sc-lab-thumb" key={image.url}>
                  <img src={image.url} alt={`第 ${index + 1} 张简历图片预览`} />
                  <button
                    type="button"
                    className="sc-lab-thumb-remove"
                    onClick={() => removeImage(index)}
                    disabled={busy}
                    aria-label={`删除第 ${index + 1} 张图片`}
                  >
                    <span aria-hidden="true">×</span>
                  </button>
                </li>
              ))}
            </ul>
            <div className="sc-lab-image-submit">
              <Button
                variant="primary"
                onClick={() => void uploadImages()}
                disabled={controlsLocked}
              >
                上传并识别（{images.length} 张）
              </Button>
              <span className="sc-lab-image-hint">识别失败可整批重试</span>
            </div>
          </>
        ) : null}
        {imageLoading ? <p className="sc-lab-image-hint">正在压缩图片…</p> : null}
        {imageError !== null ? <InlineError message={imageError} /> : null}
      </div>
      <input
        ref={captureRef}
        type="file"
        accept="image/*"
        capture="environment"
        onChange={onCaptureChange}
        hidden
        aria-hidden="true"
        tabIndex={-1}
      />
      <input
        ref={pickImagesRef}
        type="file"
        accept="image/*"
        multiple
        onChange={onPickImagesChange}
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
              phases={uploadPhases}
              active={0}
              elapsedSec={uploadSec}
              title={
                picked?.name ??
                (images.length > 0 ? `照片简历（${images.length} 张）` : undefined)
              }
            />
          </div>
          <div className="sc-actions">
            <Button variant="ghost" size="sm" onClick={cancel}>
              取消
            </Button>
          </div>
        </div>
      ) : null}

      {phase === 'recognizing' ? (
        <div className="sc-lab-panel">
          <div className="sc-upload-progress">
            <RingProgress size={56} state="indeterminate" ariaLabel="识别图片" />
            <PhaseLoader
              phases={uploadPhases}
              active={1}
              elapsedSec={uploadSec}
              title={
                images.length > 0
                  ? `照片简历（${images.length} 张）`
                  : (meta?.file_name ?? undefined)
              }
            />
          </div>
          {/* r42：识别在服务端后台跑，离开 / 锁屏不会中断 —— 给出口而不是给拦截。 */}
          <p className="sc-meta-line">
            图片识别在后台进行，离开本页不会中断，回来后会自动接上进度。
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

      {phase === 'profiling' ? (
        <div className="sc-lab-panel">
          <div className="sc-upload-progress">
            <RingProgress size={56} state="indeterminate" ariaLabel="生成画像" />
            <PhaseLoader
              phases={uploadPhases}
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
          {meta.source_type === 'image' ? (
            <p className="sc-meta-line">
              照片识别 · {meta.image_count} 张拼成一份简历；只保存识别正文，原图未留存
            </p>
          ) : null}

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
