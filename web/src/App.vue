<script setup lang="ts">
import { ref, onMounted } from 'vue'
import type { Document } from './core/types'
import { segmentHtml } from './core/segmentHtml'
import FeedView from './views/FeedView.vue'
import LibraryView from './views/LibraryView.vue'
import SettingsModal from './components/SettingsModal.vue'
import PipelineModal from './components/PipelineModal.vue'
import ReaderViewModal from './views/ReaderViewModal.vue'
import { getPaperFromLibrary } from './store/library'
import { BookOpen, Settings as SettingsIcon, Newspaper, Library, ShieldCheck } from 'lucide-vue-next'

const currentTab = ref<'feed' | 'library'>('feed')
const showSettings = ref(false)

const activePipelineDoc = ref<Document | null>(null)
const activeReaderHtml = ref<string | null>(null)
const activeReaderTitle = ref<string>('')
const activeReaderDocId = ref<string>('')

const libraryViewRef = ref<any>(null)

function handleSelectDocument(doc: Document) {
  activePipelineDoc.value = doc
}

function handleOpenReader(html: string, title?: string, docId?: string) {
  activeReaderHtml.value = html
  activeReaderTitle.value = title || ''
  activeReaderDocId.value = docId || ''
  activePipelineDoc.value = null
  // Refresh library if it's open
  libraryViewRef.value?.reload?.()
}

async function handleOpenSavedReader(docId: string) {
  const paper = await getPaperFromLibrary(docId)
  if (paper) {
    handleOpenReader(paper.html, paper.title, paper.doc_id)
  }
}

onMounted(() => {
  // 1. 书签小工具传递检查
  const urlParams = new URLSearchParams(window.location.search)
  const importId = urlParams.get('import_doc')
  if (importId) {
    const rawHtml =
      localStorage.getItem('paper_transfer_' + importId) ||
      sessionStorage.getItem('paper_transfer_' + importId)
    if (rawHtml) {
      localStorage.removeItem('paper_transfer_' + importId)
      sessionStorage.removeItem('paper_transfer_' + importId)
      const doc = segmentHtml(rawHtml, importId)
      handleSelectDocument(doc)
      window.history.replaceState({}, '', window.location.pathname)
    }
  }

  // 2. postMessage 监听 (支持从外部窗口/油猴脚本/书签小工具一键推送全文)
  window.addEventListener('message', (event) => {
    if (event.data && event.data.type === 'PAPER_ZH_IMPORT' && event.data.html) {
      const docId = event.data.docId || 'doc_' + Date.now()
      const doc = segmentHtml(event.data.html, docId)
      if (event.data.title && (doc.title === 'Academic Paper' || !doc.title)) {
        doc.title = event.data.title
      }
      handleSelectDocument(doc)
      try {
        ;(event.source as any)?.postMessage({ type: 'PAPER_ZH_IMPORT_ACK' }, '*')
      } catch (e) {
        // ignore
      }
    }
  })
})
</script>

<template>
  <div class="min-h-screen bg-slate-50 dark:bg-slate-950 text-slate-900 dark:text-slate-100 flex flex-col font-sans transition-colors">
    <!-- Top Global Header -->
    <header class="sticky top-0 z-40 bg-white/80 dark:bg-slate-900/80 backdrop-blur-md border-b border-slate-200/80 dark:border-slate-800">
      <div class="max-w-5xl mx-auto px-4 h-16 flex items-center justify-between gap-4">
        <!-- Logo & Title -->
        <div class="flex items-center gap-2.5 cursor-pointer" @click="currentTab = 'feed'">
          <div class="w-9 h-9 rounded-xl bg-gradient-to-tr from-blue-600 to-indigo-500 text-white flex items-center justify-center shadow-md shadow-blue-500/20">
            <BookOpen class="w-5 h-5" />
          </div>
          <div>
            <h1 class="text-sm font-bold tracking-tight text-slate-900 dark:text-slate-100 flex items-center gap-1.5">
              <span>Nature Reviews</span>
              <span class="text-blue-600 dark:text-blue-400 font-semibold">中文伴读</span>
            </h1>
            <p class="text-[10px] text-slate-400 font-medium">双向联动学术精读与口语播客</p>
          </div>
        </div>

        <!-- Navigation Tabs -->
        <nav class="flex items-center bg-slate-100 dark:bg-slate-800/80 p-1 rounded-xl border border-slate-200/50 dark:border-slate-700/50">
          <button
            @click="currentTab = 'feed'"
            :class="[
              'px-3.5 py-1.5 rounded-lg text-xs font-medium flex items-center gap-1.5 transition',
              currentTab === 'feed'
                ? 'bg-white dark:bg-slate-700 text-blue-600 dark:text-blue-400 shadow-sm'
                : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200'
            ]"
          >
            <Newspaper class="w-3.5 h-3.5" />
            <span>文献速览</span>
          </button>
          <button
            @click="currentTab = 'library'"
            :class="[
              'px-3.5 py-1.5 rounded-lg text-xs font-medium flex items-center gap-1.5 transition',
              currentTab === 'library'
                ? 'bg-white dark:bg-slate-700 text-blue-600 dark:text-blue-400 shadow-sm'
                : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200'
            ]"
          >
            <Library class="w-3.5 h-3.5" />
            <span>本地书架</span>
          </button>
        </nav>

        <!-- Setting Button -->
        <div class="flex items-center gap-2">
          <button
            @click="showSettings = true"
            class="px-3 py-1.5 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 hover:bg-slate-50 dark:hover:bg-slate-800 text-slate-700 dark:text-slate-300 text-xs font-medium flex items-center gap-1.5 shadow-sm transition"
          >
            <SettingsIcon class="w-3.5 h-3.5" />
            <span class="hidden sm:inline">配置与模型</span>
          </button>
        </div>
      </div>
    </header>

    <!-- Main Content Area -->
    <main class="flex-1 max-w-5xl w-full mx-auto px-4 py-6 sm:py-8">
      <FeedView
        v-if="currentTab === 'feed'"
        @select-document="handleSelectDocument"
        @open-saved-reader="handleOpenSavedReader"
      />
      <LibraryView
        v-else-if="currentTab === 'library'"
        ref="libraryViewRef"
        @open-reader="handleOpenReader"
        @go-feed="currentTab = 'feed'"
      />
    </main>

    <!-- Global Footer -->
    <footer class="border-t border-slate-200/80 dark:border-slate-800 py-6 text-center text-xs text-slate-400">
      <div class="max-w-5xl mx-auto px-4 flex flex-col sm:flex-row items-center justify-between gap-3">
        <div class="flex items-center gap-1.5">
          <ShieldCheck class="w-4 h-4 text-emerald-500" />
          <span>Local-First 架构 · 零后端服务器存储 · API 密钥与文献 100% 留存浏览器本地</span>
        </div>
        <div>
          <span>可一键部署至 GitHub Pages 免费运行</span>
        </div>
      </div>
    </footer>

    <!-- Modals -->
    <SettingsModal
      v-if="showSettings"
      @close="showSettings = false"
    />

    <PipelineModal
      v-if="activePipelineDoc"
      :document="activePipelineDoc"
      @close="activePipelineDoc = null"
      @open-reader="handleOpenReader"
    />

    <ReaderViewModal
      v-if="activeReaderHtml"
      :html="activeReaderHtml"
      :title="activeReaderTitle"
      :docId="activeReaderDocId"
      @close="activeReaderHtml = null"
    />
  </div>
</template>
