import { useEffect } from 'react'
import { Link, useParams } from 'react-router-dom'
import { TutorialArticle } from '../components/learn/TutorialArticle'
import { Chip } from '../components/ui/Chip'
import { EmptyState } from '../components/ui/EmptyState'
import { practiceHref } from '../lib/reportPlan'
import { chapterById, chapterHref, chapterNeighbors, tutorialHref } from '../lib/tutorials'

/** 文章页：一章一页，正文全部静态渲染；切章回到页首，底部给上一章 / 下一章与专项练习。 */
export default function TutorialPage() {
  const { chapterId } = useParams<{ chapterId: string }>()
  const chapter = chapterId === undefined ? undefined : chapterById(chapterId)

  // 从目录或上一章跳进来时页面会保留滚动位置，长文里必须回顶，否则会落在半截。
  useEffect(() => {
    window.scrollTo(0, 0)
  }, [chapterId])

  if (chapter === undefined) {
    return (
      <EmptyState
        reason="这一章不存在或已经更名，回到目录重新选择"
        actionLabel="返回教程目录"
        actionTo={tutorialHref()}
      />
    )
  }

  const { prev, next } = chapterNeighbors(chapter.id)

  return (
    <div className="sc-learn-page">
      <nav className="sc-learn-crumb" aria-label="教程导航">
        <Link to={tutorialHref()}>学习</Link>
        <span aria-hidden="true">/</span>
        <Link to={tutorialHref(chapter.direction)}>{chapter.direction}</Link>
      </nav>

      <header className="sc-page-header">
        <h1 className="sc-page-title">{chapter.title}</h1>
        <p className="sc-page-sub">{chapter.summary}</p>
      </header>

      <p className="sc-meta-line">
        <Chip label={chapter.direction} tone="direction" />
        <Chip label={`${chapter.sections.length} 节`} />
      </p>

      <TutorialArticle chapter={chapter} />

      <div className="sc-learn-foot">
        <Link
          className="sc-plan-task"
          to={practiceHref({ direction: chapter.direction, limit: 10 })}
        >
          <span className="sc-plan-tasklabel">{`${chapter.direction}专项练习 10 题`}</span>
          <span className="sc-plan-taskmeta">读完立刻验证 · 即时对错与解析</span>
        </Link>
      </div>

      <nav className="sc-learn-pager" aria-label="上一章与下一章">
        {prev === null ? (
          <span />
        ) : (
          <Link className="sc-learn-pageritem" to={chapterHref(prev.id)}>
            <span className="sc-learn-pagerlabel">← 上一章</span>
            <span className="sc-learn-pagertitle">{prev.title}</span>
          </Link>
        )}
        {next === null ? (
          <span />
        ) : (
          <Link className="sc-learn-pageritem is-next" to={chapterHref(next.id)}>
            <span className="sc-learn-pagerlabel">下一章 →</span>
            <span className="sc-learn-pagertitle">{next.title}</span>
          </Link>
        )}
      </nav>
    </div>
  )
}
