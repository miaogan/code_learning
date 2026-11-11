/** 重能力前置提示：模拟面试 / 诊断报告 / 简历润色消耗较大，内置 Key 只覆盖轻能力（画像生成）。
 *  在页头提前说明，避免用户点按钮后才被 403 与「需要配置 API Key」弹框拦下。 */
import { Link } from 'react-router-dom'
import { useAuth } from '../../state/auth'

export function AiHeavyNotice() {
  const { me } = useAuth()
  if (me === null || me.ai_capability === 'full') return null
  const text =
    me.ai_capability === 'none'
      ? '尚未配置 AI 服务：模拟面试、诊断报告、修文暂时不可用。'
      : '当前使用内置 AI 额度：模拟面试、诊断报告、修文需要你自己的 API Key。'
  return (
    <p className="sc-ai-notice" role="status">
      <span>{text}</span>
      <Link to="/settings">去设置填写</Link>
    </p>
  )
}
