<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { settingsState } from '../store/settings'
import type { TtsProvider } from '../core/types'
import { synthesizeEdgeTts } from '../core/edgeTts'
import {
  KeyRound,
  Sparkles,
  Volume2,
  ShieldCheck,
  X,
  VolumeX,
} from 'lucide-vue-next'

const emit = defineEmits<{
  (e: 'close'): void
}>()

const showApiKey = ref(false)
const isTestingVoice = ref(false)
const testAudioEl = ref<HTMLAudioElement | null>(null)

const ttsProviders: Array<{
  id: TtsProvider
  name: string
  badge: string
  badgeColor: string
  desc: string
}> = [
  {
    id: 'edge-tts',
    name: 'Microsoft Edge-TTS / 系统精选',
    badge: '内置推荐 · 免配置',
    badgeColor: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300',
    desc: '高质量自然流利人声，台湾晓臻、中国晓晓等多种口语风格，支持逐句卡拉OK高亮。',
  },
  {
    id: 'web-speech',
    name: '浏览器原生 Speech API',
    badge: '完全离线 · 零流量',
    badgeColor: 'bg-blue-100 text-blue-800 dark:bg-blue-950 dark:text-blue-300',
    desc: '直接调用操作系统（macOS/Windows/iOS/Android）自带朗读引擎，无需网络。',
  },
  {
    id: 'openai',
    name: 'OpenAI TTS (tts-1 / hd)',
    badge: '待适配 · 预留配置',
    badgeColor: 'bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300',
    desc: 'OpenAI 官方高精度语音接口 (Alloy, Echo, Shimmer 等)，支持配置专属 Key。',
  },
  {
    id: 'cosyvoice',
    name: '阿里 CosyVoice / 通义',
    badge: '待适配 · 预留配置',
    badgeColor: 'bg-purple-100 text-purple-800 dark:bg-purple-950 dark:text-purple-300',
    desc: '中文顶级超自然口语合成引擎，音调与语调极具感染力。',
  },
  {
    id: 'siliconflow',
    name: '硅基流动 / IndexTTS',
    badge: '待适配 · 预留配置',
    badgeColor: 'bg-indigo-100 text-indigo-800 dark:bg-indigo-950 dark:text-indigo-300',
    desc: '国产开源语音大模型高速云端托管服务。',
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
  { id: 'siliconflow-indextts-male', name: 'IndexTTS · 智臻学者 (深度男声 · 预留)', lang: 'zh-CN' },
  { id: 'siliconflow-indextts-female', name: 'IndexTTS · 晨曦学姐 (清晰女声 · 预留)', lang: 'zh-CN' },
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
  switch (settingsState.ttsProvider) {
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
  settingsState.ttsProvider = providerId as any
  stopVoicePlayback()
  const available = currentProviderVoices.value
  if (available.length > 0) {
    const exists = available.some((v) => v.id === settingsState.ttsVoice)
    if (!exists) {
      settingsState.ttsVoice = available[0].id
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

  // 1. 如果当前选定的是 Edge-TTS：真正调用云端 Edge-TTS 合成并播放真实 MP3 语音！
  if (settingsState.ttsProvider === 'edge-tts') {
    try {
      const res = await synthesizeEdgeTts(testText, settingsState.ttsVoice, settingsState.ttsRate)
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
    } catch (err: any) {
      console.warn('Edge-TTS 试听请求遇阻，回退至系统原生语音:', err)
    }
  }

  // 2. 浏览器原生 Web Speech API 试听
  if (!('speechSynthesis' in window)) {
    alert('当前浏览器不支持语音合成 API')
    isTestingVoice.value = false
    return
  }

  const u = new SpeechSynthesisUtterance(testText)
  const sysVoices = window.speechSynthesis.getVoices()
  const target = settingsState.ttsVoice

  let matched: SpeechSynthesisVoice | undefined = undefined
  // 完全精确匹配
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
      return l.startsWith('zh-cn') && (n.includes('ting-ting') || n.includes('huihui') || n.includes('yaoyao') || n.includes('普通话'))
    })
  }
  if (!matched) {
    matched = sysVoices.find((v) => v.lang.toLowerCase().includes('zh') || v.lang.toLowerCase().includes('cmn'))
  }

  if (matched) {
    u.voice = matched
    u.lang = matched.lang
  } else {
    u.lang = target.includes('TW') ? 'zh-TW' : 'zh-CN'
  }

  const rateNum = 1.0 + parseFloat(settingsState.ttsRate.replace('%', '')) / 100.0
  u.rate = Math.max(0.5, Math.min(2.0, rateNum))

  u.onend = () => {
    isTestingVoice.value = false
  }
  u.onerror = () => {
    isTestingVoice.value = false
  }

  window.speechSynthesis.speak(u)
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

function handleClearStorage() {
  if (confirm('确定要清除本地保存的配置项吗？')) {
    localStorage.removeItem('paper_zh_user_settings')
    window.location.reload()
  }
}
</script>

<template>
  <div class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-fade-in">
    <div class="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl w-full max-w-xl max-h-[90vh] overflow-y-auto shadow-2xl flex flex-col">
      <!-- Header -->
      <div class="sticky top-0 z-10 flex items-center justify-between px-6 py-4 bg-white/95 dark:bg-slate-900/95 backdrop-blur border-b border-slate-100 dark:border-slate-800">
        <div class="flex items-center gap-2">
          <div class="p-2 rounded-lg bg-blue-50 dark:bg-blue-950/60 text-blue-600 dark:text-blue-400">
            <Sparkles class="w-5 h-5" />
          </div>
          <div>
            <h2 class="text-base font-bold text-slate-900 dark:text-slate-100">运行与模型配置</h2>
            <p class="text-xs text-slate-500">100% 存储于本地浏览器 localStorage，零后端传输</p>
          </div>
        </div>
        <button
          @click="emit('close')"
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

          <div class="grid grid-cols-2 sm:grid-cols-4 gap-2">
            <button
              v-for="provider in ['deepseek', 'openai', 'gemini', 'custom'] as const"
              :key="provider"
              type="button"
              @click="settingsState.llmProvider = provider"
              :class="[
                'py-2 px-3 rounded-xl border text-xs font-semibold capitalize transition text-center',
                settingsState.llmProvider === provider
                  ? 'border-blue-500 bg-blue-50/70 dark:bg-blue-950/40 text-blue-600 dark:text-blue-400'
                  : 'border-slate-200 dark:border-slate-800 text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800'
              ]"
            >
              {{ provider === 'deepseek' ? 'DeepSeek (推荐)' : provider }}
            </button>
          </div>

          <!-- API Key Input -->
          <div>
            <label class="block text-xs font-medium text-slate-600 dark:text-slate-400 mb-1.5">
              {{ settingsState.llmProvider.toUpperCase() }} API Key
            </label>
            <div class="relative">
              <input
                :type="showApiKey ? 'text' : 'password'"
                v-model="settingsState.apiKey"
                placeholder="sk-..."
                class="w-full px-3.5 py-2.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50/50 dark:bg-slate-800/50 text-slate-900 dark:text-slate-100 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500 font-mono text-xs"
              />
              <button
                type="button"
                @click="showApiKey = !showApiKey"
                class="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
              >
                {{ showApiKey ? '隐藏' : '显示' }}
              </button>
            </div>
            <p class="text-[11px] text-slate-400 mt-1">密钥仅在发起翻译请求时直接由浏览器调用对应官方 API，绝不上报第三方服务器。</p>
          </div>

          <!-- Model Name -->
          <div>
            <label class="block text-xs font-medium text-slate-600 dark:text-slate-400 mb-1.5">
              模型名称 (Model Identifier)
            </label>
            <input
              type="text"
              v-model="settingsState.model"
              :placeholder="settingsState.llmProvider === 'deepseek' ? 'deepseek-chat' : 'gpt-4o-mini'"
              class="w-full px-3.5 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50/50 dark:bg-slate-800/50 text-slate-900 dark:text-slate-100 font-mono text-xs"
            />
          </div>

          <!-- Custom Base URL -->
          <div v-if="settingsState.llmProvider === 'custom'">
            <label class="block text-xs font-medium text-slate-600 dark:text-slate-400 mb-1.5">
              自定义 API Base URL (OpenAI 兼容协议)
            </label>
            <input
              type="text"
              v-model="settingsState.customBaseUrl"
              placeholder="https://api.yourproxy.com/v1"
              class="w-full px-3.5 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50/50 dark:bg-slate-800/50 text-slate-900 dark:text-slate-100 font-mono text-xs"
            />
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
              v-if="settingsState.ttsProvider !== 'none'"
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
                settingsState.ttsProvider === provider.id
                  ? 'border-emerald-500 bg-emerald-50/50 dark:bg-emerald-950/30'
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
          <div v-if="settingsState.ttsProvider !== 'none'" class="space-y-3 pt-2 bg-slate-50/60 dark:bg-slate-800/40 p-3.5 rounded-xl border border-slate-200/60 dark:border-slate-800">
            <div>
              <label class="block text-xs font-medium text-slate-600 dark:text-slate-400 mb-1.5">
                朗读音色选择
              </label>
              <select
                v-model="settingsState.ttsVoice"
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
                  @click="settingsState.ttsRate = r.value"
                  :class="[
                    'py-1.5 px-2 rounded-lg border text-xs text-center transition',
                    settingsState.ttsRate === r.value
                      ? 'border-emerald-500 bg-emerald-50 dark:bg-emerald-950/40 text-emerald-600 dark:text-emerald-400 font-semibold'
                      : 'border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-800 text-slate-600 dark:text-slate-400'
                  ]"
                >
                  {{ r.label }}
                </button>
              </div>
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
          class="text-xs text-rose-500 hover:text-rose-700"
        >
          重置配置
        </button>
        <button
          type="button"
          @click="emit('close')"
          class="px-5 py-2 rounded-xl bg-blue-600 hover:bg-blue-700 text-white font-medium text-xs shadow-sm transition"
        >
          保存并完成
        </button>
      </div>
    </div>
  </div>
</template>
