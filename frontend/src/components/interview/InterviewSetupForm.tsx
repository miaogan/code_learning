import { Button } from '../ui/Button'
import { Card } from '../ui/Card'
import { Chip } from '../ui/Chip'
import { InlineError } from '../ui/InlineError'
import {
  COMPANY_SIZES,
  DEFAULT_TARGET_ROLE,
  EXPERIENCE_BANDS,
  MARKETS,
  TARGET_ROLE_MAX_CHARS,
  TARGET_ROLE_WARN_CHARS,
  type SetupDraft,
  type SetupSource,
  type SetupSources,
  previewLine,
} from './setupModel'

/** 年数展示：整数不带小数（1 年 / 1.5 年）。 */
function formatYears(years: number): string {
  if (!Number.isFinite(years)) return '—'
  return Number.isInteger(years) ? String(years) : years.toFixed(1)
}

interface SourceBadgeProps {
  source: SetupSource | null
}

/** 来源徽章：来自画像（accent）/ 默认（中性）；source 为 null（用户手改）时整块不渲。 */
function SourceBadge({ source }: SourceBadgeProps) {
  if (!source) return null
  if (source === 'profile') return <Chip label="来自画像" tone="direction" />
  return <Chip label="默认" />
}

interface ChoiceChipProps {
  label: string
  selected: boolean
  onClick: () => void
}

/** 选项 chip：未选 24 中性 + hover；已选 accent 底 + 「✓」前缀（双通道，不只靠颜色）。 */
function ChoiceChip({ label, selected, onClick }: ChoiceChipProps) {
  return (
    <button
      type="button"
      className={
        selected
          ? 'sc-chip sc-chip--direction sc-iq-chip is-selected'
          : 'sc-chip sc-iq-chip is-clickable'
      }
      aria-pressed={selected}
      onClick={onClick}
    >
      {selected ? `✓ ${label}` : label}
    </button>
  )
}

export interface InterviewSetupFormProps {
  draft: SetupDraft
  sources: SetupSources
  submitting: boolean
  error: string | null
  onDraft: (next: SetupDraft) => void
  onStart: () => void
  onSkip: () => void
  /** 预填基准（画像预填值）：字段值与基准相同才显示来源徽章，手改即消失（不依赖组件内状态）。 */
  prefill?: SetupDraft | null
  /** 画像经验年数（可选，只用于「按画像 N 年 → 档位」帮助行，不参与判定）。 */
  profileYears?: number | null
}

/**
 * 配置一屏（AC-1 / AC-3，DESIGN §2.2）：四项一排一个控件、来源标注清楚、
 * 四项全空也能开始、开场后不可改、卡内没有任何「保存到画像」入口。
 *
 * 来源徽章用「当前值 vs 预填基准」派生（开局失败会重挂载本组件，组件内状态会丢，
 * 展示必须由 page 持有的 draft 派生，才不会出现「手改过的字段又标回来自画像」）。
 */
export function InterviewSetupForm({
  draft,
  sources,
  submitting,
  error,
  onDraft,
  onStart,
  onSkip,
  prefill = null,
  profileYears = null,
}: InterviewSetupFormProps) {
  const setField = <K extends keyof SetupDraft>(key: K, value: SetupDraft[K]) => {
    onDraft({ ...draft, [key]: value })
  }

  const sourceOf = (key: keyof SetupDraft): SetupSource | null => {
    if (prefill && prefill[key] !== draft[key]) return null
    return sources[key]
  }
  const roleChars = draft.target_role.length
  const roleWarn = roleChars >= TARGET_ROLE_WARN_CHARS
  const yearsHintVisible =
    sourceOf('years_experience') === 'profile' &&
    typeof profileYears === 'number' &&
    Number.isFinite(profileYears)

  return (
    <Card className="sc-iq-setup">
      <div className="sc-qcard">
        <div className="sc-qcard-head">
          <h2 className="sc-qcard-prompt">本场设定</h2>
          <Chip label="开场后不可改" />
        </div>
        <p className="sc-qcard-hint">这一次面试按下面的口径出题；四项都可以不改，直接开始也行。</p>

        <div className="sc-target-role">
          <div className="sc-qcard-head">
            <label className="sc-target-role-label" htmlFor="iq-target-role">
              目标岗位
            </label>
            <SourceBadge source={sourceOf('target_role')} />
          </div>
          <input
            id="iq-target-role"
            type="text"
            maxLength={TARGET_ROLE_MAX_CHARS}
            value={draft.target_role}
            placeholder={DEFAULT_TARGET_ROLE}
            disabled={submitting}
            onChange={(event) => setField('target_role', event.target.value)}
          />
          <div className="sc-qcard-head">
            <p className="sc-target-role-hint">留空按「{DEFAULT_TARGET_ROLE}」出题</p>
            <span className={roleWarn ? 'sc-badge sc-badge--medium' : 'sc-badge sc-badge--low'}>
              {roleChars}/{TARGET_ROLE_MAX_CHARS} 字
            </span>
          </div>
        </div>

        <div className="sc-target-role">
          <div className="sc-qcard-head">
            <span className="sc-target-role-label">工作经验</span>
            <SourceBadge source={sourceOf('years_experience')} />
          </div>
          <div className="sc-chips" role="group" aria-label="工作经验">
            {EXPERIENCE_BANDS.map((band) => (
              <ChoiceChip
                key={band}
                label={band}
                selected={draft.years_experience === band}
                onClick={() => setField('years_experience', band)}
              />
            ))}
          </div>
          {yearsHintVisible ? (
            <p className="sc-target-role-hint">
              按画像 {formatYears(profileYears as number)} 年 → {draft.years_experience}
            </p>
          ) : null}
        </div>

        <div className="sc-target-role">
          <div className="sc-qcard-head">
            <span className="sc-target-role-label">面试市场</span>
            <SourceBadge source={sourceOf('market')} />
          </div>
          <div className="sc-chips" role="group" aria-label="面试市场">
            {MARKETS.map((market) => (
              <ChoiceChip
                key={market}
                label={market}
                selected={draft.market === market}
                onClick={() => setField('market', market)}
              />
            ))}
          </div>
        </div>

        <div className="sc-target-role">
          <div className="sc-qcard-head">
            <span className="sc-target-role-label">公司规模</span>
            <SourceBadge source={sourceOf('company_size')} />
          </div>
          <div className="sc-chips" role="group" aria-label="公司规模">
            {COMPANY_SIZES.map((size) => (
              <ChoiceChip
                key={size}
                label={size}
                selected={draft.company_size === size}
                onClick={() => setField('company_size', size)}
              />
            ))}
          </div>
        </div>

        {error ? <InlineError message={error} onRetry={onStart} retryLabel="重试" /> : null}

        <div className="sc-btn-row">
          <Button size="hero" loading={submitting} onClick={onStart}>
            {submitting ? '正在开局…' : '开始面试'}
          </Button>
          <Button variant="ghost" disabled={submitting} onClick={onSkip}>
            跳过，用画像默认
          </Button>
        </div>
        <p className="sc-meta-line">
          <span>{previewLine(draft)}</span>
          <span>本场设定只作用于这一次面试，不会写回你的画像。</span>
        </p>
      </div>
    </Card>
  )
}
