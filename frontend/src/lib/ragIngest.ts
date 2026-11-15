import type { RagIngestBlock, RagIngestItem } from '../api/types'
import type { TutorialBlock } from './tutorialTypes'
import { TUTORIAL_CHAPTERS } from '../content/tutorials'

/**
 * r100：把站内教程（正文只在前端 `content/tutorials/`）整份组装成 RAG chunk，
 * 推给服务端做 embedding 与索引。**必须整份推送**——后端是全量替换语义，
 * 少推的小节旧 chunk 会被删掉。
 *
 * r103：同时传结构化 `blocks`——后端按 block 类型选切分器（代码按行、表格重复表头、
 * 正文按句子），前端只负责「原样传结构」，不猜切分口径。`content` 仍保留为兜底
 * （旧后端 / 旧客户端兼容）。
 */
function serializeBlock(block: TutorialBlock): string {
  switch (block.kind) {
    case 'text':
    case 'note':
      return block.text
    case 'list':
      return block.items.join('；')
    case 'table':
      return [block.headers.join(' | '), ...block.rows.map((row) => row.join(' | '))].join('\n')
    case 'code':
      return [block.caption ? `示例：${block.caption}` : '代码示例', block.code].join('\n')
    default:
      return ''
  }
}

function toIngestBlock(block: TutorialBlock): RagIngestBlock {
  switch (block.kind) {
    case 'text':
      return { kind: 'text', text: block.text }
    case 'note':
      return { kind: 'note', title: block.title, text: block.text }
    case 'list':
      return { kind: 'list', items: block.items }
    case 'table':
      return { kind: 'table', headers: block.headers, rows: block.rows }
    case 'code':
      return { kind: 'code', code: block.code, caption: block.caption ?? '' }
    default:
      return { kind: 'text', text: '' }
  }
}

export function buildTutorialChunks(): RagIngestItem[] {
  const items: RagIngestItem[] = []
  for (const chapter of TUTORIAL_CHAPTERS) {
    for (const section of chapter.sections) {
      const content = [
        `${chapter.title} · ${section.title}`,
        ...section.blocks.map(serializeBlock).filter(Boolean),
      ]
        .join('\n')
        .trim()
      if (content) {
        items.push({
          chapter_id: chapter.id,
          section_id: section.id,
          title: `${chapter.direction} · ${chapter.title} · ${section.title}`,
          content,
          blocks: section.blocks.map(toIngestBlock),
        })
      }
    }
  }
  return items
}
