import { describe, expect, it } from 'vitest'

import {
  collectMissingFacts,
  mirrorMissingFromState,
  toUserFacts,
} from './mirrorFacts'

describe('collectMissingFacts', () => {
  it('拍平所有卡的缺失信息并按整条文本去重，保持首次出现顺序', () => {
    const items = collectMissingFacts([
      { id: 'card-1', missing_info: ['缺 QPS 数据', '缺团队规模'] },
      { id: 'card-2', missing_info: ['缺 QPS 数据', ' 缺上线时间 '] },
      { id: 'card-3', missing_info: ['', '   '] },
    ])
    expect(items).toEqual([
      { text: '缺 QPS 数据', sourceCardId: 'card-1' },
      { text: '缺团队规模', sourceCardId: 'card-1' },
      { text: '缺上线时间', sourceCardId: 'card-2' },
    ])
  })

  it('没有复盘卡或全空时返回空数组', () => {
    expect(collectMissingFacts([])).toEqual([])
    expect(collectMissingFacts([{ id: 'c', missing_info: [] }])).toEqual([])
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
