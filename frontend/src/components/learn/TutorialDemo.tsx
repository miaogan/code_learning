import { useEffect, useState } from 'react'
import type { ReactElement } from 'react'
import type { TutorialBlock, TutorialDemoId } from '../../lib/tutorialTypes'
import type { DemoFrame, TreeFrame, TreeOrder } from '../../lib/tutorialDemos'
import {
  COMPLEXITY_N_OPTIONS,
  DEMO_KNAPSACK,
  DEMO_POINTER_TARGET,
  DEMO_POINTER_VALUES,
  DEMO_SEARCH_TARGET,
  DEMO_SEARCH_VALUES,
  DEMO_TREE,
  TREE_NODE_R,
  TREE_ORDERS,
  binarySearchFrames,
  complexityGrowth,
  knapsackFrames,
  treeLayout,
  treeTraversalFrames,
  twoPointerFrames,
} from '../../lib/tutorialDemos'
import { Button } from '../ui/Button'

/** 播放节奏：约一秒一步，够看清高亮怎么移动，也不用等太久。 */
const PLAY_INTERVAL_MS = 1000

interface Player<T extends DemoFrame> {
  index: number
  playing: boolean
  frame: T
  prev: () => void
  next: () => void
  reset: () => void
  toggle: () => void
}

/**
 * 帧播放器：`frames` 由 `lib/tutorialDemos` 预先算好，这里只管「看到第几帧」。
 * `resetKey` 变化（例如切换遍历顺序）时回到第一帧并停播，避免沿用上一组的进度。
 */
function usePlayer<T extends DemoFrame>(frames: readonly T[], resetKey: string): Player<T> {
  const [index, setIndex] = useState(0)
  const [playing, setPlaying] = useState(false)
  const last = frames.length - 1

  useEffect(() => {
    setIndex(0)
    setPlaying(false)
  }, [resetKey])

  useEffect(() => {
    if (!playing) return
    if (index >= last) {
      setPlaying(false)
      return
    }
    const timer = window.setTimeout(() => {
      setIndex((value) => Math.min(value + 1, last))
    }, PLAY_INTERVAL_MS)
    return () => window.clearTimeout(timer)
  }, [playing, index, last])

  return {
    index,
    playing,
    frame: frames[index],
    prev: () => setIndex((value) => Math.max(0, value - 1)),
    next: () => setIndex((value) => Math.min(last, value + 1)),
    reset: () => setIndex(0),
    toggle: () => {
      if (index >= last) {
        setIndex(0)
        setPlaying(true)
        return
      }
      setPlaying((value) => !value)
    },
  }
}

function PlayerControls({ player, total }: { player: Player<DemoFrame>; total: number }) {
  return (
    <div className="sc-demo-controls">
      <Button variant="ghost" size="sm" onClick={player.prev} disabled={player.index === 0}>
        上一步
      </Button>
      <Button
        variant="secondary"
        size="sm"
        onClick={player.toggle}
        aria-pressed={player.playing}
      >
        {player.playing ? '暂停' : '播放'}
      </Button>
      <Button
        variant="ghost"
        size="sm"
        onClick={player.next}
        disabled={player.index === total - 1}
      >
        下一步
      </Button>
      <Button variant="ghost" size="sm" onClick={player.reset} disabled={player.index === 0}>
        重置
      </Button>
      <span className="sc-demo-count">{`第 ${player.index + 1} / ${total} 步`}</span>
    </div>
  )
}

function FrameNote({ text }: { text: string }) {
  return (
    <p className="sc-demo-note" aria-live="polite">
      {text}
    </p>
  )
}

function Cells({
  values,
  classes,
}: {
  values: readonly number[]
  classes: (index: number) => string[]
}) {
  return (
    <div className="sc-demo-track" aria-hidden="true">
      {values.map((value, index) => (
        <span className={classes(index).join(' ')} key={`cell-${index}`}>
          <span className="sc-demo-cellindex">{index}</span>
          {value}
        </span>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------- 复杂度增长

function ComplexityGrowthView() {
  const [n, setN] = useState<number>(COMPLEXITY_N_OPTIONS[0])
  const rows = complexityGrowth(n)
  return (
    <>
      <div className="sc-demo-switch" role="group" aria-label="数据量 n">
        {COMPLEXITY_N_OPTIONS.map((option) => (
          <Button
            key={option}
            variant={option === n ? 'primary' : 'ghost'}
            size="sm"
            aria-pressed={option === n}
            onClick={() => setN(option)}
          >
            {`n = ${option}`}
          </Button>
        ))}
      </div>
      <div className="sc-demo-bars">
        {rows.map((row) => (
          <div className="sc-demo-barrow" key={row.id}>
            <span className="sc-demo-barlabel">{row.label}</span>
            <span className="sc-demo-bartrack" aria-hidden="true">
              <span className="sc-demo-barfill" style={{ width: `${row.percent}%` }} />
            </span>
            <span className="sc-demo-barvalue">{`${row.ops} 次`}</span>
            <span className="sc-demo-barnote">{row.note}</span>
          </div>
        ))}
      </div>
      <FrameNote
        text={`n = ${n}：条形按对数压缩，否则 O(log n) 会被 O(n²) 压成看不见；右侧是真实操作次数。`}
      />
    </>
  )
}

// ---------------------------------------------------------------- 二分查找

const BINARY_FRAMES = binarySearchFrames(DEMO_SEARCH_VALUES, DEMO_SEARCH_TARGET)

function BinarySearchView() {
  const player = usePlayer(BINARY_FRAMES, 'binary-search')
  const frame = player.frame
  return (
    <>
      <Cells
        values={DEMO_SEARCH_VALUES}
        classes={(index) => {
          const classes = ['sc-demo-cell']
          if (index < frame.low || index > frame.high) classes.push('is-out')
          if (index === frame.mid) classes.push(frame.status === 'found' ? 'is-hit' : 'is-mid')
          return classes
        }}
      />
      <p className="sc-demo-legend">{`目标 ${DEMO_SEARCH_TARGET} · 变暗 = 已排除 · 高亮 = 本次 mid`}</p>
      <FrameNote text={frame.note} />
      <PlayerControls player={player} total={BINARY_FRAMES.length} />
    </>
  )
}

// ---------------------------------------------------------------- 对撞双指针

const POINTER_FRAMES = twoPointerFrames(DEMO_POINTER_VALUES, DEMO_POINTER_TARGET)

function TwoPointerView() {
  const player = usePlayer(POINTER_FRAMES, 'two-pointer')
  const frame = player.frame
  return (
    <>
      <Cells
        values={DEMO_POINTER_VALUES}
        classes={(index) => {
          const classes = ['sc-demo-cell']
          if (index < frame.left || index > frame.right) classes.push('is-out')
          if (index === frame.left) classes.push('is-left')
          if (index === frame.right) classes.push('is-right')
          if (frame.status === 'found' && (index === frame.left || index === frame.right)) {
            classes.push('is-hit')
          }
          return classes
        }}
      />
      <p className="sc-demo-legend">
        {`目标 ${DEMO_POINTER_TARGET} · 左指针从最小开始 · 右指针从最大开始 · 变暗 = 已经排除`}
      </p>
      <FrameNote text={frame.note} />
      <PlayerControls player={player} total={POINTER_FRAMES.length} />
    </>
  )
}

// ---------------------------------------------------------------- 二叉树遍历

const TREE_LAYOUT = treeLayout(DEMO_TREE)
const TREE_POS = new Map(TREE_LAYOUT.nodes.map((node) => [node.id, node]))
const TREE_FRAMES: Record<TreeOrder, TreeFrame[]> = {
  pre: treeTraversalFrames(DEMO_TREE, 'pre'),
  in: treeTraversalFrames(DEMO_TREE, 'in'),
  post: treeTraversalFrames(DEMO_TREE, 'post'),
  level: treeTraversalFrames(DEMO_TREE, 'level'),
}

function TreeTraversalView() {
  const [order, setOrder] = useState<TreeOrder>('pre')
  const frames = TREE_FRAMES[order]
  const player = usePlayer(frames, order)
  const frame = player.frame
  const info = TREE_ORDERS.find((item) => item.id === order)
  return (
    <>
      <div className="sc-demo-switch" role="group" aria-label="遍历顺序">
        {TREE_ORDERS.map((item) => (
          <Button
            key={item.id}
            variant={item.id === order ? 'primary' : 'ghost'}
            size="sm"
            aria-pressed={item.id === order}
            onClick={() => setOrder(item.id)}
          >
            {item.label}
          </Button>
        ))}
      </div>
      <svg
        className="sc-demo-tree"
        viewBox={`0 0 ${TREE_LAYOUT.width} ${TREE_LAYOUT.height}`}
        role="img"
        aria-label={`样例二叉树${info?.label ?? ''}遍历（${info?.rule ?? ''}）`}
      >
        {TREE_LAYOUT.edges.map((edge) => {
          const from = TREE_POS.get(edge.from)
          const to = TREE_POS.get(edge.to)
          if (from === undefined || to === undefined) return null
          return (
            <line
              key={`${edge.from}-${edge.to}`}
              className="sc-demo-treeedge"
              x1={from.x}
              y1={from.y}
              x2={to.x}
              y2={to.y}
            />
          )
        })}
        {TREE_LAYOUT.nodes.map((node) => {
          const classes = ['sc-demo-treenode']
          if (frame.visited.includes(node.id)) classes.push('is-visited')
          if (frame.current === node.id) classes.push('is-current')
          return (
            <g key={node.id} className={classes.join(' ')}>
              <circle cx={node.x} cy={node.y} r={TREE_NODE_R} className="sc-demo-treecircle" />
              <text x={node.x} y={node.y} className="sc-demo-treetext" textAnchor="middle" dominantBaseline="central">
                {node.value}
              </text>
            </g>
          )
        })}
      </svg>
      <p className="sc-demo-legend">
        {`访问顺序：${info?.label ?? ''}（${info?.rule ?? ''}）· 已访问格变色 · 当前格高亮`}
      </p>
      <FrameNote text={frame.note} />
      <PlayerControls player={player} total={frames.length} />
    </>
  )
}

// ---------------------------------------------------------------- 0-1 背包填表

const KNAPSACK_FRAMES = knapsackFrames(DEMO_KNAPSACK)
const KNAPSACK_SLOTS = KNAPSACK_FRAMES[0].dp.map((_, index) => index)

function KnapsackView() {
  const player = usePlayer(KNAPSACK_FRAMES, 'dp-knapsack')
  const frame = player.frame
  return (
    <>
      <div className="sc-demo-items" aria-hidden="true">
        {DEMO_KNAPSACK.weights.map((weight, index) => {
          const classes = ['sc-demo-item']
          if (frame.item === index) classes.push('is-active')
          return (
            <span className={classes.join(' ')} key={`item-${index}`}>
              {`${index + 1} 号 · 重 ${weight} · 价值 ${DEMO_KNAPSACK.values[index]}`}
            </span>
          )
        })}
      </div>
      <div className="sc-demo-track" aria-hidden="true">
        {KNAPSACK_SLOTS.map((slot) => {
          const classes = ['sc-demo-cell']
          if (frame.slot === slot) classes.push('is-mid')
          return (
            <span className={classes.join(' ')} key={`slot-${slot}`}>
              <span className="sc-demo-cellindex">{slot}</span>
              {frame.dp[slot]}
            </span>
          )
        })}
      </div>
      <p className="sc-demo-legend">
        {`容量 ${DEMO_KNAPSACK.capacity} · 一格 = 某个容量下的最大价值 · 每步只更新一个容量`}
      </p>
      <FrameNote text={frame.note} />
      <PlayerControls player={player} total={KNAPSACK_FRAMES.length} />
    </>
  )
}

// ---------------------------------------------------------------- 注册表

const DEMO_VIEWS: Record<TutorialDemoId, () => ReactElement> = {
  'complexity-growth': ComplexityGrowthView,
  'binary-search': BinarySearchView,
  'two-pointer': TwoPointerView,
  'tree-traversal': TreeTraversalView,
  'dp-knapsack': KnapsackView,
}

type DemoBlock = Extract<TutorialBlock, { kind: 'demo' }>

/** 教程正文里的交互演示块：外面统一套一层「交互演示 + 标题 + 图注」的框。 */
export function TutorialDemo({ block }: { block: DemoBlock }) {
  const View = DEMO_VIEWS[block.demo]
  return (
    <figure className="sc-demo">
      <div className="sc-demo-head">
        <span className="sc-demo-kicker">交互演示</span>
        <span className="sc-demo-title">{block.title}</span>
      </div>
      <View />
      {block.caption === undefined ? null : (
        <figcaption className="sc-demo-caption">{block.caption}</figcaption>
      )}
    </figure>
  )
}
