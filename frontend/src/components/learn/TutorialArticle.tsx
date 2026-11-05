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
}

/** 章节正文：小节锚点 + 块渲染；全部按 React 文本渲染，不拼 HTML 字符串。 */
export function TutorialArticle({ chapter }: TutorialArticleProps) {
  return (
    <article className="sc-learn-article">
      {chapter.sections.map((section) => (
        <section
          className="sc-learn-section"
          id={headingId(section.id)}
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
