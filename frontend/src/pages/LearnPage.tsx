import { Link, useSearchParams } from 'react-router-dom'
import { EmptyState } from '../components/ui/EmptyState'
import { Chip } from '../components/ui/Chip'
import { MultiChipRow, type ChipOption } from '../components/ui/ChipRow'
import { LevelChip } from '../components/learn/LevelChip'
import { ResumeCard } from '../components/learn/ResumeCard'
import { progressView, resumeTarget, summarizeProgress } from '../lib/learnProgress'
import {
  ALL_TUTORIAL_CHAPTERS,
  TUTORIAL_DIRECTIONS,
  chapterHref,
  chaptersInDirections,
  filterChaptersByLevels,
  filterChaptersBySubDirections,
  learnHref,
  levelsInChapters,
  parseLearnDirections,
  parseLearnLevels,
  parseLearnSubDirections,
  subDirectionsInChapters,
  tutorialHref,
} from '../lib/tutorials'
import { useLearnProgress } from '../state/learnProgress'

const DIRECTION_OPTIONS: ChipOption<string>[] = [
  { value: 'all', label: '全部' },
  ...TUTORIAL_DIRECTIONS.map((direction) => ({ value: direction, label: direction })),
]

/**
 * 目录页：继续学习入口 + 两级筛选（方向 → 难度）+ 章节卡片。
 *
 * 筛选状态只活在 URL（`?direction=&level=`），刷新与分享都能复现；
 * 第二级只列「当前方向真实存在的档位」，所以永远不会出现点了必然没结果的按钮。
 * 阅读进度以服务端为权威、本地只作缓存（`state/learnProgress`，按账号隔离），卡片与入口只读它。
 */
export default function LearnPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const search = searchParams.toString()
  const directions = parseLearnDirections(search)
  const subs = parseLearnSubDirections(search, directions)
  const levels = parseLearnLevels(search)

  const progressState = useLearnProgress()
  const resume = resumeTarget(progressState)
  const summary = summarizeProgress(progressState, ALL_TUTORIAL_CHAPTERS)

  // 逐级收窄：方向 → 子方向 → 难度；每一级的可选项只由上一级的结果派生。
  const scope = chaptersInDirections(directions)
  const subOptions: ChipOption<string>[] = [
    { value: 'all', label: '全部' },
    ...subDirectionsInChapters(scope).map((item) => ({ value: item, label: item })),
  ]
  const subScope = filterChaptersBySubDirections(scope, subs)
  const levelOptions: ChipOption<string>[] = [
    { value: 'all', label: '全部' },
    ...levelsInChapters(subScope).map((item) => ({ value: item, label: item })),
  ]
  const chapters = filterChaptersByLevels(subScope, levels)

  /** 多选写回 URL：空数组或含 `all` 都不写参数（解析时同样把这两者当「不过滤」）。 */
  const writeChoices = (params: URLSearchParams, key: string, values: readonly string[]) => {
    params.delete(key)
    if (values.length > 0 && !values.includes('all')) {
      values.forEach((value) => params.append(key, value))
    }
  }

  /** 换方向必须清掉二级/三级筛选：新方向未必有当前子方向或档位，留着就会出现「空结果 + 按钮还亮着」。 */
  const selectDirections = (next: string[]) => {
    const params = new URLSearchParams(searchParams)
    writeChoices(params, 'direction', next)
    params.delete('sub')
    params.delete('level')
    setSearchParams(params, { replace: true })
  }

  /** 子方向只改 `sub`；换子方向清掉难度（新子方向未必有当前档位）。 */
  const selectSubDirections = (next: string[]) => {
    const params = new URLSearchParams(searchParams)
    writeChoices(params, 'sub', next)
    params.delete('level')
    setSearchParams(params, { replace: true })
  }

  /** 难度只改 `level`，方向与子方向保持不变（三级筛选互不覆盖）。 */
  const selectLevels = (next: string[]) => {
    const params = new URLSearchParams(searchParams)
    writeChoices(params, 'level', next)
    setSearchParams(params, { replace: true })
  }

  // 解析层已把「全部 / 勾满具体项」归一成空数组，这里只要判空即可。
  const allDirections = directions.length === 0
  const scopeLabel = allDirections ? '全部方向' : `「${directions.join('、')}」方向`
  const subLabel = subs.length === 0 ? '' : `「${subs.join('、')}」`
  const levelLabel = levels.length === 0 ? '全部难度' : levels.join('、')

  return (
    <div className="sc-learn-page">
      <header className="sc-lab-pagehead">
        <div>
          <p className="sc-lab-kicker sc-lab-rise">
            <span className="sc-lab-kicker-idx">02</span> CURRICULUM
          </p>
          <h1 className="sc-lab-page-title sc-lab-rise is-d1">学堂</h1>
          <p className="sc-lab-lead sc-lab-rise is-d2">
            {`站内教程共 ${ALL_TUTORIAL_CHAPTERS.length} 章，覆盖 ${TUTORIAL_DIRECTIONS.length} 个方向与基础 / 进阶 / 高级三档难度；每章都能回到对应专项练习`}
          </p>
        </div>
        <div className="sc-lab-stats sc-lab-rise is-d2">
          <div className="sc-lab-stat">
            <b>
              {ALL_TUTORIAL_CHAPTERS.length}
              <span className="u">章</span>
            </b>
            <em>CHAPTERS</em>
          </div>
          <div className="sc-lab-stat">
            <b>
              {TUTORIAL_DIRECTIONS.length}
              <span className="u">方向</span>
            </b>
            <em>DIRECTIONS</em>
          </div>
          <div className="sc-lab-stat">
            <b>
              {summary.percent}
              <span className="u">%</span>
            </b>
            <em>READ</em>
          </div>
        </div>
      </header>

      {resume === null ? null : <ResumeCard target={resume} />}

      <div className="sc-lab-filters">
        <div className="sc-lab-filter-row">
          <span className="sc-lab-filter-label">方向</span>
          <div className="sc-lab-filter-body">
            <MultiChipRow
              groupLabel="教程方向筛选"
              options={DIRECTION_OPTIONS}
              values={directions}
              allValue="all"
              onChange={selectDirections}
            />
          </div>
        </div>

        {allDirections ? null : (
          <div className="sc-lab-filter-row">
            <span className="sc-lab-filter-label">子方向</span>
            <div className="sc-lab-filter-body">
              <MultiChipRow
                groupLabel="教程子方向筛选"
                options={subOptions}
                values={subs}
                allValue="all"
                onChange={selectSubDirections}
              />
              <p className="sc-lab-filter-hint">
                只列选中方向下有章节的子方向；换方向会重置子方向与难度
              </p>
            </div>
          </div>
        )}

        <div className="sc-lab-filter-row">
          <span className="sc-lab-filter-label">难度</span>
          <div className="sc-lab-filter-body">
            <MultiChipRow
              groupLabel="教程难度筛选"
              options={levelOptions}
              values={levels}
              allValue="all"
              onChange={selectLevels}
            />
            <p className="sc-lab-filter-hint">
              {`当前${scopeLabel}${subLabel}共 ${chapters.length} 章 · 子方向与难度档位都只列有内容的项`}
            </p>
          </div>
        </div>
      </div>

      {scope.length === 0 ? (
        <EmptyState
          reason="该方向暂时还没有教程，换一个方向或看全部章节"
          actionLabel="看全部教程"
          actionTo={tutorialHref()}
        />
      ) : chapters.length === 0 ? (
        <EmptyState
          reason={`${scopeLabel}${subLabel}暂时没有「${levelLabel}」档位的教程，看看这个范围的其他档位`}
          actionLabel={subs.length === 0 ? '看该范围全部教程' : '看该子方向全部档位'}
          actionTo={learnHref(directions, [], subs)}
        />
      ) : (
        <>
          <div className="sc-lab-listhead" aria-hidden="true">
            <span>NO.</span>
            <span>章节</span>
            <span>方向</span>
            <span>难度</span>
            <span>进度</span>
            <span />
          </div>
          <div className="sc-lab-chapters">
            {chapters.map((chapter) => {
              const readState = progressView(progressState.chapters[chapter.id], chapter)
              const order = ALL_TUTORIAL_CHAPTERS.findIndex((item) => item.id === chapter.id) + 1
              const seenCount = readState.status === 'unread' ? 0 : readState.seen
              return (
                <Link
                  className={
                    readState.status === 'reading' ? 'sc-lab-chapter is-reading' : 'sc-lab-chapter'
                  }
                  key={chapter.id}
                  to={chapterHref(chapter.id)}
                >
                  <span className="sc-lab-cnum">{String(order).padStart(2, '0')}</span>
                  <span className="sc-lab-ctext">
                    <span className="sc-lab-ctitle">{chapter.title}</span>
                    <span className="sc-lab-csum">{chapter.summary}</span>
                  </span>
                  <span className="sc-lab-ctags sc-lab-cdir">
                    <Chip label={chapter.direction} tone="direction" />
                    <Chip label={chapter.sub_direction} tone="direction" />
                  </span>
                  <span className="sc-lab-ctags sc-lab-clevel">
                    <LevelChip level={chapter.level} />
                  </span>
                  <span className="sc-lab-cprog">
                    <span className="sc-lab-segbar" aria-hidden="true">
                      {chapter.sections.map((section, index) => (
                        <span
                          className={index < seenCount ? 'sc-lab-seg is-on' : 'sc-lab-seg'}
                          key={section.id}
                        />
                      ))}
                    </span>
                    <span>
                      {readState.status === 'unread'
                        ? `${chapter.sections.length} 节`
                        : `${readState.seen}/${readState.total} 节`}
                    </span>
                  </span>
                  <span className="sc-lab-go" aria-hidden="true">
                    →
                  </span>
                </Link>
              )
            })}
          </div>
          <p className="sc-lab-listfoot">
            {`当前${scopeLabel}${subLabel}共 ${chapters.length} 章 · ${summary.done} 章读完 · ${summary.reading} 章在读`}
          </p>
        </>
      )}
    </div>
  )
}
