export interface PhaseLoaderProps {
  /** 三段式阶段文案（DESIGN §0.6：AI 调用用文案步进，禁止只有转圈） */
  phases: string[]
  active: number
  elapsedSec?: number
  title?: string
}

/** 阶段文案加载：当前段 3 点脉冲，已完成段对勾，右侧显示已用秒数。 */
export function PhaseLoader({ phases, active, elapsedSec, title }: PhaseLoaderProps) {
  return (
    <div className="sc-phase">
      {title ? <p className="sc-phase-text">{title}</p> : null}
      <ul className="sc-phase-list">
        {phases.map((phase, index) => {
          const stateClass = index < active ? 'is-done' : index === active ? 'is-active' : ''
          return (
            <li key={phase} className={`sc-phase-item ${stateClass}`.trim()}>
              {index === active ? (
                <span className="sc-dots" aria-hidden="true">
                  <span />
                  <span />
                  <span />
                </span>
              ) : (
                <span aria-hidden="true">{index < active ? '✓' : '·'}</span>
              )}
              <span>{phase}</span>
            </li>
          )
        })}
      </ul>
      {typeof elapsedSec === 'number' ? (
        <span className="sc-elapsed">已用 {elapsedSec}s</span>
      ) : null}
    </div>
  )
}
