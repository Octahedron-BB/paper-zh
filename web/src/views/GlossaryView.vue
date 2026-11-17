<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import type { Term, TermMode } from '../core/types'
import {
  getGlobalTerms,
  saveGlobalTerms,
  resetGlobalTerms,
  getAllDocGlossaries,
  getDocTerms,
  saveDocTerms,
  deleteDocGlossary,
  type DocGlossaryRecord,
} from '../store/glossaryStore'
import { getAllSavedPapers, type SavedPaper } from '../store/library'
import ExtractTermsModal from '../components/ExtractTermsModal.vue'
import {
  BookMarked,
  Search,
  Plus,
  Sparkles,
  Edit2,
  Trash2,
  Download,
  Upload,
  RotateCcw,
  Globe,
  FileText,
  Info,
  Check,
  X,
  BookOpen,
} from 'lucide-vue-next'

// 1. 视图模式：总术语表 (global) vs 分术语表 (doc)
const activeTab = ref<'global' | 'doc'>('global')

// 2. 数据集合
const globalTerms = ref<Term[]>([])
const docGlossaries = ref<Record<string, DocGlossaryRecord>>({})
const savedPapers = ref<SavedPaper[]>([])
const selectedDocId = ref<string>('')

// 3. 搜索与筛选
const searchQuery = ref('')
const filterMode = ref<'all' | 'hard_replace' | 'prompt_hint'>('all')

// 4. 新增 / 编辑弹窗状态
const showEditModal = ref(false)
const isNewTerm = ref(false)
const editScope = ref<'global' | 'doc'>('global')
const editTargetDocId = ref('')
const editTargetDocTitle = ref('')
const termForm = ref<{
  originalTerm: string // 用于编辑模式定位旧 term
  term: string
  zh: string
  mode: TermMode
  note: string
  aliasesStr: string
}>({
  originalTerm: '',
  term: '',
  zh: '',
  mode: 'hard_replace',
  note: '',
  aliasesStr: '',
})

// 5. LLM 提炼弹窗状态
const showExtractModal = ref(false)

// 6. 成功消息提示条
const toastMessage = ref<string | null>(null)
function showToast(msg: string) {
  toastMessage.value = msg
  setTimeout(() => {
    if (toastMessage.value === msg) {
      toastMessage.value = null
    }
  }, 3500)
}

// 7. 加载数据
async function loadAllData() {
  try {
    globalTerms.value = await getGlobalTerms()
    docGlossaries.value = await getAllDocGlossaries()
    savedPapers.value = await getAllSavedPapers()

    // 默认选中文献分表
    const docKeys = Object.keys(docGlossaries.value)
    if (!selectedDocId.value) {
      if (docKeys.length > 0) {
        selectedDocId.value = docKeys[0]
      } else if (savedPapers.value.length > 0) {
        selectedDocId.value = savedPapers.value[0].doc_id
      }
    }
  } catch (e) {
    console.error('加载术语数据失败:', e)
  }
}

onMounted(() => {
  loadAllData()
})

// 当前处于分术语表模式时选中的文献记录
const currentDocGlossary = computed<DocGlossaryRecord | undefined>(() => {
  return docGlossaries.value[selectedDocId.value]
})

// 当前激活显示的术语列表（未过滤）
const currentRawTerms = computed<Term[]>(() => {
  if (activeTab.value === 'global') {
    return globalTerms.value
  } else {
    return currentDocGlossary.value?.terms || []
  }
})

// 过滤后的术语列表
const filteredTerms = computed<Term[]>(() => {
  const query = searchQuery.value.trim().toLowerCase()
  return currentRawTerms.value.filter((t) => {
    // 1. 替换模式过滤
    if (filterMode.value !== 'all' && t.mode !== filterMode.value) {
      return false
    }
    // 2. 搜索词匹配
    if (!query) return true
    const termMatch = t.term.toLowerCase().includes(query)
    const zhMatch = t.zh.toLowerCase().includes(query)
    const noteMatch = (t.note || '').toLowerCase().includes(query)
    const aliasMatch = (t.aliases || []).some((a) => a.toLowerCase().includes(query))
    return termMatch || zhMatch || noteMatch || aliasMatch
  })
})

// 统计信息
const stats = computed(() => {
  const totalGlobal = globalTerms.value.length
  const docKeys = Object.keys(docGlossaries.value)
  const totalDocTerms = docKeys.reduce((acc, k) => acc + (docGlossaries.value[k].terms?.length || 0), 0)
  const hardCount = currentRawTerms.value.filter((t) => t.mode === 'hard_replace').length
  const hintCount = currentRawTerms.value.filter((t) => t.mode === 'prompt_hint').length
  return {
    totalGlobal,
    docCount: docKeys.length,
    totalDocTerms,
    currentTotal: currentRawTerms.value.length,
    hardCount,
    hintCount,
  }
})

// 文献选项列表（合并已有分术语表与书架文献）
const docOptions = computed(() => {
  const map = new Map<string, { doc_id: string; title: string; termCount: number }>()

  // 1. 已有分术语表的文献
  Object.values(docGlossaries.value).forEach((d) => {
    map.set(d.doc_id, {
      doc_id: d.doc_id,
      title: d.doc_title || d.doc_id,
      termCount: d.terms?.length || 0,
    })
  })

  // 2. 书架中的文献（尚未建专属术语表的）
  savedPapers.value.forEach((p) => {
    if (!map.has(p.doc_id)) {
      map.set(p.doc_id, {
        doc_id: p.doc_id,
        title: p.title,
        termCount: 0,
      })
    }
  })

  return Array.from(map.values())
})

// 打开新增弹窗
function openAddTermModal() {
  isNewTerm.value = true
  editScope.value = activeTab.value
  editTargetDocId.value = selectedDocId.value
  editTargetDocTitle.value = currentDocGlossary.value?.doc_title || ''
  termForm.value = {
    originalTerm: '',
    term: '',
    zh: '',
    mode: 'hard_replace',
    note: '',
    aliasesStr: '',
  }
  showEditModal.value = true
}

// 打开编辑弹窗
function openEditTermModal(t: Term) {
  isNewTerm.value = false
  editScope.value = activeTab.value
  editTargetDocId.value = selectedDocId.value
  editTargetDocTitle.value = currentDocGlossary.value?.doc_title || ''
  termForm.value = {
    originalTerm: t.term,
    term: t.term,
    zh: t.zh,
    mode: t.mode,
    note: t.note || '',
    aliasesStr: (t.aliases || []).join('，'),
  }
  showEditModal.value = true
}

// 保存术语
async function handleSaveTerm() {
  const termName = termForm.value.term.trim()
  const zhName = termForm.value.zh.trim()

  if (!termName || !zhName) {
    alert('请填写英文术语与中文规范译名')
    return
  }

  const aliases = termForm.value.aliasesStr
    .split(/[,，\n]/)
    .map((s) => s.trim())
    .filter((s) => s && s !== zhName && s !== termName)

  const updatedTerm: Term = {
    term: termName,
    zh: zhName,
    mode: termForm.value.mode,
    note: termForm.value.note.trim() || undefined,
    aliases: aliases.length > 0 ? aliases : undefined,
  }

  try {
    if (editScope.value === 'global') {
      const list = [...globalTerms.value]
      if (isNewTerm.value) {
        // 查重并覆盖
        const existIdx = list.findIndex((t) => t.term.toLowerCase() === termName.toLowerCase())
        if (existIdx >= 0) {
          list[existIdx] = updatedTerm
        } else {
          list.unshift(updatedTerm)
        }
      } else {
        const idx = list.findIndex((t) => t.term.toLowerCase() === termForm.value.originalTerm.toLowerCase())
        if (idx >= 0) {
          list[idx] = updatedTerm
        } else {
          list.unshift(updatedTerm)
        }
      }
      await saveGlobalTerms(list)
      globalTerms.value = list
      showToast(`已成功保存总术语「${termName}」`)
    } else {
      const docId = editTargetDocId.value.trim() || selectedDocId.value || 'doc_' + Date.now()
      const current = await getDocTerms(docId)
      const list = [...current]
      if (isNewTerm.value) {
        const existIdx = list.findIndex((t) => t.term.toLowerCase() === termName.toLowerCase())
        if (existIdx >= 0) {
          list[existIdx] = updatedTerm
        } else {
          list.unshift(updatedTerm)
        }
      } else {
        const idx = list.findIndex((t) => t.term.toLowerCase() === termForm.value.originalTerm.toLowerCase())
        if (idx >= 0) {
          list[idx] = updatedTerm
        } else {
          list.unshift(updatedTerm)
        }
      }
      await saveDocTerms(docId, list, editTargetDocTitle.value || docId)
      selectedDocId.value = docId
      await loadAllData()
      showToast(`已成功保存文献专属术语「${termName}」`)
    }

    showEditModal.value = false
  } catch (err: any) {
    alert(`保存失败: ${err.message}`)
  }
}

// 删除单个术语
async function handleDeleteTerm(t: Term) {
  if (!confirm(`确定要从当前术语表中删除「${t.term} (${t.zh})」吗？`)) {
    return
  }

  try {
    if (activeTab.value === 'global') {
      const list = globalTerms.value.filter((x) => x.term.toLowerCase() !== t.term.toLowerCase())
      await saveGlobalTerms(list)
      globalTerms.value = list
      showToast(`已删除术语「${t.term}」`)
    } else if (selectedDocId.value) {
      const current = await getDocTerms(selectedDocId.value)
      const list = current.filter((x) => x.term.toLowerCase() !== t.term.toLowerCase())
      await saveDocTerms(selectedDocId.value, list)
      await loadAllData()
      showToast(`已删除文献专属术语「${t.term}」`)
    }
  } catch (err: any) {
    alert(`删除失败: ${err.message}`)
  }
}

// 重置总术语表
async function handleResetGlobalDefaults() {
  if (confirm('确定要恢复系统出厂内置的专业术语表吗？这将会重置总术语表为默认值。')) {
    const res = await resetGlobalTerms()
    globalTerms.value = res
    showToast('已恢复出厂默认总术语表')
  }
}

// 删除文献专属分表
async function handleDeleteCurrentDocGlossary() {
  if (!selectedDocId.value) return
  if (confirm(`确定要清空并删除该文献的分术语表吗？删除后该文献将恢复继承总术语表。`)) {
    await deleteDocGlossary(selectedDocId.value)
    await loadAllData()
    showToast('已删除该文献分术语表')
  }
}

// 导出 JSON
function handleExportJson() {
  const data = {
    exportTime: new Date().toISOString(),
    globalTerms: globalTerms.value,
    docGlossaries: docGlossaries.value,
  }
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `paper_zh_glossary_${new Date().toISOString().slice(0, 10)}.json`
  a.click()
  URL.revokeObjectURL(url)
}

// 导入 JSON
async function handleImportJson(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0]
  if (!file) return

  const reader = new FileReader()
  reader.onload = async (event) => {
    try {
      const content = event.target?.result as string
      const parsed = JSON.parse(content)

      if (parsed.globalTerms && Array.isArray(parsed.globalTerms)) {
        await saveGlobalTerms(parsed.globalTerms)
      }
      if (parsed.docGlossaries && typeof parsed.docGlossaries === 'object') {
        for (const [docId, rec] of Object.entries(parsed.docGlossaries as Record<string, DocGlossaryRecord>)) {
          if (rec && rec.terms) {
            await saveDocTerms(docId, rec.terms, rec.doc_title)
          }
        }
      }
      await loadAllData()
      showToast('术语表 JSON 导入成功！')
    } catch (err: any) {
      alert(`导入 JSON 失败: ${err.message}`)
    }
  }
  reader.readAsText(file)
}

// LLM 导入完成回调
async function handleLlmImported(target: 'global' | string, count: number) {
  await loadAllData()
  if (target === 'global') {
    activeTab.value = 'global'
    showToast(`成功提炼并向总术语表导入 ${count} 条核心学术术语！`)
  } else {
    activeTab.value = 'doc'
    selectedDocId.value = target
    showToast(`成功提炼并向文献专属分表导入 ${count} 条核心学术术语！`)
  }
}
</script>

<template>
  <div class="space-y-6 animate-fade-in">
    <!-- Toast Message Banner -->
    <div
      v-if="toastMessage"
      class="fixed top-20 right-6 z-50 p-3 rounded-xl bg-emerald-600 text-white shadow-xl text-xs flex items-center gap-2 animate-bounce transition"
    >
      <Check class="w-4 h-4 shrink-0" />
      <span>{{ toastMessage }}</span>
    </div>

    <!-- Header Section -->
    <div class="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-2 border-b border-slate-200/80 dark:border-slate-800">
      <div>
        <div class="flex items-center gap-2.5">
          <div class="w-9 h-9 rounded-xl bg-gradient-to-tr from-indigo-600 to-purple-600 text-white flex items-center justify-center shadow-md shadow-indigo-500/20">
            <BookMarked class="w-5 h-5" />
          </div>
          <div>
            <h2 class="text-lg font-bold text-slate-900 dark:text-slate-100 flex items-center gap-2">
              <span>专业学术术语库</span>
              <span class="text-xs px-2.5 py-0.5 rounded-full bg-indigo-50 dark:bg-indigo-950/60 text-indigo-600 dark:text-indigo-400 font-semibold border border-indigo-100 dark:border-indigo-900">
                双层就近优先 · 跨篇复利
              </span>
            </h2>
            <p class="text-xs text-slate-500">
              规范化跨文献翻译与播客改写 · 译后 0 Token 精确替换 · 支持大模型智能深度提炼
            </p>
          </div>
        </div>
      </div>

      <!-- Action Buttons -->
      <div class="flex flex-wrap items-center gap-2">
        <!-- AI 提炼按钮 -->
        <button
          type="button"
          @click="showExtractModal = true"
          class="px-3.5 py-2 rounded-xl bg-gradient-to-r from-purple-600 to-indigo-600 hover:from-purple-700 hover:to-indigo-700 text-white text-xs font-semibold flex items-center gap-1.5 shadow-md shadow-purple-500/20 transition"
        >
          <Sparkles class="w-4 h-4" />
          <span>LLM 智能提炼术语</span>
        </button>

        <!-- 手动新增按钮 -->
        <button
          type="button"
          @click="openAddTermModal"
          class="px-3.5 py-2 rounded-xl bg-blue-600 hover:bg-blue-700 text-white text-xs font-semibold flex items-center gap-1.5 shadow-sm transition"
        >
          <Plus class="w-4 h-4" />
          <span>新增术语</span>
        </button>

        <!-- 导入 / 导出 -->
        <div class="flex items-center gap-1 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl p-0.5">
          <button
            type="button"
            @click="handleExportJson"
            class="px-2.5 py-1.5 rounded-lg text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-100 text-xs flex items-center gap-1 transition"
            title="导出全部术语表为 JSON 备份"
          >
            <Download class="w-3.5 h-3.5" />
            <span class="hidden sm:inline">导出</span>
          </button>
          <label
            class="px-2.5 py-1.5 rounded-lg text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-100 text-xs flex items-center gap-1 cursor-pointer transition"
            title="从 JSON 文件导入术语表"
          >
            <Upload class="w-3.5 h-3.5" />
            <span class="hidden sm:inline">导入</span>
            <input type="file" accept=".json" class="hidden" @change="handleImportJson" />
          </label>
        </div>
      </div>
    </div>

    <!-- Main Navigation: 总术语表 vs 分术语表 -->
    <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
      <!-- Tab Switcher -->
      <div class="inline-flex p-1 rounded-xl bg-slate-100 dark:bg-slate-800/80 border border-slate-200/60 dark:border-slate-700/60 shrink-0">
        <button
          type="button"
          @click="activeTab = 'global'"
          :class="[
            'px-4 py-2 rounded-lg text-xs font-semibold flex items-center gap-2 transition',
            activeTab === 'global'
              ? 'bg-white dark:bg-slate-700 text-indigo-600 dark:text-indigo-400 shadow-sm'
              : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200'
          ]"
        >
          <Globe class="w-4 h-4" />
          <span>总术语表 (全局跨篇通用)</span>
          <span class="px-1.5 py-0.5 rounded-full text-[10px] bg-slate-200 dark:bg-slate-600 text-slate-700 dark:text-slate-200 font-mono">
            {{ stats.totalGlobal }}
          </span>
        </button>

        <button
          type="button"
          @click="activeTab = 'doc'"
          :class="[
            'px-4 py-2 rounded-lg text-xs font-semibold flex items-center gap-2 transition',
            activeTab === 'doc'
              ? 'bg-white dark:bg-slate-700 text-indigo-600 dark:text-indigo-400 shadow-sm'
              : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200'
          ]"
        >
          <FileText class="w-4 h-4" />
          <span>分术语表 (单篇文献专属)</span>
          <span class="px-1.5 py-0.5 rounded-full text-[10px] bg-slate-200 dark:bg-slate-600 text-slate-700 dark:text-slate-200 font-mono">
            {{ stats.docCount }} 篇 · {{ stats.totalDocTerms }} 条
          </span>
        </button>
      </div>

      <!-- Scope Description Badge -->
      <div class="text-xs text-slate-500 flex items-center gap-1.5">
        <Info class="w-3.5 h-3.5 text-slate-400 shrink-0" />
        <span v-if="activeTab === 'global'">
          💡 所有文献制作默认继承总术语表，积累的术语可永久复利。
        </span>
        <span v-else>
          ⚡ <b>就近优先</b>：单篇文献专属术语将自动覆盖总术语表中的同名条目。
        </span>
      </div>
    </div>

    <!-- 分术语表特有：文献选择器与文献标题条 -->
    <div
      v-if="activeTab === 'doc'"
      class="p-4 rounded-2xl bg-indigo-50/50 dark:bg-indigo-950/20 border border-indigo-100 dark:border-indigo-900/50 flex flex-col sm:flex-row sm:items-center justify-between gap-3 animate-fade-in"
    >
      <div class="flex items-center gap-2.5 min-w-0 flex-1">
        <BookOpen class="w-5 h-5 text-indigo-600 dark:text-indigo-400 shrink-0" />
        <div class="min-w-0 flex-1">
          <div class="text-xs font-semibold text-slate-900 dark:text-slate-100 mb-1">
            选择目标文献：
          </div>
          <select
            v-model="selectedDocId"
            class="w-full sm:max-w-lg px-3 py-1.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 text-xs focus:ring-2 focus:ring-indigo-500 outline-none truncate"
          >
            <option v-if="docOptions.length === 0" value="">暂无文献记录</option>
            <option v-for="opt in docOptions" :key="opt.doc_id" :value="opt.doc_id">
              {{ opt.title }} ({{ opt.termCount }} 条专属术语)
            </option>
          </select>
        </div>
      </div>

      <div class="flex items-center gap-2 shrink-0">
        <button
          v-if="currentDocGlossary && currentDocGlossary.terms?.length > 0"
          type="button"
          @click="handleDeleteCurrentDocGlossary"
          class="px-2.5 py-1.5 rounded-lg border border-rose-200 dark:border-rose-800 text-rose-600 dark:text-rose-400 hover:bg-rose-50 dark:hover:bg-rose-950/40 text-xs flex items-center gap-1 transition"
          title="清空当前文献的分表"
        >
          <Trash2 class="w-3.5 h-3.5" />
          <span>清空本文分表</span>
        </button>
      </div>
    </div>

    <!-- Search & Filters Toolbar -->
    <div class="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3 bg-white dark:bg-slate-900 p-3 rounded-2xl border border-slate-200/80 dark:border-slate-800 shadow-sm">
      <!-- Search Input -->
      <div class="relative flex-1">
        <Search class="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
        <input
          type="text"
          v-model="searchQuery"
          placeholder="搜索英文术语、规范中文、别名或语境释义..."
          class="w-full pl-9 pr-8 py-2 rounded-xl bg-slate-50 dark:bg-slate-800 border-none text-xs text-slate-900 dark:text-slate-100 focus:ring-2 focus:ring-indigo-500 outline-none"
        />
        <button
          v-if="searchQuery"
          @click="searchQuery = ''"
          class="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
        >
          <X class="w-3.5 h-3.5" />
        </button>
      </div>

      <!-- Mode Filters & Stats -->
      <div class="flex items-center gap-2 shrink-0">
        <div class="flex items-center bg-slate-100 dark:bg-slate-800 p-0.5 rounded-xl text-xs">
          <button
            type="button"
            @click="filterMode = 'all'"
            :class="[
              'px-2.5 py-1 rounded-lg transition font-medium',
              filterMode === 'all'
                ? 'bg-white dark:bg-slate-700 text-slate-900 dark:text-slate-100 shadow-sm'
                : 'text-slate-500 hover:text-slate-800 dark:hover:text-slate-300'
            ]"
          >
            全部 ({{ currentRawTerms.length }})
          </button>
          <button
            type="button"
            @click="filterMode = 'hard_replace'"
            :class="[
              'px-2.5 py-1 rounded-lg transition font-medium flex items-center gap-1',
              filterMode === 'hard_replace'
                ? 'bg-white dark:bg-slate-700 text-emerald-600 dark:text-emerald-400 shadow-sm'
                : 'text-slate-500 hover:text-slate-800 dark:hover:text-slate-300'
            ]"
          >
            <span>⚡ 硬替换</span>
            <span class="text-[10px] opacity-80">({{ stats.hardCount }})</span>
          </button>
          <button
            type="button"
            @click="filterMode = 'prompt_hint'"
            :class="[
              'px-2.5 py-1 rounded-lg transition font-medium flex items-center gap-1',
              filterMode === 'prompt_hint'
                ? 'bg-white dark:bg-slate-700 text-purple-600 dark:text-purple-400 shadow-sm'
                : 'text-slate-500 hover:text-slate-800 dark:hover:text-slate-300'
            ]"
          >
            <span>💡 Prompt 引导</span>
            <span class="text-[10px] opacity-80">({{ stats.hintCount }})</span>
          </button>
        </div>

        <button
          v-if="activeTab === 'global'"
          type="button"
          @click="handleResetGlobalDefaults"
          class="p-2 text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 rounded-xl hover:bg-slate-100 dark:hover:bg-slate-800 transition"
          title="重置为出厂内置术语表"
        >
          <RotateCcw class="w-4 h-4" />
        </button>
      </div>
    </div>

    <!-- Empty State -->
    <div
      v-if="filteredTerms.length === 0"
      class="p-12 text-center rounded-2xl bg-white dark:bg-slate-900 border border-slate-200/80 dark:border-slate-800 space-y-3"
    >
      <div class="w-12 h-12 rounded-2xl bg-slate-100 dark:bg-slate-800 text-slate-400 flex items-center justify-center mx-auto">
        <BookMarked class="w-6 h-6" />
      </div>
      <div class="space-y-1">
        <h3 class="text-sm font-semibold text-slate-800 dark:text-slate-200">
          {{ searchQuery ? '未搜索到匹配的术语条目' : '当前术语表暂无条目' }}
        </h3>
        <p class="text-xs text-slate-400 max-w-md mx-auto">
          {{
            searchQuery
              ? '尝试更换搜索关键词，或清除搜索条件。'
              : activeTab === 'global'
              ? '总术语表为空，您可以点击上方「新增术语」或「恢复出厂预设」导入基础规范。'
              : '该文献暂未定制专属分术语表，将默认继承总术语表。点击「LLM 智能提炼术语」一键提取专属术语。'
          }}
        </p>
      </div>
      <div class="pt-2 flex justify-center gap-2">
        <button
          v-if="searchQuery"
          @click="searchQuery = ''"
          class="px-3.5 py-1.5 rounded-xl border border-slate-200 dark:border-slate-700 text-xs font-medium"
        >
          清除搜索条件
        </button>
        <button
          v-else
          @click="showExtractModal = true"
          class="px-4 py-2 rounded-xl bg-purple-600 hover:bg-purple-700 text-white text-xs font-medium flex items-center gap-1.5 shadow-sm transition"
        >
          <Sparkles class="w-3.5 h-3.5" />
          <span>LLM 智能提炼术语</span>
        </button>
      </div>
    </div>

    <!-- Terms Table / Grid -->
    <div v-else class="border border-slate-200/80 dark:border-slate-800 rounded-2xl bg-white dark:bg-slate-900 shadow-sm overflow-hidden">
      <!-- Table Header (Desktop) -->
      <div class="hidden md:grid grid-cols-12 gap-3 px-5 py-3 bg-slate-50 dark:bg-slate-800/60 border-b border-slate-200/80 dark:border-slate-800 text-xs font-semibold text-slate-600 dark:text-slate-400">
        <div class="col-span-3">英文学术原词 / 缩写</div>
        <div class="col-span-3">中文统一规范译名</div>
        <div class="col-span-2">生效机制</div>
        <div class="col-span-3">概念说明 / 别名纠偏</div>
        <div class="col-span-1 text-right">操作</div>
      </div>

      <!-- Table Body Rows -->
      <div class="divide-y divide-slate-100 dark:divide-slate-800">
        <div
          v-for="t in filteredTerms"
          :key="t.term"
          class="p-4 md:px-5 md:py-3.5 hover:bg-slate-50/70 dark:hover:bg-slate-800/40 transition flex flex-col md:grid md:grid-cols-12 md:items-center gap-2 md:gap-3 text-xs"
        >
          <!-- 1. 英文原词 -->
          <div class="md:col-span-3 flex items-center justify-between md:justify-start gap-2">
            <span class="font-mono font-bold text-slate-900 dark:text-slate-100 text-sm">
              {{ t.term }}
            </span>
            <!-- Mobile mode badge -->
            <span
              :class="[
                'md:hidden px-2 py-0.5 rounded-full text-[10px] font-semibold',
                t.mode === 'hard_replace'
                  ? 'bg-emerald-50 dark:bg-emerald-950/60 text-emerald-600 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-800'
                  : 'bg-purple-50 dark:bg-purple-950/60 text-purple-600 dark:text-purple-400 border border-purple-200 dark:border-purple-800'
              ]"
            >
              {{ t.mode === 'hard_replace' ? '硬替换' : 'Prompt' }}
            </span>
          </div>

          <!-- 2. 中文译名 -->
          <div class="md:col-span-3 flex items-center gap-1.5 font-medium text-slate-900 dark:text-slate-100">
            <span class="text-slate-400 md:hidden">译名:</span>
            <span class="font-semibold text-indigo-600 dark:text-indigo-400 text-sm">
              {{ t.zh }}
            </span>
          </div>

          <!-- 3. 生效模式 (Desktop) -->
          <div class="hidden md:block md:col-span-2">
            <span
              :class="[
                'inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-[11px] font-medium',
                t.mode === 'hard_replace'
                  ? 'bg-emerald-50 dark:bg-emerald-950/50 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800/60'
                  : 'bg-purple-50 dark:bg-purple-950/50 text-purple-700 dark:text-purple-300 border border-purple-200 dark:border-purple-800/60'
              ]"
              :title="t.mode === 'hard_replace' ? '译后强制字符串替换，0 token 成本，确保全文绝对统一' : '译前注入 Prompt，指导大语言模型理解多重语境与句式'"
            >
              <span>{{ t.mode === 'hard_replace' ? '⚡ 硬替换 (0 Token)' : '💡 Prompt 引导' }}</span>
            </span>
          </div>

          <!-- 4. 注记与别名 -->
          <div class="md:col-span-3 space-y-1">
            <div v-if="t.note" class="text-slate-600 dark:text-slate-400 flex items-start gap-1">
              <span class="text-slate-400 shrink-0">说明:</span>
              <span class="line-clamp-2">{{ t.note }}</span>
            </div>
            <div v-if="t.aliases && t.aliases.length > 0" class="flex flex-wrap items-center gap-1 pt-0.5">
              <span class="text-[10px] text-slate-400">别名纠偏:</span>
              <span
                v-for="a in t.aliases"
                :key="a"
                class="px-1.5 py-0.5 rounded text-[10px] bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 font-normal"
              >
                {{ a }}
              </span>
            </div>
          </div>

          <!-- 5. 操作 -->
          <div class="md:col-span-1 flex items-center justify-end gap-1 pt-2 md:pt-0 border-t md:border-none border-slate-100 dark:border-slate-800">
            <button
              type="button"
              @click="openEditTermModal(t)"
              class="p-1.5 text-slate-400 hover:text-blue-600 dark:hover:text-blue-400 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 transition"
              title="修改此术语"
            >
              <Edit2 class="w-3.5 h-3.5" />
            </button>
            <button
              type="button"
              @click="handleDeleteTerm(t)"
              class="p-1.5 text-slate-400 hover:text-rose-600 dark:hover:text-rose-400 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 transition"
              title="删除此术语"
            >
              <Trash2 class="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- Add / Edit Modal -->
    <div
      v-if="showEditModal"
      class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-fade-in"
      @click.self="showEditModal = false"
    >
      <div
        class="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl w-full max-w-lg shadow-2xl overflow-hidden flex flex-col"
        @click.stop
      >
        <div class="flex items-center justify-between px-6 py-4 border-b border-slate-100 dark:border-slate-800 bg-white/95 dark:bg-slate-900/95 backdrop-blur">
          <div class="flex items-center gap-2">
            <div class="p-1.5 rounded-lg bg-indigo-50 dark:bg-indigo-950/60 text-indigo-600 dark:text-indigo-400">
              <BookMarked class="w-4 h-4" />
            </div>
            <h3 class="font-bold text-sm text-slate-900 dark:text-slate-100">
              {{ isNewTerm ? '新增专业术语' : '修改术语规范' }}
            </h3>
          </div>
          <button
            type="button"
            @click="showEditModal = false"
            class="text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
          >
            <X class="w-4 h-4" />
          </button>
        </div>

        <div class="p-6 space-y-4 text-xs">
          <!-- 目标术语库范围 -->
          <div>
            <label class="block font-semibold text-slate-700 dark:text-slate-300 mb-1.5">
              目标术语库
            </label>
            <div class="grid grid-cols-2 gap-2">
              <label class="p-2.5 rounded-xl border flex items-center gap-2 cursor-pointer transition" :class="editScope === 'global' ? 'border-indigo-500 bg-indigo-50/50 dark:bg-indigo-950/40 text-indigo-600 dark:text-indigo-400 font-semibold' : 'border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-400'">
                <input type="radio" value="global" v-model="editScope" class="text-indigo-600 focus:ring-indigo-500" />
                <span>🌐 总术语表 (全局)</span>
              </label>
              <label class="p-2.5 rounded-xl border flex items-center gap-2 cursor-pointer transition" :class="editScope === 'doc' ? 'border-indigo-500 bg-indigo-50/50 dark:bg-indigo-950/40 text-indigo-600 dark:text-indigo-400 font-semibold' : 'border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-400'">
                <input type="radio" value="doc" v-model="editScope" class="text-indigo-600 focus:ring-indigo-500" />
                <span>📑 分术语表 (当前文献)</span>
              </label>
            </div>
          </div>

          <!-- 英文原词 -->
          <div>
            <label class="block font-semibold text-slate-700 dark:text-slate-300 mb-1">
              英文学术原词 / 缩写 <span class="text-rose-500">*</span>
            </label>
            <input
              type="text"
              v-model="termForm.term"
              placeholder="例如: irritable bowel syndrome 或 IBS"
              class="w-full px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 font-mono text-xs focus:ring-2 focus:ring-indigo-500 outline-none"
            />
          </div>

          <!-- 中文规范译名 -->
          <div>
            <label class="block font-semibold text-slate-700 dark:text-slate-300 mb-1">
              中文统一规范译名 <span class="text-rose-500">*</span>
            </label>
            <input
              type="text"
              v-model="termForm.zh"
              placeholder="例如: 肠易激综合征"
              class="w-full px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 text-xs focus:ring-2 focus:ring-indigo-500 outline-none"
            />
          </div>

          <!-- 生效机制 -->
          <div>
            <label class="block font-semibold text-slate-700 dark:text-slate-300 mb-1.5">
              生效机制模式
            </label>
            <div class="grid grid-cols-2 gap-2">
              <label class="p-2.5 rounded-xl border flex flex-col gap-1 cursor-pointer transition text-left" :class="termForm.mode === 'hard_replace' ? 'border-emerald-500 bg-emerald-50/50 dark:bg-emerald-950/40' : 'border-slate-200 dark:border-slate-700'">
                <div class="flex items-center gap-1.5 font-semibold text-emerald-700 dark:text-emerald-300">
                  <input type="radio" value="hard_replace" v-model="termForm.mode" class="text-emerald-600 focus:ring-emerald-500" />
                  <span>⚡ 硬替换 (推荐)</span>
                </div>
                <span class="text-[10px] text-slate-500 leading-tight">译后精准正则替换，0 token 成本，确保全文绝对统一</span>
              </label>

              <label class="p-2.5 rounded-xl border flex flex-col gap-1 cursor-pointer transition text-left" :class="termForm.mode === 'prompt_hint' ? 'border-purple-500 bg-purple-50/50 dark:bg-purple-950/40' : 'border-slate-200 dark:border-slate-700'">
                <div class="flex items-center gap-1.5 font-semibold text-purple-700 dark:text-purple-300">
                  <input type="radio" value="prompt_hint" v-model="termForm.mode" class="text-purple-600 focus:ring-purple-500" />
                  <span>💡 Prompt 引导</span>
                </div>
                <span class="text-[10px] text-slate-500 leading-tight">注入翻译与改写 Prompt，适合一词多义与语境敏感表达</span>
              </label>
            </div>
          </div>

          <!-- 别名纠偏 -->
          <div>
            <label class="block font-semibold text-slate-700 dark:text-slate-300 mb-1">
              常见别名 / 纠偏别名 (可选，逗号分隔)
            </label>
            <input
              type="text"
              v-model="termForm.aliasesStr"
              placeholder="例如: 闯入性思维，侵扰性思维"
              class="w-full px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 text-xs focus:ring-2 focus:ring-indigo-500 outline-none"
            />
            <p class="text-[10px] text-slate-400 mt-1">若大模型译出了这些别名，流水线也会自动统一纠正为您设定的规范译名。</p>
          </div>

          <!-- 说明注记 -->
          <div>
            <label class="block font-semibold text-slate-700 dark:text-slate-300 mb-1">
              概念说明 / 语境注记 (可选)
            </label>
            <textarea
              v-model="termForm.note"
              rows="2"
              placeholder="例如: 与 thought suppression 区分，指主动停止记忆提取"
              class="w-full px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 text-xs focus:ring-2 focus:ring-indigo-500 outline-none"
            ></textarea>
          </div>
        </div>

        <div class="px-6 py-4 bg-slate-50 dark:bg-slate-800/50 border-t border-slate-100 dark:border-slate-800 flex justify-end gap-2">
          <button
            type="button"
            @click="showEditModal = false"
            class="px-4 py-2 rounded-xl border border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-300 text-xs font-medium"
          >
            取消
          </button>
          <button
            type="button"
            @click="handleSaveTerm"
            class="px-5 py-2 rounded-xl bg-blue-600 hover:bg-blue-700 text-white text-xs font-semibold shadow-sm transition flex items-center gap-1.5"
          >
            <Check class="w-3.5 h-3.5" />
            <span>保存术语</span>
          </button>
        </div>
      </div>
    </div>

    <!-- LLM Extract Modal -->
    <ExtractTermsModal
      v-if="showExtractModal"
      :initialDocId="activeTab === 'doc' ? selectedDocId : undefined"
      :initialDocTitle="activeTab === 'doc' ? currentDocGlossary?.doc_title : undefined"
      @close="showExtractModal = false"
      @imported="handleLlmImported"
    />
  </div>
</template>
