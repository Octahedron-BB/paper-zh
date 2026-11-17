<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import type { Term, Document } from '../core/types'
import { settingsState } from '../store/settings'
import { getAllSavedPapers, type SavedPaper } from '../store/library'
import {
  getGlobalTerms,
  getDocTerms,
  saveGlobalTerms,
  saveDocTerms,
} from '../store/glossaryStore'
import { extractTermsWithLlm, type ExtractedTermCandidate } from '../core/termExtractor'
import { segmentHtml } from '../core/segmentHtml'
import {
  Sparkles,
  X,
  Loader2,
  FileText,
  Check,
  AlertCircle,
  Plus,
  ArrowRight,
  RotateCcw,
  BookOpen,
} from 'lucide-vue-next'

const props = defineProps<{
  initialDocId?: string
  initialDocTitle?: string
  initialDoc?: Document
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'imported', target: 'global' | string, count: number): void
}>()

// 1. 来源选项
const sourceType = ref<'library' | 'text' | 'current'>(props.initialDoc ? 'current' : 'library')
const savedPapers = ref<SavedPaper[]>([])
const selectedDocId = ref<string>(props.initialDocId || '')
const customText = ref<string>('')
const customTitle = ref<string>(props.initialDocTitle || '')

// 2. 提炼状态
const isExtracting = ref(false)
const extractError = ref<string | null>(null)
const candidates = ref<ExtractedTermCandidate[]>([])
const step = ref<'config' | 'review'>('config')

// 3. 目标导入位置
const targetScope = ref<'global' | 'doc'>(props.initialDocId ? 'doc' : 'global')
const targetDocId = ref<string>(props.initialDocId || '')
const targetDocTitle = ref<string>(props.initialDocTitle || '')

// 4. 重复检测对比缓存
const existingGlobalTerms = ref<Term[]>([])
const existingDocTerms = ref<Term[]>([])

const isImporting = ref(false)

onMounted(async () => {
  try {
    savedPapers.value = await getAllSavedPapers()
    if (!selectedDocId.value && savedPapers.value.length > 0) {
      selectedDocId.value = savedPapers.value[0].doc_id
    }
    existingGlobalTerms.value = await getGlobalTerms()
    if (targetDocId.value) {
      existingDocTerms.value = await getDocTerms(targetDocId.value)
    }
  } catch (e) {
    console.error('加载文献或术语缓存失败:', e)
  }
})

// 当前选中文献对象
const selectedPaper = computed(() => {
  return savedPapers.value.find((p) => p.doc_id === selectedDocId.value)
})

// 全选状态
const isAllSelected = computed({
  get: () => candidates.value.length > 0 && candidates.value.every((c) => c.selected),
  set: (val: boolean) => {
    candidates.value.forEach((c) => {
      c.selected = val
    })
  },
})

const selectedCount = computed(() => {
  return candidates.value.filter((c) => c.selected).length
})

// 检查某个候选词是否已存在于目标术语表中
function isTermDuplicate(termStr: string): boolean {
  const t = termStr.toLowerCase().trim()
  if (targetScope.value === 'global') {
    return existingGlobalTerms.value.some((x) => x.term.toLowerCase().trim() === t)
  } else {
    return existingDocTerms.value.some((x) => x.term.toLowerCase().trim() === t)
  }
}

async function handleStartExtraction() {
  isExtracting.value = true
  extractError.value = null

  try {
    let inputDoc: Document | undefined = undefined
    let inputText = ''
    let title = ''

    if (sourceType.value === 'current' && props.initialDoc) {
      inputDoc = props.initialDoc
      title = props.initialDoc.title
    } else if (sourceType.value === 'library' && selectedPaper.value) {
      const p = selectedPaper.value
      title = p.title
      if (p.html) {
        inputDoc = segmentHtml(p.html, p.doc_id)
      } else {
        inputText = p.title
      }
    } else {
      inputText = customText.value.trim()
      title = customTitle.value.trim() || '自定义文本'
    }

    if (!inputDoc && !inputText.trim()) {
      throw new Error('请选择一篇文献或粘贴待分析学术文本')
    }

    // 更新目标文献的默认标题和 ID
    if (inputDoc) {
      targetDocId.value = inputDoc.doc_id
      targetDocTitle.value = inputDoc.title
    } else if (selectedPaper.value) {
      targetDocId.value = selectedPaper.value.doc_id
      targetDocTitle.value = selectedPaper.value.title
    }

    const results = await extractTermsWithLlm({
      doc: inputDoc,
      text: inputText,
      title,
    })

    if (!results || results.length === 0) {
      throw new Error('LLM 未能提炼出新的术语，请检查输入内容或稍后重试')
    }

    // 预判重复项
    results.forEach((c) => {
      c.isDuplicate = isTermDuplicate(c.term)
    })

    candidates.value = results
    step.value = 'review'
  } catch (err: any) {
    extractError.value = err.message || '提炼术语失败'
  } finally {
    isExtracting.value = false
  }
}

async function handleConfirmImport() {
  const chosen = candidates.value.filter((c) => c.selected)
  if (chosen.length === 0) {
    alert('请至少勾选一条要导入的术语')
    return
  }

  isImporting.value = true
  try {
    const cleanTerms: Term[] = chosen.map((c) => ({
      term: c.term.trim(),
      zh: c.zh.trim(),
      mode: c.mode,
      note: c.note?.trim() || undefined,
      aliases: c.aliases && c.aliases.length > 0 ? c.aliases : undefined,
    }))

    if (targetScope.value === 'global') {
      const current = await getGlobalTerms()
      const termMap = new Map<string, Term>()
      // 现有条目
      current.forEach((t) => termMap.set(t.term.toLowerCase().trim(), t))
      // 新条目（覆盖或新增）
      cleanTerms.forEach((t) => termMap.set(t.term.toLowerCase().trim(), t))

      await saveGlobalTerms(Array.from(termMap.values()))
      emit('imported', 'global', cleanTerms.length)
    } else {
      const docId = targetDocId.value.trim() || 'doc_' + Date.now()
      const current = await getDocTerms(docId)
      const termMap = new Map<string, Term>()
      current.forEach((t) => termMap.set(t.term.toLowerCase().trim(), t))
      cleanTerms.forEach((t) => termMap.set(t.term.toLowerCase().trim(), t))

      await saveDocTerms(docId, Array.from(termMap.values()), targetDocTitle.value || docId)
      emit('imported', docId, cleanTerms.length)
    }

    emit('close')
  } catch (err: any) {
    alert(`导入失败: ${err.message}`)
  } finally {
    isImporting.value = false
  }
}
</script>

<template>
  <div class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-fade-in">
    <div
      class="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl w-full max-w-3xl max-h-[92vh] overflow-hidden shadow-2xl flex flex-col"
      @click.stop
    >
      <!-- Header -->
      <div class="flex items-center justify-between px-6 py-4 bg-white/95 dark:bg-slate-900/95 backdrop-blur border-b border-slate-100 dark:border-slate-800 shrink-0">
        <div class="flex items-center gap-2.5">
          <div class="p-2 rounded-xl bg-gradient-to-tr from-purple-500 to-indigo-500 text-white shadow-md shadow-purple-500/20">
            <Sparkles class="w-5 h-5" />
          </div>
          <div>
            <h2 class="text-base font-bold text-slate-900 dark:text-slate-100 flex items-center gap-2">
              <span>LLM 智能提炼学术术语</span>
              <span class="text-xs px-2 py-0.5 rounded-full bg-purple-50 dark:bg-purple-950/50 text-purple-600 dark:text-purple-300 font-medium border border-purple-200 dark:border-purple-800">
                {{ settingsState.llmProvider.toUpperCase() }} 模型驱动
              </span>
            </h2>
            <p class="text-xs text-slate-500">
              {{ step === 'config' ? '选择文献或文本来源，自动识别领域核心专有名词与缩写' : '审核候选术语并一键批量导入术语表' }}
            </p>
          </div>
        </div>
        <button
          type="button"
          @click="emit('close')"
          class="p-2 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 transition"
        >
          <X class="w-5 h-5" />
        </button>
      </div>

      <!-- Step 1: Configuration -->
      <div v-if="step === 'config'" class="p-6 space-y-5 overflow-y-auto flex-1 text-sm">
        <!-- 来源类型切换 -->
        <div class="space-y-2">
          <label class="block text-xs font-semibold text-slate-700 dark:text-slate-300">
            1. 选择待提炼内容来源
          </label>
          <div class="grid grid-cols-2 sm:grid-cols-3 gap-2">
            <button
              v-if="props.initialDoc"
              type="button"
              @click="sourceType = 'current'"
              :class="[
                'p-3 rounded-xl border text-left flex flex-col gap-1 transition',
                sourceType === 'current'
                  ? 'border-purple-500 bg-purple-50/50 dark:bg-purple-950/30 ring-1 ring-purple-500'
                  : 'border-slate-200 dark:border-slate-800 hover:border-slate-300'
              ]"
            >
              <div class="font-medium text-xs text-slate-900 dark:text-slate-100 flex items-center gap-1.5">
                <BookOpen class="w-4 h-4 text-purple-600" />
                <span>当前打开文献</span>
              </div>
              <span class="text-[11px] text-slate-500 truncate">{{ props.initialDoc.title }}</span>
            </button>

            <button
              type="button"
              @click="sourceType = 'library'"
              :class="[
                'p-3 rounded-xl border text-left flex flex-col gap-1 transition',
                sourceType === 'library'
                  ? 'border-purple-500 bg-purple-50/50 dark:bg-purple-950/30 ring-1 ring-purple-500'
                  : 'border-slate-200 dark:border-slate-800 hover:border-slate-300'
              ]"
            >
              <div class="font-medium text-xs text-slate-900 dark:text-slate-100 flex items-center gap-1.5">
                <FileText class="w-4 h-4 text-blue-600" />
                <span>本地书架文献 ({{ savedPapers.length }})</span>
              </div>
              <span class="text-[11px] text-slate-500">从已保存的书架文献提取</span>
            </button>

            <button
              type="button"
              @click="sourceType = 'text'"
              :class="[
                'p-3 rounded-xl border text-left flex flex-col gap-1 transition',
                sourceType === 'text'
                  ? 'border-purple-500 bg-purple-50/50 dark:bg-purple-950/30 ring-1 ring-purple-500'
                  : 'border-slate-200 dark:border-slate-800 hover:border-slate-300'
              ]"
            >
              <div class="font-medium text-xs text-slate-900 dark:text-slate-100 flex items-center gap-1.5">
                <Plus class="w-4 h-4 text-emerald-600" />
                <span>直接粘贴文本 / 摘要</span>
              </div>
              <span class="text-[11px] text-slate-500">粘贴学术英文段落分析</span>
            </button>
          </div>
        </div>

        <!-- 书架文献选择器 -->
        <div v-if="sourceType === 'library'" class="space-y-2">
          <label class="block text-xs font-semibold text-slate-700 dark:text-slate-300">
            选择目标文献
          </label>
          <div v-if="savedPapers.length === 0" class="p-4 rounded-xl bg-slate-50 dark:bg-slate-800/40 text-xs text-slate-500 text-center">
            本地书架暂无文献，请先在「文献速览」中导入一篇，或切换为「直接粘贴文本」。
          </div>
          <select
            v-else
            v-model="selectedDocId"
            class="w-full px-3 py-2.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 text-xs focus:ring-2 focus:ring-purple-500 outline-none"
          >
            <option v-for="p in savedPapers" :key="p.doc_id" :value="p.doc_id">
              {{ p.title }} ({{ p.segCount }} 段)
            </option>
          </select>
        </div>

        <!-- 自由文本粘贴 -->
        <div v-else-if="sourceType === 'text'" class="space-y-3">
          <div>
            <label class="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
              文献/主题标题 (可选)
            </label>
            <input
              type="text"
              v-model="customTitle"
              placeholder="例如: Irritable Bowel Syndrome Review"
              class="w-full px-3.5 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 text-xs"
            />
          </div>
          <div>
            <label class="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
              英文学术文本 / 摘要 / 引言
            </label>
            <textarea
              v-model="customText"
              rows="6"
              placeholder="在此粘贴包含大量专业术语、缩写词的英文学术段落..."
              class="w-full p-3 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 font-mono text-xs focus:ring-2 focus:ring-purple-500 outline-none leading-relaxed"
            ></textarea>
          </div>
        </div>

        <!-- 错误提示 -->
        <div v-if="extractError" class="p-3.5 rounded-xl bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-800 text-rose-700 dark:text-rose-300 text-xs flex items-start gap-2">
          <AlertCircle class="w-4 h-4 text-rose-600 shrink-0 mt-0.5" />
          <div class="space-y-1">
            <span class="font-semibold">提炼遇阻:</span>
            <span>{{ extractError }}</span>
          </div>
        </div>

        <!-- 提示说明卡片 -->
        <div class="p-3.5 rounded-xl bg-purple-50/70 dark:bg-purple-950/30 border border-purple-200/60 dark:border-purple-900/40 text-xs text-purple-900 dark:text-purple-200 space-y-1.5 leading-relaxed">
          <div class="font-semibold flex items-center gap-1.5">
            <Sparkles class="w-3.5 h-3.5 text-purple-600 dark:text-purple-400" />
            <span>智能提炼优势</span>
          </div>
          <p>
            系统将自动结合<b>正则缩写检测算法</b>与 <b>{{ settingsState.llmProvider.toUpperCase() }} 高精度大模型</b>，从文章核心论述中精准提取 15-30 条专业名词、病理机制、分子靶点，并给出国内权威中文标准译名与替换策略。
          </p>
        </div>
      </div>

      <!-- Step 2: Candidates Review -->
      <div v-else-if="step === 'review'" class="p-6 space-y-4 overflow-y-auto flex-1 text-sm">
        <!-- 目标导入库选择 -->
        <div class="p-4 rounded-xl bg-slate-50 dark:bg-slate-800/40 border border-slate-200/80 dark:border-slate-800 space-y-3">
          <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
            <div class="text-xs font-semibold text-slate-800 dark:text-slate-200">
              目标导入术语库：
            </div>
            <div class="flex items-center gap-3">
              <label class="flex items-center gap-1.5 cursor-pointer text-xs font-medium">
                <input
                  type="radio"
                  value="global"
                  v-model="targetScope"
                  class="text-purple-600 focus:ring-purple-500"
                />
                <span>🌐 存入总术语表 (全局跨文献共享)</span>
              </label>
              <label class="flex items-center gap-1.5 cursor-pointer text-xs font-medium">
                <input
                  type="radio"
                  value="doc"
                  v-model="targetScope"
                  class="text-purple-600 focus:ring-purple-500"
                />
                <span>📑 存入分术语表 (文献专属就近生效)</span>
              </label>
            </div>
          </div>

          <div v-if="targetScope === 'doc'" class="pt-2 border-t border-slate-200 dark:border-slate-700 flex flex-wrap items-center gap-2 text-xs">
            <span class="text-slate-500">文献 ID / 标识:</span>
            <input
              type="text"
              v-model="targetDocId"
              placeholder="doc_id"
              class="px-2.5 py-1 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 font-mono text-xs w-48"
            />
            <span class="text-slate-500 ml-2">标题:</span>
            <input
              type="text"
              v-model="targetDocTitle"
              placeholder="文献标题"
              class="px-2.5 py-1 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-xs flex-1 min-w-[200px]"
            />
          </div>
        </div>

        <!-- 候选列表表头与批量操作 -->
        <div class="flex items-center justify-between text-xs px-1">
          <label class="flex items-center gap-2 cursor-pointer font-medium text-slate-700 dark:text-slate-300">
            <input
              type="checkbox"
              v-model="isAllSelected"
              class="rounded text-purple-600 focus:ring-purple-500"
            />
            <span>全选 / 反选 (已选中 {{ selectedCount }} / {{ candidates.length }} 条)</span>
          </label>
          <span class="text-slate-400">💡 可在下方直接修改译名、模式与注记</span>
        </div>

        <!-- 候选词表格 -->
        <div class="border border-slate-200 dark:border-slate-800 rounded-xl overflow-hidden divide-y divide-slate-100 dark:divide-slate-800">
          <div
            v-for="(cand, idx) in candidates"
            :key="idx"
            :class="[
              'p-3.5 transition flex flex-col sm:flex-row sm:items-center gap-3',
              cand.selected ? 'bg-white dark:bg-slate-900' : 'bg-slate-50/60 dark:bg-slate-900/40 opacity-60'
            ]"
          >
            <!-- Checkbox -->
            <div class="flex items-center gap-2.5 shrink-0">
              <input
                type="checkbox"
                v-model="cand.selected"
                class="rounded text-purple-600 focus:ring-purple-500 mt-0.5"
              />
              <span class="text-xs font-mono text-slate-400">#{{ idx + 1 }}</span>
            </div>

            <!-- English Term -->
            <div class="w-full sm:w-48 shrink-0">
              <input
                type="text"
                v-model="cand.term"
                class="w-full px-2 py-1 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/80 font-mono text-xs font-bold text-slate-900 dark:text-slate-100"
              />
            </div>

            <!-- Arrow -->
            <ArrowRight class="w-4 h-4 text-slate-400 hidden sm:block shrink-0" />

            <!-- Chinese Translation -->
            <div class="w-full sm:w-44 shrink-0">
              <input
                type="text"
                v-model="cand.zh"
                placeholder="规范中文译名"
                class="w-full px-2 py-1 rounded-lg border border-purple-200 dark:border-purple-800 bg-white dark:bg-slate-800 text-xs font-semibold text-purple-700 dark:text-purple-300"
              />
            </div>

            <!-- Mode Selector -->
            <div class="w-full sm:w-32 shrink-0">
              <select
                v-model="cand.mode"
                class="w-full px-2 py-1 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-[11px] font-medium"
              >
                <option value="hard_replace">⚡ 硬替换 (0 Token)</option>
                <option value="prompt_hint">💡 Prompt 引导</option>
              </select>
            </div>

            <!-- Note / Aliases -->
            <div class="flex-1 min-w-0">
              <input
                type="text"
                v-model="cand.note"
                placeholder="说明 / 语境注记 / 缩写全称"
                class="w-full px-2 py-1 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-xs text-slate-600 dark:text-slate-400"
              />
            </div>

            <!-- Duplicate Tag -->
            <div v-if="cand.isDuplicate" class="shrink-0">
              <span class="px-1.5 py-0.5 rounded text-[10px] bg-amber-100 dark:bg-amber-950/60 text-amber-700 dark:text-amber-300 border border-amber-200 dark:border-amber-800">
                已存在(将更新)
              </span>
            </div>
          </div>
        </div>
      </div>

      <!-- Footer Buttons -->
      <div class="px-6 py-4 bg-slate-50 dark:bg-slate-800/50 border-t border-slate-100 dark:border-slate-800 flex justify-between items-center shrink-0">
        <div>
          <button
            v-if="step === 'review'"
            type="button"
            @click="step = 'config'"
            class="text-xs text-slate-500 hover:text-slate-700 dark:hover:text-slate-300 flex items-center gap-1 transition"
          >
            <RotateCcw class="w-3.5 h-3.5" />
            <span>重新选择来源</span>
          </button>
        </div>

        <div class="flex items-center gap-2.5">
          <button
            type="button"
            @click="emit('close')"
            class="px-4 py-2 rounded-xl border border-slate-200 dark:border-slate-700 hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-600 dark:text-slate-300 text-xs font-medium transition"
          >
            取消
          </button>

          <!-- Step 1 Button -->
          <button
            v-if="step === 'config'"
            type="button"
            @click="handleStartExtraction"
            :disabled="isExtracting"
            class="px-5 py-2.5 rounded-xl bg-gradient-to-r from-purple-600 to-indigo-600 hover:from-purple-700 hover:to-indigo-700 text-white font-medium text-xs shadow-md shadow-purple-500/20 flex items-center gap-2 transition disabled:opacity-50"
          >
            <Loader2 v-if="isExtracting" class="w-4 h-4 animate-spin" />
            <Sparkles v-else class="w-4 h-4" />
            <span>{{ isExtracting ? '正在深度分析学术文本...' : '开始提炼术语' }}</span>
          </button>

          <!-- Step 2 Button -->
          <button
            v-else
            type="button"
            @click="handleConfirmImport"
            :disabled="isImporting || selectedCount === 0"
            class="px-5 py-2.5 rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white font-medium text-xs shadow-md shadow-emerald-600/20 flex items-center gap-2 transition disabled:opacity-50"
          >
            <Loader2 v-if="isImporting" class="w-4 h-4 animate-spin" />
            <Check v-else class="w-4 h-4" />
            <span>一键导入选中的 {{ selectedCount }} 条术语</span>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
