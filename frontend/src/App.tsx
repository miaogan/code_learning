import { useEffect, useRef } from 'react'
import { Link, Route, Routes, useLocation } from 'react-router-dom'
import { AiKeyModal } from './components/ui/AiKeyModal'
import { Button } from './components/ui/Button'
import { ErrorBoundary } from './components/ui/ErrorBoundary'
import { Stepper, type StepItem, type StepState } from './components/ui/Stepper'
import { ToolNav } from './components/ui/ToolNav'
import { TaifuLauncher } from './components/taifu/TaifuLauncher'
import { StreakBadge } from './components/ui/StreakBadge'
import EvalPage from './pages/EvalPage'
import EvidencePage from './pages/EvidencePage'
import CoachPage from './pages/CoachPage'
import ExamPage from './pages/ExamPage'
import GuozijianPage from './pages/GuozijianPage'
import HistoryPage from './pages/HistoryPage'
import InterviewPage from './pages/InterviewPage'
import JdPage from './pages/JdPage'
import LearnPage from './pages/LearnPage'
import LeapPage from './pages/LeapPage'
import LoginPage from './pages/LoginPage'
import MirrorPage from './pages/MirrorPage'
import NotFoundPage from './pages/NotFoundPage'
import PioneerPage from './pages/PioneerPage'
import PolishPage from './pages/PolishPage'
import PracticePage from './pages/PracticePage'
import ProfilePage from './pages/ProfilePage'
import ReportPage from './pages/ReportPage'
import SearchPage from './pages/SearchPage'
import SettingsPage from './pages/SettingsPage'
import TutorialPage from './pages/TutorialPage'
import UploadPage from './pages/UploadPage'
import VersionsPage from './pages/VersionsPage'
import ArchivePage from './pages/ArchivePage'
import { GITHUB_AVATAR_URL, GITHUB_OWNER, GITHUB_REPO_URL, PRODUCT_NAME, PRODUCT_TAGLINE } from './lib/brand'
import { TOOL_GROUPS, TOOL_ITEMS, isRouteActive } from './lib/navGroups'
import { resetResumePrompt } from './lib/resumePrompt'
import { logout, startAuth, useAuth } from './state/auth'
import { dismissKeyRequired } from './state/aiGate'
import { useFlowState } from './state/flow'

const STEP_BASE = [
  { key: 'upload', label: '投卷', to: '/' },
  { key: 'profile', label: '立传', to: '/profile' },
  { key: 'interview', label: '召对', to: '/interview' },
  { key: 'exam', label: '科考', to: '/exam' },
  { key: 'report', label: '医案', to: '/report' },
] as const

/** 侧栏「设置」组：只读看板（评鉴 / 考工）与账号 / AI 配置，从工具组里分出来。 */
const SETTINGS_ITEMS = [
  { key: 'eval', label: '评鉴', to: '/eval' },
  { key: 'evidence', label: '考工', to: '/evidence' },
  { key: 'settings', label: '典制', to: '/settings' },
]

/** 全局壳：顶栏 56 + 侧栏 240（<1024 收为顶部横向步骤条），主区 max 1080。 */
export default function App() {
  const { pathname } = useLocation()
  const flow = useFlowState()
  const auth = useAuth()

  // 启动时拉一次 /api/me（store 内部有 StrictMode 守卫，不会重复请求）。
  useEffect(() => {
    void startAuth()
  }, [])

  // r148：切页签回到页首。页签间内容高度差很大，保留旧 scrollY 会被新页面的高度
  // clamp 到顶部/中部，看起来像整页抖动。带 hash 的深链不重置——学堂「继续学习」
  // （`/learn/<chapter>#tutorial-…`）由目标页自己 scrollIntoView，先回顶会把它顶回去。
  // deps 只用 pathname：search 变化（筛选、深链定位）不动滚动位置。
  useEffect(() => {
    if (window.location.hash === '') window.scrollTo(0, 0)
  }, [pathname])

  // 登出 / 被踢回登录页时清掉 AI 能力提示与「未上传简历」会话标记，避免下一位用户看到上一轮的旧弹框。
  // 注意只认「已登录 → null」的跳变：启动首帧 auth.me 尚未知（也是 null），不能当作登出，
  // 否则每次整页刷新都会把会话引导标记清掉，「只弹一次」就失效了。
  const prevMeRef = useRef<string | null | undefined>(undefined)
  useEffect(() => {
    const prev = prevMeRef.current
    prevMeRef.current = auth.me === null ? null : auth.me.id
    if (auth.me === null && prev !== null && prev !== undefined) {
      dismissKeyRequired()
      resetResumePrompt()
    }
  }, [auth.me])

  const isDone = (key: string): boolean => {
    if (key === 'upload') return flow.hasResume
    if (key === 'profile') return flow.hasProfile
    if (key === 'interview') return flow.hasInterview
    if (key === 'exam') return flow.hasExam
    if (key === 'report') return flow.hasReport
    return false
  }

  const steps: StepItem[] = STEP_BASE.map((step) => {
    const state: StepState =
      pathname === step.to ? 'current' : isDone(step.key) ? 'done' : 'todo'
    return { key: step.key, label: step.label, to: step.to, state }
  })

  if (auth.status === 'loading') {
    return <p className="sc-boot">正在加载…</p>
  }

  if (auth.me === null) {
    return <LoginPage />
  }

  const me = auth.me
  // r127 迭代二：侧栏「流程位」显示哪一组由路由推导——设置页路由时显示三个
  // 设置页入口，其余（含全部工具页）显示流程步骤。纯渲染期推导，无状态可漂移。
  const settingsMode = SETTINGS_ITEMS.some((item) => isRouteActive(pathname, item.to))

  return (
    <>
      <header className="sc-topbar">
        <div className="sc-topbar-left">
          <Link className="sc-brand" to="/" aria-label={`${PRODUCT_NAME}首页`}>
            <span className="sc-brand-mark" aria-hidden="true">↗</span>
            <span className="sc-brand-copy">
              <span className="sc-brand-name">{PRODUCT_NAME}</span>
              <span className="sc-brand-tagline">{PRODUCT_TAGLINE}</span>
            </span>
          </Link>
          {/* 项目外链：GitHub 头像即仓库入口（新窗口打开，避免离开当前工作台）。 */}
          <a
            className="sc-github-link"
            href={GITHUB_REPO_URL}
            target="_blank"
            rel="noreferrer"
            title={`GitHub 仓库：${GITHUB_OWNER}/code_learning`}
          >
            <img
              className="sc-github-avatar"
              src={GITHUB_AVATAR_URL}
              alt={`${GITHUB_OWNER} 的 GitHub 头像`}
              width={22}
              height={22}
            />
            <span className="sc-github-label">GitHub</span>
          </a>
          {/* r127 桌面工具导航：13 个工具平铺（两字词放得下），分组语义用细分隔线
              表达（文房┃研习┃岗途┃雷达┃卷藏）——纯视觉、零交互成本。与手机端
              `.sc-topstepper` 里的横条共用 TOOL_GROUPS 数据源。<1024 隐藏。 */}
          <nav className="sc-topnav" aria-label="工具导航">
            {TOOL_GROUPS.map((group, index) => (
              <span className="sc-topnav-group" key={group.key}>
                {index > 0 ? <span className="sc-topnav-sep" aria-hidden="true" /> : null}
                {group.items.map((item) => (
                  <Link
                    key={item.key}
                    to={item.to}
                    className={isRouteActive(pathname, item.to) ? 'sc-topnav-item is-active' : 'sc-topnav-item'}
                    aria-current={isRouteActive(pathname, item.to) ? 'page' : undefined}
                  >
                    {item.label}
                  </Link>
                ))}
              </span>
            ))}
          </nav>
        </div>
        <div className="sc-topbar-right">
          {/* r127 迭代二：设置不再做下拉层级——就是一个普通按钮（链接到典制页）。
              点击后侧栏「流程」位置切换为三个设置页（由路由推导，见下方 sidebar）；
              回到流程：点 logo / 任一工具页即可。<1024 由横条平铺承接。 */}
          <Link
            className={settingsMode ? 'sc-settings-btn is-active' : 'sc-settings-btn'}
            to="/settings"
            title="评鉴 / 考工 / 典制"
            aria-current={settingsMode ? 'true' : undefined}
          >
            设置
          </Link>
          <StreakBadge />
          <span className="sc-storage">数据按账号隔离保存</span>
          <Link className="sc-topbar-link" to="/settings" title="配置：账号与 AI 服务">
            {me.display_name}
          </Link>
          <Button variant="ghost" size="sm" onClick={() => void logout()}>
            退出登录
          </Button>
        </div>
      </header>

      <div className="sc-shell">
        <aside className="sc-sidebar">
          {/* r83 §11：外层 <aside> 保持撑满整列（右侧分隔线不断），sticky 交给这层，
              导航才不会随页面滚走。见 base.css .sc-sidebar-inner。 */}
          <div className="sc-sidebar-inner">
            {/* r127 迭代二：侧栏「流程位」二选一——默认流程（5 步 Stepper）；
                当前在设置页路由时切换为三个设置页入口（评鉴/考工/典制）。
                回到流程：点 logo（→ 首页）、任一工具页或顶栏任一流程步骤。
                侧栏依旧不滚不折不浮层。 */}
            {settingsMode ? (
              <ToolNav items={SETTINGS_ITEMS} label="设置" orientation="vertical" />
            ) : (
              <Stepper steps={steps} orientation="vertical" />
            )}
          </div>
        </aside>
        <main className="sc-main">
          <div className="sc-topstepper">
            <Stepper steps={steps} orientation="horizontal" />
            {/* r21：<1024 侧栏 display:none，而 ToolNav 此前只渲染在侧栏内 —— 手机上
                「演武 / 战绩 / 修文」三个工具页没有任何入口。这里复用同一份
                TOOL_ITEMS 渲染横向工具条（组件早已支持 orientation="horizontal"）；
                桌面由 `@media (min-width:1024px) { .sc-topstepper: display:none }` 隐藏本容器。 */}
            <ToolNav items={TOOL_ITEMS} orientation="horizontal" />
            <ToolNav items={SETTINGS_ITEMS} label="设置" orientation="horizontal" />
          </div>
          <div className="sc-page">
            <AiKeyModal />
            {/* r84 §1：路由级渲染错误边界。key=pathname —— 路由切换时重置边界，
                否则 A 页崩过一次，边界 state 里留着 error，B 页会一直看到兜底卡。 */}
            <ErrorBoundary key={pathname} label="页面">
              <Routes>
                <Route path="/" element={<UploadPage />} />
                <Route path="/profile" element={<ProfilePage />} />
                <Route path="/interview" element={<InterviewPage />} />
                <Route path="/mirror" element={<MirrorPage />} />
                <Route path="/exam" element={<ExamPage />} />
                <Route path="/report" element={<ReportPage />} />
                <Route path="/history" element={<HistoryPage />} />
                <Route path="/eval" element={<EvalPage />} />
                <Route path="/evidence" element={<EvidencePage />} />
                <Route path="/polish" element={<PolishPage />} />
                <Route path="/versions" element={<VersionsPage />} />
                <Route path="/archive" element={<ArchivePage />} />
                <Route path="/jd" element={<JdPage />} />
                <Route path="/leap" element={<LeapPage />} />
                <Route path="/practice" element={<PracticePage />} />
                <Route path="/pioneer" element={<PioneerPage />} />
                <Route path="/guozijian" element={<GuozijianPage />} />
                <Route path="/search" element={<SearchPage />} />
                <Route path="/coach" element={<CoachPage />} />
                <Route path="/learn" element={<LearnPage />} />
                <Route path="/learn/:chapterId" element={<TutorialPage />} />
                <Route path="/settings" element={<SettingsPage />} />
                <Route path="*" element={<NotFoundPage />} />
              </Routes>
            </ErrorBoundary>
          </div>
        </main>
      </div>
      <TaifuLauncher userId={me.id} />
    </>
  )
}
