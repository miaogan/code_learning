import type { PracticeStats } from '../../api/types'
import {
  NO_HIT_MESSAGE,
  RELAX_OPTIONS,
  difficultyChips,
  directionChips,
  essentialityChips,
  isAllSelection,
  languageChips,
  limitChips,
  limitLabel,
  relaxSuggestions,
  scopeChips,
  subDirectionChips,
  type PracticeFiltersState,
} from '../../lib/practice'
import { Button } from '../ui/Button'
import { Card } from '../ui/Card'
import { ChipRow, MultiChipRow } from '../ui/ChipRow'

export interface PracticeFiltersProps {
  filters: PracticeFiltersState
  onChange: (patch: Partial<PracticeFiltersState>) => void
  /** 当前筛选命中数；`null` = 还没拿到（首屏 / 统计失败），与「0 命中」严格区分 */
  hitCount: number | null
  hitLoading: boolean
  globalStats: PracticeStats | null
  onStart: () => void
  startLoading: boolean
}

/**
 * 设置态筛选卡（r11 · DESIGN §2.1）：6 组筛选 + 命中行 + 全库进度 + 开始按钮。
 * r50 新增「二级方向」组：从属于方向，未选方向时只给提示，不给空 chip 行。
 *
 * 纯展示 + 回调：本组件**不发请求**、不持有筛选状态（状态归页面），
 * 因此 0 命中建议、命中行占位都能用纯函数单独测试。
 */
export function PracticeFilters({
  filters,
  onChange,
  hitCount,
  hitLoading,
  globalStats,
  onStart,
  startLoading,
}: PracticeFiltersProps) {
  const noHit = hitCount === 0
  const suggestions = noHit ? relaxSuggestions(filters) : []
  const disabled = noHit || startLoading
  const startLabel =
    filters.limit === 0 && hitCount !== null && hitCount > 0
      ? `开始练习 · 全部 ${hitCount} 题`
      : `开始练习 · ${limitLabel(filters.limit)}`

  return (
    <Card className="sc-qa-filters">
      <div className="sc-qa-filter-row">
        <span className="sc-qa-filter-label">语言</span>
        <div className="sc-qa-filter-body">
          <MultiChipRow
            groupLabel="语言筛选"
            options={languageChips()}
            values={filters.language}
            allValue="all"
            onChange={(values) => onChange({ language: values })}
          />
          <p className="sc-qa-hint">
            通用 = 与具体语言无关的题（算法与数据结构 / 计算机基础 / AI 工程 / 中间件与运维 /
            SQL 与数据库 / 研发工程实践，language 为空）
          </p>
        </div>
      </div>

      <div className="sc-qa-filter-row">
        <span className="sc-qa-filter-label">方向</span>
        <div className="sc-qa-filter-body">
          <MultiChipRow
            groupLabel="方向筛选"
            options={directionChips()}
            values={filters.direction}
            allValue="all"
            onChange={(values) => onChange({ direction: values })}
          />
        </div>
      </div>

      <div className="sc-qa-filter-row">
        <span className="sc-qa-filter-label">二级方向</span>
        <div className="sc-qa-filter-body">
          {isAllSelection(filters.direction, 'all') ? (
            <p className="sc-qa-hint">
              先选一个方向，再按二级方向聚焦；该方向题目不足时会自动补充同方向的其他题
            </p>
          ) : (
            <MultiChipRow
              groupLabel="二级方向筛选"
              options={subDirectionChips(filters.direction)}
              values={filters.sub_direction}
              allValue=""
              onChange={(values) => onChange({ sub_direction: values })}
            />
          )}
        </div>
      </div>

      <div className="sc-qa-filter-row">
        <span className="sc-qa-filter-label">难度</span>
        <div className="sc-qa-filter-body">
          <MultiChipRow
            groupLabel="难度筛选"
            options={difficultyChips()}
            values={filters.difficulty}
            allValue="all"
            onChange={(values) => onChange({ difficulty: values })}
          />
        </div>
      </div>

      <div className="sc-qa-filter-row">
        <span className="sc-qa-filter-label">必备度</span>
        <div className="sc-qa-filter-body">
          <MultiChipRow
            groupLabel="必备度筛选"
            options={essentialityChips()}
            values={filters.essentiality}
            allValue="all"
            onChange={(values) => onChange({ essentiality: values })}
          />
        </div>
      </div>

      <div className="sc-qa-filter-row">
        <span className="sc-qa-filter-label">范围</span>
        <div className="sc-qa-filter-body">
          <MultiChipRow
            groupLabel="范围筛选"
            options={scopeChips()}
            values={filters.scope}
            allValue="all"
            onChange={(values) => onChange({ scope: values })}
          />
          {/* r52：范围旁边说清默认行为，免得「全部」被误读成「一道不少」。 */}
          <p className="sc-meta-line">
            已熟练掌握的题（30 天内答对 2 次且最近答对）默认跳过，超期或答错会自动回流
          </p>
        </div>
      </div>

      <div className="sc-qa-filter-row">
        <span className="sc-qa-filter-label">题量</span>
        <div className="sc-qa-filter-body">
          <ChipRow
            groupLabel="题量筛选"
            options={limitChips()}
            value={filters.limit}
            onSelect={(value) => onChange({ limit: value })}
          />
        </div>
      </div>

      <div className="sc-qa-split" />

      <div className="sc-qa-hit" role="status" aria-live="polite">
        {hitLoading && hitCount === null ? (
          <span>统计中…</span>
        ) : noHit ? (
          <>
            <span>{NO_HIT_MESSAGE}</span>
            {suggestions.map((label) => {
              const option = RELAX_OPTIONS.find((item) => item.label === label)
              return (
                <button
                  key={label}
                  type="button"
                  className="sc-chip sc-iq-chip sc-qa-chip"
                  onClick={() => {
                    if (option) onChange(option.patch)
                  }}
                >
                  {label}
                </button>
              )
            })}
          </>
        ) : hitCount === null ? (
          <span>题库统计暂不可用</span>
        ) : (
          <>
            <span>当前组合命中</span>
            <span className="sc-mono sc-qa-hit-count">{hitCount}</span>
            <span>题</span>
          </>
        )}
      </div>

      {globalStats ? (
        <p className="sc-qa-practiced">
          <span>全库已练</span>
          <span className="sc-mono">{`${globalStats.practiced} / ${globalStats.total}`}</span>
        </p>
      ) : null}

      <div className="sc-qa-footer-row">
        {noHit ? <span className="sc-meta-line">当前筛选没有题目</span> : null}
        <Button onClick={onStart} loading={startLoading} disabled={disabled}>
          {startLabel}
        </Button>
      </div>
    </Card>
  )
}
