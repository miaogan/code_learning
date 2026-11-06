import { Link } from 'react-router-dom'
import { type ResumeTarget, resumeHref } from '../../lib/learnProgress'

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
    <Link className="sc-lab-resume" to={resumeHref(target)}>
      <span className="sc-lab-resume-main">
        <span className="sc-lab-kicker">CONTINUE</span>
        <span className="sc-lab-resume-title">{chapter.title}</span>
        <span className="sc-lab-resume-meta">
          {`${chapter.direction} · ${chapter.level} · ${resumePoint}`}
        </span>
      </span>
      <span className="sc-lab-resume-track" aria-hidden="true">
        <span style={{ width: `${view.percent}%` }} />
      </span>
      <span className="sc-lab-resume-go">
        {sectionIndex === null ? '从第一章开始 →' : '接着读 →'}
      </span>
    </Link>
  )
}
