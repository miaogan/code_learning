import { Link, useSearchParams } from 'react-router-dom'
import {
  ALL_TUTORIAL_CHAPTERS,
  TUTORIAL_DIRECTIONS,
  chapterHref,
  chaptersInDirection,
  parseLearnDirection,
  tutorialHref,
} from '../lib/tutorials'
import type { TutorialDirectionFilter } from '../lib/tutorials'
import { EmptyState } from '../components/ui/EmptyState'

const DIRECTION_OPTIONS: TutorialDirectionFilter[] = ['all', ...TUTORIAL_DIRECTIONS]

/** 目录页：方向筛选 + 章节卡片。筛选状态只活在 URL（`?direction=`），刷新与分享都能复现。 */
export default function LearnPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const direction = parseLearnDirection(searchParams.toString())
  const chapters = direction === 'all' ? ALL_TUTORIAL_CHAPTERS : chaptersInDirection(direction)

  const selectDirection = (next: TutorialDirectionFilter) => {
    // 目录链接不写 all：与 tutorialHref 的口径保持一致（「全部」= 无参数）。
    const params = new URLSearchParams(searchParams)
    if (next === 'all') {
      params.delete('direction')
    } else {
      params.set('direction', next)
    }
    const suffix = params.toString()
    setSearchParams(suffix === '' ? {} : params, { replace: true })
  }

  return (
    <div className="sc-learn-page">
      <header className="sc-page-header">
        <h1 className="sc-page-title">学习</h1>
        <p className="sc-page-sub">
          {`站内教程共 ${ALL_TUTORIAL_CHAPTERS.length} 章，按方向从概念读到自测；每章都能回到对应专项练习`}
        </p>
      </header>

      <div className="sc-qa-chips" role="group" aria-label="教程方向筛选">
        {DIRECTION_OPTIONS.map((option) => {
          const selected = option === direction
          const label = option === 'all' ? '全部' : option
          return (
            <button
              key={option}
              type="button"
              className="sc-chip sc-iq-chip sc-qa-chip"
              aria-pressed={selected}
              onClick={() => selectDirection(option)}
            >
              {selected ? `✓ ${label}` : label}
            </button>
          )
        })}
      </div>

      {chapters.length === 0 ? (
        <EmptyState
          reason="该方向暂时还没有教程，换一个方向或看全部章节"
          actionLabel="看全部教程"
          actionTo={tutorialHref()}
        />
      ) : (
        <div className="sc-grid-2 sc-learn-grid">
          {chapters.map((chapter) => (
            <Link
              className="sc-card is-interactive sc-learn-chapter"
              key={chapter.id}
              to={chapterHref(chapter.id)}
            >
              <p className="sc-meta-line">
                <span className="sc-chip sc-chip--direction">{chapter.direction}</span>
                <span>{`${chapter.sections.length} 节`}</span>
              </p>
              <h2 className="sc-learn-chaptertitle">{chapter.title}</h2>
              <p className="sc-learn-chaptersum">{chapter.summary}</p>
              <span className="sc-learn-chapterfoot">开始阅读 →</span>
            </Link>
          ))}
        </div>
      )}
    </div>
  )
}
