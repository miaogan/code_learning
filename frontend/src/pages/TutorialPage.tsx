import { PageHero } from '../components/ui/PageHero'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { spokenChapterById } from '../content/spoken'
import { audioIndexHasChapter, useSpokenAudioIndex } from '../lib/spokenAudio'
import { SpokenPlayer } from '../components/learn/SpokenPlayer'
import { TutorialArticle } from '../components/learn/TutorialArticle'
import { TutorialToc } from '../components/learn/TutorialToc'
import { LevelChip } from '../components/learn/LevelChip'
import { Chip } from '../components/ui/Chip'
import { EmptyState } from '../components/ui/EmptyState'
import { progressView } from '../lib/learnProgress'
import { practiceHref } from '../lib/studyPlan'
import { chapterById, chapterHref, chapterNeighbors, tutorialHref, ALL_TUTORIAL_CHAPTERS } from '../lib/tutorials'
import { markChapterOpened, markSectionSeen, useLearnProgress } from '../state/learnProgress'

/**
 * 文章页：一章一页，正文全部静态渲染；切章回到页首，底部给上一章 / 下一章与专项练习。
 *
 * r25 起负责采集阅读进度：打开即记「最近在读」，小节滚进视口才记「读过」；
 * 带 `#tutorial-<sectionId>` 进来（「继续学习」就是这么链过来的）时落到该小节而不是页首。
 * r26 起正文旁边有章内目录：高亮由滚动位置推导（`activeSectionId`），已读标记与进度条同源。
 */
export default function TutorialPage() {
  const { chapterId } = useParams<{ chapterId: string }>()
  const [searchParams] = useSearchParams()
  const chapter = chapterId === undefined ? undefined : chapterById(chapterId)
  const progress = useLearnProgress()
  /** 目录高亮的当前小节，由正文的可见性观察回填。 */
  const [activeSectionId, setActiveSectionId] = useState<string | null>(null)

  /**
   * 听模式（r151）：`?mode=listen` 且该章有口播稿才进；C 类章与没稿的章不出现入口，
   * URL 手输也只回落到读模式（不渲染空播放器）。
   */
  const spokenScript = chapter === undefined ? undefined : spokenChapterById(chapter.id)
  /**
   * r151 全量流水线：入口真源是 `/audio/index.json`（部署期资产）。
   * 内嵌口播稿（S 类试点章）与索引章都可进听模式——素材上线后入口自动出现，零发版。
   * 索引还没拉回来时先按「无」处理：内侧了再来就有（一次会话只拉一次，缓存模块级）。
   */
  const audioIndex = useSpokenAudioIndex()
  const hasAudio =
    spokenScript !== undefined ||
    (chapter !== undefined && audioIndexHasChapter(audioIndex, chapter.id))
  const isListenMode = searchParams.get('mode') === 'listen' && hasAudio
  /**
   * 泛听跨章续播（r151）：沿教程顺序找下一个有音频章（内嵌稿或索引），整章播完自动跳过去接着听；
   * `autoplay=1` 由播放器接（浏览器拒自动播放时静默降级为暂停态）。
   */
  const nextListenHref = useMemo(() => {
    if (chapter === undefined) return null
    const currentIndex = ALL_TUTORIAL_CHAPTERS.findIndex((item) => item.id === chapter.id)
    const next = ALL_TUTORIAL_CHAPTERS.slice(currentIndex + 1).find(
      (item) =>
        spokenChapterById(item.id) !== undefined || audioIndexHasChapter(audioIndex, item.id),
    )
    return next === undefined ? null : `${chapterHref(next.id)}?mode=listen&autoplay=1`
  }, [chapter, audioIndex])
  const autoplay = searchParams.get('autoplay') === '1'

  // 打开即记「最近在读」；只翻一眼不写已读小节，避免把进度刷成虚高。
  useEffect(() => {
    if (chapter !== undefined) markChapterOpened(chapter.id)
  }, [chapter])

  // 换章时清掉上一章的高亮，否则新章目录会先亮起旧序号。
  useEffect(() => {
    setActiveSectionId(null)
  }, [chapterId])

  // 续读锚点优先；没有锚点（或章节改版后锚点已失效）才回顶。
  useEffect(() => {
    const hash = window.location.hash
    const target =
      hash.startsWith('#tutorial-') ? document.getElementById(hash.slice(1)) : null
    if (target !== null) target.scrollIntoView({ block: 'start' })
    else window.scrollTo(0, 0)
  }, [chapterId])

  const handleSectionSeen = useCallback(
    (sectionId: string) => {
      if (chapter !== undefined) markSectionSeen(chapter.id, sectionId)
    },
    [chapter],
  )

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
  const readState = progressView(progress.chapters[chapter.id], chapter)
  // 目录里的 ✓ 与进度条的已读数同源：都来自这一章的 seen 记录。
  const readIds = new Set(progress.chapters[chapter.id]?.seen ?? [])

  return (
    <div className="sc-learn-page">
      <nav className="sc-learn-crumb" aria-label="教程导航">
        <Link to={tutorialHref()}>学习</Link>
        <span aria-hidden="true">/</span>
        <Link to={tutorialHref(chapter.direction, chapter.level)}>{chapter.direction}</Link>
        <span aria-hidden="true">/</span>
        <span>{chapter.level}</span>
      </nav>

      <PageHero
        index="07"
        kicker={`TUTORIAL / ${chapter.direction}`}
        title={chapter.title}
        lead={chapter.summary}
      />

      <p className="sc-meta-line">
        <Chip label={chapter.direction} tone="direction" />
        <LevelChip level={chapter.level} />
        <Chip label={`${chapter.sections.length} 节`} />
        {hasAudio && (
          <Link
            className={isListenMode ? 'sc-listen-entry is-active' : 'sc-listen-entry'}
            to={isListenMode ? chapterHref(chapter.id) : `${chapterHref(chapter.id)}?mode=listen`}
            aria-label={isListenMode ? '切回读模式' : '进入听模式'}
          >
            {isListenMode ? '回到读原文' : '听听 🎧'}
          </Link>
        )}
      </p>

      {/* 进度用文字说清（进度条只是辅助），屏幕阅读器读到的是 aria-valuenow 与这句文案。 */}
      <p className="sc-learn-readline">
        <span className="sc-learn-readlabel">
          {readState.status === 'unread' ? '还没开始读' : readState.label}
        </span>
        <span
          className={
            readState.status === 'done' ? 'sc-learn-track is-done' : 'sc-learn-track'
          }
          role="progressbar"
          aria-label="本章阅读进度"
          aria-valuemin={0}
          aria-valuemax={readState.total}
          aria-valuenow={readState.seen}
        >
          <span className="sc-learn-trackfill" style={{ width: `${readState.percent}%` }} />
        </span>
      </p>

      <div className="sc-learn-layout">
        {isListenMode && hasAudio ? (
          <div className="sc-learn-listenwrap">
            <SpokenPlayer
              chapterId={chapter.id}
              chapter={spokenScript ?? null}
              chapterTitle={chapter.title}
              nextListenHref={nextListenHref}
              autoplay={autoplay}
            />
          </div>
        ) : (
          <TutorialArticle
            chapter={chapter}
            onSectionSeen={handleSectionSeen}
            onActiveSectionChange={setActiveSectionId}
          />
        )}
        {isListenMode ? (
          <TutorialToc chapter={chapter} activeSectionId={null} readIds={new Set()} seen={0} />
        ) : (
          <TutorialToc
            chapter={chapter}
            activeSectionId={activeSectionId}
            readIds={readIds}
            seen={readState.seen}
          />
        )}
      </div>

      <div className="sc-learn-foot">
        <Link
          className="sc-plan-task"
          to={practiceHref({
            direction: chapter.direction,
            sub_direction: chapter.sub_direction,
            limit: 10,
          })}
        >
          <span className="sc-plan-tasklabel">{`${chapter.sub_direction}专项练习 10 题`}</span>
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
