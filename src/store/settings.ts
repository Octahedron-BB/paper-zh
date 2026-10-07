import { reactive, watch } from 'vue'
import type { Settings } from '../core/types'

const STORAGE_KEY = 'paper_zh_user_settings'

const defaultSettings: Settings = {
  llmProvider: 'deepseek',
  apiKey: '',
  model: 'deepseek-chat',
  customBaseUrl: '',
  enableTts: true,
  ttsProvider: 'edge-tts',
  ttsVoice: 'zh-TW-HsiaoChenNeural',
  ttsRate: '+0%',
  academicProxyUrl: '',
  academicProxyCookie: '',
  edgeTtsProxyUrl: '',
  siliconflowApiKey: '',
  siliconflowModel: 'FunAudioLLM/CosyVoice2-0.5B',
  customTtsApiKey: '',
  customTtsModel: '',
}

function loadSettings(): Settings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) {
      return { ...defaultSettings, ...JSON.parse(raw) }
    }
  } catch (e) {
    console.error('加载本地设置失败:', e)
  }
  return { ...defaultSettings }
}

export const settingsState = reactive<Settings>(loadSettings())

watch(
  settingsState,
  (newVal) => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(newVal))
    } catch (e) {
      console.error('保存设置失败:', e)
    }
  },
  { deep: true }
)
