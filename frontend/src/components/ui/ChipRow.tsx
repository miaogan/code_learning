import { isAllChoice, nextChoice } from '../../lib/choice'

export interface ChipOption<T extends string | number> {
  value: T
  label: string
}

export interface ChipRowProps<T extends string | number> {
  groupLabel: string
  options: ChipOption<T>[]
  value: T
  onSelect: (value: T) => void
}

/**
 * 单选 chip 组（原生 button + `aria-pressed`，不用 `<select>`：深色主题下原生下拉会白底）。
 * 选中态给「✓」前缀 —— 颜色不是唯一信息（DESIGN §5-7）。
 *
 * 练习页与学习页共用同一份实现：两处的筛选手感必须一致，不给下游各写一套。
 */
export function ChipRow<T extends string | number>({
  groupLabel,
  options,
  value,
  onSelect,
}: ChipRowProps<T>) {
  return (
    <div className="sc-qa-chips" role="group" aria-label={groupLabel}>
      {options.map((option) => {
        const selected = option.value === value
        return (
          <button
            key={String(option.value)}
            type="button"
            className="sc-chip sc-iq-chip sc-qa-chip"
            aria-pressed={selected}
            onClick={() => onSelect(option.value)}
          >
            {selected ? `✓ ${option.label}` : option.label}
          </button>
        )
      })}
    </div>
  )
}

export interface MultiChipRowProps<T extends string | number> {
  groupLabel: string
  options: ChipOption<T>[]
  values: T[]
  /** 「全部」选项的取值（语言/方向等是 `'all'`，二级方向是空串 `''`）。 */
  allValue: T
  onChange: (values: T[]) => void
}

/**
 * 多选 chip 组：所有允许选「全部」的筛选都走这里。
 * 手动勾满全部具体项时自动折叠回「全部」按钮（状态里只留哨兵，不出现「全部 + 全部具体项」）。
 */
export function MultiChipRow<T extends string | number>({
  groupLabel,
  options,
  values,
  allValue,
  onChange,
}: MultiChipRowProps<T>) {
  const concreteValues = options
    .filter((option) => option.value !== allValue)
    .map((option) => option.value)
  const all = isAllChoice(values, allValue, concreteValues)

  return (
    <div className="sc-qa-chips" role="group" aria-label={groupLabel}>
      {options.map((option) => {
        const selected = all ? option.value === allValue : values.includes(option.value)
        return (
          <button
            key={String(option.value)}
            type="button"
            className="sc-chip sc-iq-chip sc-qa-chip"
            aria-pressed={selected}
            onClick={() => onChange(nextChoice(values, option.value, allValue, concreteValues))}
          >
            {selected ? `✓ ${option.label}` : option.label}
          </button>
        )
      })}
    </div>
  )
}
