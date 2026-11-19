import { describe, expect, it } from 'vitest'

import {
  collectMissingFacts,
  mirrorMissingFromState,
  rankMissingFactsByImportance,
  toUserFacts,
} from './mirrorFacts'

describe('collectMissingFacts', () => {
  it('拍平所有卡的缺失信息并按整条文本去重，保持首次出现顺序', () => {
    const items = collectMissingFacts([
      { id: 'card-1', missing_info: ['缺 QPS 数据', '缺团队规模'] },
      { id: 'card-2', missing_info: ['缺 QPS 数据', ' 缺上线时间 '] },
      { id: 'card-3', missing_info: ['', '   '] },
    ])
    expect(
      items.map(({ text, sourceCardId, occurrences }) => ({ text, sourceCardId, occurrences })),
    ).toEqual([
      { text: '缺 QPS 数据', sourceCardId: 'card-1', occurrences: 2 },
      { text: '缺团队规模', sourceCardId: 'card-1', occurrences: 1 },
      { text: '缺上线时间', sourceCardId: 'card-2', occurrences: 1 },
    ])
  })

  it('没有复盘卡或全空时返回空数组', () => {
    expect(collectMissingFacts([])).toEqual([])
    expect(collectMissingFacts([{ id: 'c', missing_info: [] }])).toEqual([])
  })
})

describe('rankMissingFactsByImportance', () => {
  it('量化指标优先于责任项，泛泛补充排最后', () => {
    const items = collectMissingFacts([
      { id: 'c1', missing_info: ['再补充一下具体细节', '缺延迟数据', '负责的模块'] },
    ])
    expect(rankMissingFactsByImportance(items).map((item) => item.text)).toEqual([
      '缺延迟数据',
      '负责的模块',
      '再补充一下具体细节',
    ])
  })

  it('同一条同时含泛泛措辞与量化指标时按高档位算', () => {
    const [item] = collectMissingFacts([
      { id: 'c1', missing_info: ['补充一下 QPS 数据'] },
    ])
    expect(item?.importance).toBe('high')
  })

  it('跨卡重复提及提升顺序，但不改写文本', () => {
    const items = collectMissingFacts([
      { id: 'c1', missing_info: ['缺架构设计细节', '缺稳定性数据'] },
      { id: 'c2', missing_info: ['缺架构设计细节', '缺延迟数据'] },
      { id: 'c3', missing_info: ['缺架构设计细节'] },
    ])
    const ranked = rankMissingFactsByImportance(items)
    expect(ranked.map((item) => item.text)).toEqual([
      '缺架构设计细节',
      '缺延迟数据',
      '缺稳定性数据',
    ])
    expect(ranked.map((item) => item.text).sort()).toEqual(items.map((item) => item.text).sort())
  })

  it('分数相同时保持首次出现顺序', () => {
    const items = collectMissingFacts([
      { id: 'c1', missing_info: ['缺并发数据', '缺 QPS 数据'] },
    ])
    expect(rankMissingFactsByImportance(items).map((item) => item.text)).toEqual([
      '缺并发数据',
      '缺 QPS 数据',
    ])
  })

  it('按分数给出 high / medium / low 档位', () => {
    const byText = new Map(
      rankMissingFactsByImportance(
        collectMissingFacts([
          {
            id: 'c1',
            missing_info: ['缺 QPS 数据', '负责的模块', '再补充一下具体细节'],
          },
        ]),
      ).map((item) => [item.text, item.importance]),
    )
    expect(byText.get('缺 QPS 数据')).toBe('high')
    expect(byText.get('负责的模块')).toBe('medium')
    expect(byText.get('再补充一下具体细节')).toBe('low')
  })
})

describe('mirrorMissingFromState', () => {
  it('只认字符串；空串 / 非对象 / 缺键一律 null', () => {
    expect(mirrorMissingFromState({ mirrorMissing: '缺 QPS 数据' })).toBe('缺 QPS 数据')
    expect(mirrorMissingFromState({ mirrorMissing: '   ' })).toBeNull()
    expect(mirrorMissingFromState({ mirrorMissing: 42 })).toBeNull()
    expect(mirrorMissingFromState({})).toBeNull()
    expect(mirrorMissingFromState(null)).toBeNull()
    expect(mirrorMissingFromState('str')).toBeNull()
  })
})

describe('toUserFacts', () => {
  it('trim 后丢弃不足 2 字的条目，section 原样透传', () => {
    expect(
      toUserFacts([
        { text: ' QPS 8000 ', section: 'project' },
        { text: 'x', section: null },
        { text: 'Kubernetes 部署经验', section: null },
      ]),
    ).toEqual([
      { text: 'QPS 8000', section: 'project' },
      { text: 'Kubernetes 部署经验', section: null },
    ])
  })
})
