import { useId, useState } from 'react'

export interface ExplanationProps {
  /** 解析正文（空串 → 降级「本题暂无解析」，不留空白块） */
  text: string
  /** 默认展开（PRD 决策：提交后必须直接看到解析；折叠是可选动作，不是默认） */
  defaultOpen?: boolean
}

const EMPTY_TEXT = '本题暂无解析'

/**
 * 解析折叠块（r11）：默认展开，可折叠 / 再展开。
 *
 * 结构：折叠按钮（`aria-expanded` + `aria-controls` 指向正文 id）+ 正文（2px accent 竖线）。
 * 无障碍口径（DESIGN §5）：展开/收起**不移动焦点**；正文 `id` 由 `useId()` 稳定生成；内容直接挂载/卸载，
 * 不做高度动画（只让箭头 120ms 旋转）。
 *
 * 布局协作：外层 `.sc-qa-exp-block` 用 `display: contents`，让按钮与正文直接落进父级
 * `.sc-qa-feedback` 的网格 —— 按钮与「✓ 正确 / 正确答案」同行右端，正文通栏在下一行，
 * 而组件自己不必知道父级长什么样。
 */
export function Explanation({ text, defaultOpen = true }: ExplanationProps) {
  const [open, setOpen] = useState(defaultOpen)
  const bodyId = useId()
  const body = text.trim() === '' ? EMPTY_TEXT : text

  return (
    <div className="sc-qa-exp-block">
      <button
        type="button"
        className="sc-btn sc-btn--ghost is-sm sc-qa-exp-toggle"
        aria-expanded={open}
        aria-controls={bodyId}
        onClick={() => setOpen((previous) => !previous)}
      >
        {open ? '收起解析' : '展开解析'}
        <span className={open ? 'sc-qa-caret is-open' : 'sc-qa-caret'} aria-hidden="true">
          ⌄
        </span>
      </button>
      {open ? (
        <p className="sc-qa-exp" id={bodyId}>
          {body}
        </p>
      ) : null}
    </div>
  )
}
