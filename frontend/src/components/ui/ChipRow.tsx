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
