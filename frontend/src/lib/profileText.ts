/**
 * 画像文本的空值归一与拼接（r8）的**纯函数单一出处**（无 DOM、无请求，vitest 可直接测）。
 *
 * 为什么单独成模块：`ProfileProject.role` / `period` 在契约上可空（后端 `str | None = None`，
 * 提示词明确允许模型「无法判断填 null」），于是「渲染项目卡 meta」「编辑框取值」「出站 PATCH 组装」
 * 三条路径都要面对 `string | null | undefined`。如果三处各写一遍 `?? ''`，任一处漂移就会再次出现
 * `null.trim()` 白屏或页面渲染出 `null` / 悬空 ` · `（PRD anti-goal 3）。
 *
 * `null` 语义三分（TECHNICAL §2.3）：
 * - `null` = 简历里没写（未知，**不是**空字符串伪装成已知）；
 * - `''`  = 用户编辑时显式清空 → 出站前由页面 `trimToNull` 归一为 `null`；
 * - 键缺失 = 存量 payload（旧库无该字段）→ 这里与 `null` 同口径兜住。
 */

/** meta 行的分隔符（与既有 `' · '` 渲染一致，不引入新样式）。 */
const META_SEPARATOR = ' · '

/**
 * `null` / `undefined` → `''`；有值时去掉首尾空白。
 *
 * 同时服务两条路径：编辑框的 `value`（受控输入不接受 `null`）与 meta 拼接的每一侧。
 * 纯空白（`'   '`）视同未填写 —— 否则会渲染出一条只有空格的「已知」信息。
 */
export function textOrEmpty(value: string | null | undefined): string {
  if (typeof value !== 'string') return ''
  return value.trim()
}

/**
 * 项目卡 meta：「角色 · 时间」。
 *
 * 整侧为空则只显示另一侧；两侧皆空返回 `''`（`ProfileDimension` 的 `entry.meta ? … : null`
 * 会吞掉空串 ⇒ 不渲染 meta 行、不出现悬空分隔符）。入参保持 `ReadonlyArray`：调用点直接
 * 传 `[item.role, item.period]` 字面量，不要求先过滤。
 */
export function joinMeta(parts: ReadonlyArray<string | null | undefined>): string {
  return parts
    .map(textOrEmpty)
    .filter((part) => part !== '')
    .join(META_SEPARATOR)
}
