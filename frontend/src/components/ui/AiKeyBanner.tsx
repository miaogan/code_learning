import { useNavigate } from 'react-router-dom'
import { Button } from './Button'
import { dismissKeyRequired, useKeyRequired } from '../../state/aiGate'

/**
 * AI 能力未开启时的全局提示条（r23 P2）：任何 AI 端点返回 403 `AI_KEY_REQUIRED`
 * 都由 api/client 上报到这里，因此不必在每个页面重复实现「去设置」入口。
 */
export function AiKeyBanner() {
  const message = useKeyRequired()
  const navigate = useNavigate()
  if (message === null) return null
  return (
    <div className="sc-inline-error" role="alert">
      <span aria-hidden="true">!</span>
      <span className="sc-inline-error-msg">{message}</span>
      <Button
        variant="secondary"
        size="sm"
        onClick={() => {
          dismissKeyRequired()
          navigate('/settings')
        }}
      >
        去设置
      </Button>
      <Button variant="ghost" size="sm" onClick={dismissKeyRequired}>
        知道了
      </Button>
    </div>
  )
}
