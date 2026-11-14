import { describe, expect, it } from 'vitest'
import {
  AI_PROVIDER_PRESETS,
  CUSTOM_PROVIDER_ID,
  DEFAULT_PROVIDER_ID,
  initialProviderValues,
  normalizeBaseUrl,
  presetById,
  presetNoteOf,
  providerIdOf,
  providerLabelOf,
  providerOptions,
} from '../lib/aiProviders'

/**
 * BYOK 厂商预设的纯函数口径：只钉前端这一层填表助手的行为，
 * 后端契约（AiSettingsRequest 四件套）零改动，故这里没有 HTTP 断言。
 */
describe('AI 厂商预设', () => {
  it('默认就是 DeepSeek，且默认项真的存在于闭集里', () => {
    const preset = presetById(DEFAULT_PROVIDER_ID)
    expect(preset).not.toBeNull()
    const seed = initialProviderValues('', '')
    expect(seed.providerId).toBe('deepseek')
    expect(seed.baseUrl).toBe(preset?.baseUrl)
    expect(seed.model).toBe(preset?.model)
    expect(providerIdOf(seed.baseUrl)).toBe('deepseek')
  })

  it('已有配置一律原样保留，绝不因默认值被覆盖', () => {
    const seed = initialProviderValues('https://api.moonshot.cn/v1', 'kimi-k2.5')
    expect(seed).toEqual({
      providerId: 'moonshot',
      baseUrl: 'https://api.moonshot.cn/v1',
      model: 'kimi-k2.5',
    })
    const custom = initialProviderValues('https://api.example.test/v1', 'my-model')
    expect(custom.providerId).toBe(CUSTOM_PROVIDER_ID)
    expect(custom.baseUrl).toBe('https://api.example.test/v1')
    expect(custom.model).toBe('my-model')
  })

  it('地址为空但已有模型名时，只补 DeepSeek 地址，不覆盖模型名', () => {
    const seed = initialProviderValues('', 'my-model')
    expect(seed.providerId).toBe('deepseek')
    expect(seed.model).toBe('my-model')
    expect(seed.baseUrl).toBe(presetById('deepseek')?.baseUrl)
  })

  it('每个预设都能从自己的地址反查回来（含尾斜杠与大小写）', () => {
    for (const preset of AI_PROVIDER_PRESETS) {
      expect(providerIdOf(preset.baseUrl)).toBe(preset.id)
      expect(providerIdOf(`${preset.baseUrl}/`)).toBe(preset.id)
      expect(providerIdOf(`  ${preset.baseUrl.toUpperCase()}  `)).toBe(preset.id)
    }
  })

  it('认不出的地址与空地址都归到自定义', () => {
    expect(providerIdOf('https://api.example.test/v1')).toBe(CUSTOM_PROVIDER_ID)
    expect(providerIdOf('')).toBe(CUSTOM_PROVIDER_ID)
    expect(providerIdOf('   ')).toBe(CUSTOM_PROVIDER_ID)
    expect(normalizeBaseUrl('HTTPS://API.DeepSeek.COM/v1///')).toBe('https://api.deepseek.com/v1')
  })

  it('闭集字段完整且无重复，地址都是 https 前缀', () => {
    const ids = AI_PROVIDER_PRESETS.map((preset) => preset.id)
    const urls = AI_PROVIDER_PRESETS.map((preset) => normalizeBaseUrl(preset.baseUrl))
    expect(new Set(ids).size).toBe(ids.length)
    expect(new Set(urls).size).toBe(urls.length)
    for (const preset of AI_PROVIDER_PRESETS) {
      expect(preset.label).not.toBe('')
      expect(preset.model).not.toBe('')
      expect(preset.baseUrl).toMatch(/^https:\/\//)
      expect(preset.baseUrl.endsWith('/')).toBe(false)
    }
  })

  it('下拉选项首项 DeepSeek、末项自定义，且取值唯一', () => {
    const options = providerOptions()
    expect(options[0].value).toBe(DEFAULT_PROVIDER_ID)
    expect(options.at(-1)?.value).toBe(CUSTOM_PROVIDER_ID)
    expect(options).toHaveLength(AI_PROVIDER_PRESETS.length + 1)
    expect(new Set(options.map((option) => option.value)).size).toBe(options.length)
  })

  it('状态卡展示真实配置的厂商名，不带「（默认）」后缀', () => {
    expect(providerLabelOf('https://api.deepseek.com/v1')).toBe('DeepSeek')
    expect(providerLabelOf('https://api.moonshot.cn/v1')).toBe('月之暗面 Kimi')
    expect(providerLabelOf('https://api.example.test/v1')).toBe('自定义')
    expect(providerLabelOf('')).toBe('未配置')
  })

  it('自定义没有预设可取，只有个别厂商带填写提醒', () => {
    expect(presetById(CUSTOM_PROVIDER_ID)).toBeNull()
    expect(presetById('not-exist')).toBeNull()
    expect(presetNoteOf(CUSTOM_PROVIDER_ID)).toBe('')
    expect(presetNoteOf('ark')).toContain('ep-')
    expect(presetNoteOf('deepseek')).toBe('')
  })
})
