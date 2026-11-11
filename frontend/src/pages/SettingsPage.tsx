import { useState } from 'react'
import type { FormEvent } from 'react'
import { ApiError, api } from '../api/client'
import type { AiCapability, JsonMode, KeyMode } from '../api/types'
import { Button } from '../components/ui/Button'
import { Card } from '../components/ui/Card'
import { ConfirmModal } from '../components/ui/ConfirmModal'
import { InlineError } from '../components/ui/InlineError'
import { applyMe, useAuth } from '../state/auth'
import { dismissKeyRequired } from '../state/aiGate'

const CAPABILITY_TEXT: Record<AiCapability, string> = {
  full: '全部 AI 能力可用（含召对、医案等高消耗场景）',
  light: '仅画像生成与润色建议可用；高消耗场景需配置自己的 Key',
  none: 'AI 能力不可用，请配置自己的 Key 或联系管理员开通内置 Key',
}

const KEY_MODE_TEXT: Record<KeyMode, string> = {
  own: '自带 Key（不受内置 Key 的能力分级与每日配额限制）',
  shared: '内置 Key（管理员同意，仅 light 能力 + 每日配额）',
}

/**
 * r23 设置页：AI Key 配置（测试连接 / 保存）与密码修改。
 * 保存 Key 后端只回 `****后4位`，明文不落前端状态、也不进任何日志。
 */
export default function SettingsPage() {
  const { me } = useAuth()
  const [baseUrl, setBaseUrl] = useState(me?.ai_base_url ?? '')
  const [model, setModel] = useState(me?.ai_model ?? '')
  const [apiKey, setApiKey] = useState('')
  const [jsonMode, setJsonMode] = useState<JsonMode>(me?.ai_json_mode ?? 'json_object')
  const [aiBusy, setAiBusy] = useState<'test' | 'save' | 'clear' | null>(null)
  const [aiError, setAiError] = useState<string | null>(null)
  const [aiNotice, setAiNotice] = useState<string | null>(null)
  /** 清除 Key 先确认：这个动作会让所有 AI 能力立刻不可用。 */
  const [clearOpen, setClearOpen] = useState(false)

  const [oldPassword, setOldPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [pwdBusy, setPwdBusy] = useState(false)
  const [pwdError, setPwdError] = useState<string | null>(null)
  const [pwdNotice, setPwdNotice] = useState<string | null>(null)

  if (me === null) return null

  const aiPayload = {
    base_url: baseUrl.trim(),
    model: model.trim(),
    api_key: apiKey.trim(),
    json_mode: jsonMode,
  }

  const testConnection = async () => {
    if (aiBusy !== null) return
    setAiBusy('test')
    setAiError(null)
    setAiNotice(null)
    try {
      const result = await api.testAiSettings(aiPayload)
      if (result.ok) setAiNotice(result.message)
      else setAiError(result.message)
    } catch (err) {
      setAiError(err instanceof ApiError ? err.message : '测试失败，请稍后重试')
    } finally {
      setAiBusy(null)
    }
  }

  const saveAi = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (aiBusy !== null) return
    setAiBusy('save')
    setAiError(null)
    setAiNotice(null)
    try {
      const updated = await api.saveAiSettings(aiPayload)
      applyMe(updated)
      setApiKey('')
      setAiNotice('已保存。之后的可视 Key 为 ' + updated.ai_masked_key)
      // 能力已恢复时收起壳层的「去设置」提示。
      dismissKeyRequired()
    } catch (err) {
      setAiError(err instanceof ApiError ? err.message : '保存失败，请稍后重试')
    } finally {
      setAiBusy(null)
    }
  }

  const clearKey = async () => {
    if (aiBusy !== null) return
    setAiBusy('clear')
    setAiError(null)
    setAiNotice(null)
    try {
      const updated = await api.clearAiSettings()
      applyMe(updated)
      setApiKey('')
      setAiNotice('已清除保存的 Key，AI 能力随之关闭。')
      dismissKeyRequired()
    } catch (err) {
      setAiError(err instanceof ApiError ? err.message : '清除失败，请稍后重试')
    } finally {
      setAiBusy(null)
    }
  }

  const changePassword = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (pwdBusy) return
    setPwdBusy(true)
    setPwdError(null)
    setPwdNotice(null)
    try {
      await api.changePassword({ old_password: oldPassword, new_password: newPassword })
      setOldPassword('')
      setNewPassword('')
      setPwdNotice('密码已更新，下次登录使用新密码')
    } catch (err) {
      setPwdError(err instanceof ApiError ? err.message : '修改失败，请稍后重试')
    } finally {
      setPwdBusy(false)
    }
  }

  return (
    <section>
      <header className="sc-page-header">
        <h1 className="sc-page-title">典制</h1>
        <p className="sc-page-sub">
          {me.display_name} · {me.email} · 账号与 AI 服务
        </p>
      </header>

      <div className="sc-settings-grid">
        <Card>
          <h2 className="sc-settings-title">当前状态</h2>
          <dl className="sc-kv">
            <dt>AI 能力</dt>
            <dd>{CAPABILITY_TEXT[me.ai_capability]}</dd>
            <dt>Key 来源</dt>
            <dd>{KEY_MODE_TEXT[me.key_mode]}</dd>
            <dt>当前 Key</dt>
            <dd className="sc-mono">{me.ai_masked_key || '未配置'}</dd>
            {me.key_mode === 'shared' ? (
              <>
                <dt>今日额度</dt>
                <dd>
                  {me.ai_quota_limit > 0
                    ? `${me.ai_quota_used} / ${me.ai_quota_limit} 次`
                    : '不限次数'}
                </dd>
              </>
            ) : null}
            {me.ai_updated_at ? (
              <>
                <dt>更新时间</dt>
                <dd>{me.ai_updated_at.replace('T', ' ').slice(0, 19)}</dd>
              </>
            ) : null}
          </dl>
          {me.key_mode === 'shared' ? (
            <p className="sc-settings-hint">
              内置 Key 仅开放画像生成与润色建议，并有每日次数上限；召对、医案等高消耗场景请配置自己的
              Key（保存后自动切到自带 Key）。
            </p>
          ) : null}
        </Card>

        <Card>
          <h2 className="sc-settings-title">我的 AI Key</h2>
          <form className="sc-form" onSubmit={saveAi}>
            <label className="sc-field">
              <span className="sc-field-label">Base URL</span>
              <input
                type="url"
                value={baseUrl}
                disabled={aiBusy !== null}
                onChange={(event) => setBaseUrl(event.target.value)}
                placeholder="https://api.example.com/v1"
              />
            </label>
            <label className="sc-field">
              <span className="sc-field-label">模型</span>
              <input
                type="text"
                value={model}
                disabled={aiBusy !== null}
                onChange={(event) => setModel(event.target.value)}
                placeholder="例如 gpt-4o-mini"
              />
            </label>
            <label className="sc-field">
              <span className="sc-field-label">API Key</span>
              <input
                type="password"
                autoComplete="off"
                value={apiKey}
                disabled={aiBusy !== null}
                onChange={(event) => setApiKey(event.target.value)}
                placeholder={me.ai_masked_key ? `留空沿用 ${me.ai_masked_key}` : '粘贴你的 API Key'}
              />
              <span className="sc-field-hint">
                密钥只加密保存在本机数据库，页面与接口都只回显后 4 位。
              </span>
            </label>
            <label className="sc-field">
              <span className="sc-field-label">JSON 模式</span>
              <select
                value={jsonMode}
                disabled={aiBusy !== null}
                onChange={(event) => setJsonMode(event.target.value as JsonMode)}
              >
                <option value="json_object">json_object（要求模型支持 JSON 输出）</option>
                <option value="none">none（纯文本模型，解析更宽松）</option>
              </select>
            </label>
            {aiError !== null ? <InlineError message={aiError} /> : null}
            {aiNotice !== null ? <p className="sc-settings-ok">{aiNotice}</p> : null}
            <div className="sc-btn-row">
              <Button type="button" variant="secondary" loading={aiBusy === 'test'} onClick={testConnection}>
                测试连接
              </Button>
              <Button type="submit" loading={aiBusy === 'save'}>
                保存
              </Button>
              <Button
                type="button"
                variant="ghost"
                disabled={!me.ai_masked_key || aiBusy !== null}
                loading={aiBusy === 'clear'}
                onClick={() => setClearOpen(true)}
              >
                清除已保存的 Key
              </Button>
            </div>
          </form>
        </Card>

        <Card>
          <h2 className="sc-settings-title">修改密码</h2>
          <form className="sc-form" onSubmit={changePassword}>
            <label className="sc-field">
              <span className="sc-field-label">当前密码</span>
              <input
                type="password"
                autoComplete="current-password"
                required
                value={oldPassword}
                disabled={pwdBusy}
                onChange={(event) => setOldPassword(event.target.value)}
              />
            </label>
            <label className="sc-field">
              <span className="sc-field-label">新密码</span>
              <input
                type="password"
                autoComplete="new-password"
                required
                value={newPassword}
                disabled={pwdBusy}
                onChange={(event) => setNewPassword(event.target.value)}
                placeholder="8–72 位"
              />
            </label>
            {pwdError !== null ? <InlineError message={pwdError} /> : null}
            {pwdNotice !== null ? <p className="sc-settings-ok">{pwdNotice}</p> : null}
            <div className="sc-btn-row">
              <Button type="submit" loading={pwdBusy}>
                更新密码
              </Button>
            </div>
          </form>
        </Card>
      </div>

      <ConfirmModal
        open={clearOpen}
        title="清除已保存的 Key"
        message="清除后 AI 能力会立即关闭：画像生成、召对、医案等都需要重新配置 Key 才能使用。"
        confirmLabel="清除 Key"
        cancelLabel="保留"
        onConfirm={() => {
          setClearOpen(false)
          void clearKey()
        }}
        onCancel={() => setClearOpen(false)}
      />
    </section>
  )
}
