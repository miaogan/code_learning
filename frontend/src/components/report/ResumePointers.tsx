import { Link } from 'react-router-dom'
import type { ResumePointer } from '../../api/types'
import { COACH_COPY, blockStateOf, polishHref } from '../../lib/coach'
import { askTaifu } from '../../lib/taifuBridge'
import { Card } from '../ui/Card'

export interface ResumePointersProps {
  /** `null` = 旧报告｜`[]` = 无可定位要点｜非空 = 正常渲染（三态**不可合并**）。 */
  pointers: ResumePointer[] | null
  /** 服务端给的中文原因（没有正文 / AI 降级），只在空态渲染；非空数组时恒为 `null`。 */
  notice: string | null
}

/**
 * 区块 B · 简历改进要点（DESIGN r7 §2.2）。
 *
 * - 每条都带**逐字原句**（服务端已过反幻觉校验，锚点就是简历正文切片），因此「去改这一条」
 *   点跳 `/polish?focus=…` 后能精确滚动到那一条（AC-5）；
 * - 跳转用真实 `<Link>`：键盘可达、可新标签打开；只带三个短参数；
 * - 无简历 / AI 降级：只给中文原因，**不渲染任何跳转按钮**（AC-6，避免把用户丢进空列表）。
 */
export function ResumePointers({ pointers, notice }: ResumePointersProps) {
  const state = blockStateOf(pointers)

  if (state !== 'ready' || pointers === null) {
    return (
      <Card className="sc-coach-block">
        <div className="sc-coach-blockhead">
          <h3 className="sc-coach-blocktitle">简历改进要点</h3>
        </div>
        <p className="sc-coach-note">
          {state === 'legacy' ? COACH_COPY.legacy : (notice ?? COACH_COPY.resumeEmpty)}
        </p>
      </Card>
    )
  }

  return (
    <Card className="sc-coach-block">
      <div className="sc-coach-blockhead">
        <h3 className="sc-coach-blocktitle">简历改进要点</h3>
        <p className="sc-coach-meta">只列正文里能逐字定位的条目</p>
      </div>

      <div className="sc-profile-dim">
        {pointers.map((pointer, index) => (
          <Card className="sc-hint" key={`${pointer.focus_key}-${index}`}>
            <div className="sc-hint-head">
              {/* 段落 + 行号由服务端拼好（与 .md 同源），前端不再自造一份中文段名 */}
              <span className="sc-chip">{pointer.location}</span>
              {/* r82：这条原句是简历正文的逐字切片，正好当焦点原句用（服务端会再验一次）。 */}
              <button
                type="button"
                className="sc-taifu-inline"
                onClick={() =>
                  askTaifu({
                    question: '这句简历怎么写更好？',
                    focus: { kind: 'resume', anchor: pointer.anchor_text },
                    label: pointer.location,
                  })
                }
              >
                问太傅
              </button>
              <Link
                className="sc-btn sc-btn--secondary is-sm"
                to={polishHref(pointer.focus_key, pointer.section, pointer.anchor_text)}
              >
                去改这一条 →
              </Link>
            </div>

            <div className="sc-source-quote">
              <span className="sc-source-quote-label">原句</span>
              {pointer.anchor_text}
            </div>

            <p className="sc-hint-issue">
              <span className="sc-hint-label">问题</span>
              {pointer.issue}
            </p>
          </Card>
        ))}
      </div>
    </Card>
  )
}
