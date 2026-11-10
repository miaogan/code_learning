import { NavLink } from 'react-router-dom'

export type StepState = 'done' | 'current' | 'todo'

export interface StepItem {
  key: string
  label: string
  to: string
  state: StepState
}

export interface StepperProps {
  steps: StepItem[]
  /** 侧栏 240 用 vertical；<1024 顶部横向 40 用 horizontal */
  orientation?: 'vertical' | 'horizontal'
  /** 组标题（只在侧栏竖排显示；横向导航空间紧，组标题由 ToolNav 前的竖线分隔代替）。 */
  label?: string
}

/** 步骤导航：当前步 = 强调色 + 左侧 2px 竖条；已完成 = 对勾；未到达 = 三级文字。 */
export function Stepper({ steps, orientation = 'vertical', label = '流程' }: StepperProps) {
  const classes = ['sc-stepper', orientation === 'vertical' ? 'is-vertical' : 'is-horizontal']

  return (
    <nav className={classes.join(' ')} aria-label={label}>
      {orientation === 'vertical' ? <span className="sc-nav-label">{label}</span> : null}
      {steps.map((step) => (
        <NavLink
          key={step.key}
          to={step.to}
          className={`sc-step is-${step.state}`}
          aria-current={step.state === 'current' ? 'step' : undefined}
        >
          <span className="sc-step-dot" aria-hidden="true">
            {step.state === 'done' ? '✓' : ''}
          </span>
          <span className="sc-step-label">{step.label}</span>
        </NavLink>
      ))}
    </nav>
  )
}
