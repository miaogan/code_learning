import { describe, expect, it } from 'vitest'
import {
  COMPLEXITY_CURVES,
  COMPLEXITY_N_OPTIONS,
  DEMO_IDS,
  DEMO_KNAPSACK,
  DEMO_POINTER_TARGET,
  DEMO_POINTER_VALUES,
  DEMO_SEARCH_TARGET,
  DEMO_SEARCH_VALUES,
  DEMO_TREE,
  TREE_ORDERS,
  binarySearchFrames,
  complexityGrowth,
  knapsackFrames,
  treeLayout,
  treeOrderIds,
  treeTraversalFrames,
  twoPointerFrames,
} from '../lib/tutorialDemos'
import { ALL_TUTORIAL_CHAPTERS } from '../lib/tutorials'

describe('演示闭集与内容一致', () => {
  it('DEMO_IDS 无重复，且覆盖 5 个演示', () => {
    expect(new Set(DEMO_IDS).size).toBe(DEMO_IDS.length)
    expect(DEMO_IDS).toHaveLength(5)
  })

  it('教程里出现的每个 demo 块都在闭集内，且 5 个演示都被真正用上', () => {
    const used: string[] = []
    ALL_TUTORIAL_CHAPTERS.forEach((chapter) => {
      chapter.sections.forEach((section) => {
        section.blocks.forEach((block) => {
          if (block.kind !== 'demo') return
          expect(DEMO_IDS).toContain(block.demo)
          expect(block.title.trim()).not.toBe('')
          used.push(block.demo)
        })
      })
    })
    DEMO_IDS.forEach((id) => expect(used).toContain(id))
  })

  it('所有帧的 note 都非空：每一步都要讲清「刚发生了什么」', () => {
    const frames = [
      ...binarySearchFrames(DEMO_SEARCH_VALUES, DEMO_SEARCH_TARGET),
      ...twoPointerFrames(DEMO_POINTER_VALUES, DEMO_POINTER_TARGET),
      ...TREE_ORDERS.flatMap((order) => treeTraversalFrames(DEMO_TREE, order.id)),
      ...knapsackFrames(DEMO_KNAPSACK),
    ]
    frames.forEach((frame) => expect(frame.note.trim()).not.toBe(''))
  })
})

describe('复杂度增长', () => {
  it('四条曲线都有一个可选数据量的读数，percent 落在 0–100 且 n² 打满', () => {
    COMPLEXITY_N_OPTIONS.forEach((n) => {
      const rows = complexityGrowth(n)
      expect(rows).toHaveLength(COMPLEXITY_CURVES.length)
      rows.forEach((row) => {
        expect(row.percent).toBeGreaterThanOrEqual(0)
        expect(row.percent).toBeLessThanOrEqual(100)
        expect(row.ops).toBeGreaterThan(0)
      })
      expect(rows.find((row) => row.id === 'n2')?.percent).toBe(100)
    })
  })

  it('percent 与真实次数同序：次数越大条形越长', () => {
    COMPLEXITY_N_OPTIONS.forEach((n) => {
      const rows = [...complexityGrowth(n)].sort((left, right) => left.ops - right.ops)
      const percents = rows.map((row) => row.percent)
      expect(percents).toEqual([...percents].sort((left, right) => left - right))
    })
  })

  it('n 变大时四条曲线的操作次数都不减少', () => {
    COMPLEXITY_CURVES.forEach((curve) => {
      for (let index = 1; index < COMPLEXITY_N_OPTIONS.length; index += 1) {
        const prev = curve.ops(COMPLEXITY_N_OPTIONS[index - 1])
        const next = curve.ops(COMPLEXITY_N_OPTIONS[index])
        expect(next).toBeGreaterThan(prev)
      }
    })
  })
})

describe('二分查找', () => {
  it('样例能命中 11：最后落 found，且 mid 指向目标', () => {
    const frames = binarySearchFrames(DEMO_SEARCH_VALUES, DEMO_SEARCH_TARGET)
    const last = frames[frames.length - 1]
    expect(last.status).toBe('found')
    expect(DEMO_SEARCH_VALUES[last.mid]).toBe(DEMO_SEARCH_TARGET)
    expect(last.note).toContain(String(DEMO_SEARCH_TARGET))
  })

  it('搜索区间逐帧收缩：后一帧的 [low, high] 一定落在前一帧里', () => {
    const frames = binarySearchFrames(DEMO_SEARCH_VALUES, DEMO_SEARCH_TARGET)
    for (let index = 1; index < frames.length; index += 1) {
      const prev = frames[index - 1]
      const next = frames[index]
      expect(next.low).toBeGreaterThanOrEqual(prev.low)
      expect(next.high).toBeLessThanOrEqual(prev.high)
    }
  })

  it('起始帧没有比较，mid 为 -1', () => {
    expect(binarySearchFrames(DEMO_SEARCH_VALUES, DEMO_SEARCH_TARGET)[0].mid).toBe(-1)
    expect(binarySearchFrames(DEMO_SEARCH_VALUES, DEMO_SEARCH_TARGET)[0].status).toBe('start')
  })

  it('找不到时以 miss 收尾，且区间已经空掉', () => {
    const frames = binarySearchFrames([1, 2, 3], 9)
    const last = frames[frames.length - 1]
    expect(last.status).toBe('miss')
    expect(last.low).toBeGreaterThan(last.high)
  })

  it('空数组只给一帧 miss，不会死循环', () => {
    const frames = binarySearchFrames([], 1)
    expect(frames).toHaveLength(1)
    expect(frames[0].status).toBe('miss')
  })

  it('比较次数不超过 log2 量级：8 个元素 3 帧以内命中', () => {
    const frames = binarySearchFrames(DEMO_SEARCH_VALUES, DEMO_SEARCH_TARGET)
    expect(frames.length).toBeLessThanOrEqual(Math.ceil(Math.log2(DEMO_SEARCH_VALUES.length)) + 1)
  })
})

describe('对撞双指针', () => {
  it('样例凑出 13：found 帧两个指针之和等于目标', () => {
    const frames = twoPointerFrames(DEMO_POINTER_VALUES, DEMO_POINTER_TARGET)
    const last = frames[frames.length - 1]
    expect(last.status).toBe('found')
    expect(DEMO_POINTER_VALUES[last.left] + DEMO_POINTER_VALUES[last.right]).toBe(
      DEMO_POINTER_TARGET,
    )
    expect(last.sum).toBe(DEMO_POINTER_TARGET)
  })

  it('每一步只动一个指针，且指针从不回退', () => {
    const frames = twoPointerFrames(DEMO_POINTER_VALUES, DEMO_POINTER_TARGET)
    for (let index = 1; index < frames.length; index += 1) {
      const prev = frames[index - 1]
      const next = frames[index]
      const movedLeft = next.left !== prev.left
      const movedRight = next.right !== prev.right
      expect(movedLeft !== movedRight).toBe(true)
      expect(next.left).toBeGreaterThanOrEqual(prev.left)
      expect(next.right).toBeLessThanOrEqual(prev.right)
    }
  })

  it('偏小就右移左指针、偏大就左移右指针', () => {
    const frames = twoPointerFrames(DEMO_POINTER_VALUES, DEMO_POINTER_TARGET)
    for (let index = 1; index < frames.length; index += 1) {
      const prev = frames[index - 1]
      const next = frames[index]
      if (prev.status === 'small') expect(next.left).toBe(prev.left + 1)
      if (prev.status === 'large') expect(next.right).toBe(prev.right - 1)
    }
  })

  it('无解时以指针相遇的 miss 帧收尾', () => {
    const frames = twoPointerFrames([1, 2, 3], 10)
    const last = frames[frames.length - 1]
    expect(last.status).toBe('miss')
    expect(last.left).toBe(last.right)
  })

  it('少于两个元素只给一帧 miss', () => {
    expect(twoPointerFrames([1], 3)).toHaveLength(1)
  })
})

describe('二叉树遍历', () => {
  const pre = ['node-4', 'node-2', 'node-1', 'node-3', 'node-6', 'node-5', 'node-7']
  const inOrder = ['node-1', 'node-2', 'node-3', 'node-4', 'node-5', 'node-6', 'node-7']
  const post = ['node-1', 'node-3', 'node-2', 'node-5', 'node-7', 'node-6', 'node-4']
  const level = ['node-4', 'node-2', 'node-6', 'node-1', 'node-3', 'node-5', 'node-7']

  it('四种顺序的访问序列都正确', () => {
    expect(treeOrderIds(DEMO_TREE, 'pre')).toEqual(pre)
    expect(treeOrderIds(DEMO_TREE, 'in')).toEqual(inOrder)
    expect(treeOrderIds(DEMO_TREE, 'post')).toEqual(post)
    expect(treeOrderIds(DEMO_TREE, 'level')).toEqual(level)
  })

  it('中序就是 BST 的升序序列', () => {
    const values = treeOrderIds(DEMO_TREE, 'in').map((id) => {
      const node = treeLayout(DEMO_TREE).nodes.find((item) => item.id === id)
      return node?.value
    })
    expect(values).toEqual([1, 2, 3, 4, 5, 6, 7])
  })

  it('帧数 = 节点数 + 1：每访问一个节点一帧，最后一帧收尾', () => {
    TREE_ORDERS.forEach((order) => {
      const frames = treeTraversalFrames(DEMO_TREE, order.id)
      expect(frames).toHaveLength(7 + 1)
      const last = frames[frames.length - 1]
      expect(last.current).toBe('')
      expect(last.visited).toHaveLength(7)
      expect(last.note).toContain('遍历结束')
    })
  })

  it('visited 逐帧只追加一个节点（收尾帧不新增）', () => {
    const frames = treeTraversalFrames(DEMO_TREE, 'pre')
    for (let index = 1; index < frames.length - 1; index += 1) {
      expect(frames[index].visited).toHaveLength(frames[index - 1].visited.length + 1)
    }
  })

  it('布局：7 个节点 6 条边，边两端都是真实节点，中序横坐标递增', () => {
    const layout = treeLayout(DEMO_TREE)
    expect(layout.nodes).toHaveLength(7)
    expect(layout.edges).toHaveLength(6)
    const ids = new Set(layout.nodes.map((node) => node.id))
    layout.edges.forEach((edge) => {
      expect(ids.has(edge.from)).toBe(true)
      expect(ids.has(edge.to)).toBe(true)
    })
    const xs = layout.nodes.map((node) => node.x)
    expect(xs).toEqual([...xs].sort((left, right) => left - right))
    expect(layout.width).toBeGreaterThan(0)
    expect(layout.height).toBeGreaterThan(0)
  })
})

describe('0-1 背包填表', () => {
  const frames = knapsackFrames(DEMO_KNAPSACK)

  it('末帧 dp[capacity] 与暴力枚举一致（样例答案是 7，不是 8）', () => {
    const { capacity, weights, values } = DEMO_KNAPSACK
    let best = 0
    for (let mask = 0; mask < 1 << weights.length; mask += 1) {
      let weight = 0
      let value = 0
      weights.forEach((itemWeight, index) => {
        if ((mask & (1 << index)) !== 0) {
          weight += itemWeight
          value += values[index]
        }
      })
      if (weight <= capacity) best = Math.max(best, value)
    }
    const last = frames[frames.length - 1]
    expect(last.dp[capacity]).toBe(best)
    expect(best).toBe(7)
  })

  it('首帧全 0 且没有处理任何物品；末帧两个下标都是 -1', () => {
    expect(frames[0].dp).toEqual([0, 0, 0, 0, 0, 0])
    expect(frames[0].item).toBe(-1)
    const last = frames[frames.length - 1]
    expect(last.item).toBe(-1)
    expect(last.slot).toBe(-1)
  })

  it('dp 单调不减，且容量 0 永远是 0', () => {
    for (let index = 1; index < frames.length; index += 1) {
      frames[index].dp.forEach((value, slot) => {
        expect(value).toBeGreaterThanOrEqual(frames[index - 1].dp[slot])
      })
      expect(frames[index].dp[0]).toBe(0)
    }
  })

  it('中间每一帧只改进一个容量格（逆序写法不会重复取同一件物品）', () => {
    for (let index = 1; index < frames.length - 1; index += 1) {
      const prev = frames[index - 1]
      const next = frames[index]
      expect(next.slot).toBeGreaterThanOrEqual(0)
      const changed = next.dp
        .map((value, slot) => (value === prev.dp[slot] ? -1 : slot))
        .filter((slot) => slot >= 0)
      expect(changed).toEqual([next.slot])
    }
  })

  it('物品数量与 dp 表长度一致：容量 5 有 6 个格子', () => {
    frames.forEach((frame) => expect(frame.dp).toHaveLength(DEMO_KNAPSACK.capacity + 1))
    expect(DEMO_KNAPSACK.weights).toHaveLength(DEMO_KNAPSACK.values.length)
  })
})
