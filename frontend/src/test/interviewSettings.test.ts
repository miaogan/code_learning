import { describe, expect, it } from 'vitest'
import type { Profile } from '../api/types'
import {
  COMPANY_SIZES,
  DEFAULT_COMPANY_SIZE,
  DEFAULT_EXPERIENCE_BAND,
  DEFAULT_MARKET,
  DEFAULT_TARGET_ROLE,
  EXPERIENCE_BANDS,
  MARKETS,
  TARGET_ROLE_MAX_CHARS,
  bandOfYears,
  draftToPatch,
  prefillOf,
  previewLine,
  type SetupDraft,
} from '../components/interview/setupModel'

/**
 * 四项面试配置的纯函数口径（TECHNICAL §6.2）。
 * 后端对称实现：`rules.experience_band_of` / `interview.fill_settings` / `calibration_of`；
 * 这里只钉前端侧的边界与文案，闭集字面量逐字比对用于防单侧漂移（AC-14）。
 */

const PROFILE_BASE: Profile = {
  id: 'prof-1',
  resume_id: 'res-1',
  updated_at: '2026-10-31T05:00:00+00:00',
  skills: [],
  tech_stack: ['React', 'TypeScript'],
  years_experience: null,
  projects: [],
  target_role: null,
}

function profileWith(patch: Partial<Profile>): Profile {
  return { ...PROFILE_BASE, ...patch }
}

function draftWith(patch: Partial<SetupDraft>): SetupDraft {
  return {
    target_role: '',
    years_experience: DEFAULT_EXPERIENCE_BAND,
    market: DEFAULT_MARKET,
    company_size: DEFAULT_COMPANY_SIZE,
    direction: '',
    sub_direction: '',
    ...patch,
  }
}

describe('bandOfYears：年数 → 经验档（AC-1 预填口径）', () => {
  it.each([
    [null, '应届'],
    [0.5, '应届'],
    [1, '1-3年'],
    [2.9, '1-3年'],
    [3, '3-5年'],
    [4.9, '3-5年'],
    [5, '5-10年'],
    [9.9, '5-10年'],
    [10, '10年以上'],
    [12, '10年以上'],
  ] as const)('%s 年 → %s', (years, band) => {
    expect(bandOfYears(years)).toBe(band)
  })
})

describe('prefillOf：画像预填与来源标注（画像有值 / 画像空 / 无画像）', () => {
  it('画像有值：岗位与经验档标 profile，市场与规模回落默认', () => {
    const { draft, sources } = prefillOf(
      profileWith({ target_role: '后端工程师', years_experience: 3 }),
    )

    expect(draft).toEqual({
      target_role: '后端工程师',
      years_experience: '3-5年',
      market: DEFAULT_MARKET,
      company_size: DEFAULT_COMPANY_SIZE,
      direction: '',
      sub_direction: '',
    })
    expect(sources).toEqual({
      target_role: 'profile',
      years_experience: 'profile',
      market: 'default',
      company_size: 'default',
      direction: 'default',
      sub_direction: 'default',
    })
  })

  it('画像空（岗位空白 + 无年数）：岗位留空交服务端默认，年数回落默认档', () => {
    const { draft, sources } = prefillOf(
      profileWith({ target_role: '   ', years_experience: null }),
    )

    expect(draft).toEqual({
      target_role: '',
      years_experience: DEFAULT_EXPERIENCE_BAND,
      market: DEFAULT_MARKET,
      company_size: DEFAULT_COMPANY_SIZE,
      direction: '',
      sub_direction: '',
    })
    expect(sources.target_role).toBe('default')
    expect(sources.years_experience).toBe('default')
  })

  it('无画像：四项与来源全回落默认，不伪造画像来源', () => {
    const { draft, sources } = prefillOf(null)

    expect(draft.target_role).toBe('')
    expect(draft.years_experience).toBe(DEFAULT_EXPERIENCE_BAND)
    expect(Object.values(sources)).toEqual(Array(6).fill('default'))
  })

  it('超长岗位按 TARGET_ROLE_MAX_CHARS 截断（与服务端 TARGET_ROLE_MAX_CHARS 同值）', () => {
    const longRole = '前'.repeat(TARGET_ROLE_MAX_CHARS + 12)
    const { draft } = prefillOf(profileWith({ target_role: longRole }))

    expect(draft.target_role).toHaveLength(TARGET_ROLE_MAX_CHARS)
    expect(TARGET_ROLE_MAX_CHARS).toBe(40)
  })
})

describe('draftToPatch：表单 → 提交补丁', () => {
  it('空白目标岗位不下发（交给服务端补默认），其余三项始终携带', () => {
    const patch = draftToPatch(
      draftWith({ target_role: '   ', years_experience: '3-5年', market: '北美', company_size: '初创' }),
    )

    expect('target_role' in patch).toBe(false)
    expect(patch.years_experience).toBe('3-5年')
    expect(patch.market).toBe('北美')
    expect(patch.company_size).toBe('初创')
  })

  it('有值岗位去首尾空白后下发（服务端仍是唯一补全方）', () => {
    const patch = draftToPatch(draftWith({ target_role: '  后端工程师  ' }))

    expect(patch.target_role).toBe('后端工程师')
  })

  it('方向不限时不下发方向键（服务端按画像均衡出题）', () => {
    const patch = draftToPatch(draftWith({ direction: '', sub_direction: 'python' }))

    expect('direction' in patch).toBe(false)
    expect('sub_direction' in patch).toBe(false)
  })

  it('选了方向才下发，且子方向必须挂在方向上', () => {
    expect(draftToPatch(draftWith({ direction: '后端' })).sub_direction).toBeUndefined()

    const both = draftToPatch(draftWith({ direction: '后端', sub_direction: 'python' }))
    expect(both.direction).toBe('后端')
    expect(both.sub_direction).toBe('python')
  })
})

describe('previewLine：开局预览行逐字中文', () => {
  it('空白岗位按默认值展示，与 fill_settings 口径一致', () => {
    expect(
      previewLine(
        draftWith({ target_role: '', years_experience: '1-3年', market: '国内', company_size: '中型' }),
      ),
    ).toBe('将按：通用软件工程师 · 1-3年 · 国内 · 中型')
  })

  it('有值岗位去空白后拼接，四项以「·」分隔', () => {
    expect(
      previewLine(
        draftWith({ target_role: ' 后端工程师 ', years_experience: '5-10年', market: '北美', company_size: '大厂' }),
      ),
    ).toBe('将按：后端工程师 · 5-10年 · 北美 · 大厂')
  })

  it('选了方向 / 子方向时追加在四项之后，不限方向不产生多余分隔符', () => {
    expect(previewLine(draftWith({ target_role: '后端工程师', direction: '前端' }))).toBe(
      '将按：后端工程师 · 1-3年 · 国内 · 中型 · 前端',
    )
    expect(
      previewLine(draftWith({ target_role: '后端工程师', direction: '前端', sub_direction: 'react' })),
    ).toBe('将按：后端工程师 · 1-3年 · 国内 · 中型 · 前端 · react')
  })
})

describe('闭集字面量与后端 rules.py 逐字一致（AC-14 防漂移）', () => {
  it('三组枚举与四个默认值的字面量', () => {
    expect([...EXPERIENCE_BANDS]).toEqual(['应届', '1-3年', '3-5年', '5-10年', '10年以上'])
    expect([...MARKETS]).toEqual(['国内', '北美', '欧洲', '其他'])
    expect([...COMPANY_SIZES]).toEqual(['大厂', '中型', '初创'])

    expect(DEFAULT_TARGET_ROLE).toBe('通用软件工程师')
    expect(DEFAULT_EXPERIENCE_BAND).toBe('1-3年')
    expect(DEFAULT_MARKET).toBe('国内')
    expect(DEFAULT_COMPANY_SIZE).toBe('中型')
  })
})
