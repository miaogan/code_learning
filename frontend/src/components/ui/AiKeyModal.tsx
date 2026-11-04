import { useNavigate } from 'react-router-dom'
import { NoticeModal } from './NoticeModal'
import { dismissKeyRequired, useKeyRequired } from '../../state/aiGate'

/**
 * AI 能力未开启时的全局弹框（r23 P2 / r24 改为弹框）：任何 AI 端点返回 403
 * `AI_KEY_REQUIRED` 都由 api/client 上报到这里，因此不必在每个页面重复实现「去设置」入口。
 */
export function AiKeyModal() {
  const message = useKeyRequired()
  const navigate = useNavigate()
  return (
    <NoticeModal
      open={message !== null}
      title="需要配置 API Key"
      message={message ?? ''}
      primaryLabel="去设置"
      onPrimary={() => {
        dismissKeyRequired()
        navigate('/settings')
      }}
      onClose={dismissKeyRequired}
    />
  )
}
