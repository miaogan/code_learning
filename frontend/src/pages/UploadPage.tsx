import { useEffect, useRef, useState } from 'react'
import type { ChangeEvent, DragEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { ApiError, api } from '../api/client'
import type { ResumeMeta } from '../api/types'
import { Button } from '../components/ui/Button'
import { Card } from '../components/ui/Card'
import { Chip } from '../components/ui/Chip'
import { InlineError } from '../components/ui/InlineError'
import { PhaseLoader } from '../components/ui/PhaseLoader'
import { RingProgress } from '../components/ui/RingProgress'
import { formatChars } from '../lib/format'
import { setFlow } from '../state/flow'

const MAX_BYTES = 10 * 1024 * 1024
const ACCEPTED = ['.pdf', '.docx', '.txt']

type Phase = 'idle' | 'uploading' | 'done' | 'error'

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

export default function UploadPage() {
  const navigate = useNavigate()
  const inputRef = useRef<HTMLInputElement>(null)
  const abortRef = useRef<AbortController | null>(null)
  const [phase, setPhase] = useState<Phase>('idle')
  const [dragOver, setDragOver] = useState(false)
  const [picked, setPicked] = useState<File | null>(null)
  const [meta, setMeta] = useState<ResumeMeta | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [elapsedSec, setElapsedSec] = useState(0)

  useEffect(() => {
    if (phase !== 'uploading') return
    const timer = window.setInterval(() => setElapsedSec((value) => value + 1), 1000)
    return () => window.clearInterval(timer)
  }, [phase])

  const upload = async (file: File) => {
    const localError = validateLocally(file)
    if (localError) {
      setError(localError)
      setPhase('error')
      return
    }
    setPicked(file)
    setError(null)
    setMeta(null)
    setElapsedSec(0)
    setPhase('uploading')

    const controller = new AbortController()
    abortRef.current = controller
    try {
      const result = await api.uploadResume(file, controller.signal)
      setMeta(result)
      setFlow({ hasResume: true })
      setPhase('done')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '解析失败，请稍后重试')
      setPhase('error')
    }
  }

  const cancel = () => {
    abortRef.current?.abort()
    setPhase('idle')
    setElapsedSec(0)
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

  return (
    <section>
      <header className="sc-page-header">
        <h1 className="sc-page-title">上传简历，建立你的技术画像</h1>
        <p className="sc-page-sub">一次闭环：画像 → 面试 / 笔试 → 短板报告 → 课程</p>
      </header>

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

      {error ? (
        <div className="sc-actions">
          <InlineError
            message={error}
            onRetry={picked ? () => void upload(picked) : undefined}
          />
        </div>
      ) : null}

      {phase === 'uploading' ? (
        <div className="sc-actions">
          <Card>
            <div className="sc-upload-summary">
              <RingProgress size={56} state="indeterminate" ariaLabel="解析中" />
              <PhaseLoader
                phases={['上传简历', '解析简历 → 提取正文']}
                active={1}
                elapsedSec={elapsedSec}
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

      {phase === 'done' && meta ? (
        <div className="sc-actions">
          <Card>
            <div className="sc-upload-summary">
              <p className="sc-file-name">{meta.file_name}</p>
              <p className="sc-summary-meta">
                抽取 {formatChars(meta.chars)} · {meta.sections} 章节
              </p>
              <div className="sc-actions">
                <Button onClick={() => navigate('/profile')}>开始分析画像</Button>
              </div>
            </div>
          </Card>
        </div>
      ) : null}
    </section>
  )
}
