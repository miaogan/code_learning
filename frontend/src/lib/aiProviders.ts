/**
 * 用户自带 Key（BYOK）的国内模型服务商预设 —— 前端单点真源。
 *
 * 边界：这只是一层「填表助手」。选中厂商后把该厂商的 OpenAI 兼容地址与常用模型名
 * 写进表单，HTTP 契约仍是 `AiSettingsRequest` 的 base_url / model / api_key / json_mode
 * 四件套，后端不感知「厂商」这个概念，也不新增字段或新增闭集。
 *
 * 端点来自各厂商公开的 OpenAI 兼容文档（2026-11 核对）；模型名迭代很快，预设给的只是
 * 「当下常用值」，两个输入框始终可编辑，用户以厂商控制台的可用模型为准。
 */

export interface AiProviderPreset {
  id: string
  label: string
  /** 不含尾斜杠；后端会自行拼 `/chat/completions`。 */
  baseUrl: string
  /** 推荐默认模型名，可改。 */
  model: string
  /** 该厂商特有的填写提醒。 */
  note?: string
}

export const DEFAULT_PROVIDER_ID = 'deepseek'
export const CUSTOM_PROVIDER_ID = 'custom'

export const AI_PROVIDER_PRESETS: readonly AiProviderPreset[] = [
  {
    id: 'deepseek',
    label: 'DeepSeek（默认）',
    baseUrl: 'https://api.deepseek.com/v1',
    model: 'deepseek-flash',
  },
  {
    id: 'bailian',
    label: '阿里云百炼 · 通义千问',
    baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    model: 'qwen-plus',
  },
  {
    id: 'zhipu',
    label: '智谱 GLM',
    baseUrl: 'https://open.bigmodel.cn/api/paas/v4',
    model: 'glm-4.6',
  },
  {
    id: 'moonshot',
    label: '月之暗面 Kimi',
    baseUrl: 'https://api.moonshot.cn/v1',
    model: 'moonshot-v1-8k',
  },
  {
    id: 'qianfan',
    label: '百度千帆 · 文心',
    baseUrl: 'https://qianfan.baidubce.com/v2',
    model: 'ernie-4.0-turbo-8k',
  },
  {
    id: 'ark',
    label: '火山方舟 · 豆包',
    baseUrl: 'https://ark.cn-beijing.volces.com/api/v3',
    model: 'doubao-seed-1-6-250615',
    note: '火山方舟通常需要在控制台创建推理接入点，模型名建议改成 ep- 开头的接入点 ID。',
  },
  {
    id: 'hunyuan',
    label: '腾讯混元',
    baseUrl: 'https://api.hunyuan.cloud.tencent.com/v1',
    model: 'hunyuan-turbo',
  },
  {
    id: 'minimax',
    label: 'MiniMax',
    baseUrl: 'https://api.minimaxi.com/v1',
    model: 'MiniMax-M2',
  },
]

/** 与 `components/ui/Select` 的 `SelectOption` 结构一致，避免 lib 反向依赖 UI 组件。 */
export interface AiProviderOption {
  value: string
  label: string
}

/** 只做「去空白 / 去尾斜杠 / 转小写」的比较归一，不改用户实际提交的值。 */
export function normalizeBaseUrl(baseUrl: string): string {
  return baseUrl.trim().replace(/\/+$/, '').toLowerCase()
}

export function presetById(id: string): AiProviderPreset | null {
  if (id === CUSTOM_PROVIDER_ID) return null
  return AI_PROVIDER_PRESETS.find((preset) => preset.id === id) ?? null
}

/** 已有配置反查厂商：地址逐字命中才认，命中不了就是自定义（绝不猜）。 */
export function providerIdOf(baseUrl: string): string {
  const normalized = normalizeBaseUrl(baseUrl)
  if (!normalized) return CUSTOM_PROVIDER_ID
  return (
    AI_PROVIDER_PRESETS.find((preset) => normalizeBaseUrl(preset.baseUrl) === normalized)?.id ??
    CUSTOM_PROVIDER_ID
  )
}

export function presetNoteOf(id: string): string {
  return presetById(id)?.note ?? ''
}

/** 「当前状态」卡片展示真实配置：已存地址命中哪家就说哪家，认不出就说自定义。 */
export function providerLabelOf(baseUrl: string): string {
  if (!baseUrl.trim()) return '未配置'
  const preset = presetById(providerIdOf(baseUrl))
  if (preset === null) return '自定义'
  return preset.label.replace('（默认）', '')
}

export function providerOptions(): AiProviderOption[] {
  return [
    ...AI_PROVIDER_PRESETS.map((preset) => ({ value: preset.id, label: preset.label })),
    { value: CUSTOM_PROVIDER_ID, label: '自定义（自行填写地址与模型）' },
  ]
}

export interface ProviderFormSeed {
  providerId: string
  baseUrl: string
  model: string
}

/**
 * 进入设置页时的初值：已有配置一律原样保留；从未配过才落 DeepSeek 预设。
 * 这样「默认 DeepSeek」只是空态的填充值，不会覆盖任何已保存的地址或模型。
 */
export function initialProviderValues(baseUrl: string, model: string): ProviderFormSeed {
  const savedBaseUrl = baseUrl.trim()
  const savedModel = model.trim()
  if (savedBaseUrl) {
    return { providerId: providerIdOf(savedBaseUrl), baseUrl: savedBaseUrl, model: savedModel }
  }
  const preset = presetById(DEFAULT_PROVIDER_ID)
  if (preset === null) {
    return { providerId: CUSTOM_PROVIDER_ID, baseUrl: '', model: savedModel }
  }
  return { providerId: preset.id, baseUrl: preset.baseUrl, model: savedModel || preset.model }
}
