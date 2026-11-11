import type { PracticeLanguageFilter, PracticeWrongItem } from '../../api/types'
import {
  DIFFICULTY_LABEL,
  LANGUAGE_LABEL,
  WRONG_BOOK_EMPTY_REASON,
  answerText,
  formatWrongTime,
  languageChips,
  promptPreview,
} from '../../lib/practice'
import { PromptBody } from '../exam/PromptBody'
import { Button } from '../ui/Button'
import { Card } from '../ui/Card'
import { Chip } from '../ui/Chip'
import { MultiChipRow } from '../ui/ChipRow'
import { EmptyState } from '../ui/EmptyState'
import { Pagination } from '../ui/Pagination'
import { Explanation } from './Explanation'

/** 正确选项键归一化：服务端可能给 `["A"]` 或旧数据的字符串 `"A"`。 */
function correctKeys(answer: PracticeWrongItem['correct_answer']): string[] {
  if (Array.isArray(answer)) return answer.map(String)
  return answer ? [String(answer)] : []
}

export interface WrongBookListProps {
  items: PracticeWrongItem[]
  /** 全库错题数（服务端给的 total，不是 `items.length`，语言过滤后两者会不同） */
  total: number
  /** 当前语言过滤（多选，页面持有，重练题单与列表必须用同一组值） */
  language: PracticeLanguageFilter[]
  /** 当前页码（从 1 起）与每页条数：列表按页展示，`total` 是全库错题数 */
  page: number
  pageSize: number
  onPageChange: (page: number) => void
  /** 已展开的行 id；`null` = 全部收起（同一时刻最多展开一行） */
  expandedId: string | null
  onToggle: (questionId: string) => void
  onFilterLanguage: (language: PracticeLanguageFilter[]) => void
  onRetrain: () => void
  /** 空态出口「开始练习」→ 切回练习 tab */
  onStartPractice: () => void
}

/**
 * 错题本（r11 · DESIGN §2.5 / AC-10）：语言 chip 过滤 + 行展开 + 列表级「错题重练」。
 *
 * 口径：
 * - 排序由服务端定（最近答错时间倒序），前端**不二次排序**；
 * - 行高 `--qa-row-min-h`(78) 是 min-height，展开态转 auto（长题面/代码块在行内向下生长，不覆盖相邻行）；
 * - 答错一次进、答对一次出（最近一次作答口径），前端不做本地加减，刷新一律以服务端返回为准；
 * - 空态必须给原因句 + 出口（禁止只写「暂无数据」）。
 */
export function WrongBookList({
  items,
  total,
  language,
  page,
  pageSize,
  onPageChange,
  expandedId,
  onToggle,
  onFilterLanguage,
  onRetrain,
  onStartPractice,
}: WrongBookListProps) {
  if (total === 0) {
    return <EmptyState reason={WRONG_BOOK_EMPTY_REASON} actionLabel="开始练习" onAction={onStartPractice} />
  }

  return (
    <Card className="sc-qa-wrongbook">
      <div className="sc-qa-wrong-head">
        <MultiChipRow
          groupLabel="错题本语言筛选"
          options={languageChips()}
          values={language}
          allValue="all"
          onChange={onFilterLanguage}
        />
        <p className="sc-qa-hint">
          {`答错一次就会进来，答对一次即移出（最近一次作答口径） · 通用题在「全部」中`}
        </p>
        <p className="sc-qa-wrong-total">
          <span>共</span>
          <span className="sc-mono">{total}</span>
          <span>道</span>
        </p>
      </div>

      {items.length === 0 ? (
        <p className="sc-qa-wrong-empty">当前语言下没有错题，改用「全部」看看</p>
      ) : (
        <ul className="sc-qa-wrong-list">
          {items.map((item) => {
            const expanded = expandedId === item.question_id
            return (
              <li key={item.question_id} className="sc-qa-wrong-row">
                <div className="sc-qa-wrong-prompt">
                  <span className="sc-qa-wrong-text">{promptPreview(item.prompt)}</span>
                  <button
                    type="button"
                    className="sc-btn sc-btn--ghost is-sm"
                    aria-expanded={expanded}
                    onClick={() => onToggle(item.question_id)}
                  >
                    {expanded ? '收起' : '展开'}
                  </button>
                </div>
                {expanded ? (
                  <div className="sc-qa-wrong-full">
                    <PromptBody prompt={item.prompt} textClassName="sc-qa-wrong-full-text" />
                    {item.options.length > 0 ? (
                      <div className="sc-upload-summary">
                        {item.options.map((option) => {
                          const isCorrect = correctKeys(item.correct_answer).includes(option.key)
                          return (
                            <div
                              key={option.key}
                              className={isCorrect ? 'sc-opt is-correct' : 'sc-opt'}
                              aria-disabled="true"
                            >
                              <span className="sc-opt-key">{option.key}</span>
                              <span className="sc-opt-text">{option.text}</span>
                            </div>
                          )
                        })}
                      </div>
                    ) : null}
                    <div className="sc-qa-feedback">
                      <div className="sc-qa-feedback-head">
                        <span className="sc-qa-answer-label">正确答案：</span>
                        <span className="sc-mono sc-qa-answer">{answerText(item.correct_answer)}</span>
                      </div>
                      <Explanation text={item.explanation} />
                    </div>
                  </div>
                ) : null}
                <div className="sc-qa-wrong-meta">
                  <Chip label={LANGUAGE_LABEL[item.language]} />
                  {item.direction ? <Chip label={item.direction} tone="direction" /> : null}
                  <Chip label={DIFFICULTY_LABEL[item.difficulty]} />
                  <span className="sc-mono sc-qa-wrong-time">
                    {`最近答错 ${formatWrongTime(item.last_wrong_at)}`}
                  </span>
                  <span className="sc-mono sc-qa-wrong-count">{`答错 ${item.wrong_count} 次`}</span>
                </div>
              </li>
            )
          })}
        </ul>
      )}

      {items.length > 0 ? (
        <>
          <Pagination
            page={page}
            pageSize={pageSize}
            total={total}
            onChange={onPageChange}
            label="错题本分页"
          />
          <div className="sc-qa-footer-row">
            <Button onClick={onRetrain}>{`错题重练 · ${total} 题`}</Button>
          </div>
        </>
      ) : null}
    </Card>
  )
}
