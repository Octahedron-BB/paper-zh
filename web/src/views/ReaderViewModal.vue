<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { X, ExternalLink, Download } from 'lucide-vue-next'
import { downloadHtml } from '../core/readerBuilder'

const props = defineProps<{
  html: string
  title?: string
  docId?: string
}>()

const emit = defineEmits<{
  (e: 'close'): void
}>()

const blobUrl = ref('')

onMounted(() => {
  const blob = new Blob([props.html], { type: 'text/html;charset=utf-8' })
  blobUrl.value = URL.createObjectURL(blob)
})

onUnmounted(() => {
  if (blobUrl.value) {
    URL.revokeObjectURL(blobUrl.value)
  }
})

function openInNewTab() {
  if (blobUrl.value) {
    window.open(blobUrl.value, '_blank')
  }
}

function handleDownload() {
  const filename = props.docId ? `${props.docId}.html` : 'reader.html'
  downloadHtml(filename, props.html)
}
</script>

<template>
  <div class="fixed inset-0 z-50 flex flex-col bg-slate-950 animate-fade-in">
    <!-- Header Controls -->
    <div class="h-12 bg-slate-900 border-b border-slate-800 flex items-center justify-between px-4 text-xs text-slate-300">
      <div class="flex items-center gap-2 overflow-hidden pr-4">
        <span class="font-bold text-blue-400 shrink-0">📖 在线伴读预览</span>
        <span class="truncate text-slate-400">{{ props.title || props.docId || '伴读网页' }}</span>
      </div>

      <div class="flex items-center gap-2 shrink-0">
        <button
          @click="openInNewTab"
          class="px-2.5 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 flex items-center gap-1.5 transition"
          title="在新标签页中打开完整网页"
        >
          <ExternalLink class="w-3.5 h-3.5" />
          <span>新标签页打开</span>
        </button>
        <button
          @click="handleDownload"
          class="px-2.5 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-700 text-white flex items-center gap-1.5 transition"
          title="下载离线 HTML 文件"
        >
          <Download class="w-3.5 h-3.5" />
          <span>下载 HTML</span>
        </button>
        <button
          @click="emit('close')"
          class="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition"
        >
          <X class="w-4 h-4" />
        </button>
      </div>
    </div>

    <!-- Iframe Container -->
    <div class="flex-1 w-full h-[calc(100vh-48px)] bg-slate-900">
      <iframe
        v-if="blobUrl"
        :src="blobUrl"
        class="w-full h-full border-none"
        sandbox="allow-scripts allow-same-origin allow-popups"
      ></iframe>
    </div>
  </div>
</template>
