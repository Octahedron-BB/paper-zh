<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { settingsState, saveSettings } from '../store/settings'
import type { TtsProvider, LlmProvider, Settings } from '../core/types'
import { synthesizeEdgeTts } from '../core/edgeTts'
import { synthesizeSiliconFlowTts } from '../core/siliconflowTts'
import { fetchAvailableModels, type FetchedModel } from '../core/modelFetcher'
import {
  KeyRound,
  Sparkles,
  Volume2,
  ShieldCheck,
  X,
  VolumeX,
  ExternalLink,
  Check,
  AlertTriangle,
  RefreshCw,
  Loader2,
} from 'lucide-vue-next'

const emit = defineEmits<{
  (e: 'close'): void
}>()

// 创建独立可编辑的 draft 副本，只有用户点击「保存设置」时才写入 localStorage
const draft = ref<Settings>(JSON.parse(JSON.stringify(settingsState)))

// 确保嵌套对象完整存在
if (!draft.value.apiKeys) {
  draft.value.apiKeys = { deepseek: '', openai: '', gemini: '', custom: '' }
}
if (!draft.value.models) {
  draft.value.models = {
    deepseek: 'deepseek-chat',
    openai: 'gpt-4o-mini',
    gemini: 'gemini-1.5-flash',
    custom: '',
  }
}

// 检查是否有未保存的改动
const isDirty = computed(() => {
  return JSON.stringify(draft.value) !== JSON.stringify(settingsState)
})

const showApiKey = ref(false)
const showSiliconflowKey = ref(false)
const isTestingVoice = ref(false)
const testAudioEl = ref<HTMLAudioElement | null>(null)

// 各主流厂商推荐模型列表预设
const modelPresets: Record<LlmProvider, string[]> = {
  deepseek: [
    'deepseek-chat',
    'deepseek-reasoner',
  ],
  openai: [
    'gpt-4o-mini',
    'gpt-4o',
    'o3-mini',
    'gpt-4.5-preview',
  ],
  gemini: [
    'gemini-1.5-flash',
    'gemini-2.0-flash',
    'gemini-1.5-pro',
    'gemini-2.0-pro-exp',
  ],
  custom: [
    'qwen2.5:7b',
    'llama3.3:70b',
    'deepseek-r1:7b',
  ],
}

// 动态从服务商获取的模型列表缓存
const fetchedModelsMap = ref<Record<LlmProvider, FetchedModel[]>>({
  deepseek: [],
  openai: [],
  gemini: [],
  custom: [],
})

const isFetchingModels = ref(false)
const fetchModelError = ref<string | null>(null)
const fetchModelSuccess = ref<string | null>(null)

// 组合可用的模型列表：优先使用在线获取到的模型，否则使用内置静态推荐预设
const combinedModelOptions = computed<Array<{ id: string; label: string }>>(() => {
  const provider = draft.value.llmProvider
  const online = fetchedModelsMap.value[provider] || []
  if (online.length > 0) {
    return online.map((m) => ({
      id: m.id,
      label: m.name || m.id,
    }))
  }
  const presets = modelPresets[provider] || []
  return presets.map((id) => ({
    id,
    label: `${id} ${id.includes('flash') || id.includes('mini') || id.includes('chat') ? '（推荐 · 极速高性价比）' : '（高推理能力）'}`,
  }))
})

// 模型选择器模式：如果是预设/获取列表中某一个，或是自定义输入
const isCustomModel = ref(false)

// 当前服务商绑定的模型名称
const activeModelValue = computed({
  get: () => {
    return draft.value.models?.[draft.value.llmProvider] || ''
  },
  set: (val: string) => {
    if (!draft.value.models) draft.value.models = {} as any
    draft.value.models[draft.value.llmProvider] = val
    draft.value.model = val
  },
})

// 下拉选框的值（若不在当前列表中则显示 custom）
const selectModelChoice = computed({
  get: () => {
    const cur = activeModelValue.value
    const exists = combinedModelOptions.value.some((o) => o.id === cur)
    if (exists) {
      return cur
    }
    return '__custom__'
  },
  set: (val: string) => {
    if (val === '__custom__') {
      isCustomModel.value = true
    } else {
      isCustomModel.value = false
      activeModelValue.value = val
    }
  },
})

// 初始化时如果不在预设中，激活自定义输入框
if (!combinedModelOptions.value.some((o) => o.id === activeModelValue.value) && activeModelValue.value) {
  isCustomModel.value = true
}

async function handleFetchOnlineModels() {
  const provider = draft.value.llmProvider
  const key = draft.value.apiKeys[provider] || ''
  isFetchingModels.value = true
  fetchModelError.value = null
  fetchModelSuccess.value = null

  try {
    const models = await fetchAvailableModels(provider, key, {
      customBaseUrl: draft.value.customBaseUrl,
      geminiProxyUrl: draft.value.geminiProxyUrl,
    })

    if (!models || models.length === 0) {
      throw new Error('未检索到可用模型')
    }

    fetchedModelsMap.value[provider] = models
    fetchModelSuccess.value = `成功获取 ${models.length} 个可用模型！`
    setTimeout(() => { fetchModelSuccess.value = null }, 3500)

    // 如果当前选中的模型不在新拉取的列表中，默认选中拉取到的第一个模型
    if (!models.some((m) => m.id === activeModelValue.value)) {
      activeModelValue.value = models[0].id
      isCustomModel.value = false
    }
  } catch (err: any) {
    fetchModelError.value = err.message || '获取模型列表失败'
  } finally {
    isFetchingModels.value = false
  }
}

function handleSelectProvider(provider: LlmProvider) {
  draft.value.llmProvider = provider
  fetchModelError.value = null
  fetchModelSuccess.value = null
  const curModel = draft.value.models?.[provider] || ''
  const available = combinedModelOptions.value
  if (curModel && !available.some((o) => o.id === curModel)) {
    isCustomModel.value = true
  } else {
    isCustomModel.value = false
    if (!curModel && available.length > 0) {
      if (!draft.value.models) draft.value.models = {} as any
      draft.value.models[provider] = available[0].id
      draft.value.model = available[0].id
    }
  }
}


const ttsProviders: Array<{
  id: TtsProvider
  name: string
  badge: string
  badgeColor: string
  desc: string
}> = [
  {
    id: 'siliconflow',
    name: '硅基流动 (CosyVoice 2 / 阿里通义)',
    badge: '✨ 强烈推荐 · 免反代直连',
    badgeColor: 'bg-indigo-100 text-indigo-800 dark:bg-indigo-950 dark:text-indigo-300 font-semibold',
    desc: '阿里顶尖开源语音大模型（带呼吸声与真实起伏），支持浏览器跨域直连。',
  },
  {
    id: 'edge-tts',
    name: 'Microsoft Edge-TTS / 系统精选',
    badge: '高清神经音色 · 本地开箱即用',
    badgeColor: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300',
    desc: '高质量真人流利人声，台湾晓臻、中国晓晓等。本地直接使用；静态网页配有内置安全反代。',
  },
  {
    id: 'web-speech',
    name: '浏览器原生 Speech API',
    badge: '完全离线 · 零流量',
    badgeColor: 'bg-blue-100 text-blue-800 dark:bg-blue-950 dark:text-blue-300',
    desc: '直接调用操作系统（macOS/Windows/iOS/Android）自带朗读引擎，无需网络。',
  },
  {
    id: 'none',
    name: '纯文本伴读 (无语音)',
    badge: '极速',
    badgeColor: 'bg-slate-100 text-slate-800 dark:bg-slate-800 dark:text-slate-300',
    desc: '跳过语音合成阶段，仅生成中英对照与口语讲稿。',
  },
]

const edgePresetVoices = [
  { id: 'zh-TW-HsiaoChenNeural', name: '微软 · 晓臻 (台湾腔 · 亲切自然 · 推荐)', lang: 'zh-TW' },
  { id: 'zh-CN-XiaoxiaoNeural', name: '微软 · 晓晓 (中国 · 清晰生动)', lang: 'zh-CN' },
  { id: 'zh-CN-YunxiNeural', name: '微软 · 云希 (中国 · 阳光男声)', lang: 'zh-CN' },
  { id: 'zh-CN-YunjianNeural', name: '微软 · 云健 (中国 · 沉稳叙事)', lang: 'zh-CN' },
  { id: 'zh-HK-HiuGaaiNeural', name: '微软 · 晓佳 (香港 · 粤语温柔)', lang: 'zh-HK' },
]

const cosyPresetVoices = [
  { id: 'cosyvoice-longxiaochun', name: 'CosyVoice · 龙小淳 (女声叙事 · 预留)', lang: 'zh-CN' },
  { id: 'cosyvoice-longxiaobai', name: 'CosyVoice · 龙小白 (沉稳男声 · 预留)', lang: 'zh-CN' },
]

const siliconflowPresetVoices = [
  { id: 'FunAudioLLM/CosyVoice2-0.5B:alex', name: 'CosyVoice 2 · Alex (男声 · 沉稳学者 · 推荐)', lang: 'zh-CN' },
  { id: 'FunAudioLLM/CosyVoice2-0.5B:benjamin', name: 'CosyVoice 2 · Benjamin (男声 · 低沉磁性)', lang: 'zh-CN' },
  { id: 'FunAudioLLM/CosyVoice2-0.5B:charles', name: 'CosyVoice 2 · Charles (男声 · 深情播报)', lang: 'zh-CN' },
  { id: 'FunAudioLLM/CosyVoice2-0.5B:david', name: 'CosyVoice 2 · David (男声 · 明朗阳光)', lang: 'zh-CN' },
  { id: 'FunAudioLLM/CosyVoice2-0.5B:anna', name: 'CosyVoice 2 · Anna (女声 · 沉稳专业 · 推荐)', lang: 'zh-CN' },
  { id: 'FunAudioLLM/CosyVoice2-0.5B:bella', name: 'CosyVoice 2 · Bella (女声 · 热情生动)', lang: 'zh-CN' },
  { id: 'FunAudioLLM/CosyVoice2-0.5B:claire', name: 'CosyVoice 2 · Claire (女声 · 温柔知性)', lang: 'zh-CN' },
  { id: 'FunAudioLLM/CosyVoice2-0.5B:diana', name: 'CosyVoice 2 · Diana (女声 · 清晰明亮)', lang: 'zh-CN' },
]

const systemVoices = ref<{ id: string; name: string; lang: string }[]>([])

function populateVoices() {
  if (!('speechSynthesis' in window)) return
  const sysVoices = window.speechSynthesis.getVoices()
  if (sysVoices.length > 0) {
    const zhVoices = sysVoices.filter((v) => v.lang.toLowerCase().includes('zh') || v.lang.toLowerCase().includes('cmn'))
    const list = zhVoices.length > 0 ? zhVoices : sysVoices
    systemVoices.value = list.map((v) => ({
      id: v.name,
      name: `系统原生 · ${v.name} (${v.lang})`,
      lang: v.lang,
    }))
  }
}

interface VoiceOption {
  id: string
  name: string
  lang: string
}

const currentProviderVoices = computed<VoiceOption[]>(() => {
  switch (draft.value.ttsProvider) {
    case 'edge-tts':
      return edgePresetVoices
    case 'web-speech':
      return systemVoices.value.length > 0
        ? systemVoices.value
        : [{ id: 'default', name: '系统默认声音', lang: 'zh-CN' }]
    case 'cosyvoice':
      return cosyPresetVoices
    case 'siliconflow':
      return siliconflowPresetVoices
    default:
      return []
  }
})

function selectProvider(providerId: string) {
  draft.value.ttsProvider = providerId as any
  stopVoicePlayback()
  const available = currentProviderVoices.value
  if (available.length > 0) {
    const exists = available.some((v) => v.id === draft.value.ttsVoice)
    if (!exists) {
      draft.value.ttsVoice = available[0].id
    }
  }
}

onMounted(() => {
  populateVoices()
  if ('speechSynthesis' in window) {
    window.speechSynthesis.onvoiceschanged = populateVoices
    setTimeout(populateVoices, 250)
    setTimeout(populateVoices, 800)
  }
})

const speedRates = [
  { label: '慢速 (-15%)', value: '-15%' },
  { label: '正常 (+0%)', value: '+0%' },
  { label: '稍快 (+10%)', value: '+10%' },
  { label: '快速 (+20%)', value: '+20%' },
]

async function testVoicePlayback() {
  stopVoicePlayback()
  isTestingVoice.value = true

  const testText = '您好，这是学术文献伴读语音试听效果。我将为您清晰、自然地朗读学术论文与中英讲稿。'

  // 1. 如果当前选定的是 SiliconFlow：调用硅基流动 CosyVoice 接口 (免反代，直连)
  if (draft.value.ttsProvider === 'siliconflow') {
    try {
      const res = await synthesizeSiliconFlowTts(
        testText,
        draft.value.siliconflowApiKey || draft.value.customTtsApiKey || '',
        draft.value.ttsVoice || 'FunAudioLLM/CosyVoice2-0.5B:alex',
        draft.value.siliconflowModel || 'FunAudioLLM/CosyVoice2-0.5B',
        draft.value.ttsRate
      )
      if (res.audioBlob && res.audioBlob.size > 0) {
        const url = URL.createObjectURL(res.audioBlob)
        const audio = new Audio(url)
        testAudioEl.value = audio
        audio.onended = () => {
          isTestingVoice.value = false
          URL.revokeObjectURL(url)
          testAudioEl.value = null
        }
        audio.onerror = () => {
          isTestingVoice.value = false
          URL.revokeObjectURL(url)
          testAudioEl.value = null
        }
        await audio.play()
        return
      }
      throw new Error('未接收到有效的音频数据')
    } catch (err: any) {
      isTestingVoice.value = false
      alert(
        `硅基流动 (CosyVoice) 试听受阻：\n${err.message || '请求受阻'}\n\n` +
        `💡 提示：请在下方填入有效的硅基流动 API Key（以 sk- 开头，可在 cloud.siliconflow.cn 免费注册）。`
      )
      return
    }
  }

  // 2. 如果当前选定的是 Edge-TTS：真正调用云端 Edge-TTS 合成并播放真实 MP3 语音！
  if (draft.value.ttsProvider === 'edge-tts') {
    try {
      const res = await synthesizeEdgeTts(
        testText,
        draft.value.ttsVoice,
        draft.value.ttsRate,
        draft.value.edgeTtsProxyUrl
      )
      if (res.audioBlob && res.audioBlob.size > 0) {
        const url = URL.createObjectURL(res.audioBlob)
        const audio = new Audio(url)
        testAudioEl.value = audio
        audio.onended = () => {
          isTestingVoice.value = false
          URL.revokeObjectURL(url)
          testAudioEl.value = null
        }
        audio.onerror = () => {
          isTestingVoice.value = false
          URL.revokeObjectURL(url)
          testAudioEl.value = null
        }
        await audio.play()
        return
      }
      throw new Error('未接收到有效的 Edge-TTS 音频数据')
    } catch (err: any) {
      isTestingVoice.value = false
      alert(
        `Edge-TTS 试听受阻：\n${err.message || '网络连接失败'}\n\n` +
        `【原因与排查】\n` +
        `由于 GitHub Pages 为纯静态托管，微软安全策略拒绝了浏览器网页的跨域直连 (403 Forbidden)。\n\n` +
        `【解决方案】\n` +
        `1. 静态页面：系统已默认配置专属 Cloudflare Worker 安全反代；\n` +
        `2. 本地使用：在电脑终端运行 npm run dev 打开本地页面，自带 Node.js 代理；\n` +
        `3. 免代理方案：可将伴读引擎切换为『系统原生 Web Speech』。`
      )
      return
    }
  }

  // 3. 浏览器原生 Web Speech API 试听
  if (draft.value.ttsProvider === 'web-speech') {
    if (!('speechSynthesis' in window)) {
      alert('当前浏览器不支持 Web Speech API')
      isTestingVoice.value = false
      return
    }

    const u = new SpeechSynthesisUtterance(testText)
    const sysVoices = window.speechSynthesis.getVoices()
    const target = draft.value.ttsVoice

    let matched: SpeechSynthesisVoice | undefined = undefined
    matched = sysVoices.find((v) => v.name === target || v.voiceURI === target)
    if (!matched) matched = sysVoices.find((v) => v.name.includes(target) || target.includes(v.name))
    if (!matched && (target.includes('TW') || target.includes('HsiaoChen') || target.includes('台湾'))) {
      matched = sysVoices.find((v) => {
        const n = v.name.toLowerCase()
        const l = v.lang.replace('_', '-').toLowerCase()
        return l.includes('zh-tw') || l.includes('zh-hk') || n.includes('mei-jia') || n.includes('hanhan') || n.includes('國語')
      })
    }
    if (!matched && (target.includes('Yunxi') || target.includes('Yunjian') || target.includes('男'))) {
      matched = sysVoices.find((v) => {
        const n = v.name.toLowerCase()
        const l = v.lang.toLowerCase()
        return l.includes('zh') && (n.includes('kangkang') || n.includes('danny') || n.includes('male') || n.includes('男'))
      })
    }
    if (!matched && (target.includes('HK') || target.includes('HiuGaai') || target.includes('粤'))) {
      matched = sysVoices.find((v) => {
        const n = v.name.toLowerCase()
        const l = v.lang.replace('_', '-').toLowerCase()
        return l.includes('zh-hk') || n.includes('sin-ji') || n.includes('粵語') || n.includes('cantonese')
      })
    }
    if (!matched && (target.includes('Xiaoxiao') || target.includes('CN') || target.includes('女'))) {
      matched = sysVoices.find((v) => {
        const n = v.name.toLowerCase()
        const l = v.lang.replace('_', '-').toLowerCase()
        return l.includes('zh') && (n.includes('ting-ting') || n.includes('yaoyao') || n.includes('female') || n.includes('女'))
      })
    }
    if (!matched) {
      matched = sysVoices.find((v) => v.lang.toLowerCase().includes('zh'))
    }

    if (matched) {
      u.voice = matched
      u.lang = matched.lang
    }

    const rateNum = parseFloat(draft.value.ttsRate.replace('%', '')) || 0
    u.rate = Math.max(0.5, Math.min(2.0, 1.0 + rateNum / 100))

    u.onend = () => {
      isTestingVoice.value = false
    }
    u.onerror = (e) => {
      isTestingVoice.value = false
      console.error('Web Speech 试听失败:', e)
    }

    window.speechSynthesis.speak(u)
    return
  }

  isTestingVoice.value = false
}

function stopVoicePlayback() {
  if (testAudioEl.value) {
    try {
      testAudioEl.value.pause()
      testAudioEl.value.currentTime = 0
    } catch {}
    testAudioEl.value = null
  }
  if ('speechSynthesis' in window) {
    try { window.speechSynthesis.cancel() } catch {}
  }
  isTestingVoice.value = false
}

// 尝试关闭弹窗（检查未保存修改）
function handleCloseAttempt() {
  if (isDirty.value) {
    const ok = window.confirm('您有未保存的配置修改，是否放弃更改并关闭？')
    if (!ok) return
  }
  stopVoicePlayback()
  emit('close')
}

// 显式保存所有修改
function handleSave() {
  stopVoicePlayback()
  saveSettings(draft.value)
  emit('close')
}

function handleClearStorage() {
  if (confirm('确定要清除本地保存的配置项并恢复出厂默认值吗？')) {
    localStorage.removeItem('paper_zh_user_settings')
    window.location.reload()
  }
}
</script>

<template>
  <div class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-fade-in">
    <div
      class="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl w-full max-w-xl max-h-[90vh] overflow-y-auto shadow-2xl flex flex-col"
      @click.stop
    >
      <!-- Header -->
      <div class="sticky top-0 z-10 flex items-center justify-between px-6 py-4 bg-white/95 dark:bg-slate-900/95 backdrop-blur border-b border-slate-100 dark:border-slate-800">
        <div class="flex items-center gap-2">
          <div class="p-2 rounded-lg bg-blue-50 dark:bg-blue-950/60 text-blue-600 dark:text-blue-400">
            <Sparkles class="w-5 h-5" />
          </div>
          <div>
            <div class="flex items-center gap-2">
              <h2 class="text-base font-bold text-slate-900 dark:text-slate-100">运行与模型配置</h2>
              <span v-if="isDirty" class="inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-full bg-amber-100 dark:bg-amber-950/60 text-amber-700 dark:text-amber-300 font-medium">
                <AlertTriangle class="w-3 h-3" /> 未保存更改
              </span>
            </div>
            <p class="text-xs text-slate-500">100% 存储于本地浏览器 localStorage，手动保存生效</p>
          </div>
        </div>
        <button
          type="button"
          @click="handleCloseAttempt"
          class="p-2 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 transition"
        >
          <X class="w-5 h-5" />
        </button>
      </div>

      <div class="p-6 space-y-6 flex-1 text-sm">
        <!-- 1. LLM 模型与 API Key -->
        <section class="space-y-4">
          <div class="flex items-center gap-2 font-semibold text-slate-800 dark:text-slate-200">
            <KeyRound class="w-4 h-4 text-blue-500" />
            <span>LLM 大语言模型服务 (BYOK)</span>
          </div>

          <!-- 提供商选项卡 -->
          <div class="grid grid-cols-2 sm:grid-cols-4 gap-2">
            <button
              v-for="provider in ['deepseek', 'openai', 'gemini', 'custom'] as const"
              :key="provider"
              type="button"
              @click="handleSelectProvider(provider)"
              :class="[
                'py-2 px-3 rounded-xl border text-xs font-semibold capitalize transition text-center flex flex-col items-center justify-center gap-0.5',
                draft.llmProvider === provider
                  ? 'border-blue-500 bg-blue-50/70 dark:bg-blue-950/40 text-blue-600 dark:text-blue-400 shadow-sm'
                  : 'border-slate-200 dark:border-slate-800 text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800'
              ]"
            >
              <span>{{ provider === 'deepseek' ? 'DeepSeek' : provider === 'gemini' ? 'Gemini (免费)' : provider }}</span>
              <span v-if="provider === 'gemini'" class="text-[9px] text-emerald-600 dark:text-emerald-400 font-normal scale-90">提供试用</span>
            </button>
          </div>

          <!-- API Key Input（每个服务商独立存储，切换不丢失） -->
          <div>
            <div class="flex items-center justify-between mb-1.5">
              <label class="block text-xs font-medium text-slate-600 dark:text-slate-400">
                {{ draft.llmProvider.toUpperCase() }} API Key
              </label>

              <!-- 各厂商获取 Key 的官方跳转链接 -->
              <a
                v-if="draft.llmProvider === 'gemini'"
                href="https://aistudio.google.com/app/apikey"
                target="_blank"
                class="text-[11px] text-blue-600 dark:text-blue-400 hover:underline flex items-center gap-0.5"
              >
                <span>免费申请 Google API Key</span>
                <ExternalLink class="w-3 h-3" />
              </a>
              <a
                v-else-if="draft.llmProvider === 'deepseek'"
                href="https://platform.deepseek.com/api_keys"
                target="_blank"
                class="text-[11px] text-blue-600 dark:text-blue-400 hover:underline flex items-center gap-0.5"
              >
                <span>获取 DeepSeek Key</span>
                <ExternalLink class="w-3 h-3" />
              </a>
              <a
                v-else-if="draft.llmProvider === 'openai'"
                href="https://platform.openai.com/api-keys"
                target="_blank"
                class="text-[11px] text-blue-600 dark:text-blue-400 hover:underline flex items-center gap-0.5"
              >
                <span>获取 OpenAI Key</span>
                <ExternalLink class="w-3 h-3" />
              </a>
            </div>

            <div class="relative">
              <input
                :type="showApiKey ? 'text' : 'password'"
                v-model="draft.apiKeys[draft.llmProvider]"
                :placeholder="draft.llmProvider === 'gemini' ? '留空可自动体验内置免费试用代理，或填入您的私有 Key' : 'sk-...'"
                class="w-full px-3.5 py-2.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50/50 dark:bg-slate-800/50 text-slate-900 dark:text-slate-100 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500 font-mono text-xs pr-16"
              />
              <button
                type="button"
                @click="showApiKey = !showApiKey"
                class="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
              >
                {{ showApiKey ? '隐藏' : '显示' }}
              </button>
            </div>

            <!-- Gemini 专属贴心提示 -->
            <p v-if="draft.llmProvider === 'gemini'" class="text-[11px] text-emerald-600 dark:text-emerald-400 mt-1.5 flex items-center gap-1">
              ✨ <b>新手友好</b>：若您尚未申请 Key，留空即可通过安全反代免费体验 Gemini 伴读翻译；填入您自己的 Key 则直连官方。
            </p>
            <p v-else class="text-[11px] text-slate-400 mt-1">每个厂商的密钥均独立保留，切换厂商不会相互覆盖；数据 100% 留存在浏览器本地。</p>
          </div>

          <!-- Model Name (在线拉取 + 下拉常用预设 + 自定义输入组合) -->
          <div class="space-y-1.5">
            <div class="flex items-center justify-between">
              <div class="flex items-center gap-2">
                <label class="block text-xs font-medium text-slate-600 dark:text-slate-400">
                  模型选择 (Model)
                </label>
                <!-- 在线获取可用模型按钮 -->
                <button
                  type="button"
                  @click="handleFetchOnlineModels"
                  :disabled="isFetchingModels"
                  class="inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-lg border border-blue-200 dark:border-blue-800 bg-blue-50/70 dark:bg-blue-950/40 text-blue-600 dark:text-blue-400 hover:bg-blue-100 dark:hover:bg-blue-900/60 transition disabled:opacity-50 font-medium"
                  :title="draft.llmProvider === 'gemini' && !draft.apiKeys.gemini ? '通过内置代理获取当前支持的 Gemini 模型' : '向官方验证 API Key 并拉取此 Key 有权调用的所有模型'"
                >
                  <Loader2 v-if="isFetchingModels" class="w-3 h-3 animate-spin" />
                  <RefreshCw v-else class="w-3 h-3" />
                  <span>{{ isFetchingModels ? '正在查询可用模型...' : '⚡ 获取模型列表' }}</span>
                </button>
              </div>

              <button
                type="button"
                @click="isCustomModel = !isCustomModel"
                class="text-[11px] text-blue-600 dark:text-blue-400 hover:underline font-medium"
              >
                {{ isCustomModel ? '返回模型列表' : '✏️ 手动输入其他模型' }}
              </button>
            </div>

            <!-- 成功/失败提示 -->
            <div v-if="fetchModelSuccess" class="text-[11px] text-emerald-600 dark:text-emerald-400 flex items-center gap-1 bg-emerald-50/60 dark:bg-emerald-950/30 px-2.5 py-1 rounded-lg border border-emerald-200/50 dark:border-emerald-900/40">
              <Check class="w-3.5 h-3.5" />
              <span>{{ fetchModelSuccess }}已为您更新下拉列表。</span>
            </div>
            <div v-if="fetchModelError" class="text-[11px] text-rose-600 dark:text-rose-400 flex items-start gap-1 bg-rose-50/60 dark:bg-rose-950/30 px-2.5 py-1.5 rounded-lg border border-rose-200/50 dark:border-rose-900/40 leading-snug">
              <AlertTriangle class="w-3.5 h-3.5 shrink-0 mt-0.5" />
              <span>{{ fetchModelError }}</span>
            </div>

            <!-- 下拉菜单 -->
            <div v-if="!isCustomModel">
              <select
                v-model="selectModelChoice"
                class="w-full px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 text-xs focus:ring-2 focus:ring-blue-500 outline-none"
              >
                <option v-for="m in combinedModelOptions" :key="m.id" :value="m.id">
                  {{ m.label }}
                </option>
                <option value="__custom__">✏️ 自定义输入其他模型名称...</option>
              </select>
            </div>

            <!-- 自定义输入框 -->
            <div v-else class="space-y-1">
              <input
                type="text"
                v-model="activeModelValue"
                placeholder="例如 deepseek-chat 或 gpt-4o 等"
                class="w-full px-3.5 py-2 rounded-xl border border-blue-400 dark:border-blue-500 bg-slate-50/50 dark:bg-slate-800/50 text-slate-900 dark:text-slate-100 font-mono text-xs focus:ring-2 focus:ring-blue-500 outline-none"
              />
              <p class="text-[10px] text-slate-400">厂商更新模型时，您可在此直接填入最新模型标识符，无需等待前端发版更新。</p>
            </div>
          </div>

          <!-- Custom Base URL -->
          <div v-if="draft.llmProvider === 'custom'" class="space-y-2">
            <div>
              <div class="flex items-center justify-between mb-1.5">
                <label class="block text-xs font-medium text-slate-600 dark:text-slate-400">
                  自定义 API Base URL (OpenAI 兼容协议)
                </label>
                <button
                  type="button"
                  @click="
                    draft.customBaseUrl = 'http://localhost:11434/v1';
                    activeModelValue = 'qwen2.5:7b';
                    if (!draft.apiKeys.custom) draft.apiKeys.custom = 'ollama';
                  "
                  class="text-[11px] text-blue-600 dark:text-blue-400 hover:underline flex items-center gap-1 font-medium"
                >
                  ⚡ 一键填入 Ollama 本地模型 (Mac 芯片 GPU 加速)
                </button>
              </div>
              <input
                type="text"
                v-model="draft.customBaseUrl"
                placeholder="https://api.yourproxy.com/v1 或 http://localhost:11434/v1"
                class="w-full px-3.5 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50/50 dark:bg-slate-800/50 text-slate-900 dark:text-slate-100 font-mono text-xs"
              />
            </div>
            <p class="text-[11px] text-slate-400 leading-relaxed">
              💡 提示：在电脑终端运行 <code class="px-1 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300">ollama run qwen2.5:7b</code> 即可充分利用本地硬件算力，离线、零成本运行。
            </p>
          </div>
        </section>

        <hr class="border-slate-100 dark:border-slate-800" />

        <!-- 2. TTS 伴读引擎设置 (多引擎可选) -->
        <section class="space-y-4">
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-2 font-semibold text-slate-800 dark:text-slate-200">
              <Volume2 class="w-4 h-4 text-emerald-500" />
              <span>伴读语音合成引擎 (TTS Engine)</span>
            </div>

            <!-- 试听按钮 -->
            <button
              v-if="draft.ttsProvider !== 'none'"
              type="button"
              @click="isTestingVoice ? stopVoicePlayback() : testVoicePlayback()"
              class="px-2.5 py-1 rounded-lg bg-emerald-50 hover:bg-emerald-100 dark:bg-emerald-950/60 text-emerald-600 dark:text-emerald-300 text-xs font-medium flex items-center gap-1 transition"
            >
              <VolumeX v-if="isTestingVoice" class="w-3.5 h-3.5" />
              <Volume2 v-else class="w-3.5 h-3.5" />
              <span>{{ isTestingVoice ? '停止试听' : '🔊 试听发音' }}</span>
            </button>
          </div>

          <!-- 引擎卡片选择器 -->
          <div class="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
            <div
              v-for="provider in ttsProviders"
              :key="provider.id"
              @click="selectProvider(provider.id)"
              :class="[
                'p-3 rounded-xl border cursor-pointer transition text-left flex flex-col justify-between gap-1.5',
                draft.ttsProvider === provider.id
                  ? 'border-emerald-500 bg-emerald-50/50 dark:bg-emerald-950/30 ring-1 ring-emerald-500/20'
                  : 'border-slate-200 dark:border-slate-800 hover:border-slate-300 dark:hover:border-slate-700'
              ]"
            >
              <div class="flex items-center justify-between gap-2">
                <span class="font-semibold text-xs text-slate-900 dark:text-slate-100">{{ provider.name }}</span>
                <span :class="['text-[10px] px-1.5 py-0.5 rounded font-medium shrink-0', provider.badgeColor]">
                  {{ provider.badge }}
                </span>
              </div>
              <p class="text-[11px] text-slate-500 leading-snug">{{ provider.desc }}</p>
            </div>
          </div>

          <!-- 音色选择与语速 -->
          <div v-if="draft.ttsProvider !== 'none'" class="space-y-3 pt-2 bg-slate-50/60 dark:bg-slate-800/40 p-3.5 rounded-xl border border-slate-200/60 dark:border-slate-800">
            <div>
              <label class="block text-xs font-medium text-slate-600 dark:text-slate-400 mb-1.5">
                朗读音色选择
              </label>
              <select
                v-model="draft.ttsVoice"
                class="w-full px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 text-xs"
              >
                <option v-for="v in currentProviderVoices" :key="v.id" :value="v.id">{{ v.name }}</option>
              </select>
            </div>

            <div>
              <label class="block text-xs font-medium text-slate-600 dark:text-slate-400 mb-1.5">朗读语速调节</label>
              <div class="grid grid-cols-4 gap-2">
                <button
                  v-for="r in speedRates"
                  :key="r.value"
                  type="button"
                  @click="draft.ttsRate = r.value"
                  :class="[
                    'py-1.5 px-2 rounded-lg border text-xs text-center transition',
                    draft.ttsRate === r.value
                      ? 'border-emerald-500 bg-emerald-50 dark:bg-emerald-950/40 text-emerald-600 dark:text-emerald-400 font-semibold'
                      : 'border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-800 text-slate-600 dark:text-slate-400'
                  ]"
                >
                  {{ r.label }}
                </button>
              </div>
            </div>

            <!-- 硅基流动专属配置 (CosyVoice API Key & Model) -->
            <div
              v-if="draft.ttsProvider === 'siliconflow'"
              class="pt-3 border-t border-slate-200/60 dark:border-slate-700/60 space-y-3"
            >
              <div>
                <div class="flex items-center justify-between mb-1.5">
                  <label class="block text-xs font-medium text-slate-600 dark:text-slate-400">
                    硅基流动 API Key
                  </label>
                  <a
                    href="https://cloud.siliconflow.cn/"
                    target="_blank"
                    class="text-[11px] text-indigo-600 dark:text-indigo-400 hover:underline flex items-center gap-1 font-medium"
                  >
                    <span>获取 API Key</span>
                    <ExternalLink class="w-3 h-3" />
                  </a>
                </div>
                <div class="relative">
                  <input
                    :type="showSiliconflowKey ? 'text' : 'password'"
                    v-model="draft.siliconflowApiKey"
                    placeholder="sk-xxxxxxxxxxxxxxxxxxxxxxxx"
                    class="w-full pl-3.5 pr-12 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 font-mono text-xs"
                  />
                  <button
                    type="button"
                    @click="showSiliconflowKey = !showSiliconflowKey"
                    class="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 text-[11px]"
                  >
                    {{ showSiliconflowKey ? '隐藏' : '显示' }}
                  </button>
                </div>
              </div>

              <div>
                <label class="block text-xs font-medium text-slate-600 dark:text-slate-400 mb-1.5">
                  语音合成模型
                </label>
                <select
                  v-model="draft.siliconflowModel"
                  class="w-full px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 text-xs"
                >
                  <option value="FunAudioLLM/CosyVoice2-0.5B">FunAudioLLM/CosyVoice2-0.5B (强烈推荐 · 顶级拟真口语 · 极度自然)</option>
                  <option value="FunAudioLLM/CosyVoice-300M">FunAudioLLM/CosyVoice-300M (轻量版 · 极速响应)</option>
                </select>
              </div>

              <div class="p-2.5 rounded-xl bg-indigo-50/70 dark:bg-indigo-950/40 border border-indigo-200/60 dark:border-indigo-900/40 text-[11px] text-indigo-900 dark:text-indigo-200 leading-relaxed">
                ✨ <b>静态网页原生支持</b>：硅基流动开放了全套 CORS 跨域权限，在 GitHub Pages 纯静态网页上可直接调用，零反代、零本地服务！
              </div>
            </div>

            <!-- Edge-TTS 代理配置（解决静态部署跨域拦截） -->
            <div
              v-if="draft.ttsProvider === 'edge-tts'"
              class="pt-3 border-t border-slate-200/60 dark:border-slate-700/60 space-y-2"
            >
              <div class="flex items-center justify-between">
                <label class="block text-xs font-medium text-slate-600 dark:text-slate-400">
                  Edge-TTS 代理 URL
                </label>
                <span class="text-[10px] text-emerald-600 dark:text-emerald-400 font-medium">✓ 内置反代已就绪</span>
              </div>
              <input
                type="text"
                v-model="draft.edgeTtsProxyUrl"
                placeholder="https://edge-tts-proxy.ryoctahedron1998.workers.dev/api/edge-tts"
                class="w-full px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 font-mono text-xs"
              />
              <p class="text-[11px] text-slate-400 leading-relaxed">
                💡 <b>运行环境说明</b>：系统已默认内置专用安全反代服务，开箱即听正版微软晓臻。如需使用自己的私有反代节点，直接在上方填入即可自动覆盖。
              </p>
            </div>
          </div>
        </section>

        <!-- Privacy & Tips Badge -->
        <div class="p-3.5 rounded-xl bg-slate-50 dark:bg-slate-800/60 border border-slate-200/60 dark:border-slate-800 flex items-start gap-3">
          <ShieldCheck class="w-5 h-5 text-emerald-600 shrink-0 mt-0.5" />
          <div class="text-xs text-slate-600 dark:text-slate-400 space-y-1">
            <p class="font-medium text-slate-800 dark:text-slate-200">100% 隐私安全防护</p>
            <p>本系统为静态单页应用 (SPA)，所有的文献解析、多语言翻译调用、口语改写和音频合成均直接在您的浏览器客户端运行，不经过任何中间服务器。</p>
          </div>
        </div>
      </div>

      <!-- Footer -->
      <div class="px-6 py-4 bg-slate-50 dark:bg-slate-800/50 border-t border-slate-100 dark:border-slate-800 flex justify-between items-center">
        <button
          type="button"
          @click="handleClearStorage"
          class="text-xs text-rose-500 hover:text-rose-700 font-medium"
        >
          重置配置
        </button>
        <div class="flex items-center gap-2">
          <button
            type="button"
            @click="handleCloseAttempt"
            class="px-4 py-2 rounded-xl border border-slate-200 dark:border-slate-700 hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-600 dark:text-slate-300 font-medium text-xs transition"
          >
            取消
          </button>
          <button
            type="button"
            @click="handleSave"
            class="px-5 py-2 rounded-xl bg-blue-600 hover:bg-blue-700 text-white font-medium text-xs shadow-sm transition flex items-center gap-1.5"
          >
            <Check class="w-3.5 h-3.5" />
            <span>保存设置</span>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
