import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { ApiError, api } from '../api/client'
import type { AiCapability, JsonMode, KeyMode } from '../api/types'
import { Button } from '../components/ui/Button'
import { Card } from '../components/ui/Card'
import { ConfirmModal } from '../components/ui/ConfirmModal'
import { InlineError } from '../components/ui/InlineError'
import { Select } from '../components/ui/Select'
import {
  CUSTOM_PROVIDER_ID,
  initialProviderValues,
  presetById,
  presetNoteOf,
  providerIdOf,
  providerLabelOf,
  providerOptions,
} from '../lib/aiProviders'
import { applyMe, useAuth } from '../state/auth'
import { dismissKeyRequired } from '../state/aiGate'

const PROVIDER_OPTIONS = providerOptions()

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
  // 空配置默认 DeepSeek；已有配置原样保留，并按地址反查它属于哪家（认不出就是自定义）。
  const [seed] = useState(() =>
    initialProviderValues(me?.ai_base_url ?? '', me?.ai_model ?? ''),
  )
  const [providerId, setProviderId] = useState(seed.providerId)
  const [baseUrl, setBaseUrl] = useState(seed.baseUrl)
  const [model, setModel] = useState(seed.model)
  const [apiKey, setApiKey] = useState('')
  const [jsonMode, setJsonMode] = useState<JsonMode>(me?.ai_json_mode ?? 'json_object')
  /** 登录态可能晚于首屏到达：只补一次真实配置，之后绝不覆盖用户正在编辑的表单。 */
  const synced = useRef(false)
  useEffect(() => {
    if (me === null || synced.current) return
    synced.current = true
    const next = initialProviderValues(me.ai_base_url, me.ai_model)
    setProviderId(next.providerId)
    setBaseUrl(next.baseUrl)
    setModel(next.model)
    setJsonMode(me.ai_json_mode || 'json_object')
  }, [me])
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

  /** 选厂商＝填入该厂商的地址与常用模型；选「自定义」只保留现值，不擅自清空。 */
  const changeProvider = (next: string) => {
    setProviderId(next)
    setAiError(null)
    setAiNotice(null)
    if (next === CUSTOM_PROVIDER_ID) return
    const preset = presetById(next)
    if (preset === null) return
    setBaseUrl(preset.baseUrl)
    setModel(preset.model)
  }

  /** 手改地址后让下拉如实反映：命中预设就显示该厂商，否则回落到「自定义」。 */
  const changeBaseUrl = (next: string) => {
    setBaseUrl(next)
    setProviderId(providerIdOf(next))
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
            {me.ai_base_url ? (
              <>
                <dt>服务商</dt>
                <dd>{providerLabelOf(me.ai_base_url)}</dd>
              </>
            ) : null}
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
              <span className="sc-field-label">模型服务商</span>
              <Select
                ariaLabel="模型服务商"
                value={providerId}
                options={PROVIDER_OPTIONS}
                disabled={aiBusy !== null}
                onChange={changeProvider}
              />
              <span className="sc-field-hint">
                默认 DeepSeek。选中后自动填入该厂商的 API 地址与常用模型，两项都能手动改；
                厂商提供的模型名更新较快，请以控制台为准。Key 需到所选厂商的控制台申请。
              </span>
            </label>
            <label className="sc-field">
              <span className="sc-field-label">Base URL</span>
              <input
                type="url"
                value={baseUrl}
                disabled={aiBusy !== null}
                onChange={(event) => changeBaseUrl(event.target.value)}
                placeholder="https://api.deepseek.com/v1"
              />
              <span className="sc-field-hint">
                须为该厂商的 OpenAI 兼容地址（服务端会自动补 /chat/completions）；自己填地址时下拉会显示「自定义」。
              </span>
            </label>
            <label className="sc-field">
              <span className="sc-field-label">模型</span>
              <input
                type="text"
                value={model}
                disabled={aiBusy !== null}
                onChange={(event) => setModel(event.target.value)}
                placeholder="例如 deepseek-flash"
              />
            </label>
            {presetNoteOf(providerId) !== '' ? (
              <p className="sc-field-hint">{presetNoteOf(providerId)}</p>
            ) : null}
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
              <Select
                ariaLabel="JSON 模式"
                value={jsonMode}
                disabled={aiBusy !== null}
                options={[
                  { value: 'json_object', label: 'json_object（要求模型支持 JSON 输出）' },
                  { value: 'none', label: 'none（纯文本模型，解析更宽松）' },
                ]}
                onChange={(value) => setJsonMode(value as JsonMode)}
              />
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
