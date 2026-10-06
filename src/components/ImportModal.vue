<script setup lang="ts">
import { ref, computed } from 'vue'
import type { FeedItem, Document } from '../core/types'
import { segmentHtml } from '../core/segmentHtml'
import { parsePdf } from '../core/pdfParser'
import {
  X,
  ExternalLink,
  UploadCloud,
  Bookmark,
  Copy,
  Check,
  Sparkles,
  HelpCircle,
  Loader2,
  Compass,
} from 'lucide-vue-next'

const props = defineProps<{
  item: FeedItem | null
  isOpen: boolean
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'select-document', doc: Document): void
}>()

const fileInputRef = ref<HTMLInputElement | null>(null)
const isDragging = ref(false)
const isParsing = ref(false)
const parsingMsg = ref('')
const copied = ref(false)
const showBookmarkHelp = ref(false)

// 动态生成适配当前部署地址的书签脚本代码
const bookmarkletCode = computed(() => {
  const currentOrigin = window.location.origin
  const currentPath = window.location.pathname.replace(/\/$/, '')
  const targetUrl = `${currentOrigin}${currentPath}/`

  return `javascript:(function(){try{var t=(document.querySelector('h1')&&document.querySelector('h1').innerText)||document.title;var h=document.documentElement.outerHTML;var u='${targetUrl}';var w=window.open(u,'_blank');if(!w){alert('请在浏览器地址栏允许弹出窗口，以完成文献一键导入！');return;}var c=0;var timer=setInterval(function(){c++;if(c>60||w.closed){clearInterval(timer);return;}w.postMessage({type:'PAPER_ZH_IMPORT',html:h,title:t,url:window.location.href},'*');},500);window.addEventListener('message',function onAck(e){if(e.data&&e.data.type==='PAPER_ZH_IMPORT_ACK'){clearInterval(timer);}});setTimeout(function(){clearInterval(timer);},30000);}catch(e){alert('提取正文失败:'+e.message);}})();`
})

async function copyBookmarklet() {
  try {
    await navigator.clipboard.writeText(bookmarkletCode.value)
    copied.value = true
    setTimeout(() => {
      copied.value = false
    }, 2500)
  } catch (err) {
    alert('复制失败，请手动选择并复制')
  }
}

function handleBookmarkClick() {
  window.alert('请按住此按钮直接拖拽到浏览器的书签栏（Bookmarks Bar）中，即可保存为书签！')
}

function triggerUpload() {
  fileInputRef.value?.click()
}

async function handleFileChange(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (file && props.item) {
    await processFile(file, props.item)
  }
}

async function handleDrop(event: DragEvent) {
  isDragging.value = false
  const file = event.dataTransfer?.files?.[0]
  if (file && props.item) {
    await processFile(file, props.item)
  }
}

async function processFile(file: File, item: FeedItem) {
  isParsing.value = true
  parsingMsg.value = '正在解析文献结构并进行语义分段...'
  try {
    let doc: Document
    if (file.name.endsWith('.html') || file.name.endsWith('.htm')) {
      const htmlText = await file.text()
      doc = segmentHtml(htmlText, item.doc_id)
    } else if (file.name.endsWith('.pdf')) {
      parsingMsg.value = '正在加载 PDF.js 提取正文文本...'
      doc = await parsePdf(file, item.doc_id)
    } else {
      alert('请上传 .html 或 .pdf 格式的学术文献')
      return
    }

    // 绑定精选文献元数据，确保标题和文献 ID 精确无误
    if (item.title_en) {
      doc.title = item.title_en
    }
    doc.doc_id = item.doc_id

    emit('select-document', doc)
    emit('close')
  } catch (err: any) {
    alert(`解析文献失败: ${err.message}`)
  } finally {
    isParsing.value = false
    parsingMsg.value = ''
  }
}

// 备选方案：仅制作摘要伴读
function handleCreateAbstractReader() {
  if (!props.item) return
  const abstractText = props.item.abstract || props.item.detail || props.item.brief
  const doc: Document = {
    doc_id: props.item.doc_id,
    title: props.item.title_en,
    sections: [
      {
        heading: 'Abstract & Overview',
        level: 2,
        slug: 'sec-0',
        sec_path: 'sec-0',
        segments: [
          {
            sid: 'sec-0#p0',
            doc_id: props.item.doc_id,
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
        doc_id: props.item.doc_id,
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
  emit('close')
}
</script>

<template>
  <div
    v-if="isOpen && item"
    class="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-4 bg-slate-900/60 backdrop-blur-sm animate-fade-in"
    @click.self="emit('close')"
  >
    <div
      class="bg-white dark:bg-slate-900 w-full max-w-2xl rounded-2xl shadow-2xl border border-slate-200 dark:border-slate-800 flex flex-col max-h-[92vh] overflow-hidden"
    >
      <!-- Header -->
      <div
        class="px-5 py-4 border-b border-slate-200 dark:border-slate-800 flex items-start justify-between gap-4 bg-slate-50/50 dark:bg-slate-900/50"
      >
        <div class="space-y-1">
          <div class="flex items-center gap-2">
            <span
              class="px-2 py-0.5 text-[10px] font-bold rounded bg-blue-100 dark:bg-blue-900/60 text-blue-700 dark:text-blue-300 uppercase tracking-wider"
            >
              {{ item.journal }}
            </span>
            <span class="text-xs text-slate-400 font-mono">DOI: {{ item.doi }}</span>
          </div>
          <h3 class="text-sm sm:text-base font-bold text-slate-900 dark:text-slate-100 line-clamp-2 leading-snug">
            {{ item.title_zh || item.title_en }}
          </h3>
          <p class="text-xs text-slate-500 font-serif italic line-clamp-1">
            {{ item.title_en }}
          </p>
        </div>

        <button
          @click="emit('close')"
          class="text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 p-1 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 transition shrink-0"
        >
          <X class="w-5 h-5" />
        </button>
      </div>

      <!-- Body Content -->
      <div class="p-5 overflow-y-auto space-y-6 text-xs sm:text-sm">
        <!-- 核心提示 -->
        <div class="p-3.5 rounded-xl bg-blue-50/60 dark:bg-blue-950/30 border border-blue-200/70 dark:border-blue-900/50 flex gap-3 text-blue-900 dark:text-blue-200 text-xs leading-relaxed">
          <Compass class="w-4 h-4 text-blue-600 dark:text-blue-400 shrink-0 mt-0.5" />
          <p>
            由于顶刊正文处于学术版权保护下，需通过机构/校园网权限获取全文。请先访问原刊获取文件，随后拖入下方即可一键开启全文伴读流水线。
          </p>
        </div>

        <!-- 步骤 1：前往原刊 -->
        <div class="space-y-2">
          <div class="flex items-center justify-between">
            <div class="font-bold text-slate-900 dark:text-slate-100 flex items-center gap-2">
              <span class="w-5 h-5 rounded-full bg-blue-600 text-white text-[11px] font-bold flex items-center justify-center shrink-0">1</span>
              <span>直达原刊获取全文 (HTML / PDF)</span>
            </div>
            <span class="text-[11px] text-slate-400">支持机构 VPN / CARSI 认证</span>
          </div>

          <div class="p-3.5 rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50/70 dark:bg-slate-800/40 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
            <div class="space-y-0.5">
              <div class="text-xs font-semibold text-slate-800 dark:text-slate-200">
                Nature 官方文章链接
              </div>
              <div class="text-[11px] text-slate-500">
                支持在网页空白处右键『存储为 / 另存为』网页 HTML，或直接下载 PDF
              </div>
            </div>

            <a
              :href="`https://doi.org/${item.doi}`"
              target="_blank"
              class="px-4 py-2 rounded-xl bg-slate-900 hover:bg-black dark:bg-slate-100 dark:hover:bg-white text-white dark:text-slate-900 font-medium text-xs flex items-center gap-1.5 shadow-sm transition shrink-0"
            >
              <span>前往原刊页面</span>
              <ExternalLink class="w-3.5 h-3.5" />
            </a>
          </div>
        </div>

        <!-- 步骤 2：拖拽上传 (核心入口) -->
        <div class="space-y-2">
          <div class="font-bold text-slate-900 dark:text-slate-100 flex items-center gap-2">
            <span class="w-5 h-5 rounded-full bg-blue-600 text-white text-[11px] font-bold flex items-center justify-center shrink-0">2</span>
            <span>拖拽上传已下载的文献文件</span>
          </div>

          <div
            @dragover.prevent="isDragging = true"
            @dragleave.prevent="isDragging = false"
            @drop.prevent="handleDrop"
            @click="triggerUpload"
            :class="[
              'p-6 sm:p-7 rounded-2xl border-2 border-dashed cursor-pointer transition text-center space-y-2.5 relative',
              isDragging
                ? 'border-blue-500 bg-blue-50/70 dark:bg-blue-950/40 scale-[1.01]'
                : 'border-slate-300 dark:border-slate-700 bg-slate-50/40 dark:bg-slate-800/20 hover:border-blue-400 hover:bg-blue-50/30 dark:hover:bg-blue-950/20'
            ]"
          >
            <input
              ref="fileInputRef"
              type="file"
              accept=".html,.htm,.pdf"
              class="hidden"
              @change="handleFileChange"
            />

            <div v-if="isParsing" class="py-4 space-y-2">
              <Loader2 class="w-8 h-8 text-blue-600 animate-spin mx-auto" />
              <p class="text-xs font-medium text-slate-700 dark:text-slate-300">{{ parsingMsg }}</p>
            </div>

            <template v-else>
              <div class="w-10 h-10 rounded-xl bg-blue-100 dark:bg-blue-900/60 text-blue-600 dark:text-blue-300 flex items-center justify-center mx-auto">
                <UploadCloud class="w-5 h-5" />
              </div>
              <div>
                <p class="text-xs sm:text-sm font-semibold text-slate-800 dark:text-slate-200">
                  点击选择文件，或直接拖拽至此处
                </p>
                <p class="text-[11px] text-slate-400 mt-0.5">
                  支持 Nature 原网页另存的 .html（强烈推荐，天然保留段落与图注）或原版 .pdf
                </p>
              </div>
            </template>
          </div>
        </div>

        <!-- 步骤 3：极客捷径：书签小工具 (Bookmarklet) -->
        <div class="space-y-2.5 pt-2 border-t border-slate-100 dark:border-slate-800">
          <div class="flex items-center justify-between">
            <div class="font-bold text-slate-900 dark:text-slate-100 flex items-center gap-2">
              <span class="w-5 h-5 rounded-full bg-indigo-600 text-white text-[11px] font-bold flex items-center justify-center shrink-0">3</span>
              <span>极客捷径：浏览器书签小工具 (免手动下载)</span>
            </div>
            <button
              @click="showBookmarkHelp = !showBookmarkHelp"
              class="text-[11px] text-indigo-600 dark:text-indigo-400 hover:underline flex items-center gap-1 font-medium"
            >
              <HelpCircle class="w-3.5 h-3.5" />
              <span>{{ showBookmarkHelp ? '收起说明' : '如何使用？' }}</span>
            </button>
          </div>

          <div class="p-3.5 rounded-xl border border-indigo-100 dark:border-indigo-900/60 bg-indigo-50/40 dark:bg-indigo-950/20 space-y-3">
            <div class="flex flex-wrap items-center gap-2.5">
              <!-- 可拖拽的书签链接 -->
              <a
                :href="bookmarkletCode"
                title="拖拽此按钮至浏览器书签栏"
                @click.prevent="handleBookmarkClick"
                class="px-3.5 py-1.5 rounded-xl bg-indigo-600 hover:bg-indigo-700 text-white text-xs font-semibold shadow-sm flex items-center gap-1.5 cursor-grab active:cursor-grabbing transition"
              >
                <Bookmark class="w-3.5 h-3.5" />
                <span>📌 伴读一键导入 (拖拽至书签栏)</span>
              </a>

              <!-- 复制脚本按钮 -->
              <button
                @click="copyBookmarklet"
                class="px-3 py-1.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 hover:bg-slate-50 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-300 text-xs font-medium flex items-center gap-1.5 transition"
              >
                <Check v-if="copied" class="w-3.5 h-3.5 text-emerald-500" />
                <Copy v-else class="w-3.5 h-3.5 text-slate-400" />
                <span>{{ copied ? '已复制脚本代码' : '复制书签代码' }}</span>
              </button>
            </div>

            <!-- 使用说明折叠区 -->
            <div v-if="showBookmarkHelp" class="text-[11px] text-slate-600 dark:text-slate-400 space-y-1.5 pt-2 border-t border-indigo-100/70 dark:border-indigo-900/40">
              <div class="flex items-start gap-1.5">
                <span class="font-bold text-indigo-600 dark:text-indigo-400">① 保存书签：</span>
                <span>直接将上方的紫色按钮拖入浏览器的书签栏（或右键收藏夹 ➔ 新建书签 ➔ 网址粘贴复制的代码）。</span>
              </div>
              <div class="flex items-start gap-1.5">
                <span class="font-bold text-indigo-600 dark:text-indigo-400">② 打开论文：</span>
                <span>在校园网/VPN 环境下正常打开任意 Nature 或期刊论文的完整正文页面。</span>
              </div>
              <div class="flex items-start gap-1.5">
                <span class="font-bold text-indigo-600 dark:text-indigo-400">③ 点击导入：</span>
                <span>在论文网页点击书签栏上的『伴读一键导入』，将自动抓取当前页面 DOM 并跳回本站开启制作！</span>
              </div>
            </div>
          </div>
        </div>

        <!-- 备选：仅制作摘要伴读 -->
        <div class="pt-2 flex items-center justify-between text-xs text-slate-400">
          <span>暂无全文下载权限？</span>
          <button
            @click="handleCreateAbstractReader"
            class="text-blue-600 dark:text-blue-400 hover:underline font-medium flex items-center gap-1"
          >
            <Sparkles class="w-3.5 h-3.5" />
            <span>仅针对 PubMed 摘要制作伴读 (约2分钟)</span>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
