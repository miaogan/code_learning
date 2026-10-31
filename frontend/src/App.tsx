import { Route, Routes, useLocation } from 'react-router-dom'
import { Stepper, type StepItem, type StepState } from './components/ui/Stepper'
import ExamPage from './pages/ExamPage'
import HistoryPage from './pages/HistoryPage'
import InterviewPage from './pages/InterviewPage'
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
        </aside>
        <main className="sc-main">
          <div className="sc-topstepper">
            <Stepper steps={steps} orientation="horizontal" />
          </div>
          <div className="sc-page">
            <Routes>
              <Route path="/" element={<UploadPage />} />
              <Route path="/profile" element={<ProfilePage />} />
              <Route path="/interview" element={<InterviewPage />} />
              <Route path="/exam" element={<ExamPage />} />
              <Route path="/report" element={<ReportPage />} />
              <Route path="/history" element={<HistoryPage />} />
            </Routes>
          </div>
        </main>
      </div>
    </>
  )
}
