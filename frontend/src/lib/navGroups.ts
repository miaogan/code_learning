import type { ToolNavItem } from '../components/ui/ToolNav'

/** 工具分组：key 供渲染列表用，label 用于将来需要展示分组名的场景。 */
export interface ToolNavGroup {
  key: string
  label: string
  items: ToolNavItem[]
}

/**
 * 工具分组数据源（r127：桌面顶栏 `.sc-topnav` 按组分隔线平铺的唯一数据源）。
 *
 * - 桌面顶栏：分组间渲染细分隔线，分组语义纯视觉、零交互成本；
 * - 手机横条（<1024）：`TOOL_ITEMS` 平铺，入口同源不分叉；
 * - 分组语义：文房=AI 辅助（检索/讲席/修文）、研习=学习练习（学堂/演武/镜试）、
 *   岗途=岗位闭环（对岗/跃迁）、雷达=采集看板（先锋/国子监）、卷藏=记录存档（战绩/卷宗/校勘）。
 */
export const TOOL_GROUPS: ToolNavGroup[] = [
  {
    key: 'desk',
    label: '文房',
    items: [
      { key: 'search', label: '检索', to: '/search' },
      { key: 'coach', label: '讲席', to: '/coach' },
      { key: 'polish', label: '修文', to: '/polish' },
    ],
  },
  {
    key: 'study',
    label: '研习',
    items: [
      { key: 'learn', label: '学堂', to: '/learn' },
      { key: 'practice', label: '演武', to: '/practice' },
      { key: 'mirror', label: '镜试', to: '/mirror' },
    ],
  },
  {
    key: 'path',
    label: '岗途',
    items: [
      { key: 'jd', label: '对岗', to: '/jd' },
      { key: 'leap', label: '跃迁', to: '/leap' },
    ],
  },
  {
    key: 'radar',
    label: '雷达',
    items: [
      { key: 'pioneer', label: '先锋', to: '/pioneer' },
      { key: 'guozijian', label: '国子监', to: '/guozijian' },
    ],
  },
  {
    key: 'shelf',
    label: '卷藏',
    items: [
      { key: 'history', label: '战绩', to: '/history' },
      { key: 'archive', label: '卷宗', to: '/archive' },
      { key: 'versions', label: '校勘', to: '/versions' },
    ],
  },
]

/** 顶部横条用的平铺清单：从分组推导，保证两处入口永远同源。 */
export const TOOL_ITEMS: ToolNavItem[] = TOOL_GROUPS.flatMap((group) => [...group.items])

/**
 * 路由激活判定：全等或子路径。与 Stepper 判定口径一致——
 * 学习模块有 `/learn/:chapterId` 子页面，只判全等会让文章页的侧栏失去高亮。
 */
export const isRouteActive = (pathname: string, to: string): boolean =>
  pathname === to || pathname.startsWith(`${to}/`)
