/**
 * 题面围栏代码块解析（r11，纯函数，无 React 依赖）。
 *
 * 为什么单独抽出来：练习题面含代码块，共享题卡（ExamQuestionCard）与错题本展开都要渲染同一份规则；
 * 两处各写一份解析必然漂移（TECHNICAL §6.5）。一次解析 → 两处复用。
 *
 * 三条硬口径：
 * 1. **无围栏 → 恰好一个 text 块，内容与入参逐字相等**（既有 80 题零回归的前提）。
 * 2. 围栏行 = 以 ```` ``` ```` 开头的行（可带语言标注，缺省为空串）；CRLF 先归一成 LF。
 * 3. 未闭合围栏**不抛错**：整体退化成单个 text 块（题面照原样展示，不吞内容、不丢行）。
 */

export type PromptBlock =
  | { type: 'text'; content: string }
  | { type: 'code'; content: string; lang: string }

/** 围栏标记：三个反引号。抽成常量，避免多处字面量写错。 */
const FENCE = '```'

/** 行内代码的切片：`text` 原样展示，`code` 用 `.sc-qa-code-inline` 等宽展示。 */
export interface InlineSegment {
  type: 'text' | 'code'
  content: string
}

/** CRLF / 孤立 CR 一律归一成 LF（题库文件可能是任一平台写出的）。 */
function normalizeNewlines(input: string): string {
  return input.replace(/\r\n?/g, '\n')
}

/**
 * 把题面按围栏切成 text / code 块。
 * 空文本段（围栏之间的空行、首尾空白）不产出块，避免渲染多余空行。
 */
export function parsePromptBlocks(prompt: string): PromptBlock[] {
  const source = typeof prompt === 'string' ? normalizeNewlines(prompt) : ''
  if (!source.includes(FENCE)) return [{ type: 'text', content: source }]

  const blocks: PromptBlock[] = []
  let textBuffer: string[] = []
  let open: { lang: string; lines: string[] } | null = null

  const flushText = (): void => {
    const content = textBuffer.join('\n').trim()
    if (content !== '') blocks.push({ type: 'text', content })
    textBuffer = []
  }

  for (const line of source.split('\n')) {
    const trimmed = line.trim()
    if (trimmed.startsWith(FENCE)) {
      if (open === null) {
        flushText()
        open = { lang: trimmed.slice(FENCE.length).trim(), lines: [] }
      } else {
        blocks.push({ type: 'code', content: open.lines.join('\n'), lang: open.lang })
        open = null
      }
      continue
    }
    if (open !== null) {
      open.lines.push(line)
      continue
    }
    textBuffer.push(line)
  }

  // 未闭合：整体当文本（不抛错、不丢内容）。
  if (open !== null) return [{ type: 'text', content: source }]

  flushText()
  return blocks.length > 0 ? blocks : [{ type: 'text', content: source }]
}

/**
 * 行内代码切片（只用于「含围栏」的题面：无围栏题面必须逐字渲染，不能改写既有 80 题的 DOM）。
 * 反引号成对出现；落单的最后一个反引号按普通字符处理。
 */
export function splitInlineCode(text: string): InlineSegment[] {
  const segments: InlineSegment[] = []
  let cursor = 0
  while (cursor < text.length) {
    const openIndex = text.indexOf('`', cursor)
    if (openIndex < 0) break
    const closeIndex = text.indexOf('`', openIndex + 1)
    if (closeIndex < 0) break
    if (openIndex > cursor) {
      segments.push({ type: 'text', content: text.slice(cursor, openIndex) })
    }
    const content = text.slice(openIndex + 1, closeIndex)
    if (content !== '') segments.push({ type: 'code', content })
    cursor = closeIndex + 1
  }
  if (cursor < text.length) segments.push({ type: 'text', content: text.slice(cursor) })
  return segments.length > 0 ? segments : [{ type: 'text', content: text }]
}
