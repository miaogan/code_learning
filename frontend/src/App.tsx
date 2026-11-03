import { Route, Routes, useLocation } from 'react-router-dom'
import { Stepper, type StepItem, type StepState } from './components/ui/Stepper'
import { ToolNav } from './components/ui/ToolNav'
import ExamPage from './pages/ExamPage'
import HistoryPage from './pages/HistoryPage'
import InterviewPage from './pages/InterviewPage'
import PolishPage from './pages/PolishPage'
import PracticePage from './pages/PracticePage'
import ProfilePage from './pages/ProfilePage'
import ReportPage from './pages/ReportPage'
import UploadPage from './pages/UploadPage'
import { useFlowState } from './state/flow'

const STEP_BASE = [
  { key: 'upload', label: '上传简历', to: '/' },
  { key: 'profile', label: '技术画像', to: '/profile' },
  { key: 'interview', label: '模拟面试', to: '/interview' },
  { key: 'exam', label: '模拟笔试', to: '/exam' },
  { key: 'report', label: '诊断报告', to: '/report' },
] as const

/** 侧栏「工具」组：非线性的能力出口，不混进步骤（DESIGN §1.1）。 */
const TOOL_ITEMS = [
  { key: 'practice', label: '练习', to: '/practice' },
  { key: 'history', label: '成绩趋势', to: '/history' },
  { key: 'polish', label: '简历润色', to: '/polish' },
]

/** 全局壳：顶栏 56 + 侧栏 240（<1024 收为顶部横向步骤条），主区 max 1080。 */
export default function App() {
  const { pathname } = useLocation()
  const flow = useFlowState()

  const isDone = (key: string): boolean => {
    if (key === 'upload') return flow.hasResume
    if (key === 'profile') return flow.hasProfile
    if (key === 'interview' || key === 'exam') return flow.hasProfile
    if (key === 'report') return flow.hasReport
    return false
  }

  const steps: StepItem[] = STEP_BASE.map((step) => {
    const state: StepState =
      pathname === step.to ? 'current' : isDone(step.key) ? 'done' : 'todo'
    return { key: step.key, label: step.label, to: step.to, state }
  })

  return (
    <>
      <header className="sc-topbar">
        <div className="sc-brand">
          <span className="sc-brand-mark" aria-hidden="true" />
          <span className="sc-brand-name">Skill Coach</span>
        </div>
        <span className="sc-storage">本地存储 · 数据只保存在这台机器</span>
      </header>

      <div className="sc-shell">
        <aside className="sc-sidebar">
          <Stepper steps={steps} orientation="vertical" />
          <ToolNav items={TOOL_ITEMS} />
        </aside>
        <main className="sc-main">
          <div className="sc-topstepper">
            <Stepper steps={steps} orientation="horizontal" />
            {/* r21：<1024 侧栏 display:none，而 ToolNav 此前只渲染在侧栏内 —— 手机上
                「练习 / 成绩趋势 / 简历润色」三个工具页没有任何入口。这里复用同一份
                TOOL_ITEMS 渲染横向工具条（组件早已支持 orientation="horizontal"）；
                桌面由 `@media (min-width:1024px) { .sc-topstepper: display:none }` 隐藏本容器。 */}
            <ToolNav items={TOOL_ITEMS} orientation="horizontal" />
          </div>
          <div className="sc-page">
            <Routes>
              <Route path="/" element={<UploadPage />} />
              <Route path="/profile" element={<ProfilePage />} />
              <Route path="/interview" element={<InterviewPage />} />
              <Route path="/exam" element={<ExamPage />} />
              <Route path="/report" element={<ReportPage />} />
              <Route path="/history" element={<HistoryPage />} />
              <Route path="/polish" element={<PolishPage />} />
              <Route path="/practice" element={<PracticePage />} />
            </Routes>
          </div>
        </main>
      </div>
    </>
  )
}
