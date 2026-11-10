/**
 * r66 交互式演示的纯函数层：每个演示的「帧序列」与几何布局都在这里算好，
 * 组件只负责把当前帧画出来 —— 页面零计算，与站内其他派生逻辑保持同一口径。
 *
 * 样例数据是固定的（不读后端、不读用户输入）：教程要的是「看懂机制」，
 * 随机输入只会让读者怀疑自己看到的这一步是不是对的。
 */
import type { TutorialDemoId } from './tutorialTypes'

/** 所有演示共有的一帧：`note` 用中文讲清「刚发生了什么、下一步为什么这样走」。 */
export interface DemoFrame {
  note: string
}

/** 演示闭集：组件注册表按类型穷举，新增演示必须同时补 `TutorialDemoId` 与这里。 */
export const DEMO_IDS: readonly TutorialDemoId[] = [
  'complexity-growth',
  'binary-search',
  'two-pointer',
  'tree-traversal',
  'dp-knapsack',
]

// ---------------------------------------------------------------- 复杂度增长

export type ComplexityId = 'logn' | 'n' | 'nlogn' | 'n2'

export interface ComplexityCurve {
  id: ComplexityId
  label: string
  /** 数据量 n 下的操作次数（近似值，只用于对比量级，不是基准测试结果）。 */
  ops: (n: number) => number
  note: string
}

export const COMPLEXITY_CURVES: readonly ComplexityCurve[] = [
  {
    id: 'logn',
    label: 'O(log n)',
    ops: (n) => Math.max(1, Math.round(Math.log2(n))),
    note: '每次规模减半：n 翻倍只多一步',
  },
  {
    id: 'n',
    label: 'O(n)',
    ops: (n) => n,
    note: '与数据量线性增长',
  },
  {
    id: 'nlogn',
    label: 'O(n log n)',
    ops: (n) => n * Math.max(1, Math.round(Math.log2(n))),
    note: '排序的典型量级',
  },
  {
    id: 'n2',
    label: 'O(n²)',
    ops: (n) => n * n,
    note: '双层枚举：n 翻倍，操作变四倍',
  },
]

/** 可选的数据量：跨三个数量级，才看得出差距怎么拉开。 */
export const COMPLEXITY_N_OPTIONS: readonly number[] = [8, 64, 512, 4096]

export interface ComplexityRow {
  id: ComplexityId
  label: string
  ops: number
  /** 条形长度 0–100：**对数压缩**，否则 O(log n) 会被 O(n²) 直接压成 0 宽；真实次数看右侧读数。 */
  percent: number
  note: string
}

export function complexityGrowth(n: number): ComplexityRow[] {
  const ops = COMPLEXITY_CURVES.map((curve) => curve.ops(n))
  const max = Math.max(...ops, 1)
  return COMPLEXITY_CURVES.map((curve, index) => ({
    id: curve.id,
    label: curve.label,
    ops: ops[index],
    percent: Math.round((Math.log(ops[index] + 1) / Math.log(max + 1)) * 100),
    note: curve.note,
  }))
}

// ---------------------------------------------------------------- 二分查找

export type BinarySearchStatus = 'start' | 'shrink-left' | 'shrink-right' | 'found' | 'miss'

export interface BinarySearchFrame extends DemoFrame {
  /** 当前搜索区间（闭区间）；无解收尾帧的 `low` 会大于 `high`。 */
  low: number
  high: number
  /** 本帧比较的下标；`-1` 表示这一帧没有比较（起始帧与无解帧）。 */
  mid: number
  status: BinarySearchStatus
}

export const DEMO_SEARCH_VALUES: readonly number[] = [1, 3, 5, 7, 9, 11, 13, 15]
export const DEMO_SEARCH_TARGET = 11

export function binarySearchFrames(
  values: readonly number[],
  target: number,
): BinarySearchFrame[] {
  if (values.length === 0) {
    return [
      { low: 0, high: -1, mid: -1, status: 'miss', note: '数组为空，直接返回没找到。' },
    ]
  }
  let low = 0
  let high = values.length - 1
  let probes = 0
  const frames: BinarySearchFrame[] = [
    {
      low,
      high,
      mid: -1,
      status: 'start',
      note: `在 ${values.length} 个有序元素里找 ${target}：搜索范围 [0, ${high}]，下一步比较中点。`,
    },
  ]
  while (low <= high) {
    const mid = Math.floor((low + high) / 2)
    const value = values[mid]
    probes += 1
    if (value === target) {
      frames.push({
        low,
        high,
        mid,
        status: 'found',
        note: `第 ${probes} 次比较：mid=${mid} 的值正好是 ${target}，返回下标 ${mid}。`,
      })
      return frames
    }
    if (value < target) {
      frames.push({
        low,
        high,
        mid,
        status: 'shrink-left',
        note: `第 ${probes} 次比较：mid=${mid} 的值 ${value} < ${target}，它和左半边全部更小，整块排除，low 移到 ${mid + 1}。`,
      })
      low = mid + 1
    } else {
      frames.push({
        low,
        high,
        mid,
        status: 'shrink-right',
        note: `第 ${probes} 次比较：mid=${mid} 的值 ${value} > ${target}，它和右半边全部更大，整块排除，high 移到 ${mid - 1}。`,
      })
      high = mid - 1
    }
  }
  frames.push({
    low,
    high,
    mid: -1,
    status: 'miss',
    note: `区间已经空掉（low=${low} > high=${high}），共比较 ${probes} 次，确认没有 ${target}。`,
  })
  return frames
}

// ---------------------------------------------------------------- 对撞双指针

export type TwoPointerStatus = 'small' | 'large' | 'found' | 'miss'

export interface TwoPointerFrame extends DemoFrame {
  left: number
  right: number
  /** 本帧两个指针所指元素之和；指针相遇（无解收尾）时为 0。 */
  sum: number
  status: TwoPointerStatus
}

export const DEMO_POINTER_VALUES: readonly number[] = [1, 2, 4, 7, 11, 15]
export const DEMO_POINTER_TARGET = 13

export function twoPointerFrames(
  values: readonly number[],
  target: number,
): TwoPointerFrame[] {
  if (values.length < 2) {
    return [
      { left: 0, right: values.length - 1, sum: 0, status: 'miss', note: '少于两个元素，凑不成一对。' },
    ]
  }
  let left = 0
  let right = values.length - 1
  let step = 0
  const frames: TwoPointerFrame[] = []
  while (left < right) {
    const sum = values[left] + values[right]
    step += 1
    if (sum === target) {
      frames.push({
        left,
        right,
        sum,
        status: 'found',
        note: `第 ${step} 步：${values[left]} + ${values[right]} = ${target}，两个下标都找到了。`,
      })
      return frames
    }
    if (sum < target) {
      frames.push({
        left,
        right,
        sum,
        status: 'small',
        note: `第 ${step} 步：${values[left]} + ${values[right]} = ${sum} < ${target}；右指针已经指到最大，只能让左指针右移去凑更大的数。`,
      })
      left += 1
    } else {
      frames.push({
        left,
        right,
        sum,
        status: 'large',
        note: `第 ${step} 步：${values[left]} + ${values[right]} = ${sum} > ${target}；左指针已经指到最小，只能让右指针左移去凑更小的数。`,
      })
      right -= 1
    }
  }
  frames.push({
    left: Math.min(left, values.length - 1),
    right,
    sum: 0,
    status: 'miss',
    note: `两个指针相遇（left=${left}、right=${right}）仍然没凑出 ${target}，说明无解。`,
  })
  return frames
}

// ---------------------------------------------------------------- 二叉树遍历

export type TreeOrder = 'pre' | 'in' | 'post' | 'level'

export interface DemoTreeNode {
  id: string
  value: number
  left?: DemoTreeNode
  right?: DemoTreeNode
}

/** 固定样例树（值 1–7 的 BST）：根 4，左子树 2(1,3)，右子树 6(5,7)。 */
export const DEMO_TREE: DemoTreeNode = {
  id: 'node-4',
  value: 4,
  left: {
    id: 'node-2',
    value: 2,
    left: { id: 'node-1', value: 1 },
    right: { id: 'node-3', value: 3 },
  },
  right: {
    id: 'node-6',
    value: 6,
    left: { id: 'node-5', value: 5 },
    right: { id: 'node-7', value: 7 },
  },
}

export interface TreeOrderInfo {
  id: TreeOrder
  label: string
  rule: string
}

export const TREE_ORDERS: readonly TreeOrderInfo[] = [
  { id: 'pre', label: '前序', rule: '根 → 左 → 右' },
  { id: 'in', label: '中序', rule: '左 → 根 → 右' },
  { id: 'post', label: '后序', rule: '左 → 右 → 根' },
  { id: 'level', label: '层序', rule: '逐层从左到右' },
]

export interface TreeFrame extends DemoFrame {
  /** 已经访问过的节点 id（含本帧的 `current`）。 */
  visited: string[]
  /** 本帧刚访问的节点 id；`''` 表示遍历结束帧。 */
  current: string
  order: TreeOrder
}

/** 按指定顺序给出的访问 id 序列（不含结束帧）。 */
export function treeOrderIds(root: DemoTreeNode | undefined, order: TreeOrder): string[] {
  const ids: string[] = []
  if (root === undefined) return ids
  if (order === 'level') {
    const queue: DemoTreeNode[] = [root]
    while (queue.length > 0) {
      const node = queue.shift() as DemoTreeNode
      ids.push(node.id)
      if (node.left !== undefined) queue.push(node.left)
      if (node.right !== undefined) queue.push(node.right)
    }
    return ids
  }
  const walk = (node: DemoTreeNode | undefined): void => {
    if (node === undefined) return
    if (order === 'pre') ids.push(node.id)
    walk(node.left)
    if (order === 'in') ids.push(node.id)
    walk(node.right)
    if (order === 'post') ids.push(node.id)
  }
  walk(root)
  return ids
}

function treeValues(root: DemoTreeNode | undefined): Map<string, number> {
  const values = new Map<string, number>()
  const walk = (node: DemoTreeNode | undefined): void => {
    if (node === undefined) return
    values.set(node.id, node.value)
    walk(node.left)
    walk(node.right)
  }
  walk(root)
  return values
}

export function treeTraversalFrames(root: DemoTreeNode, order: TreeOrder): TreeFrame[] {
  const info = TREE_ORDERS.find((item) => item.id === order)
  const label = info?.label ?? '前序'
  const rule = info?.rule ?? '根 → 左 → 右'
  const values = treeValues(root)
  const ids = treeOrderIds(root, order)
  const frames: TreeFrame[] = ids.map((id, index) => ({
    visited: ids.slice(0, index + 1),
    current: id,
    order,
    note: `第 ${index + 1} 个访问：节点 ${values.get(id) ?? 0}（${label}：${rule}）。`,
  }))
  frames.push({
    visited: ids,
    current: '',
    order,
    note: `遍历结束：${ids.map((id) => values.get(id) ?? 0).join(' → ')}。`,
  })
  return frames
}

/** SVG 几何常量：只参与坐标计算，不参与 CSS（样式里的尺寸仍只走 token）。 */
const TREE_MARGIN = 32
const TREE_GAP_X = 64
const TREE_GAP_Y = 72
export const TREE_NODE_R = 18

export interface TreeLayoutNode {
  id: string
  value: number
  x: number
  y: number
  depth: number
}

export interface TreeLayoutEdge {
  from: string
  to: string
}

export interface TreeLayout {
  nodes: TreeLayoutNode[]
  edges: TreeLayoutEdge[]
  width: number
  height: number
}

/** 中序序号决定横坐标、深度决定纵坐标：BST 的节点不会互相压住。 */
export function treeLayout(root: DemoTreeNode): TreeLayout {
  const nodes: TreeLayoutNode[] = []
  let inorder = 0
  let maxDepth = 0
  const walk = (node: DemoTreeNode | undefined, depth: number): void => {
    if (node === undefined) return
    walk(node.left, depth + 1)
    nodes.push({
      id: node.id,
      value: node.value,
      x: TREE_MARGIN + inorder * TREE_GAP_X,
      y: TREE_MARGIN + depth * TREE_GAP_Y,
      depth,
    })
    inorder += 1
    maxDepth = Math.max(maxDepth, depth)
    walk(node.right, depth + 1)
  }
  walk(root, 0)
  // 边必须单独按父子关系走一遍：`nodes` 是按中序压入的，相邻两项不一定是父子。
  const edges: TreeLayoutEdge[] = []
  const link = (node: DemoTreeNode): void => {
    if (node.left !== undefined) {
      edges.push({ from: node.id, to: node.left.id })
      link(node.left)
    }
    if (node.right !== undefined) {
      edges.push({ from: node.id, to: node.right.id })
      link(node.right)
    }
  }
  link(root)
  return {
    nodes,
    edges,
    width: TREE_MARGIN * 2 + Math.max(0, nodes.length - 1) * TREE_GAP_X,
    height: TREE_MARGIN * 2 + maxDepth * TREE_GAP_Y,
  }
}

// ---------------------------------------------------------------- 0-1 背包填表

export interface KnapsackSample {
  capacity: number
  weights: readonly number[]
  values: readonly number[]
}

/** 与 `algo-dp-graph` 教程正文同一个样例：容量 5、三件物品。 */
export const DEMO_KNAPSACK: KnapsackSample = {
  capacity: 5,
  weights: [2, 3, 4],
  values: [3, 4, 5],
}

export interface KnapsackFrame extends DemoFrame {
  /** 当前一维 dp 表（长度 = capacity + 1），`dp[j]` = 容量 j 能装下的最大价值。 */
  dp: number[]
  /** 正在处理的物品下标；`-1` 表示初始帧与收尾帧。 */
  item: number
  /** 本帧刚被改进的容量下标；`-1` 表示这一帧没有写入。 */
  slot: number
}

export function knapsackFrames(sample: KnapsackSample): KnapsackFrame[] {
  const { capacity, weights, values } = sample
  const dp: number[] = new Array<number>(capacity + 1).fill(0)
  const frames: KnapsackFrame[] = [
    {
      dp: [...dp],
      item: -1,
      slot: -1,
      note: `dp 全为 0：还没放任何物品，容量 ${capacity} 下能装的最大价值是 0。`,
    },
  ]
  weights.forEach((weight, item) => {
    const value = values[item]
    if (value === undefined) return
    for (let slot = capacity; slot >= weight; slot -= 1) {
      const candidate = dp[slot - weight] + value
      if (candidate <= dp[slot]) continue
      const before = dp[slot]
      dp[slot] = candidate
      frames.push({
        dp: [...dp],
        item,
        slot,
        note: `第 ${item + 1} 件（重 ${weight}、价值 ${value}）：容量 ${slot} 从 ${before} 提到 ${candidate} = dp[${slot - weight}](${dp[slot - weight]}) + ${value}；逆序保证 dp[${slot - weight}] 还是上一件的旧值。`,
      })
    }
  })
  frames.push({
    dp: [...dp],
    item: -1,
    slot: -1,
    note: `收尾：dp[${capacity}] = ${dp[capacity]}，逆序保证每件物品只用了一次。`,
  })
  return frames
}
