<script setup lang="ts">
import { ref, computed } from 'vue'
import type { Document, PipelineProgress } from '../core/types'
import { settingsState } from '../store/settings'
import { runDocumentPipeline } from '../core/pipeline'
import { downloadHtml } from '../core/readerBuilder'
import {
  FileText,
  Play,
  CheckCircle2,
  AlertCircle,
  Loader2,
  Download,
  BookOpen,
  X,
  Volume2,
  Zap,
} from 'lucide-vue-next'

const props = defineProps<{
  document: Document
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'open-reader', html: string): void
}>()

const isRunning = ref(false)
const trialMode = ref(false)
const generatedHtml = ref('')

const progress = ref<PipelineProgress>({
  stage: 'idle',
  current: 0,
  total: 0,
  percent: 0,
  message: '准备就绪，点击下方按钮开始流水线',
  logs: [],
})

const stages = [
  { key: 'segment', label: '分段解析' },
  { key: 'terms', label: '术语匹配' },
  { key: 'translate', label: '双语翻译' },
  { key: 'script', label: '讲稿改写' },
  { key: 'audio', label: '语音合成' },
  { key: 'pack', label: '打包自包含' },
]

const currentStageIdx = computed(() => {
  if (progress.value.stage === 'idle') return -1
  if (progress.value.stage === 'done') return 6
  return stages.findIndex((s) => s.key === progress.value.stage)
})

async function startPipeline() {
  if (!settingsState.apiKey && settingsState.llmProvider !== 'custom') {
    alert(`请先在设置中填写 ${settingsState.llmProvider.toUpperCase()} API Key`)
    return
  }

  isRunning.value = true
  generatedHtml.value = ''

  let targetDoc = props.document
  if (trialMode.value) {
    // 试跑仅前 3 个段落
    const slicedSegments = props.document.segments.slice(0, 3)
    targetDoc = {
      ...props.document,
      segments: slicedSegments,
    }
  }

  try {
    const html = await runDocumentPipeline(targetDoc, settingsState, (p) => {
      progress.value = p
    })
    generatedHtml.value = html
  } catch (err: any) {
    console.error(err)
  } finally {
    isRunning.value = false
  }
}

function handleDownload() {
  if (generatedHtml.value) {
    downloadHtml(`${props.document.doc_id}.html`, generatedHtml.value)
  }
}

function handleOpenReader() {
  if (generatedHtml.value) {
    emit('open-reader', generatedHtml.value)
  }
}
</script>

<template>
  <div class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-fade-in">
    <div class="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl w-full max-w-2xl max-h-[90vh] overflow-y-auto shadow-2xl flex flex-col">
      <!-- Header -->
      <div class="sticky top-0 z-10 flex items-center justify-between px-6 py-4 bg-white/95 dark:bg-slate-900/95 backdrop-blur border-b border-slate-100 dark:border-slate-800">
        <div class="flex items-center gap-2">
          <div class="p-2 rounded-lg bg-blue-50 dark:bg-blue-950/60 text-blue-600 dark:text-blue-400">
            <FileText class="w-5 h-5" />
          </div>
          <div>
            <h2 class="text-base font-bold text-slate-900 dark:text-slate-100">制作伴读工作流</h2>
            <p class="text-xs text-slate-500 font-mono">{{ props.document.doc_id }}</p>
          </div>
        </div>
        <button
          v-if="!isRunning"
          @click="emit('close')"
          class="p-2 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 transition"
        >
          <X class="w-5 h-5" />
        </button>
      </div>

      <div class="p-6 space-y-6 flex-1 text-sm">
        <!-- Paper summary info -->
        <div class="p-4 rounded-xl bg-slate-50 dark:bg-slate-800/40 border border-slate-200/60 dark:border-slate-800">
          <div class="font-semibold text-slate-900 dark:text-slate-100 text-sm mb-2 line-clamp-2">
            {{ props.document.title }}
          </div>
          <div class="flex flex-wrap gap-4 text-xs text-slate-500">
            <span>章节数: <strong class="text-slate-700 dark:text-slate-300">{{ props.document.sections.length }}</strong></span>
            <span>总段落: <strong class="text-slate-700 dark:text-slate-300">{{ props.document.segments.length }}</strong></span>
            <span>当前音色: <strong class="text-slate-700 dark:text-slate-300">{{ settingsState.ttsVoice }}</strong></span>
            <span>模型: <strong class="text-slate-700 dark:text-slate-300">{{ settingsState.model }}</strong></span>
          </div>
        </div>

        <!-- Options before start -->
        <div v-if="progress.stage === 'idle'" class="space-y-3">
          <div class="flex items-center gap-4 text-xs text-slate-700 dark:text-slate-300">
            <label class="flex items-center gap-2 cursor-pointer">
              <input type="checkbox" v-model="trialMode" class="rounded text-blue-600 focus:ring-blue-500" />
              <span class="flex items-center gap-1 font-medium text-amber-600 dark:text-amber-400">
                <Zap class="w-3.5 h-3.5" />
                极速试跑模式 (仅前 3 段，验证效果与 API)
              </span>
            </label>
            <label class="flex items-center gap-2 cursor-pointer">
              <input type="checkbox" v-model="settingsState.enableTts" class="rounded text-blue-600 focus:ring-blue-500" />
              <span class="flex items-center gap-1">
                <Volume2 class="w-3.5 h-3.5" />
                生成 Edge-TTS 语音
              </span>
            </label>
          </div>
        </div>

        <!-- Stage Timeline -->
        <div class="space-y-2">
          <div class="flex justify-between items-center text-xs">
            <span class="font-medium text-slate-700 dark:text-slate-300">{{ progress.message }}</span>
            <span class="font-mono text-slate-500">{{ progress.percent }}%</span>
          </div>

          <!-- Progress Bar -->
          <div class="h-2 w-full bg-slate-100 dark:bg-slate-800 rounded-full overflow-hidden">
            <div
              class="h-full bg-blue-600 transition-all duration-300 ease-out"
              :style="{ width: `${progress.percent}%` }"
            ></div>
          </div>

          <!-- Stage Badges -->
          <div class="grid grid-cols-6 gap-1.5 pt-2">
            <div
              v-for="(st, idx) in stages"
              :key="st.key"
              :class="[
                'px-1.5 py-1.5 rounded-lg text-[11px] text-center font-medium transition',
                idx < currentStageIdx
                  ? 'bg-emerald-50 dark:bg-emerald-950/40 text-emerald-600 dark:text-emerald-400'
                  : idx === currentStageIdx
                  ? 'bg-blue-100 dark:bg-blue-900/50 text-blue-600 dark:text-blue-300 animate-pulse'
                  : 'bg-slate-100 dark:bg-slate-800/60 text-slate-400'
              ]"
            >
              {{ st.label }}
            </div>
          </div>
        </div>

        <!-- Real-time Log Console -->
        <div class="space-y-1">
          <div class="text-xs font-semibold text-slate-600 dark:text-slate-400">实时流水线日志</div>
          <div class="bg-slate-900 text-slate-200 font-mono text-xs p-3.5 rounded-xl h-44 overflow-y-auto space-y-1 border border-slate-800 shadow-inner">
            <div v-if="progress.logs.length === 0" class="text-slate-500 italic">
              等待运行指令...
            </div>
            <div
              v-for="(log, idx) in progress.logs"
              :key="idx"
              :class="[
                log.includes('遇阻') || log.includes('失败')
                  ? 'text-rose-400'
                  : log.includes('完成') || log.includes('成功')
                  ? 'text-emerald-400'
                  : 'text-slate-300'
              ]"
            >
              {{ log }}
            </div>
          </div>
        </div>

        <!-- Success Result Actions -->
        <div v-if="progress.stage === 'done'" class="p-4 rounded-xl bg-emerald-50 dark:bg-emerald-950/30 border border-emerald-200 dark:border-emerald-800/50 space-y-3 animate-fade-in">
          <div class="flex items-center gap-2 text-emerald-700 dark:text-emerald-300 font-semibold text-sm">
            <CheckCircle2 class="w-5 h-5" />
            <span>伴读网页构建完成！已持久化至浏览器书架 (IndexedDB)</span>
          </div>
          <div class="flex flex-wrap gap-3 pt-1">
            <button
              @click="handleOpenReader"
              class="px-4 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white font-medium text-xs flex items-center gap-1.5 shadow-sm transition"
            >
              <BookOpen class="w-4 h-4" />
              立即在线伴读
            </button>
            <button
              @click="handleDownload"
              class="px-4 py-2 rounded-xl bg-white dark:bg-slate-800 border border-slate-300 dark:border-slate-700 text-slate-700 dark:text-slate-200 hover:bg-slate-50 dark:hover:bg-slate-700 font-medium text-xs flex items-center gap-1.5 transition"
            >
              <Download class="w-4 h-4" />
              下载自包含 HTML (支持离线/AirDrop)
            </button>
          </div>
        </div>

        <!-- Error State -->
        <div v-if="progress.stage === 'error'" class="p-4 rounded-xl bg-rose-50 dark:bg-rose-950/30 border border-rose-200 dark:border-rose-800 text-rose-700 dark:text-rose-300 flex items-start gap-2 text-xs">
          <AlertCircle class="w-5 h-5 shrink-0 mt-0.5" />
          <div>
            <div class="font-semibold">工作流执行中断</div>
            <div>{{ progress.message }}</div>
          </div>
        </div>
      </div>

      <!-- Footer Buttons -->
      <div class="px-6 py-4 bg-slate-50 dark:bg-slate-800/50 border-t border-slate-100 dark:border-slate-800 flex justify-end items-center gap-3">
        <button
          v-if="!isRunning"
          type="button"
          @click="emit('close')"
          class="px-4 py-2 rounded-xl text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-100 text-xs font-medium"
        >
          {{ progress.stage === 'done' ? '完成' : '取消' }}
        </button>
        <button
          v-if="progress.stage === 'idle'"
          type="button"
          @click="startPipeline"
          class="px-6 py-2.5 rounded-xl bg-blue-600 hover:bg-blue-700 text-white font-medium text-xs shadow-sm flex items-center gap-2 transition"
        >
          <Play class="w-4 h-4 fill-current" />
          {{ trialMode ? '开始极速试跑 (3段)' : '开始全篇工作流' }}
        </button>
        <button
          v-else-if="isRunning"
          disabled
          class="px-6 py-2.5 rounded-xl bg-blue-400 text-white font-medium text-xs flex items-center gap-2 cursor-not-allowed"
        >
          <Loader2 class="w-4 h-4 animate-spin" />
          流水线运行中...
        </button>
      </div>
    </div>
  </div>
</template>
