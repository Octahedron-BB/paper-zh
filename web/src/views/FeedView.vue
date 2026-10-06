<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import type { Document, FeedItem } from '../core/types'
import { fetchPubMedReviews, PRESET_PAPERS } from '../core/pubmed'
import { segmentHtml } from '../core/segmentHtml'
import { parsePdf } from '../core/pdfParser'
import { getAllSavedPapers } from '../store/library'
import {
  Search,
  RefreshCw,
  UploadCloud,
  FileText,
  Sparkles,
  ChevronDown,
  ChevronUp,
  CheckCircle2,
  ExternalLink,
  BookOpen,
} from 'lucide-vue-next'

const emit = defineEmits<{
  (e: 'select-document', doc: Document): void
  (e: 'open-saved-reader', docId: string): void
}>()

const items = ref<FeedItem[]>([])
const loading = ref(false)
const searchQuery = ref('')
const expandedDoi = ref<Record<string, boolean>>({})
const savedDocIds = ref<Set<string>>(new Set())

async function refreshSavedStatus() {
  const saved = await getAllSavedPapers()
  savedDocIds.value = new Set(saved.map((p) => p.doc_id))
}

onMounted(async () => {
  items.value = PRESET_PAPERS
  await refreshSavedStatus()
})

const filteredItems = computed(() => {
  const q = searchQuery.value.trim().toLowerCase()
  if (!q) return items.value
  return items.value.filter(
    (item) =>
      item.title_en.toLowerCase().includes(q) ||
      item.title_zh.toLowerCase().includes(q) ||
      item.journal.toLowerCase().includes(q) ||
      item.brief.toLowerCase().includes(q) ||
      item.doc_id.toLowerCase().includes(q)
  )
})

async function handleRefreshPubMed() {
  loading.value = true
  try {
    const list = await fetchPubMedReviews('"Nat Rev*"[jour]', 60)
    items.value = list
  } finally {
    loading.value = false
  }
}

function toggleExpand(doi: string) {
  expandedDoi.value[doi] = !expandedDoi.value[doi]
}

// 文件上传 (HTML / PDF)
const fileInputRef = ref<HTMLInputElement | null>(null)
const isDragging = ref(false)

function triggerUpload() {
  fileInputRef.value?.click()
}

async function handleFileChange(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (file) {
    await processFile(file)
  }
}

async function handleDrop(event: DragEvent) {
  isDragging.value = false
  const file = event.dataTransfer?.files?.[0]
  if (file) {
    await processFile(file)
  }
}

async function processFile(file: File) {
  const docId = file.name.replace(/\.[^/.]+$/, '')
  try {
    if (file.name.endsWith('.html') || file.name.endsWith('.htm')) {
      const htmlText = await file.text()
      const doc = segmentHtml(htmlText, docId)
      emit('select-document', doc)
    } else if (file.name.endsWith('.pdf')) {
      const doc = await parsePdf(file, docId)
      emit('select-document', doc)
    } else {
      alert('请上传 .html 或 .pdf 格式的学术文献')
    }
  } catch (err: any) {
    alert(`解析文件失败: ${err.message}`)
  }
}

// 针对精选文献点击“制作伴读”
function handleActionForFeedItem(item: FeedItem) {
  if (savedDocIds.value.has(item.doc_id)) {
    emit('open-saved-reader', item.doc_id)
    return
  }

  // 虚拟构建一个基础文献结构（若无本地全文，以摘要为示范）
  const abstractText = item.abstract || item.detail || item.brief
  const doc: Document = {
    doc_id: item.doc_id,
    title: item.title_en,
    sections: [
      {
        heading: 'Abstract & Overview',
        level: 2,
        slug: 'sec-0',
        sec_path: 'sec-0',
        segments: [
          {
            sid: 'sec-0#p0',
            doc_id: item.doc_id,
            sec_path: 'sec-0',
            sec_heading: 'Abstract & Overview',
            sec_level: 2,
            index: 0,
            page: 1,
            src_text: abstractText,
            n_words: abstractText.split(/\s+/).length,
          },
        ],
      },
    ],
    segments: [
      {
        sid: 'sec-0#p0',
        doc_id: item.doc_id,
        sec_path: 'sec-0',
        sec_heading: 'Abstract & Overview',
        sec_level: 2,
        index: 0,
        page: 1,
        src_text: abstractText,
        n_words: abstractText.split(/\s+/).length,
      },
    ],
  }

  emit('select-document', doc)
}
</script>

<template>
  <div class="space-y-6">
    <!-- Top Banner & Upload Dropzone -->
    <div
      @dragover.prevent="isDragging = true"
      @dragleave.prevent="isDragging = false"
      @drop.prevent="handleDrop"
      :class="[
        'p-6 sm:p-8 rounded-2xl border-2 border-dashed transition-all relative overflow-hidden',
        isDragging
          ? 'border-blue-500 bg-blue-50/70 dark:bg-blue-950/30'
          : 'border-slate-200 dark:border-slate-800 bg-gradient-to-br from-white to-slate-50 dark:from-slate-900 dark:to-slate-900/60'
      ]"
    >
      <input
        ref="fileInputRef"
        type="file"
        accept=".html,.htm,.pdf"
        class="hidden"
        @change="handleFileChange"
      />

      <div class="max-w-2xl mx-auto text-center space-y-3">
        <div class="w-12 h-12 mx-auto rounded-2xl bg-blue-50 dark:bg-blue-950/60 text-blue-600 dark:text-blue-400 flex items-center justify-center shadow-sm">
          <UploadCloud class="w-6 h-6" />
        </div>
        <h2 class="text-base sm:text-lg font-bold text-slate-900 dark:text-slate-100">
          拖拽上传 Nature 论文 HTML / PDF 全文
        </h2>
        <p class="text-xs text-slate-500 dark:text-slate-400">
          推荐使用从期刊官网保存的完整 HTML 网页（保留公式、图注与天然段落结构）；也支持 PDF 自动分段提取。
        </p>
        <div class="pt-2 flex justify-center gap-3">
          <button
            @click="triggerUpload"
            class="px-5 py-2.5 rounded-xl bg-blue-600 hover:bg-blue-700 text-white font-medium text-xs shadow-md shadow-blue-500/20 transition flex items-center gap-2"
          >
            <FileText class="w-4 h-4" />
            选择本地文献文件
          </button>
        </div>
      </div>
    </div>

    <!-- Toolbar: Search & Refresh -->
    <div class="flex flex-col sm:flex-row justify-between items-stretch sm:items-center gap-3">
      <div class="relative flex-1 max-w-md">
        <Search class="w-4 h-4 text-slate-400 absolute left-3.5 top-1/2 -translate-y-1/2" />
        <input
          type="text"
          v-model="searchQuery"
          placeholder="搜索文献标题、疾病、术语或 DOI..."
          class="w-full pl-9 pr-4 py-2 text-xs rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-100 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
      </div>

      <div class="flex items-center gap-2">
        <button
          @click="handleRefreshPubMed"
          :disabled="loading"
          class="px-3.5 py-2 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800 text-xs font-medium flex items-center gap-1.5 transition"
        >
          <RefreshCw :class="['w-3.5 h-3.5', loading ? 'animate-spin text-blue-500' : '']" />
          <span>PubMed 实时流刷新</span>
        </button>
      </div>
    </div>

    <!-- Literature Cards Feed -->
    <div class="space-y-4">
      <div
        v-for="item in filteredItems"
        :key="item.doi || item.doc_id"
        class="p-5 rounded-2xl border border-slate-200/80 dark:border-slate-800 bg-white dark:bg-slate-900 hover:border-blue-300 dark:hover:border-blue-900/60 hover:shadow-lg hover:shadow-slate-100 dark:hover:shadow-none transition-all space-y-3"
      >
        <!-- Card Top Meta -->
        <div class="flex flex-wrap items-center justify-between gap-2 text-xs">
          <div class="flex items-center gap-2">
            <span class="px-2.5 py-0.5 rounded-full bg-blue-50 dark:bg-blue-950/60 text-blue-600 dark:text-blue-400 font-semibold text-[11px]">
              {{ item.journal }}
            </span>
            <span class="text-slate-400">{{ item.pub_date }}</span>
          </div>

          <div class="flex items-center gap-2">
            <span v-if="savedDocIds.has(item.doc_id)" class="px-2 py-0.5 rounded-full bg-emerald-50 dark:bg-emerald-950/60 text-emerald-600 dark:text-emerald-400 text-[11px] font-medium flex items-center gap-1">
              <CheckCircle2 class="w-3 h-3" />
              已生成伴读
            </span>
            <span class="font-mono text-[11px] text-slate-400">ID: {{ item.doc_id }}</span>
          </div>
        </div>

        <!-- Titles -->
        <div>
          <h3 class="text-base font-bold text-slate-900 dark:text-slate-100 leading-snug">
            {{ item.title_zh || item.title_en }}
          </h3>
          <p class="text-xs text-slate-500 font-serif mt-1">
            {{ item.title_en }}
          </p>
        </div>

        <!-- Brief -->
        <p class="text-xs text-slate-600 dark:text-slate-300 leading-relaxed bg-slate-50 dark:bg-slate-800/40 p-3 rounded-xl border border-slate-100 dark:border-slate-800/60">
          {{ item.brief }}
        </p>

        <!-- Detail Accordion -->
        <div v-if="expandedDoi[item.doi || item.doc_id]" class="text-xs text-slate-600 dark:text-slate-400 space-y-2 pt-1 border-t border-slate-100 dark:border-slate-800 animate-fade-in">
          <div class="font-medium text-slate-700 dark:text-slate-300">📌 详细病理机制与要点:</div>
          <p class="leading-relaxed bg-blue-50/40 dark:bg-blue-950/20 p-2.5 rounded-lg border-l-2 border-blue-500">
            {{ item.detail }}
          </p>
          <div v-if="item.abstract" class="pt-1">
            <div class="text-[11px] font-semibold text-slate-400">ABSTRACT:</div>
            <p class="text-[11px] text-slate-500 font-serif leading-relaxed mt-0.5">
              {{ item.abstract }}
            </p>
          </div>
        </div>

        <!-- Card Footer Actions -->
        <div class="flex items-center justify-between pt-2">
          <button
            @click="toggleExpand(item.doi || item.doc_id)"
            class="text-xs text-slate-500 hover:text-slate-700 dark:hover:text-slate-300 flex items-center gap-1 transition"
          >
            <span>{{ expandedDoi[item.doi || item.doc_id] ? '收起详情' : '展开详释' }}</span>
            <ChevronUp v-if="expandedDoi[item.doi || item.doc_id]" class="w-3.5 h-3.5" />
            <ChevronDown v-else class="w-3.5 h-3.5" />
          </button>

          <div class="flex items-center gap-2">
            <a
              v-if="item.doi"
              :href="`https://doi.org/${item.doi}`"
              target="_blank"
              class="px-2.5 py-1.5 rounded-lg text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 text-xs flex items-center gap-1 transition"
            >
              <span>原刊链接</span>
              <ExternalLink class="w-3 h-3" />
            </a>

            <button
              v-if="savedDocIds.has(item.doc_id)"
              @click="emit('open-saved-reader', item.doc_id)"
              class="px-3.5 py-1.5 rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white font-medium text-xs flex items-center gap-1.5 shadow-sm transition"
            >
              <BookOpen class="w-3.5 h-3.5" />
              <span>打开伴读</span>
            </button>
            <button
              v-else
              @click="handleActionForFeedItem(item)"
              class="px-3.5 py-1.5 rounded-xl bg-blue-600 hover:bg-blue-700 text-white font-medium text-xs flex items-center gap-1.5 shadow-sm shadow-blue-500/20 transition"
            >
              <Sparkles class="w-3.5 h-3.5" />
              <span>制作伴读</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
