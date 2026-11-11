/**
 * 检索增强学习计划（M3）的前端纯函数层。
 *
 * 职责：把教程章节切分成小节级可检索文档，用 BM25 做关键词召回，
 * 并提供多路召回结果的 RRF 融合。全程无 DOM、无存储、无第三方依赖，
 * 相同入参的输出保持确定性。
 */
import { DIRECTIONS, SUBDIRECTIONS } from './questionDirections'
import { TUTORIAL_LEVELS } from './tutorials'
import type { TutorialBlock, TutorialChapter } from './tutorialTypes'

/** 小节级检索文档：一节一条，text 汇总该节全部正文块的可检索文本。 */
export interface SectionDoc {
  chapter_id: string
  section_id: string
  title: string
  direction: string
  sub_direction: string
  level: string
  text: string
}

/** 一条检索命中：href 复用 r25 的断点续读锚点。 */
export interface Citation {
  chapter_id: string
  section_id: string
  title: string
  snippet: string
  href: string
  score: number
  source: 'tutorial' | 'question'
}

/** 元数据过滤条件：闭集外的取值一律静默忽略；方向支持多选（数组取并集）。 */
export interface SearchFilters {
  direction?: string | readonly string[]
  sub_direction?: string
  level?: string
}

/** RRF 的输入与输出单元：融合只按名次计算，输入的 score 不参与。 */
export interface RankedHit {
  id: string
  score: number
  source: 'tutorial' | 'question'
}

const DIRECTION_SET = new Set<string>(DIRECTIONS)
const LEVEL_SET = new Set<string>(TUTORIAL_LEVELS)
const SUB_DIRECTION_SET = new Set<string>(Object.values(SUBDIRECTIONS).flat())

const K1 = 1.5
const B = 0.75

/** 取一个正文块里所有可检索文本片段，顺序按块内自然顺序。 */
function blockText(block: TutorialBlock): string[] {
  switch (block.kind) {
    case 'text':
      return [block.text]
    case 'list':
      return block.items
    case 'code':
      return block.caption ? [block.code, block.caption] : [block.code]
    case 'note':
      return [block.title, block.text]
    case 'table':
      return [block.headers.join(' '), ...block.rows.map((row) => row.join(' '))]
    case 'qa':
      return block.items.flatMap((item) => [item.question, item.answer])
    case 'demo':
      return block.caption ? [block.title, block.caption] : [block.title]
    default:
      return []
  }
}

/** 按章节数组原序、小节原序生成小节文档；text 以空格连接各片段，结果确定。 */
export function buildSectionDocs(chapters: TutorialChapter[]): SectionDoc[] {
  const docs: SectionDoc[] = []
  for (const chapter of chapters) {
    for (const section of chapter.sections) {
      const parts: string[] = []
      for (const block of section.blocks) {
        parts.push(...blockText(block))
      }
      docs.push({
        chapter_id: chapter.id,
        section_id: section.id,
        title: section.title,
        direction: chapter.direction,
        sub_direction: chapter.sub_direction,
        level: chapter.level,
        text: parts.join(' '),
      })
    }
  }
  return docs
}

/** 一个码元是否属于英文或数字连续串。 */
function isWordChar(code: number): boolean {
  return (code >= 48 && code <= 57) || (code >= 97 && code <= 122)
}

/** 一个码元是否属于中日韩统一表意文字基本区与扩展 A 区。 */
function isCjkChar(code: number): boolean {
  return code >= 0x3400 && code <= 0x9fff
}

/**
 * 轻量分词：统一小写，英文与数字连续串整体为一个 term，
 * 中文连续串拆成单字 term 与相邻二元字组 term，空白与标点作为分隔忽略。
 * 查询与文档共用同一套切分，保证 term 口径一致。
 */
function tokenize(text: string): string[] {
  const lower = text.toLowerCase()
  const terms: string[] = []
  let i = 0
  while (i < lower.length) {
    const code = lower.charCodeAt(i)
    if (isWordChar(code)) {
      let j = i + 1
      while (j < lower.length && isWordChar(lower.charCodeAt(j))) j += 1
      terms.push(lower.slice(i, j))
      i = j
    } else if (isCjkChar(code)) {
      let j = i + 1
      while (j < lower.length && isCjkChar(lower.charCodeAt(j))) j += 1
      const run = lower.slice(i, j)
      for (let p = 0; p < run.length; p += 1) {
        terms.push(run[p])
        if (p + 1 < run.length) terms.push(run[p] + run[p + 1])
      }
      i = j
    } else {
      i += 1
    }
  }
  return terms
}

/** 过滤取值：空串、闭集外取值、非字符串一律回落到不筛选，绝不抛错。 */
function resolveFilter(value: string | undefined, closedSet: Set<string>): string | null {
  if (typeof value !== 'string' || value === '' || !closedSet.has(value)) return null
  return value
}

/** 多选过滤取值：闭集外取值静默丢弃；一个都不剩（或本身就是全选）回 `null` = 不过滤。 */
function resolveFilterList(
  value: string | readonly string[] | undefined,
  closedSet: Set<string>,
): string[] | null {
  const raw = typeof value === 'string' ? [value] : value
  if (raw === undefined) return null
  const picked = raw.filter((item): item is string => typeof item === 'string' && closedSet.has(item))
  return picked.length === 0 ? null : picked
}

/** 字典序比较，供确定性平局排序使用。 */
function compareText(left: string, right: string): number {
  if (left < right) return -1
  if (left > right) return 1
  return 0
}

/** 从匹配到的第一个 query term 起截 60 字；正文无命中时取正文前 60 字。 */
function makeSnippet(text: string, queryTerms: string[]): string {
  const normalized = text.toLowerCase().replace(/[^a-z0-9\u3400-\u9fff]/g, ' ')
  let start = -1
  for (const term of queryTerms) {
    const at = normalized.indexOf(term)
    if (at !== -1 && (start === -1 || at < start)) start = at
  }
  const from = start === -1 ? 0 : start
  return text.slice(from, from + 60)
}

interface CorpusEntry {
  doc: SectionDoc
  tf: Map<string, number>
  docLen: number
}

/**
 * 关键词检索：先按元数据硬过滤得到文档集，再在该集合上计算 BM25。
 * 检索文本在小节正文之外补上章节标题与小节标题，让标题类关键词也能召回；
 * snippet 仍只基于小节正文。
 */
export function searchTutorials(
  query: string,
  filters: SearchFilters,
  chapters: TutorialChapter[],
  limit = 5,
): Citation[] {
  const rawQuery = typeof query === 'string' ? query : ''
  const queryTerms = [...new Set(tokenize(rawQuery))]
  if (queryTerms.length === 0) return []

  const safeFilters: SearchFilters = filters ?? {}
  const directions = resolveFilterList(safeFilters.direction, DIRECTION_SET)
  const subDirection = resolveFilter(safeFilters.sub_direction, SUB_DIRECTION_SET)
  const level = resolveFilter(safeFilters.level, LEVEL_SET)

  const filtered = buildSectionDocs(chapters).filter(
    (doc) =>
      (directions === null || directions.includes(doc.direction)) &&
      (subDirection === null || doc.sub_direction === subDirection) &&
      (level === null || doc.level === level),
  )
  if (filtered.length === 0) return []

  const chapterTitles = new Map<string, string>()
  for (const chapter of chapters) chapterTitles.set(chapter.id, chapter.title)

  const corpus: CorpusEntry[] = filtered.map((doc) => {
    const head = chapterTitles.get(doc.chapter_id) ?? ''
    const terms = tokenize(`${head} ${doc.title} ${doc.text}`)
    const tf = new Map<string, number>()
    for (const term of terms) tf.set(term, (tf.get(term) ?? 0) + 1)
    return { doc, tf, docLen: terms.length }
  })

  const total = corpus.length
  const avgdl = corpus.reduce((sum, entry) => sum + entry.docLen, 0) / total

  const df = new Map<string, number>()
  for (const term of queryTerms) {
    let count = 0
    for (const entry of corpus) if (entry.tf.has(term)) count += 1
    df.set(term, count)
  }

  const scored: { doc: SectionDoc; score: number }[] = []
  for (const entry of corpus) {
    let score = 0
    for (const term of queryTerms) {
      const freq = entry.tf.get(term)
      if (freq === undefined) continue
      const docFreq = df.get(term) ?? 0
      const idf = Math.log(1 + (total - docFreq + 0.5) / (docFreq + 0.5))
      const lengthRatio = avgdl > 0 ? entry.docLen / avgdl : 0
      const denominator = freq + K1 * (1 - B + B * lengthRatio)
      score += (idf * freq * (K1 + 1)) / denominator
    }
    if (score > 0) scored.push({ doc: entry.doc, score })
  }

  scored.sort(
    (left, right) =>
      right.score - left.score ||
      compareText(left.doc.chapter_id, right.doc.chapter_id) ||
      compareText(left.doc.section_id, right.doc.section_id),
  )

  return scored.slice(0, Math.max(0, limit)).map(
    (entry): Citation => ({
      chapter_id: entry.doc.chapter_id,
      section_id: entry.doc.section_id,
      title: entry.doc.title,
      snippet: makeSnippet(entry.doc.text, queryTerms),
      href: `/learn/${entry.doc.chapter_id}#tutorial-${entry.doc.section_id}`,
      score: Math.round(entry.score * 10000) / 10000,
      source: 'tutorial',
    }),
  )
}

/**
 * 标准 RRF：每条 list 按名次累加 1/(k+rank)，rank 从 1 起，同 id 合并。
 * 输入 hit 自带 score 不参与融合，输出 score 保留 6 位小数。
 */
export function reciprocalRankFusion(lists: RankedHit[][], k = 60): RankedHit[] {
  const fused = new Map<string, { score: number; source: RankedHit['source'] }>()
  for (const list of lists) {
    list.forEach((hit, index) => {
      const gain = 1 / (k + index + 1)
      const current = fused.get(hit.id)
      if (current === undefined) {
        fused.set(hit.id, { score: gain, source: hit.source })
      } else {
        current.score += gain
      }
    })
  }

  const result: RankedHit[] = []
  for (const [id, entry] of fused) {
    result.push({
      id,
      score: Math.round(entry.score * 1000000) / 1000000,
      source: entry.source,
    })
  }
  result.sort(
    (left, right) => right.score - left.score || compareText(left.id, right.id),
  )
  return result
}
