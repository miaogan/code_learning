import { useEffect, useRef } from 'react'
import { Link, Route, Routes, useLocation } from 'react-router-dom'
import { AiKeyModal } from './components/ui/AiKeyModal'
import { Button } from './components/ui/Button'
import { Stepper, type StepItem, type StepState } from './components/ui/Stepper'
import { ToolNav } from './components/ui/ToolNav'
import EvalPage from './pages/EvalPage'
import ExamPage from './pages/ExamPage'
import HistoryPage from './pages/HistoryPage'
import InterviewPage from './pages/InterviewPage'
import LearnPage from './pages/LearnPage'
import LoginPage from './pages/LoginPage'
import PolishPage from './pages/PolishPage'
import PracticePage from './pages/PracticePage'
import ProfilePage from './pages/ProfilePage'
import ReportPage from './pages/ReportPage'
import SettingsPage from './pages/SettingsPage'
import TutorialPage from './pages/TutorialPage'
import UploadPage from './pages/UploadPage'
import VersionsPage from './pages/VersionsPage'
import { PRODUCT_NAME, PRODUCT_TAGLINE } from './lib/brand'
import { resetResumePrompt } from './lib/resumePrompt'
import { logout, startAuth, useAuth } from './state/auth'
import { dismissKeyRequired } from './state/aiGate'
import { useFlowState } from './state/flow'

const STEP_BASE = [
  { key: 'upload', label: '上传简历', to: '/' },
  { key: 'profile', label: '技术画像', to: '/profile' },
  { key: 'interview', label: '模拟面试', to: '/interview' },
  { key: 'exam', label: '模拟笔试', to: '/exam' },
  { key: 'report', label: '诊断报告', to: '/report' },
] as const

/** 侧栏「工具」组：日常使用的非线性出口，不混进步骤（DESIGN §1.1）。 */
const TOOL_ITEMS = [
  { key: 'learn', label: '学习', to: '/learn' },
  { key: 'practice', label: '练习', to: '/practice' },
  { key: 'history', label: '成绩趋势', to: '/history' },
  { key: 'polish', label: '简历润色', to: '/polish' },
  { key: 'versions', label: '版本对比', to: '/versions' },
]

/** 侧栏「设置」组：只读看板（模型质量）与账号 / AI 配置，从工具组里分出来。 */
const SETTINGS_ITEMS = [
  { key: 'eval', label: '模型质量', to: '/eval' },
  { key: 'settings', label: '配置', to: '/settings' },
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

  return (
    <>
      <header className="sc-topbar">
        <Link className="sc-brand" to="/" aria-label={`${PRODUCT_NAME}首页`}>
          <span className="sc-brand-mark" aria-hidden="true">↗</span>
          <span className="sc-brand-copy">
            <span className="sc-brand-name">{PRODUCT_NAME}</span>
            <span className="sc-brand-tagline">{PRODUCT_TAGLINE}</span>
          </span>
        </Link>
        <div className="sc-topbar-right">
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
          <Stepper steps={steps} orientation="vertical" />
          <ToolNav items={TOOL_ITEMS} />
          <ToolNav items={SETTINGS_ITEMS} label="设置" />
        </aside>
        <main className="sc-main">
          <div className="sc-topstepper">
            <Stepper steps={steps} orientation="horizontal" />
            {/* r21：<1024 侧栏 display:none，而 ToolNav 此前只渲染在侧栏内 —— 手机上
                「练习 / 成绩趋势 / 简历润色」三个工具页没有任何入口。这里复用同一份
                TOOL_ITEMS 渲染横向工具条（组件早已支持 orientation="horizontal"）；
                桌面由 `@media (min-width:1024px) { .sc-topstepper: display:none }` 隐藏本容器。 */}
            <ToolNav items={TOOL_ITEMS} orientation="horizontal" />
            <ToolNav items={SETTINGS_ITEMS} label="设置" orientation="horizontal" />
          </div>
          <div className="sc-page">
            <AiKeyModal />
            <Routes>
              <Route path="/" element={<UploadPage />} />
              <Route path="/profile" element={<ProfilePage />} />
              <Route path="/interview" element={<InterviewPage />} />
              <Route path="/exam" element={<ExamPage />} />
              <Route path="/report" element={<ReportPage />} />
              <Route path="/history" element={<HistoryPage />} />
              <Route path="/eval" element={<EvalPage />} />
              <Route path="/polish" element={<PolishPage />} />
              <Route path="/versions" element={<VersionsPage />} />
              <Route path="/practice" element={<PracticePage />} />
              <Route path="/learn" element={<LearnPage />} />
              <Route path="/learn/:chapterId" element={<TutorialPage />} />
              <Route path="/settings" element={<SettingsPage />} />
            </Routes>
          </div>
        </main>
      </div>
    </>
  )
}
