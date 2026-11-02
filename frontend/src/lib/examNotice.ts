/**
 * AC-12 一行透明度文案的**唯一出处**（纯函数，vitest 可直接覆盖 —— 本项目无 RTL/jsdom，
 * 所以「文案怎么算」必须与「怎么渲染」分离，否则这段判定无法被测试）。
 *
 * 语义：`filtered_count` 是服务端算好的**净过滤数**（`|熟练 ∩ 可用| − |熟练 ∩ 本卷|`，恒 `>= 0`）。
 * 前端只负责把它解读成一句话：**不做比较、不做减法、不改写措辞** ——
 * 一旦页面自己再判定一次，就会出现「文案说过滤了 3 道、卷面却抽出 2 道」这类自相矛盾。
 *
 * 静默口径：`0` / 负数 / `NaN` / `±Infinity` / `null` / `undefined` 一律返回 `null`，
 * 调用方据此**不挂载节点**（不是 `display:none`），避免「本次已过滤 0 道」这种误导性断言
 * （L6 全库兜底时尤其不能说谎）；旧 payload / 刷新后的会话缺该字段也走这条静默路径。
 */
export function filteredNotice(count: number | null | undefined): string | null {
  if (!isPositiveCount(count)) return null
  return `本次已过滤 ${count} 道你已熟练掌握的题`
}

/** 正数判定：`filteredNotice` 与 `proficiencyRuleHint` 共用同一静默口径（含 `NaN` / `±Infinity`）。 */
function isPositiveCount(count: number | null | undefined): count is number {
  return typeof count === 'number' && Number.isFinite(count) && count > 0
}

/**
 * 熟练过滤的**规则说明**（r6 D-7 / D-9 收口，2026-11-02 · r19）：解释「为什么被过滤、怎样回流」，
 * 以及「为什么卷面里仍会出现已熟练的题」（兜底会为保持卷面结构把个别熟练题放回）。
 *
 * 只与 `filteredNotice` 同一开关：`N <= 0` / 缺失时返回 `null`，调用方不挂载节点——
 * L6 全库兜底时不能凭空解释一条不存在的过滤事实。
 *
 * **不写具体阈值**（30 天 / 答对 2 次 / 近 3 卷只住在后端 `config.Settings`）：前端硬编码数字
 * 会在阈值调整后变成假话；这里只描述规则方向，数字以服务端行为为准。
 */
export function proficiencyRuleHint(count: number | null | undefined): string | null {
  if (!isPositiveCount(count)) return null
  return '近期多次答对的题会暂时跳过，不再算作熟练后自动回流；个别熟练题可能因卷面结构重新出现'
}
