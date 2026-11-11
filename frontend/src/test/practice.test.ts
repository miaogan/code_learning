import { describe, expect, it } from 'vitest'
import { isAllChoice, nextChoice } from '../lib/choice'
import {
  ANSWER_ERROR_MESSAGE,
  DEFAULT_PRACTICE_FILTERS,
  DIFFICULTY_LABEL,
  EMPTY_BANK_REASON,
  ESSENTIALITY_LABEL,
  KIND_LABEL,
  LANGUAGE_LABEL,
  NEED_ANSWER_MESSAGE,
  NO_HIT_MESSAGE,
  SCOPE_LABEL,
  WRONG_BOOK_EMPTY_REASON,
  accuracyText,
  allowedSubDirections,
  answerText,
  directionChips,
  filtersLabel,
  formatWrongTime,
  languageChips,
  limitChips,
  limitLabel,
  parsePracticeSearch,
  promptPreview,
  relaxSuggestions,
  subDirectionChips,
  wrongTabLabel,
  type PracticeFiltersState,
} from '../lib/practice'

/** 全「全部」基准，便于叠加单维度断言。 */
const ALL_FILTERS: PracticeFiltersState = { ...DEFAULT_PRACTICE_FILTERS }

describe('practice 文案与纯逻辑', () => {
  it('语言映射覆盖 11 项（含空串「通用」与 9 门语言的展示名）', () => {
    expect(Object.keys(LANGUAGE_LABEL)).toHaveLength(10)
    expect(LANGUAGE_LABEL['']).toBe('通用')
    expect(LANGUAGE_LABEL.js).toBe('JavaScript')
    expect(LANGUAGE_LABEL.ts).toBe('TypeScript')
    expect(LANGUAGE_LABEL.vue3).toBe('Vue 3')
    expect(LANGUAGE_LABEL.react).toBe('React')
    expect(LANGUAGE_LABEL.python).toBe('Python')
    expect(LANGUAGE_LABEL.go).toBe('Go')
  })

  it('语言 chip 组 = 全部 + 通用 + 9 门语言（11 个，顺序与后端闭集一致）', () => {
    const chips = languageChips()
    expect(chips).toHaveLength(11)
    expect(chips[0]).toEqual({ value: 'all', label: '全部' })
    expect(chips[1]).toEqual({ value: '', label: '通用' })
    expect(chips.map((chip) => chip.value)).toContain('react')
  })

  it('题型映射含 judge（判断题），text 保留但不进练习池', () => {
    expect(KIND_LABEL.judge).toBe('判断')
    expect(KIND_LABEL.single).toBe('单选')
    expect(KIND_LABEL.multiple).toBe('多选')
    expect(KIND_LABEL.text).toBe('简答')
  })

  it('难度 / 必备度 / 范围映射逐字', () => {
    expect(DIFFICULTY_LABEL).toEqual({ basic: '基础', intermediate: '进阶', challenge: '挑战' })
    expect(ESSENTIALITY_LABEL).toEqual({
      must_know: '必须掌握',
      advanced: '进阶',
      nice_to_know: '加分项',
    })
    expect(SCOPE_LABEL).toEqual({ all: '全部', unseen: '只看未做过', wrong: '只看错题' })
  })

  it('题量文案：10 / 20 / 0（全部），chip 顺序固定 10 → 20 → 全部', () => {
    expect(limitLabel(10)).toBe('10 题')
    expect(limitLabel(20)).toBe('20 题')
    expect(limitLabel(0)).toBe('全部')
    expect(limitChips().map((chip) => chip.value)).toEqual([10, 20, 0])
  })

  it('正确率：3/10 = 30%、10/10 = 100%、0/0 与非法值给「—」', () => {
    expect(accuracyText(3, 10)).toBe('30%')
    expect(accuracyText(10, 10)).toBe('100%')
    expect(accuracyText(0, 10)).toBe('0%')
    expect(accuracyText(0, 0)).toBe('—')
    expect(accuracyText(1, 0)).toBe('—')
    expect(accuracyText(Number.NaN, 10)).toBe('—')
  })

  it('错题时间：ISO → 本地 MM-dd HH:mm，非法串原样回退', () => {
    expect(formatWrongTime('2026-11-01T12:05:00')).toBe('11-01 12:05')
    expect(formatWrongTime('2026-01-09T03:07:00')).toBe('01-09 03:07')
    expect(formatWrongTime('not-a-date')).toBe('not-a-date')
    expect(formatWrongTime('')).toBe('')
  })

  it('正确答案回显：多选用「、」连接，空值给「未记录」', () => {
    expect(answerText(['A', 'C'])).toBe('A、C')
    expect(answerText(['B'])).toBe('B')
    expect(answerText([])).toBe('未记录')
    expect(answerText(null)).toBe('未记录')
    expect(answerText('A')).toBe('A')
    expect(answerText('')).toBe('未记录')
  })

  it('0 命中放宽建议：只建议非「全部」的维度，最多三条', () => {
    expect(relaxSuggestions(ALL_FILTERS)).toEqual([])
    expect(relaxSuggestions({ ...ALL_FILTERS, language: ['python'] })).toEqual(['语言=全部'])
    expect(
      relaxSuggestions({ ...ALL_FILTERS, difficulty: ['basic'], essentiality: ['must_know'] }),
    ).toEqual(['难度=全部', '必备度=全部'])
    expect(
      relaxSuggestions({
        ...ALL_FILTERS,
        difficulty: ['basic'],
        essentiality: ['must_know'],
        direction: ['前端'],
        language: ['go'],
        scope: ['wrong'],
      }),
    ).toEqual(['难度=全部', '必备度=全部', '方向=全部'])
  })

  it('完成态筛选描述把四个维度并列（多选用「、」连接，不写枚举值）', () => {
    expect(filtersLabel(ALL_FILTERS)).toBe('全部语言 · 全部方向 · 全部难度 · 全部必备度')
    expect(
      filtersLabel({
        ...ALL_FILTERS,
        language: ['python', 'go'],
        direction: ['后端'],
        difficulty: ['basic'],
      }),
    ).toBe('Python、Go · 后端 · 基础 · 全部必备度')
    // 错题重练一轮：scope 不是「全部」时必须显式出现，否则看不出这轮为什么只有错题
    expect(filtersLabel({ ...ALL_FILTERS, scope: ['wrong'] })).toBe(
      '全部语言 · 全部方向 · 全部难度 · 全部必备度 · 只看错题',
    )
  })

  it('错题行预览：去围栏 / 去反引号 / 压空白 / 超长加省略号', () => {
    expect(promptPreview('在 Python 中，`list.append()` 是 O(1)')).toBe('在 Python 中，list.append() 是 O(1)')
    expect(promptPreview('第一行\n\n第二行')).toBe('第一行 第二行')
    expect(promptPreview('```python\nprint(1)\n```\n看输出')).toBe('print(1) 看输出')
    expect(promptPreview('字'.repeat(100), 10)).toBe(`${'字'.repeat(10)}…`)
  })

  it('错题本 tab 角标：0 条时不带数字，>0 时带数字', () => {
    expect(wrongTabLabel(0)).toBe('错题本')
    expect(wrongTabLabel(3)).toBe('错题本 3')
  })

  it('五态文案逐字（DESIGN §2.6，组件不得另写字面量）', () => {
    expect(NO_HIT_MESSAGE).toBe('该组合下没有题目，试试放宽难度或必备度')
    expect(EMPTY_BANK_REASON).toBe('题库未就绪，暂时没有可练习的题目')
    expect(ANSWER_ERROR_MESSAGE).toBe('判分失败，你的选择已保留，可直接重试')
    expect(NEED_ANSWER_MESSAGE).toBe('先选一个答案，再提交')
    expect(WRONG_BOOK_EMPTY_REASON).toBe('练习里答错的题会自动进来，答对一次就移出')
  })

  it('默认筛选与服务端默认值一致（全部 + 10 题，筛选维度为多选数组）', () => {
    expect(DEFAULT_PRACTICE_FILTERS).toEqual({
      language: ['all'],
      direction: ['all'],
      sub_direction: [],
      difficulty: ['all'],
      essentiality: ['all'],
      scope: ['all'],
      limit: 10,
    })
  })

  it('r50 二级方向闭集：从属于方向，未选方向时可取全库子方向', () => {
    expect(subDirectionChips(['all'])).toEqual([])
    expect(subDirectionChips(['AI 工程'])[0]).toEqual({ value: '', label: '全部' })
    expect(subDirectionChips(['AI 工程']).map((chip) => chip.value)).toContain('部署与推理')
    expect(allowedSubDirections(['AI 工程'])).toContain('Agent')
    expect(allowedSubDirections(['all'])).toContain('部署与推理')
    expect(allowedSubDirections(['all'])).toContain('python')
    // 多方向取并集：两个方向的子方向都要出现
    expect(allowedSubDirections(['前端', 'AI 工程'])).toContain('react')
    expect(allowedSubDirections(['前端', 'AI 工程'])).toContain('Agent')
  })

  it('r50 0 命中建议含「二级方向=全部」，且不影响既有前三条次序', () => {
    expect(relaxSuggestions({ ...ALL_FILTERS, sub_direction: ['react'] })).toEqual([
      '二级方向=全部',
    ])
    expect(
      relaxSuggestions({
        ...ALL_FILTERS,
        difficulty: ['basic'],
        essentiality: ['must_know'],
        direction: ['前端'],
        sub_direction: ['react'],
        language: ['go'],
        scope: ['wrong'],
      }),
    ).toEqual(['难度=全部', '必备度=全部', '方向=全部'])
  })

  it('r50 完成态描述显式带上聚焦的二级方向（多个用「、」并列）', () => {
    expect(filtersLabel({ ...ALL_FILTERS, sub_direction: ['部署与推理'] })).toBe(
      '全部语言 · 全部方向 · 全部难度 · 全部必备度 · 部署与推理',
    )
    expect(filtersLabel({ ...ALL_FILTERS, sub_direction: ['部署与推理', 'Agent'] })).toBe(
      '全部语言 · 全部方向 · 全部难度 · 全部必备度 · 部署与推理、Agent',
    )
  })
})

describe('MultiChipRow 多选折叠（勾满全部具体项 → 自动回到「全部」）', () => {
  const concrete = ['python', 'go', 'java']
  const allValue = 'all'

  it('「全部」判定：空数组 / 含哨兵 / 已勾满全部具体项', () => {
    expect(isAllChoice([], allValue, concrete)).toBe(true)
    expect(isAllChoice([allValue], allValue, concrete)).toBe(true)
    expect(isAllChoice(['python', 'go', 'java'], allValue, concrete)).toBe(true)
    expect(isAllChoice(['python'], allValue, concrete)).toBe(false)
  })

  it('从「全部」点具体项 → 只选该项；再点第二项 → 两项并存', () => {
    expect(nextChoice([allValue], 'python', allValue, concrete)).toEqual(['python'])
    expect(nextChoice(['python'], 'go', allValue, concrete)).toEqual(['python', 'go'])
  })

  it('手动勾满全部具体项 → 自动折叠成「全部」；取消最后一个具体项也回到「全部」', () => {
    expect(nextChoice(['python', 'go'], 'java', allValue, concrete)).toEqual([allValue])
    expect(nextChoice(['python'], 'python', allValue, concrete)).toEqual([allValue])
  })

  it('二级方向用空串作「全部」哨兵，行为与 all 一致', () => {
    const subs = ['react', 'vue3']
    expect(nextChoice([''], 'react', '', subs)).toEqual(['react'])
    expect(nextChoice(['react'], 'vue3', '', subs)).toEqual([''])
    expect(nextChoice(['react', 'vue3'], 'react', '', subs)).toEqual(['react'])
  })
})

describe('parsePracticeSearch（7 天计划的筛选链接 → 首渲染筛选）', () => {
  it('缺省 / 无关参数一律回落默认筛选', () => {
    expect(parsePracticeSearch('')).toEqual(DEFAULT_PRACTICE_FILTERS)
    expect(parsePracticeSearch('?foo=bar')).toEqual(DEFAULT_PRACTICE_FILTERS)
  })

  it('闭集内的方向 / 难度 / 必备度 / 范围 / 题量原样生效（单值归一成单元素数组）', () => {
    expect(
      parsePracticeSearch(
        '?direction=前端&difficulty=basic&essentiality=must_know&scope=wrong&limit=0',
      ),
    ).toEqual({
      language: ['all'],
      direction: ['前端'],
      sub_direction: [],
      difficulty: ['basic'],
      essentiality: ['must_know'],
      scope: ['wrong'],
      limit: 0,
    })
  })

  it('多选：重复键与逗号并列都吃，勾满具体项折叠成「全部」', () => {
    expect(parsePracticeSearch('?language=python&language=go').language).toEqual(['python', 'go'])
    expect(parsePracticeSearch('?language=python,go&difficulty=basic,challenge')).toMatchObject({
      language: ['python', 'go'],
      difficulty: ['basic', 'challenge'],
    })
    // 全部具体方向都勾上 → 折叠回「全部」
    const languages = parsePracticeSearch('?language=').language
    expect(languages).toEqual([''])
    const allDirections = parsePracticeSearch(
      `?direction=${directionChips()
        .filter((chip) => chip.value !== 'all')
        .map((chip) => chip.value)
        .join(',')}`,
    ).direction
    expect(allDirections).toEqual(['all'])
  })

  it('r50 `?sub=` 落在方向闭集内时生效；方向缺省时按全库子方向接受（支持多选）', () => {
    expect(parsePracticeSearch('?direction=AI 工程&sub=部署与推理').sub_direction).toEqual([
      '部署与推理',
    ])
    expect(parsePracticeSearch('?sub=python').sub_direction).toEqual(['python'])
    expect(parsePracticeSearch('?direction=前端&sub=react&sub=vue3').sub_direction).toEqual([
      'react',
      'vue3',
    ])
  })

  it('r50 `?sub=` 越界 / 与方向冲突时静默回落，不抛错', () => {
    expect(parsePracticeSearch('?direction=前端&sub=python').sub_direction).toEqual([])
    expect(parsePracticeSearch('?sub=不存在').sub_direction).toEqual([])
    expect(parsePracticeSearch('?sub=').sub_direction).toEqual([])
  })

  it('空串语言是闭集成员（通用），不能被当成「全部」', () => {
    expect(parsePracticeSearch('?language=').language).toEqual([''])
  })

  it('越界值全部回落默认，且不抛错', () => {
    expect(
      parsePracticeSearch(
        '?direction=不存在&difficulty=extreme&essentiality=legendary&scope=done&limit=7&language=rust',
      ),
    ).toEqual(DEFAULT_PRACTICE_FILTERS)
  })
})
