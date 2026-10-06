<script setup lang="ts">
import { ref } from 'vue'
import { settingsState } from '../store/settings'
import type { TtsProvider } from '../core/types'
import {
  KeyRound,
  Sparkles,
  Volume2,
  Globe,
  ShieldCheck,
  X,
  HelpCircle,
} from 'lucide-vue-next'

const emit = defineEmits<{
  (e: 'close'): void
}>()

const showApiKey = ref(false)
const showWebVpnGuide = ref(false)

const ttsProviders: Array<{
  id: TtsProvider
  name: string
  badge: string
  badgeColor: string
  desc: string
}> = [
  {
    id: 'edge-tts',
    name: 'Microsoft Edge-TTS',
    badge: '推荐 · 内置可用',
    badgeColor: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300',
    desc: '直接通过浏览器建立连接，微软高保真神经人声，支持逐句时间戳。',
  },
  {
    id: 'web-speech',
    name: '浏览器原生 Speech API',
    badge: '内置 · 完全离线',
    badgeColor: 'bg-blue-100 text-blue-800 dark:bg-blue-950 dark:text-blue-300',
    desc: '调用操作系统本地朗读引擎，无需网络开销，随时可用。',
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
    name: '阿里 CosyVoice / 千问',
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

const voices = [
  { id: 'zh-TW-HsiaoChenNeural', name: '台湾 · 晓臻 (HsiaoChen) - 亲切自然 · 推荐', lang: 'zh-TW' },
  { id: 'zh-CN-XiaoxiaoNeural', name: '大陆 · 晓晓 (Xiaoxiao) - 清晰生动', lang: 'zh-CN' },
  { id: 'zh-CN-YunxiNeural', name: '大陆 · 云希 (Yunxi) - 阳光男声', lang: 'zh-CN' },
  { id: 'zh-CN-YunjianNeural', name: '大陆 · 云健 (Yunjian) - 沉稳叙事', lang: 'zh-CN' },
  { id: 'zh-HK-HiuGaaiNeural', name: '香港 · 晓佳 (HiuGaai) - 粤语', lang: 'zh-HK' },
]

const speedRates = [
  { label: '慢速 (-15%)', value: '-15%' },
  { label: '正常 (+0%)', value: '+0%' },
  { label: '稍快 (+10%)', value: '+10%' },
  { label: '快速 (+20%)', value: '+20%' },
]

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
          <div class="flex items-center gap-2 font-semibold text-slate-800 dark:text-slate-200">
            <Volume2 class="w-4 h-4 text-emerald-500" />
            <span>伴读语音合成引擎 (TTS Engine)</span>
          </div>

          <!-- 引擎卡片选择器 -->
          <div class="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
            <div
              v-for="provider in ttsProviders"
              :key="provider.id"
              @click="settingsState.ttsProvider = provider.id"
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

          <!-- Edge-TTS 专属配置 -->
          <div v-if="settingsState.ttsProvider === 'edge-tts'" class="space-y-3 pt-2 bg-slate-50/60 dark:bg-slate-800/40 p-3.5 rounded-xl border border-slate-200/60 dark:border-slate-800">
            <div>
              <label class="block text-xs font-medium text-slate-600 dark:text-slate-400 mb-1.5">Edge-TTS 推荐音色</label>
              <select
                v-model="settingsState.ttsVoice"
                class="w-full px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 text-xs"
              >
                <option v-for="v in voices" :key="v.id" :value="v.id">{{ v.name }}</option>
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

          <!-- 预留其他 TTS (OpenAI / CosyVoice / SiliconFlow) 配置项 -->
          <div
            v-else-if="['openai', 'cosyvoice', 'siliconflow'].includes(settingsState.ttsProvider)"
            class="space-y-3 pt-2 bg-amber-50/40 dark:bg-amber-950/20 p-3.5 rounded-xl border border-amber-200/60 dark:border-amber-900/40"
          >
            <div class="text-xs text-amber-800 dark:text-amber-300 font-medium flex items-center gap-1.5">
              <span>⚠️ 该引擎接口已预留，目前工作流运行中会自动无缝切换至浏览器原生语音播报。</span>
            </div>
            <div>
              <label class="block text-xs font-medium text-slate-600 dark:text-slate-400 mb-1.5">
                {{ settingsState.ttsProvider.toUpperCase() }} API Key (预留)
              </label>
              <input
                type="password"
                v-model="settingsState.customTtsApiKey"
                placeholder="sk-..."
                class="w-full px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 text-xs font-mono"
              />
            </div>
          </div>
        </section>

        <hr class="border-slate-100 dark:border-slate-800" />

        <!-- 3. 高校机构 WebVPN 反代指引 -->
        <section class="space-y-3">
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-2 font-semibold text-slate-800 dark:text-slate-200">
              <Globe class="w-4 h-4 text-purple-500" />
              <span>高校/机构 WebVPN 全文获取 (指南与反代)</span>
            </div>
            <button
              type="button"
              @click="showWebVpnGuide = !showWebVpnGuide"
              class="text-xs text-blue-600 hover:text-blue-700 dark:text-blue-400 flex items-center gap-1"
            >
              <HelpCircle class="w-3.5 h-3.5" />
              <span>{{ showWebVpnGuide ? '收起教程' : '怎么使用？' }}</span>
            </button>
          </div>

          <!-- 展开的详细 WebVPN 指南 -->
          <div
            v-if="showWebVpnGuide"
            class="p-3.5 rounded-xl bg-purple-50/60 dark:bg-purple-950/30 border border-purple-200 dark:border-purple-800/60 text-xs space-y-2 text-slate-700 dark:text-slate-300 animate-fade-in"
          >
            <div class="font-semibold text-purple-900 dark:text-purple-200">📚 为什么以及如何使用高校文献权限：</div>
            <p>由于 Nature 期刊正文需要高校订阅权限，且浏览器存在跨域安全限制（CORS），推荐以下两种用法：</p>
            <div class="space-y-1.5 pl-2 border-l-2 border-purple-400">
              <p>
                <strong>方法 1（最推荐 · 零门槛）：</strong>
                在学校 WebVPN 或校园网打开 Nature 论文网页，直接在浏览器按 <kbd class="px-1.5 py-0.5 rounded bg-white dark:bg-slate-800 border font-mono">Ctrl+S</kbd> / <kbd class="px-1.5 py-0.5 rounded bg-white dark:bg-slate-800 border font-mono">Cmd+S</kbd>，另存为「网页，仅 HTML」，然后拖入本站首页虚线框，即可完美提取！
              </p>
              <p>
                <strong>方法 2（高级用户）：</strong>
                配置 Cloudflare Worker 或支持 CORS 透传的代理服务器，并在下方填入反代地址与 WebVPN Cookie（如 <code>wengine_vpn_ticket</code>），即可在网页中直接输入 DOI 一键抓取。
              </p>
            </div>
          </div>

          <div class="space-y-2">
            <label class="block text-xs font-medium text-slate-600 dark:text-slate-400">
              自定义 CORS 反代 URL (可选)
            </label>
            <input
              type="text"
              v-model="settingsState.academicProxyUrl"
              placeholder="https://your-cors-proxy.workers.dev/?url=https://webvpn.univ.edu.cn"
              class="w-full px-3.5 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50/50 dark:bg-slate-800/50 text-slate-900 dark:text-slate-100 text-xs font-mono"
            />
          </div>
        </section>

        <!-- Privacy Badge -->
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
