/**
 * 导出文件名（r4 D-2 的**单一命名真源**）。
 *
 * 口径：`修文-<原文件名去扩展名>.md`；原名不可用（空/缺失/全脏）时回退 `修文-<yyyy-mm-dd>.md`。
 *
 * 三条边界：
 * 1. 文件名来自契约字段 `file_name`（`documents.file_name`，后端读出），**不在前端自造**；
 * 2. 清洗是**白名单式**：只过滤路径分隔符、Windows 非法字符与 C0 控制符，绝不剥中文 / 空格 / 常见标点；
 * 3. 纯函数（入参 + 可选 `now`），无 DOM / 无网络 → 页面、检查器与 vitest 共用同一口径，页面内零规则。
 */

/** 导出名前缀（与「修文」入口同名，含全角连接符）。 */
export const EXPORT_PREFIX = '修文-'

/** 清洗后基名的长度上限（按 code point 计，避免中文被按字节切一半）。 */
export const EXPORT_MAX_BASE_CHARS = 120

/** Windows 文件名非法字符（`/` 与 `\` 已先用基名切分剥离）。 */
const ILLEGAL_NAME_CHARS = '<>:"/\\|?*'

/** 视为「简历扩展名」的后缀（不区分大小写）；未知后缀原样保留。 */
const KNOWN_RESUME_EXTENSION = /\.(pdf|docx|doc|txt|md|rtf|html?)$/i

/** Windows 会吞掉结尾的点，所以尾部 `.` 必须去掉。 */
const TRAILING_DOT = /\.+$/

const PATH_SEPARATORS = /[/\\]/

/** 去掉 C0 控制符与 Windows 非法字符（逐 code point 过滤，不动任何其它字符）。 */
function stripIllegalNameChars(input: string): string {
  let cleaned = ''
  for (const char of input) {
    if (ILLEGAL_NAME_CHARS.includes(char)) continue
    const codePoint = char.codePointAt(0) ?? 0
    if (codePoint < 0x20) continue
    cleaned += char
  }
  return cleaned
}

/**
 * 清洗后的基名（不含 `EXPORT_PREFIX` 与 `.md`）。
 * 返回 `''` 表示「没有可用的原名」——由调用方回退日期格式（AC-8）。
 */
export function sanitizeFileBase(fileName: string | null | undefined): string {
  // 1. 空值 / 全空白 → 无可用原名
  if (fileName === null || fileName === undefined) return ''
  if (fileName.trim() === '') return ''

  // 2. 取基名：`a/b.pdf`、`C:\x\c.pdf` 都只剩文件名本身
  const segments = fileName.split(PATH_SEPARATORS)
  const baseName = segments[segments.length - 1] ?? ''

  // 3. 剥 Windows 非法字符与 C0 控制符
  let base = stripIllegalNameChars(baseName)

  // 4. 去扩展名（仅已知简历后缀；无扩展名原样保留）
  base = base.replace(KNOWN_RESUME_EXTENSION, '')

  // 5. 去首尾空白与尾部 `.`（Windows 会吞尾点）
  base = base.trim().replace(TRAILING_DOT, '').trim()

  // 6. 清洗后为空 → 交回调用方回退
  if (base === '') return ''

  // 7. 按 code point 截断到 120，截断后再去尾部空白
  return Array.from(base).slice(0, EXPORT_MAX_BASE_CHARS).join('').trimEnd()
}

/** 本地时间 `yyyy-mm-dd`（补零；沿用 r3 的日期版式，仅作无原名时的回退）。 */
function dateStamp(now: Date): string {
  const pad = (value: number) => String(value).padStart(2, '0')
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`
}

/**
 * 导出文件名：`修文-<清洗后原名>.md`；无可用原名时回退 `修文-<yyyy-mm-dd>.md`。
 * 全程不抛错、不弹错误（AC-8：旧简历没有文件名也要能导出）。
 */
export function exportFileName(fileName: string | null | undefined, now: Date = new Date()): string {
  const base = sanitizeFileBase(fileName)
  const resolved = base === '' ? dateStamp(now) : base
  return `${EXPORT_PREFIX}${resolved}.md`
}
