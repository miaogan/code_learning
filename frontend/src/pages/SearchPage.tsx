import { useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import type { QuestionSearchItem } from '../api/types'
import { LevelChip } from '../components/learn/LevelChip'
import { Chip } from '../components/ui/Chip'
import { ChipRow, type ChipOption } from '../components/ui/ChipRow'
import { InlineError } from '../components/ui/InlineError'
import {
  QUESTION_DEBOUNCE_MS,
  QUESTION_HIT_LIMIT,
  TUTORIAL_HIT_LIMIT,
  isSearchable,
  normalizeQuery,
  previewText,
  questionHref,
} from '../lib/search'
import { practiceHref } from '../lib/studyPlan'
import { searchTutorials } from '../lib/tutorialSearch'
import {
  ALL_TUTORIAL_CHAPTERS,
  TUTORIAL_DIRECTIONS,
  chapterById,
  parseLearnDirection,
  tutorialHref,
} from '../lib/tutorials'
import type { TutorialDirectionFilter } from '../lib/tutorials'
import { useAsync } from '../lib/useAsync'

const DIRECTION_OPTIONS: ChipOption<TutorialDirectionFilter>[] = [
  { value: 'all', label: '全部' },
  ...TUTORIAL_DIRECTIONS.map((direction) => ({ value: direction, label: direction })),
]

/** 空结果时补一句「当前收窄在哪个方向」，避免用户以为是全库没有。 */
function scopeText(direction: TutorialDirectionFilter): string {
  return direction === 'all' ? '' : `（方向：${direction}）`
}

function QuestionHit({ item }: { item: QuestionSearchItem }) {
  return (
    <Link className="sc-search-hit" to={questionHref(item)}>
      <span className="sc-search-hit-body">
        <span className="sc-search-hit-title">{previewText(item.prompt)}</span>
      </span>
      <span className="sc-search-hit-meta">
        <Chip label={item.direction} tone="direction" />
        {item.sub_direction === '' ? null : <Chip label={item.sub_direction} />}
      </span>
      <span className="sc-search-go" aria-hidden="true">
        →
      </span>
    </Link>
  )
}

/**
 * 全站搜索页（r64）：教程小节 BM25 + 题库 FTS5 合一。
 *
 * 两组检索能力本来就存在（`lib/tutorialSearch.ts` / `POST /api/search/questions`），
 * 之前只是没有任何入口 —— 本页只把已有能力接上入口，**不改检索口径与后端契约**。
 *
 * 三条口径边界：
 * 1. 只搜站内教程与题库题面，**不搜简历正文、立传、医案原文**（隐私边界）；
 * 2. 题库响应永不含答案（服务端保证），命中只带你到练习页按方向 / 子方向继续练；
 * 3. 方向是唯一共用筛选，教程与题库都只接受同一份方向闭集。
 */
export default function SearchPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const direction = parseLearnDirection(searchParams.toString())

  const [raw, setRaw] = useState('')
  const query = normalizeQuery(raw)
  const searchable = isSearchable(query)

  // 教程侧是同步纯函数：输入即出结果，不需要防抖。
  const tutorialHits = useMemo(
    () =>
      searchable
        ? searchTutorials(
            query,
            direction === 'all' ? {} : { direction },
            ALL_TUTORIAL_CHAPTERS,
            TUTORIAL_HIT_LIMIT,
          )
        : [],
    [query, searchable, direction],
  )

  // 题库侧是网络请求：先防抖定稿查询词，再由 useAsync 管竞态、取消与重试。
  const [settled, setSettled] = useState('')
  useEffect(() => {
    const timer = window.setTimeout(() => setSettled(query), QUESTION_DEBOUNCE_MS)
    return () => window.clearTimeout(timer)
  }, [query])

  const questions = useAsync(async () => {
    if (!isSearchable(settled)) return null
    return api.searchQuestions({
      query: settled,
      direction: direction === 'all' ? undefined : direction,
      limit: QUESTION_HIT_LIMIT,
    })
  }, [settled, direction])

  // settled 与当前输入不一致时（还在防抖窗口里）一律按「检索中」渲染，不展示上一轮结果。
  const questionsCurrent = searchable && settled === query
  const questionsFailed = questionsCurrent && questions.status === 'error'
  const questionsPending = searchable && !(questionsCurrent && questions.status === 'success')
  const questionData = questionsCurrent && questions.status === 'success' ? questions.data : null
  const questionTotal = questionData === null ? 0 : questionData.total

  const barMeta = !searchable
    ? '输入关键词开始检索'
    : questionsPending
      ? '正在检索题库…'
      : questionsFailed
        ? '题库检索失败'
        : `教程 ${tutorialHits.length} 条 · 题库 ${questionTotal} 题`

  const selectDirection = (next: TutorialDirectionFilter): void => {
    // 换方向清掉目录页带过来的子方向 / 难度参数，避免 URL 里留下与检索无关的筛选。
    const params = new URLSearchParams(searchParams)
    if (next === 'all') params.delete('direction')
    else params.set('direction', next)
    params.delete('sub')
    params.delete('level')
    setSearchParams(params, { replace: true })
  }

  return (
    <div className="sc-learn-page">
      <header className="sc-lab-pagehead">
        <div>
          <p className="sc-lab-kicker sc-lab-rise">SEARCH / 站内检索</p>
          <h1 className="sc-lab-page-title sc-lab-rise is-d1">检索</h1>
          <p className="sc-lab-lead sc-lab-rise is-d2">
            教程按小节正文与标题命中并给出摘要，题库按题面命中并带你到对应方向的练习；教程侧即时出结果，题库侧停止输入后自动检索。只读站内教程与题库，不读简历正文、立传与医案原文。
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
              {searchable ? tutorialHits.length : 0}
              <span className="u">条</span>
            </b>
            <em>TUTORIAL HITS</em>
          </div>
          <div className="sc-lab-stat">
            <b>
              {questionsPending || questionsFailed ? '—' : questionTotal}
              <span className="u">题</span>
            </b>
            <em>QUESTION HITS</em>
          </div>
        </div>
      </header>

      <div className="sc-search-bar">
        <input
          className="sc-search-input"
          type="text"
          value={raw}
          onChange={(event) => setRaw(event.target.value)}
          placeholder="搜教程小节或题库题面，例如「索引」「幂等」「PagedAttention」"
          aria-label="搜索教程与题库"
          autoComplete="off"
          spellCheck={false}
        />
        <span className="sc-search-barmeta">{barMeta}</span>
      </div>

      <div className="sc-lab-filters">
        <div className="sc-lab-filter-row">
          <span className="sc-lab-filter-label">方向</span>
          <div className="sc-lab-filter-body">
            <ChipRow
              groupLabel="检索方向筛选"
              options={DIRECTION_OPTIONS}
              value={direction}
              onSelect={selectDirection}
            />
            <p className="sc-lab-filter-hint">
              教程与题库共用同一份方向闭集；换方向会同时收窄两组结果
            </p>
          </div>
        </div>
      </div>

      {!searchable ? (
        <p className="sc-search-hint">
          输入关键词开始检索。教程按小节命中并给摘要，题库按题面命中并带你到对应方向的练习；两组都只读站内内容。
        </p>
      ) : (
        <div className="sc-search-results">
          <section className="sc-search-group">
            <div className="sc-search-grouphead">
              <span className="sc-search-grouptag">01 / TUTORIAL</span>
              <h2 className="sc-search-grouptitle">教程小节</h2>
              <span className="sc-search-groupcount">{`${tutorialHits.length} 条`}</span>
            </div>
            {tutorialHits.length === 0 ? (
              <p className="sc-search-hint">
                {`教程里没有匹配「${query}」的小节${scopeText(direction)}；换个关键词，或去 `}
                <Link to={tutorialHref(direction === 'all' ? undefined : direction)}>学堂</Link>
                {' 按方向翻。'}
              </p>
            ) : (
              <div className="sc-search-hits">
                {tutorialHits.map((hit) => {
                  const chapter = chapterById(hit.chapter_id)
                  return (
                    <Link
                      className="sc-search-hit"
                      key={`${hit.chapter_id}:${hit.section_id}`}
                      to={hit.href}
                    >
                      <span className="sc-search-hit-body">
                        <span className="sc-search-hit-title">{hit.title}</span>
                        <span className="sc-search-hit-snippet">
                          {previewText(hit.snippet, 90)}
                        </span>
                      </span>
                      <span className="sc-search-hit-meta">
                        {chapter === undefined ? null : (
                          <>
                            <Chip label={chapter.direction} tone="direction" />
                            <LevelChip level={chapter.level} />
                          </>
                        )}
                      </span>
                      <span className="sc-search-go" aria-hidden="true">
                        →
                      </span>
                    </Link>
                  )
                })}
              </div>
            )}
          </section>

          <section className="sc-search-group">
            <div className="sc-search-grouphead">
              <span className="sc-search-grouptag">02 / QUESTION BANK</span>
              <h2 className="sc-search-grouptitle">题库题面</h2>
              <span className="sc-search-groupcount">
                {questionsPending || questionsFailed ? '—' : `${questionTotal} 题`}
              </span>
            </div>
            {questionsFailed ? (
              <InlineError
                message={questions.error?.message ?? '题库检索失败，请稍后重试'}
                onRetry={questions.reload}
              />
            ) : questionsPending ? (
              <p className="sc-search-hint">正在检索题库…</p>
            ) : questionData === null || questionData.items.length === 0 ? (
              <p className="sc-search-hint">
                {`题库里没有匹配「${query}」的题面${scopeText(direction)}；换个关键词，或直接去 `}
                <Link
                  to={practiceHref({ direction: direction === 'all' ? null : direction })}
                >
                  练习
                </Link>
                {' 按方向刷题。'}
              </p>
            ) : (
              <>
                <div className="sc-search-hits">
                  {questionData.items.map((item) => (
                    <QuestionHit key={item.question_id} item={item} />
                  ))}
                </div>
                <p className="sc-search-foot">
                  {`共 ${questionData.total} 题命中，显示前 ${questionData.items.length} 题 · 检索方式 ${
                    questionData.mode === 'fts5' ? '全文索引（FTS5）' : '关键词降级匹配'
                  } · 命中不带答案，点开进入对应方向的练习`}
                </p>
                {questionData.notice === '' ? null : (
                  <p className="sc-search-foot">{questionData.notice}</p>
                )}
              </>
            )}
          </section>
        </div>
      )}
    </div>
  )
}
