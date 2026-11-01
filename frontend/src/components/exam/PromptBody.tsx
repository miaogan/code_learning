import { parsePromptBlocks, splitInlineCode } from '../../lib/promptCode'

export interface PromptBodyProps {
  /** 题面原文（可能含 ```` ```lang ```` 围栏代码块） */
  prompt: string
  /** 文本段的类名：题卡用 `.sc-qcard-prompt`，错题本展开用 `.sc-qa-wrong-full-text` */
  textClassName?: string
}

/**
 * 题面渲染（r11 新增，题卡与错题本共用一份实现）。
 *
 * 为什么抽组件而不是各写一份：围栏规则一旦在题卡与练习页各写一份就会漂移
 * （TECHNICAL 的「重复风险」清单），所以解析只走 `lib/promptCode.ts`，渲染只走这里。
 *
 * **零回归口径**：无围栏题面必须输出 `<p class={textClassName}>{prompt}</p>`，与改前逐字相同——
 * 既有 80 题全部无围栏，笔试观感 0 变化。行内代码只在「含围栏」的题面上启用，
 * 因为无围栏路径不允许改写既有 DOM。
 */
export function PromptBody({ prompt, textClassName = 'sc-qcard-prompt' }: PromptBodyProps) {
  const blocks = parsePromptBlocks(prompt)
  const hasFence = blocks.some((block) => block.type === 'code')

  if (!hasFence) {
    // 无围栏：与改前逐字一致（AC-14 零回归）。
    return <p className={textClassName}>{prompt}</p>
  }

  return (
    <div className="sc-qa-prompt">
      {blocks.map((block, index) => {
        if (block.type === 'code') {
          return (
            <pre key={`code-${index}`} className="sc-qa-code">
              <code>{block.content}</code>
            </pre>
          )
        }
        return (
          <p key={`text-${index}`} className={textClassName}>
            {splitInlineCode(block.content).map((segment, segmentIndex) =>
              segment.type === 'code' ? (
                <code key={`inline-${segmentIndex}`} className="sc-qa-code-inline">
                  {segment.content}
                </code>
              ) : (
                <span key={`text-${segmentIndex}`}>{segment.content}</span>
              ),
            )}
          </p>
        )
      })}
    </div>
  )
}
