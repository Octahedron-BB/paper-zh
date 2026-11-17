<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { getAllSavedPapers, deletePaperFromLibrary, type SavedPaper } from '../store/library'
import { downloadHtml } from '../core/readerBuilder'
import {
  BookOpen,
  Download,
  Trash2,
  Calendar,
  Layers,
  Volume2,
  Inbox,
  Sparkles,
} from 'lucide-vue-next'

const emit = defineEmits<{
  (e: 'open-reader', html: string, title?: string, docId?: string): void
  (e: 'go-feed'): void
}>()

const papers = ref<SavedPaper[]>([])
const loading = ref(true)

async function loadLibrary() {
  loading.value = true
  try {
    papers.value = await getAllSavedPapers()
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  loadLibrary()
})

async function handleDelete(docId: string, title: string) {
  if (confirm(`确定要从本地书架移除《${title}》吗？`)) {
    await deletePaperFromLibrary(docId)
    await loadLibrary()
  }
}

function handleDownload(paper: SavedPaper) {
  downloadHtml(`${paper.doc_id}.html`, paper.html)
}

function handleOpen(paper: SavedPaper) {
  emit('open-reader', paper.html, paper.title, paper.doc_id)
}

function formatDuration(sec?: number): string {
  if (!sec) return ''
  const m = Math.floor(sec / 60)
  const s = Math.floor(sec % 60)
  return `${m}m ${s}s`
}

defineExpose({
  reload: loadLibrary,
})
</script>

<template>
  <div class="space-y-6">
    <div class="flex items-center justify-between">
      <div>
        <h2 class="text-base sm:text-lg font-bold text-slate-900 dark:text-slate-100">
          本地伴读书架 (Local Library)
        </h2>
        <p class="text-xs text-slate-500">
          存储于浏览器本地 IndexedDB，随时离线播放与查阅
        </p>
      </div>

      <span class="text-xs text-slate-400 font-mono">
        共 {{ papers.length }} 篇已生成
      </span>
    </div>

    <!-- Empty State -->
    <div
      v-if="!loading && papers.length === 0"
      class="p-12 text-center rounded-2xl border border-dashed border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 space-y-4"
    >
      <div class="w-12 h-12 mx-auto rounded-2xl bg-slate-100 dark:bg-slate-800 text-slate-400 flex items-center justify-center">
        <Inbox class="w-6 h-6" />
      </div>
      <div>
        <h3 class="font-semibold text-slate-800 dark:text-slate-200 text-sm">书架暂无文献</h3>
        <p class="text-xs text-slate-400 mt-1">从首页速览中选择文献，或上传 PDF/HTML 运行工作流生成伴读</p>
      </div>
      <button
        @click="emit('go-feed')"
        class="px-4 py-2 rounded-xl bg-blue-600 hover:bg-blue-700 text-white font-medium text-xs shadow-sm transition inline-flex items-center gap-1.5"
      >
        <Sparkles class="w-4 h-4" />
        浏览速览流去制作
      </button>
    </div>

    <!-- Library Grid -->
    <div v-else class="grid grid-cols-1 md:grid-cols-2 gap-4">
      <div
        v-for="paper in papers"
        :key="paper.doc_id"
        class="p-5 rounded-2xl border border-slate-200/80 dark:border-slate-800 bg-white dark:bg-slate-900 hover:border-blue-300 dark:hover:border-blue-900/60 shadow-sm transition space-y-3 flex flex-col justify-between"
      >
        <div class="space-y-2">
          <div class="flex items-center justify-between text-xs text-slate-400">
            <span class="font-mono text-[11px]">{{ paper.doc_id }}</span>
            <span class="flex items-center gap-1 text-[11px]">
              <Calendar class="w-3 h-3" />
              {{ new Date(paper.createdAt).toLocaleDateString() }}
            </span>
          </div>

          <h3 class="font-bold text-slate-900 dark:text-slate-100 text-sm leading-snug line-clamp-2">
            {{ paper.title }}
          </h3>

          <div class="flex flex-wrap gap-2 text-[11px]">
            <span class="px-2 py-0.5 rounded-md bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 flex items-center gap-1">
              <Layers class="w-3 h-3" />
              {{ paper.segCount }} 段
            </span>
            <span
              v-if="paper.hasAudio"
              class="px-2 py-0.5 rounded-md bg-emerald-50 dark:bg-emerald-950/60 text-emerald-600 dark:text-emerald-400 font-medium flex items-center gap-1"
            >
              <Volume2 class="w-3 h-3" />
              音频 {{ formatDuration(paper.durationSec) }}
            </span>
            <span
              v-else
              class="px-2 py-0.5 rounded-md bg-slate-100 dark:bg-slate-800 text-slate-400"
            >
              纯文本伴读
            </span>
          </div>
        </div>

        <!-- Actions -->
        <div class="pt-3 border-t border-slate-100 dark:border-slate-800 flex items-center justify-between">
          <button
            @click="handleDelete(paper.doc_id, paper.title)"
            class="p-1.5 text-slate-400 hover:text-rose-600 rounded-lg transition"
            title="从书架移除"
          >
            <Trash2 class="w-4 h-4" />
          </button>

          <div class="flex items-center gap-2">
            <button
              @click="handleDownload(paper)"
              class="px-3 py-1.5 rounded-xl border border-slate-200 dark:border-slate-700 text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800 text-xs font-medium flex items-center gap-1 transition"
              title="导出单文件 HTML"
            >
              <Download class="w-3.5 h-3.5" />
              <span>导出</span>
            </button>
            <button
              @click="handleOpen(paper)"
              class="px-3.5 py-1.5 rounded-xl bg-blue-600 hover:bg-blue-700 text-white font-medium text-xs flex items-center gap-1.5 shadow-sm transition"
            >
              <BookOpen class="w-3.5 h-3.5" />
              <span>立即阅读</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
