/**
 * 多选 chip 的纯逻辑（与 React 无关，独立成模块以满足 Fast Refresh 的「组件文件只导出组件」约束）。
 * 所有允许选「全部」的筛选组（练习、错题本及后续页面）共用这一份折叠语义。
 */

/** 「全部」判定：空数组 / 含「全部」哨兵 / 已勾满全部具体项，三种形态都算全选。 */
export function isAllChoice<T extends string | number>(
  values: readonly T[],
  allValue: T,
  concreteValues: readonly T[],
): boolean {
  if (values.length === 0 || values.includes(allValue)) return true
  return concreteValues.length > 0 && concreteValues.every((value) => values.includes(value))
}

/**
 * 点选一个 chip 后的下一组选中值：
 * - 点「全部」→ 只留哨兵；
 * - 当前是全选时点具体项 → 只选该项（从「全部」进入精挑）；
 * - 否则 toggle；清空或勾满全部具体项都自动折叠成 `[allValue]`。
 */
export function nextChoice<T extends string | number>(
  values: readonly T[],
  value: T,
  allValue: T,
  concreteValues: readonly T[],
): T[] {
  if (value === allValue) return [allValue]
  const all = isAllChoice(values, allValue, concreteValues)
  const next = all
    ? [value]
    : values.includes(value)
      ? values.filter((item) => item !== value)
      : [...values, value]
  if (next.length === 0 || concreteValues.every((item) => next.includes(item))) {
    return [allValue]
  }
  return next
}
