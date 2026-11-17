import { reactive } from 'vue'
import type { Settings } from '../core/types'

const STORAGE_KEY = 'paper_zh_user_settings'

const defaultSettings: Settings = {
  llmProvider: 'deepseek',
  apiKey: '',
  apiKeys: {
    deepseek: '',
    openai: '',
    gemini: '',
    custom: '',
  },
  model: 'deepseek-chat',
  models: {
    deepseek: 'deepseek-chat',
    openai: 'gpt-4o-mini',
    gemini: 'gemini-3.5-flash-lite',
    custom: '',
  },
  customBaseUrl: '',
  enableTts: true,
  ttsProvider: 'edge-tts',
  ttsVoice: 'zh-TW-HsiaoChenNeural',
  ttsRate: '+0%',
  academicProxyUrl: '',
  academicProxyCookie: '',
  edgeTtsProxyUrl: 'https://edge-tts-proxy.ryoctahedron1998.workers.dev/api/edge-tts',
  geminiProxyUrl: 'https://edge-tts-proxy.ryoctahedron1998.workers.dev/api/gemini',
  siliconflowApiKey: '',
  siliconflowModel: 'FunAudioLLM/CosyVoice2-0.5B',
  customTtsApiKey: '',
  customTtsModel: '',
}

function loadSettings(): Settings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) {
      const parsed = JSON.parse(raw)
      if (!parsed.edgeTtsProxyUrl) {
        parsed.edgeTtsProxyUrl = defaultSettings.edgeTtsProxyUrl
      }
      if (!parsed.geminiProxyUrl) {
        parsed.geminiProxyUrl = defaultSettings.geminiProxyUrl
      }

      // 迁移旧版单一 apiKey 到独立 apiKeys
      const apiKeys = { ...defaultSettings.apiKeys, ...(parsed.apiKeys || {}) }
      if (parsed.apiKey && parsed.llmProvider && !apiKeys[parsed.llmProvider]) {
        apiKeys[parsed.llmProvider] = parsed.apiKey
      }

      // 迁移各模型记录
      const models = { ...defaultSettings.models, ...(parsed.models || {}) }
      if (parsed.model && parsed.llmProvider && !models[parsed.llmProvider]) {
        models[parsed.llmProvider] = parsed.model
      }

      return {
        ...defaultSettings,
        ...parsed,
        apiKeys,
        models,
      }
    }
  } catch (e) {
    console.error('加载本地设置失败:', e)
  }
  return { ...defaultSettings }
}

export const settingsState = reactive<Settings>(loadSettings())

/**
 * 手动显式保存设置到 localStorage 并同步更新状态
 */
export function saveSettings(newSettings: Settings): void {
  // 同步主 apiKey 与 model 保证向后兼容
  const provider = newSettings.llmProvider
  newSettings.apiKey = newSettings.apiKeys?.[provider] || ''
  newSettings.model = newSettings.models?.[provider] || newSettings.model || ''

  Object.assign(settingsState, JSON.parse(JSON.stringify(newSettings)))
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(settingsState))
  } catch (e) {
    console.error('保存设置到 localStorage 失败:', e)
  }
}
