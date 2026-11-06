import type { Shortfall } from '../../api/types'
import { severityLabel } from '../../lib/format'
import { InlineError } from '../ui/InlineError'
import { CourseCard } from './CourseCard'
import { EvidenceChip } from './EvidenceChip'

export interface ShortfallCardProps {
  shortfall: Shortfall
  /** 1 起的序号，仅用于标出报告小节顺序（排序一律沿用后端给的顺序） */
  order: number
}

/**
 * 短板卡（DESIGN §2.5）：左 4px 严重度扇区 + 名称/徽章/证据 chip + 一句诊断 + 建议动作 + 课程区。
 *
 * 约定：
 * - 严重度是**双通道**：扇区取色 + 徽章文字「严重度 高/中/低」（颜色不单独承载信息）。
 * - 排序不在前端做：报告页只渲染后端 `(severity, 均分)` 排好的顺序（禁止二次排序）。
 * - 每条短板至少 1 门课由后端兜底；万一缺失则给出 inline 提示，而不是静默空白（AC-6）。
 */
export function ShortfallCard({ shortfall, order }: ShortfallCardProps) {
  const { name, severity, evidence, diagnosis, actions, courses, question_ref } = shortfall

  return (
    <article className="sc-lab-sf" data-severity={severity}>
      <span className={order === 1 ? 'sc-lab-sf-rank is-sig' : 'sc-lab-sf-rank'} aria-hidden="true">
        {String(order).padStart(2, '0')}
      </span>

      <div className="sc-lab-sf-body">
        <div className="sc-lab-sf-top">
          <h2 className="sc-lab-sf-title">{name}</h2>
          <span className={`sc-lab-sf-sev is-${severity}`} data-severity={severity}>
            {`严重度 ${severityLabel(severity)}`}
          </span>
        </div>

        <p className="sc-lab-sf-diagnosis">{diagnosis}</p>

        <div className="sc-lab-sf-evidence">
          <p className="sc-lab-sf-ek">EVIDENCE</p>
          <EvidenceChip evidence={evidence} questionRef={question_ref} />
        </div>

        <div className="sc-lab-sf-action">
          <div className="sc-lab-sf-actions">
            <p className="sc-lab-sf-ak">ACTIONS</p>
            {actions.map((action, index) => (
              <p key={`${order}-action-${index}`}>{`▸ ${action}`}</p>
            ))}
          </div>
        </div>

        {courses.length > 0 ? (
          <div className="sc-grid-2">
            {courses.map((course) => (
              <CourseCard course={course} key={course.id} />
            ))}
          </div>
        ) : (
          <InlineError message="暂无匹配课程，已记录；可先按上面的动作自查这一短板" />
        )}
      </div>
    </article>
  )
}
