import { useEffect, useRef, useState } from 'react'
import type { ChangeEvent, DragEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ApiError, api } from '../api/client'
import type { ProfileMergeSummary, ResumeMeta } from '../api/types'
import { mergeSummaryText } from '../components/profile/MergeSummaryBar'
import { Button } from '../components/ui/Button'
import { Card } from '../components/ui/Card'
import { Chip } from '../components/ui/Chip'
import { InlineError } from '../components/ui/InlineError'
import { PhaseLoader } from '../components/ui/PhaseLoader'
import { RingProgress } from '../components/ui/RingProgress'
import { formatChars } from '../lib/format'
import { useAsync } from '../lib/useAsync'
import { setFlow } from '../state/flow'

const MAX_BYTES = 10 * 1024 * 1024
const ACCEPTED = ['.pdf', '.docx', '.txt']

/** idle →（上传）→（生成/合并画像）→ done；任一步失败进 error 并记住失败在哪一步（重试只重跑那一步）。 */
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
 * 上传页（r3 行为变更，TECHNICAL §10-1）：上传成功后**立即**生成/合并画像。
 * 既有实现上传完直接跳 `/profile` 读 `latestProfile`，首份画像永远生成不出来（死链）；
 * r3 的 AC-6 以「上传 → 生成/合并」为入口，合并摘要随 `location.state` 一次性带给画像页。
 */
export default function UploadPage() {
  const navigate = useNavigate()
  const inputRef = useRef<HTMLInputElement>(null)
  const abortRef = useRef<AbortController | null>(null)
  const [phase, setPhase] = useState<Phase>('idle')
  const [dragOver, setDragOver] = useState(false)
  const [picked, setPicked] = useState<File | null>(null)
  const [meta, setMeta] = useState<ResumeMeta | null>(null)
  const [merge, setMerge] = useState<ProfileMergeSummary | null>(null)
  const [failure, setFailure] = useState<Failure | null>(null)
  const [uploadSec, setUploadSec] = useState(0)
  const [profileSec, setProfileSec] = useState(0)

  // 回访识别：已有画像的用户（换设备/重新登录后）不必再传一份简历，首页给「继续」入口。
  // 没有画像时接口报 PROFILE_MISSING，这里按「新用户」处理，不显示任何错误。
  const savedProfileAsync = useAsync((signal) => api.latestProfile(signal), [])
  const saved = savedProfileAsync.status === 'success' ? savedProfileAsync.data : null

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

  /** 上传之后的第二步：生成/合并画像；失败只影响本步（简历已在服务端，重试不必重传）。 */
  const buildProfile = async (resumeId: string, controller: AbortController): Promise<void> => {
    setPhase('profiling')
    try {
      const generated = await api.generateProfile(resumeId, controller.signal)
      setMerge(generated.merge_summary ?? null)
      setFlow({ hasResume: true, hasProfile: true })
      setPhase('done')
    } catch (err) {
      if (controller.signal.aborted) {
        setPhase('idle')
        return
      }
      setFailure({
        message: err instanceof ApiError ? err.message : '画像生成失败，请稍后重试',
        stage: 'profile',
        retryable: true,
      })
      setPhase('error')
    }
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
    setMerge(null)
    setUploadSec(0)
    setProfileSec(0)
    setPhase('uploading')

    const controller = new AbortController()
    abortRef.current = controller
    try {
      const result = await api.uploadResume(file, controller.signal)
      setMeta(result)
      setFlow({ hasResume: true })
      // 第二步的失败由 buildProfile 内部处理，不会落到这里的 catch（只有上传解析失败才进这里）。
      await buildProfile(result.resume_id, controller)
    } catch (err) {
      if (controller.signal.aborted) {
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
    if (meta === null) {
      setPhase('idle')
      return
    }
    const controller = new AbortController()
    abortRef.current = controller
    void buildProfile(meta.resume_id, controller)
  }

  const cancel = () => {
    abortRef.current?.abort()
    setPhase('idle')
    setUploadSec(0)
    setProfileSec(0)
  }

  const reset = () => {
    abortRef.current?.abort()
    setPicked(null)
    setMeta(null)
    setMerge(null)
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

  const busy = phase === 'uploading' || phase === 'profiling'

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
        <Chip label="解析约 30 秒" />
      </div>

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
              <div className="sc-actions">
                <Button variant="ghost" size="sm" onClick={cancel}>
                  取消
                </Button>
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
    </section>
  )
}
