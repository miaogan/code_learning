import type { InterviewSettings } from '../../api/types'
import { settingsLine } from './chatModel'

export interface SettingsBarProps {
  settings: InterviewSettings | null
  /** 条首前缀，默认「本场设定」；报告页沿用同一表面与文案口径。 */
  label?: string
}

/**
 * 只读「本场设定」条（48 高，会话顶 / 报告顶共用，DESIGN §0.3）。
 * 纯展示、无交互、无请求；四项一行，窄屏允许换行（不截断不省略）。
 */
export function SettingsBar({ settings, label = '本场设定' }: SettingsBarProps) {
  return (
    <div className="sc-settings-bar" role="group" aria-label={label}>
      <span className="sc-merge-bar-label">{label}</span>
      <span className="sc-settings-bar-text">{settingsLine(settings)}</span>
    </div>
  )
}
