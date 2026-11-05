import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { consumeResumePrompt } from '../../lib/resumePrompt'
import { EmptyState } from './EmptyState'
import { NoticeModal } from './NoticeModal'

export interface ResumeGateProps {
  /** 本页为什么需要画像（页特异性原因句，空态与弹框共用）。 */
  reason: string
  /** 解锁后回到本页要做的事，例如「回来开始面试」。 */
  unlockLabel: string
}

/**
 * 未上传简历（最新画像 404）的统一门禁：原因句 + 上传入口 + 解锁路径 + 无需画像的旁路。
 * 原来 5 个页面各写一套（面试 / 画像有弹框、笔试 / 润色 / 报告只有空态），这里收成一处；
 * 「未上传简历」弹框按标签页会话只弹一次（`lib/resumePrompt.ts`），登出时由 App 重置。
 */
export function ResumeGate({ reason, unlockLabel }: ResumeGateProps) {
  const navigate = useNavigate()
  const [promptOpen, setPromptOpen] = useState(false)
  /** StrictMode 会把 effect 跑两遍：第一遍消费掉会话配额，第二遍会把弹框重新关上 —— 只消费一次。 */
  const consumedRef = useRef(false)

  useEffect(() => {
    if (consumedRef.current) return
    consumedRef.current = true
    setPromptOpen(consumeResumePrompt())
  }, [])

  return (
    <>
      <EmptyState reason={reason} actionLabel="上传简历" actionTo="/" />
      <div className="sc-btn-row">
        <p className="sc-meta-line">解锁路径：上传简历 → AI 生成画像 → {unlockLabel}</p>
        <Link className="sc-btn sc-btn--secondary" to="/practice">
          不需要画像？先去练习
        </Link>
        <Link className="sc-btn sc-btn--secondary" to="/learn">
          或先看教程
        </Link>
      </div>
      <NoticeModal
        open={promptOpen}
        title="未上传简历"
        message="还没有检测到简历。上传一份简历（PDF / DOCX / TXT，≤10MB）后 AI 会自动生成画像，本页随即恢复可用。"
        primaryLabel="去上传简历"
        onPrimary={() => navigate('/')}
        onClose={() => setPromptOpen(false)}
      />
    </>
  )
}
