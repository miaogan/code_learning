/**
 * 开局四项配置的**闭集与纯函数**（AC-1 / AC-2④ / AC-14）—— 组件文件只导出组件。
 *
 * 单独成文件的理由同 `chatModel.ts`：`react-refresh/only-export-components` 不允许
 * 组件文件导出纯函数（热更新会整页重载，AC-15 的 lint 上限，QA D-3）。
 * 这里的闭集必须与 `backend/app/services/rules.py` 的 EXPERIENCE_BANDS / MARKETS /
 * COMPANY_SIZES 逐字一致（前端能选、后端必不 422）。
 */

import type {
  CompanySize,
  ExperienceBand,
  InterviewMarket,
  InterviewSettingsPatch,
  Profile,
} from '../../api/types'

/** 四项配置闭集（AC-1 / AC-14）。 */
export const EXPERIENCE_BANDS = ['应届', '1-3年', '3-5年', '5-10年', '10年以上'] as const
export const MARKETS = ['国内', '北美', '欧洲', '其他'] as const
export const COMPANY_SIZES = ['大厂', '中型', '初创'] as const

/** 默认值闭集（与 rules.py 的 DEFAULT_* 逐字一致；服务端 fill_settings 为唯一补全方）。 */
export const DEFAULT_TARGET_ROLE = '通用软件工程师'
export const DEFAULT_EXPERIENCE_BAND: ExperienceBand = '1-3年'
export const DEFAULT_MARKET: InterviewMarket = '国内'
export const DEFAULT_COMPANY_SIZE: CompanySize = '中型'

/** 目标岗位输入上限与计数告警阈值（DESIGN §2.2：计数 ≥34 转 warn）。 */
export const TARGET_ROLE_MAX_CHARS = 40
export const TARGET_ROLE_WARN_CHARS = 34

export interface SetupDraft {
  target_role: string
  years_experience: ExperienceBand
  market: InterviewMarket
  company_size: CompanySize
  /** 方向聚焦：空串 = 不限（不指定时服务端按画像短板均衡出题）。 */
  direction: string
  /** 二级方向：只有 direction 非空时才有意义。 */
  sub_direction: string
}

/** 单个字段的来源：画像取值 / 回落默认（用户手改后徽章消失，不再标注来源）。 */
export type SetupSource = 'profile' | 'default'
export type SetupSources = Record<keyof SetupDraft, SetupSource>

/**
 * 年数 → 经验档（AC-2④，DESIGN §2.2；与后端 rules.experience_band_of 逐档对称）：
 * <1 应届 · [1,3) 1-3年 · [3,5) 3-5年 · [5,10) 5-10年 · ≥10 10年以上。
 */
export function bandOfYears(years: number | null): ExperienceBand {
  if (typeof years !== 'number' || !Number.isFinite(years) || years < 1) return '应届'
  if (years < 3) return '1-3年'
  if (years < 5) return '3-5年'
  if (years < 10) return '5-10年'
  return '10年以上'
}

/** 画像预填（AC-1）：目标岗位取 target_role（空则留空 → 服务端补默认），经验按年数映射，市场/规模回落默认。 */
export function prefillOf(profile: Profile | null): { draft: SetupDraft; sources: SetupSources } {
  const role = (profile?.target_role ?? '').trim()
  const years = profile?.years_experience ?? null
  const hasYears = typeof years === 'number' && Number.isFinite(years)
  return {
    draft: {
      target_role: role.slice(0, TARGET_ROLE_MAX_CHARS),
      years_experience: hasYears ? bandOfYears(years) : DEFAULT_EXPERIENCE_BAND,
      market: DEFAULT_MARKET,
      company_size: DEFAULT_COMPANY_SIZE,
      direction: '',
      sub_direction: '',
    },
    sources: {
      target_role: role.length > 0 ? 'profile' : 'default',
      years_experience: hasYears ? 'profile' : 'default',
      market: 'default',
      company_size: 'default',
      direction: 'default',
      sub_direction: 'default',
    },
  }
}

/** 表单 → 提交补丁（空白目标岗位 / 不限方向不下发，交给服务端默认；其余三项始终携带）。 */
export function draftToPatch(draft: SetupDraft): InterviewSettingsPatch {
  const patch: InterviewSettingsPatch = {
    years_experience: draft.years_experience,
    market: draft.market,
    company_size: draft.company_size,
  }
  const role = draft.target_role.trim()
  if (role.length > 0) patch.target_role = role
  const direction = draft.direction.trim()
  if (direction.length > 0) {
    patch.direction = direction
    const subDirection = draft.sub_direction.trim()
    if (subDirection.length > 0) patch.sub_direction = subDirection
  }
  return patch
}

/** 开局预览行（跳过按钮旁的「将按：…」，空白岗位按默认值展示，与 fill_settings 口径一致）。 */
export function previewLine(draft: SetupDraft): string {
  const role = draft.target_role.trim() || DEFAULT_TARGET_ROLE
  const base = `将按：${role} · ${draft.years_experience} · ${draft.market} · ${draft.company_size}`
  const direction = draft.direction.trim()
  if (direction.length === 0) return base
  const subDirection = draft.sub_direction.trim()
  return subDirection.length > 0 ? `${base} · ${direction} · ${subDirection}` : `${base} · ${direction}`
}
