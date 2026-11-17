import { get, set } from 'idb-keyval'
import type { Term } from '../core/types'
import { DEFAULT_GLOSSARY_TERMS } from '../core/glossary'

export interface DocGlossaryRecord {
  doc_id: string
  doc_title: string
  updatedAt: string
  terms: Term[]
}

const GLOBAL_KEY = 'paper_glossary_global'
const DOCS_KEY = 'paper_glossary_docs'

/**
 * 1. 获取总术语表 (Global Glossary)
 * 若首次加载无数据，则自动以系统预设术语表初始化
 */
export async function getGlobalTerms(): Promise<Term[]> {
  try {
    const val = await get<Term[]>(GLOBAL_KEY)
    if (val && Array.isArray(val) && val.length > 0) {
      return val
    }
    // 初次加载时以内置预设初始化
    await set(GLOBAL_KEY, DEFAULT_GLOSSARY_TERMS)
    return [...DEFAULT_GLOSSARY_TERMS]
  } catch (e) {
    console.error('获取总术语表失败:', e)
    return [...DEFAULT_GLOSSARY_TERMS]
  }
}

/**
 * 2. 保存总术语表
 */
export async function saveGlobalTerms(terms: Term[]): Promise<void> {
  await set(GLOBAL_KEY, terms)
}

/**
 * 3. 重置总术语表为出厂预设
 */
export async function resetGlobalTerms(): Promise<Term[]> {
  await set(GLOBAL_KEY, DEFAULT_GLOSSARY_TERMS)
  return [...DEFAULT_GLOSSARY_TERMS]
}

/**
 * 4. 获取所有文献分术语表字典 (Record<doc_id, DocGlossaryRecord>)
 */
export async function getAllDocGlossaries(): Promise<Record<string, DocGlossaryRecord>> {
  try {
    const val = await get<Record<string, DocGlossaryRecord>>(DOCS_KEY)
    return val || {}
  } catch (e) {
    console.error('获取分术语表字典失败:', e)
    return {}
  }
}

/**
 * 5. 获取指定文献的分术语表条目
 */
export async function getDocTerms(docId: string): Promise<Term[]> {
  if (!docId) return []
  const all = await getAllDocGlossaries()
  return all[docId]?.terms || []
}

/**
 * 6. 保存指定文献的分术语表
 */
export async function saveDocTerms(docId: string, terms: Term[], docTitle?: string): Promise<void> {
  if (!docId) return
  const all = await getAllDocGlossaries()
  all[docId] = {
    doc_id: docId,
    doc_title: docTitle || all[docId]?.doc_title || docId,
    updatedAt: new Date().toISOString(),
    terms,
  }
  await set(DOCS_KEY, all)
}

/**
 * 7. 删除指定文献的分术语表
 */
export async function deleteDocGlossary(docId: string): Promise<void> {
  if (!docId) return
  const all = await getAllDocGlossaries()
  delete all[docId]
  await set(DOCS_KEY, all)
}

/**
 * 8. 核心合并函数：就近优先（doc > global）
 * 在流水线执行时调用，单篇文献的专属术语覆盖全局同名术语
 */
export async function getMergedGlossary(docId?: string): Promise<Term[]> {
  const globalTerms = await getGlobalTerms()
  if (!docId) return globalTerms

  const docTerms = await getDocTerms(docId)
  if (!docTerms || docTerms.length === 0) return globalTerms

  const docTermSet = new Set(docTerms.map((t) => t.term.toLowerCase().trim()))
  const filteredGlobal = globalTerms.filter(
    (gt) => !docTermSet.has(gt.term.toLowerCase().trim())
  )

  return [...docTerms, ...filteredGlobal]
}
