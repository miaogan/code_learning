import { describe, expect, it } from 'vitest'
import {
  COACH_COPY,
  DIFFICULTY_LABEL,
  ESSENTIALITY_LABEL,
  WEAKNESS_FOLD_LIMIT,
  blockStateOf,
  difficultyLabel,
  essentialityLabel,
  foldWeakness,
  polishHref,
  roleGapLabel,
  weaknessCountLabel,
  weaknessRateLabel,
} from '../lib/coach'

/** 造 N 条同构条目：只为验证折叠边界，不关心内容。 */
function makeItems(count: number): number[] {
  return Array.from({ length: count }, (_unused, index) => index + 1)
}

describe('blockStateOf 三态', () => {
  it('null / undefined = 旧报告（legacy），绝不当成空数据', () => {
    expect(blockStateOf<number>(null)).toBe('legacy')
    expect(blockStateOf<number>(undefined)).toBe('legacy')
  })

  it('空数组 = 本块无内容（empty），与旧报告分属两态', () => {
    expect(blockStateOf<number>([])).toBe('empty')
  })

  it('非空 = ready', () => {
    expect(blockStateOf([1])).toBe('ready')
  })
})

describe('foldWeakness', () => {
  it('等于上限时不折叠', () => {
    const folded = foldWeakness(makeItems(WEAKNESS_FOLD_LIMIT), false)
    expect(folded.visible).toHaveLength(WEAKNESS_FOLD_LIMIT)
    expect(folded.hiddenCount).toBe(0)
  })

  it('超过上限 1 条：只给前 8 条 + 折叠 1 条', () => {
    const folded = foldWeakness(makeItems(WEAKNESS_FOLD_LIMIT + 1), false)
    expect(folded.visible).toHaveLength(WEAKNESS_FOLD_LIMIT)
    expect(folded.hiddenCount).toBe(1)
  })

  it('展开后全部可见且顺序不变（前端不排序、不去重）', () => {
    const items = makeItems(12)
    const folded = foldWeakness(items, true)
    expect(folded.visible).toHaveLength(12)
    expect(folded.hiddenCount).toBe(0)
    expect(folded.visible[0]).toBe(1)
    expect(folded.visible[11]).toBe(12)
  })

  it('不改写入参（纯函数）', () => {
    const items = makeItems(10)
    foldWeakness(items, false)
    expect(items).toHaveLength(10)
  })
})

describe('错误率与计数文案', () => {
  it('错误率取整数百分比', () => {
    expect(weaknessRateLabel(0.616)).toBe('62%')
    expect(weaknessRateLabel(0)).toBe('0%')
    expect(weaknessRateLabel(1)).toBe('100%')
  })

  it('非法值降级为短横，不渲染 NaN%', () => {
    expect(weaknessRateLabel(Number.NaN)).toBe('—')
  })

  it('错题计数与错误率同屏出现（同一分组的两段文案）', () => {
    expect(weaknessCountLabel(8, 13)).toBe('错 8 / 共 13 题')
    expect(weaknessCountLabel(0, 5)).toBe('错 0 / 共 5 题')
  })
})

describe('roleGapLabel', () => {
  it('0 渲染「达标」而不是数字 0', () => {
    expect(roleGapLabel(0)).toBe('达标')
  })

  it('正数差距原样输出，负数视为已达标', () => {
    expect(roleGapLabel(2)).toBe('2')
    expect(roleGapLabel(-1)).toBe('达标')
  })
})

describe('标签字典', () => {
  it('难度三档全部有中文', () => {
    expect(Object.keys(DIFFICULTY_LABEL).sort()).toEqual(['basic', 'challenge', 'intermediate'])
    expect(difficultyLabel('intermediate')).toBe('进阶')
  })

  it('必备度三档全部有中文', () => {
    expect(Object.keys(ESSENTIALITY_LABEL).sort()).toEqual(['advanced', 'must_know', 'nice_to_know'])
    expect(essentialityLabel('must_know')).toBe('必备')
  })

  it('未知档位原样显示（后端加档时前端不瞎猜）', () => {
    expect(difficultyLabel('expert')).toBe('expert')
    expect(essentialityLabel('optional')).toBe('optional')
  })
})

describe('polishHref', () => {
  it('只带 focus / section / anchor 三个参数并做 URL 编码', () => {
    const href = polishHref('参与开发了订单系统', 'project', '参与开发了订单系统')
    expect(href.startsWith('/polish?')).toBe(true)
    expect(href).toContain(`focus=${encodeURIComponent('参与开发了订单系统')}`)
    expect(href).toContain('section=project')
    expect(href).toContain(`anchor=${encodeURIComponent('参与开发了订单系统')}`)
  })

  it('超长原句不携带 anchor（URL 不撑爆），focus 仍在', () => {
    const long = '很长的原句'.repeat(40)
    const href = polishHref(long, 'experience', long)
    expect(href).not.toContain('anchor=')
    expect(href).toContain(`focus=${encodeURIComponent(long)}`)
  })
})

describe('COACH_COPY 文案镜像', () => {
  it('与 backend/app/services/coach_copy.py 逐字一致（门禁 test_r7_copy_parity 同口径）', () => {
    expect(COACH_COPY.legacy).toBe('旧报告不含该区块，重新生成可补全')
    expect(COACH_COPY.weaknessEmpty).toBe('本次测评还没有可统计的计分题')
    expect(COACH_COPY.resumeEmpty).toBe('还没有可定位的简历正文，先上传简历再回来看改进要点')
    expect(COACH_COPY.resumeFallback).toBe('简历要点暂时没生成出来，可以先去润色页逐条查看')
    expect(COACH_COPY.roleNoModel).toBe('暂无该岗位的能力模型')
    expect(COACH_COPY.roleNoModelHint).toBe('可以先按上面的薄弱地图补，或在简历画像里填写更常见的岗位名')
  })
})
