import type { InterviewSessionQuestion } from '../../api/types'
import type { Bubble } from './chatModel'
import { questionNoOf } from './chatModel'
import { AnswerScore } from './AnswerScore'

/** 题型文案：仅作身份行的辅助说明（DESIGN §2.3 未把题型做成独立徽章）。 */
const KIND_LABEL: Record<InterviewSessionQuestion['kind'], string> = {
  technical: '技术题',
  project: '项目深挖',
  challenge: '进阶',
}

/** 身份行文案里的题号：「第 3 问」（编号为 0 时不编造序号）。 */
function roundLabel(no: number): string {
  return no > 0 ? `第 ${no} 问` : '发言'
}

export interface ChatBubbleProps {
  bubble: Bubble
  /** 追问父题的题号（`parent_id` → Q 编号）；正题为 undefined */
  parentNo?: number
}

/** 气泡内 id 只允许 [a-zA-Z0-9-]，避免 aria-labelledby 解析出岔。 */
function whoIdOf(id: string): string {
  return `iq-who-${id.replace(/[^a-zA-Z0-9]+/g, '-')}`
}

/**
 * 单条发言气泡（纯展示，无请求、无状态）：
 * 面试官左（题面 + 提示 + 题号 + 追问标注）/ 候选人右（作答正文 + 评分区并置）。
 * 评分区在候选人气泡**内**、正文之下（AC-5），不以浮层/弹窗/新卡片另开一处。
 */
export function ChatBubble({ bubble, parentNo }: ChatBubbleProps) {
  const question = bubble.question
  const no = question ? questionNoOf(question.id) : questionNoOf(bubble.id)
  const whoId = whoIdOf(bubble.id)

  if (bubble.role === 'candidate') {
    const score = bubble.score
    return (
      <article className="sc-iq-msg sc-iq-msg--candidate" role="group" aria-labelledby={whoId}>
        <div className="sc-iq-who-row" id={whoId}>
          <span className="sc-iq-dot" aria-hidden="true" />
          <span className="sc-iq-who">你</span>
          <span className="sc-iq-who-meta">{no > 0 ? `第 ${no} 轮作答` : '本轮作答'}</span>
        </div>
        <div className="sc-iq-bubble sc-iq-bubble--candidate">
          {/* 作答正文原样展示：不 trim、不改写（服务端已做长度约束） */}
          <p className="sc-iq-text">{bubble.answer}</p>
          {typeof score === 'number' ? (
            <>
              <div className="sc-iq-divider" aria-hidden="true" />
              <AnswerScore score={score} comment={bubble.comment ?? ''} />
            </>
          ) : null}
        </div>
      </article>
    )
  }

  return (
    <article className="sc-iq-msg sc-iq-msg--interviewer" role="group" aria-labelledby={whoId}>
      <div className="sc-iq-who-row" id={whoId}>
        <span className="sc-iq-dot" aria-hidden="true" />
        <span className="sc-iq-who">面试官</span>
        <span className="sc-iq-who-meta">{roundLabel(no)}</span>
        {no > 0 ? <span className="sc-iq-qno">Q{no}</span> : null}
        {question ? <span className="sc-iq-kind">{KIND_LABEL[question.kind]}</span> : null}
        {parentNo && parentNo > 0 ? <span className="sc-iq-parent">↳ 追问自 Q{parentNo}</span> : null}
      </div>
      <div className="sc-iq-bubble sc-iq-bubble--interviewer">
        <p className="sc-iq-text">{question?.prompt ?? ''}</p>
        {question?.hint ? (
          <p className="sc-iq-hint">
            <span className="sc-iq-hint-label">提示</span>
            {question.hint}
          </p>
        ) : null}
      </div>
    </article>
  )
}
