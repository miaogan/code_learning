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
 * 兜底回流的单句事实（r43）：`reintroduced_count <= 0` / 缺失时返回 `null`。
 * 与 `filteredNotice` 拼在**同一行**里复显，不单独挂标签（r6 三条遗留合并成一处说明）。
 */
export function backfillNotice(count: number | null | undefined): string | null {
  if (!isPositiveCount(count)) return null
  return `另有 ${count} 道因保持卷面结构被重新纳入`
}

/**
 * 熟练过滤的**规则说明**（r6 D-7 / D-9 收口，2026-11-02 · r19；r43 合并兜底回流计数）。
 * 解释「题怎么才会回流」「为什么卷面里仍会出现已熟练的题」，与兜底回流数合并成**一处**说明
 * —— 不再拆成三个分散标签（规则 / 复显 / L2 回流）。
 *
 * 开关：`filtered_count` 与 `reintroduced_count` 都 <= 0 / 缺失时返回 `null`，调用方不挂载节点。
 * 两者各自为 0 时也有真实场景：L2 把全部熟练题放回卷面（净过滤 0，但确实有回流）。
 *
 * 阈值措辞带「默认」：30 天 / 答对 2 次实际住在后端 `config.Settings`，可由环境变量覆盖；
 * 前端不据此做判定，只做说明，默认值漂移时文案仍以「默认」限定。
 */
export function proficiencyRuleHint(
  count: number | null | undefined,
  reintroduced: number | null | undefined = 0,
): string | null {
  const backfilled = isPositiveCount(reintroduced) ? reintroduced : 0
  if (!isPositiveCount(count) && backfilled === 0) return null
  const rule =
    '默认 30 天内答对 2 次及以上、且最近一次答对才计为熟练；超过 30 天或最近一次答错会自动回流到题池'
  return backfilled > 0
    ? `${rule}。${backfillNotice(backfilled)}`
    : rule
}
