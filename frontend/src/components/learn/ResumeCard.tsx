import { Link } from 'react-router-dom'
import { type ResumeTarget, resumeHref } from '../../lib/learnProgress'
import { Chip } from '../ui/Chip'
import { LevelChip } from './LevelChip'

/**
 * 「继续学习」入口：只展示一个目标，不做列表。
 *
 * 目标是 `resumeTarget()` 算出来的——上次没读完就回那一节，读完了就顺延到下一本，
 * 全读完则整个入口不渲染（由调用方判空），所以这里不需要「没有进度」的分支。
 */
export function ResumeCard({ target }: { target: ResumeTarget }) {
  const { chapter, view, sectionIndex } = target
  const resumePoint =
    sectionIndex === null ? view.label : `${view.label} · 上次读到第 ${sectionIndex} 节`

  return (
    <Link className="sc-learn-resume" to={resumeHref(target)}>
      <span className="sc-learn-resumehead">
        <span className="sc-learn-resumekicker">继续学习</span>
        <span className="sc-learn-resumego">
          {sectionIndex === null ? '从第一章开始 →' : '从这里接着读 →'}
        </span>
      </span>
      <span className="sc-learn-resumetitle">{chapter.title}</span>
      <span className="sc-learn-resumemeta">
        <Chip label={chapter.direction} tone="direction" />
        <LevelChip level={chapter.level} />
        <span className="sc-learn-resumepoint">{resumePoint}</span>
      </span>
      {/* 进度条限宽：拉满整卡读起来像一条分隔线，丢掉了「进度」的语义 */}
      <span className="sc-learn-track" aria-hidden="true">
        <span className="sc-learn-trackfill" style={{ width: `${view.percent}%` }} />
      </span>
    </Link>
  )
}
