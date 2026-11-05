import type { Evidence } from '../../api/types'

/** 来源日期：ISO 串取前 10 位（yyyy-mm-dd），其它形态原样返回（不猜、不补假日期）。 */
export function evidenceDate(raw: string): string | null {
  const trimmed = raw.trim()
  if (trimmed === '') return null
  const head = trimmed.slice(0, 10)
  return /^\d{4}-\d{2}-\d{2}$/.test(head) ? head : trimmed
}

/** 「来源 · 文件名 · 日期」meta 行（DESIGN §2.2 证据块）；缺失字段诚实占位。 */
export function evidenceSourceLine(item: Evidence): string {
  const file = item.file_name.trim() === '' ? '来源未记录' : item.file_name.trim()
  const date = evidenceDate(item.captured_at)
  return date === null ? `来源 · ${file}` : `来源 · ${file} · ${date}`
}

/** 空引文（模型空串/幻觉占位）不进入可视证据链。 */
export function visibleEvidence(evidence: Evidence[]): Evidence[] {
  return evidence.filter((item) => item.quote.trim() !== '')
}
