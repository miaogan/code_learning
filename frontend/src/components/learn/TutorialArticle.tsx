import { useEffect, useRef } from 'react'
import { activeSectionIndex } from '../../lib/tutorials'
import type { TutorialBlock, TutorialChapter } from '../../lib/tutorialTypes'

function headingId(sectionId: string): string {
  return `tutorial-${sectionId}`
}

/** 正文块渲染：按 `kind` 分支，新增块类型必须在这里补一支（类型穷举由 TS 保证）。 */
function BlockView({ block }: { block: TutorialBlock }) {
  switch (block.kind) {
    case 'text':
      return <p className="sc-learn-text">{block.text}</p>

    case 'list':
      return block.ordered ? (
        <ol className="sc-learn-list">
          {block.items.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ol>
      ) : (
        <ul className="sc-learn-list">
          {block.items.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      )

    case 'code':
      return (
        <div className="sc-learn-codeblock">
          <div className="sc-learn-codehead">
            {block.caption ? <span>{block.caption}</span> : <span />}
            <span className="sc-learn-lang">{block.language}</span>
          </div>
          <pre className="sc-qa-code sc-learn-code">
            <code>{block.code}</code>
          </pre>
        </div>
      )

    case 'note':
      return (
        <div className={block.tone === 'warn' ? 'sc-learn-note is-warn' : 'sc-learn-note'}>
          <p className="sc-learn-notetitle">{block.title}</p>
          <p className="sc-learn-notetext">{block.text}</p>
        </div>
      )

    case 'table':
      return (
        <div className="sc-learn-tablewrap">
          <table className="sc-learn-table">
            <thead>
              <tr>
                {block.headers.map((header) => (
                  <th key={header}>{header}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {block.rows.map((row, rowIndex) => (
                <tr key={`row-${rowIndex}`}>
                  {row.map((cell, cellIndex) => (
                    <td key={`cell-${cellIndex}`}>{cell}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )

    case 'qa':
      return (
        <div className="sc-learn-qa">
          {block.items.map((item) => (
            <details className="sc-learn-qaitem" key={item.question}>
              <summary className="sc-learn-question">{item.question}</summary>
              <p className="sc-learn-answer">{item.answer}</p>
            </details>
          ))}
        </div>
      )
  }
}

export interface TutorialArticleProps {
  chapter: TutorialChapter
  /** 某小节滚进视口时回调（用于记已读）；不传就不观察。 */
  onSectionSeen?: (sectionId: string) => void
  /** 当前正在读的小节变化时回调（用于目录高亮）；不传就不观察。 */
  onActiveSectionChange?: (sectionId: string | null) => void
}

/**
 * 小节可见性观察，两个观察器各管一件事：
 *
 * 1. **已读**：小节进入视口上部 75% 即算读到（`rootMargin: 0 0 -25% 0`）。
 *    留 25% 底部余量，避免小节刚从屏幕底边露头就计数；也不能留太多，
 *    否则短小节贴在页脚时永远进不来，读完就卡在 3/4。
 * 2. **高亮**：只盯视口上部 40% 这条带（`0 0 -60% 0`）作为「触发时机」，
 *    回调里再按各节顶边相对视口的位置重算（`activeSectionIndex`）——
 *    直接用「谁在带里」会滞后一节：滚到第 3 节时第 2 节的尾巴还在带里。
 *
 * 环境不支持 IntersectionObserver（老浏览器 / 测试环境）时静默跳过，不阻断阅读。
 */
function useSectionObserver(
  chapter: TutorialChapter,
  onSectionSeen: ((sectionId: string) => void) | undefined,
  onActiveSectionChange: ((sectionId: string | null) => void) | undefined,
) {
  const ref = useRef<HTMLElement | null>(null)

  useEffect(() => {
    const root = ref.current
    if (root === null) return
    if (onSectionSeen === undefined && onActiveSectionChange === undefined) return
    if (typeof IntersectionObserver === 'undefined') return

    const elements = Array.from(root.querySelectorAll<HTMLElement>('[data-section-id]'))
    const readSectionId = (element: Element): string | undefined =>
      (element as HTMLElement).dataset.sectionId

    const seenObserver =
      onSectionSeen === undefined
        ? null
        : new IntersectionObserver(
            (entries) => {
              entries.forEach((entry) => {
                if (!entry.isIntersecting) return
                const sectionId = readSectionId(entry.target)
                if (sectionId !== undefined) onSectionSeen(sectionId)
              })
            },
            { rootMargin: '0px 0px -25% 0px' },
          )

    const recomputeActive = () => {
      if (onActiveSectionChange === undefined) return
      const line = window.innerHeight * 0.4
      const tops = elements.map((element) => element.getBoundingClientRect().top)
      const index = activeSectionIndex(tops, line)
      const sectionId = chapter.sections[index]?.id
      if (sectionId !== undefined) onActiveSectionChange(sectionId)
    }

    const activeObserver =
      onActiveSectionChange === undefined
        ? null
        : new IntersectionObserver(recomputeActive, { rootMargin: '0px 0px -60% 0px' })

    elements.forEach((element) => {
      seenObserver?.observe(element)
      activeObserver?.observe(element)
    })

    return () => {
      seenObserver?.disconnect()
      activeObserver?.disconnect()
    }
  }, [chapter, onSectionSeen, onActiveSectionChange])

  return ref
}

/** 章节正文：小节锚点 + 块渲染；全部按 React 文本渲染，不拼 HTML 字符串。 */
export function TutorialArticle({
  chapter,
  onSectionSeen,
  onActiveSectionChange,
}: TutorialArticleProps) {
  const articleRef = useSectionObserver(chapter, onSectionSeen, onActiveSectionChange)

  return (
    <article className="sc-learn-article" ref={articleRef}>
      {chapter.sections.map((section) => (
        <section
          className="sc-learn-section"
          id={headingId(section.id)}
          data-section-id={section.id}
          key={section.id}
          aria-labelledby={`${headingId(section.id)}-title`}
        >
          <h2 className="sc-learn-sectiontitle" id={`${headingId(section.id)}-title`}>
            {section.title}
          </h2>
          {section.blocks.map((block, index) => (
            <BlockView block={block} key={`${section.id}-${index}`} />
          ))}
        </section>
      ))}
    </article>
  )
}
