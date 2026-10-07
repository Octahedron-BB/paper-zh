import { get, set, del, keys } from 'idb-keyval'

export interface SavedPaper {
  doc_id: string
  title: string
  createdAt: string
  html: string
  durationSec?: number
  segCount: number
  hasAudio: boolean
}

const LIB_PREFIX = 'paper_reader_'

export async function savePaperToLibrary(paper: SavedPaper): Promise<void> {
  await set(`${LIB_PREFIX}${paper.doc_id}`, paper)
}

export async function getPaperFromLibrary(docId: string): Promise<SavedPaper | undefined> {
  return await get(`${LIB_PREFIX}${docId}`)
}

export async function deletePaperFromLibrary(docId: string): Promise<void> {
  await del(`${LIB_PREFIX}${docId}`)
}

export async function getAllSavedPapers(): Promise<SavedPaper[]> {
  try {
    const allKeys = await keys()
    const paperKeys = allKeys.filter((k) => typeof k === 'string' && k.startsWith(LIB_PREFIX))
    const papers: SavedPaper[] = []

    for (const key of paperKeys) {
      const item = await get<SavedPaper>(key)
      if (item) papers.push(item)
    }

    // 按创建时间倒序
    papers.sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime())
    return papers
  } catch (e) {
    console.error('读取书架失败:', e)
    return []
  }
}

/**
 * 伴读工作流断点缓存数据结构
 */
export interface PipelineCheckpoint {
  doc_id: string
  updatedAt: string
  translations: Record<string, string>
  scripts: Record<string, string>
  ttsResults?: Record<string, {
    audioBlob?: Blob
    audioBase64?: string
    durationSec: number
    timestamps: any[]
    scriptText: string
  }>
}

const CHECKPOINT_PREFIX = 'paper_pipeline_ckpt_'

export async function savePipelineCheckpoint(ckpt: PipelineCheckpoint): Promise<void> {
  try {
    await set(`${CHECKPOINT_PREFIX}${ckpt.doc_id}`, ckpt)
  } catch (e) {
    console.warn('保存断点失败:', e)
  }
}

export async function getPipelineCheckpoint(docId: string): Promise<PipelineCheckpoint | undefined> {
  try {
    return await get(`${CHECKPOINT_PREFIX}${docId}`)
  } catch (e) {
    return undefined
  }
}

export async function clearPipelineCheckpoint(docId: string): Promise<void> {
  try {
    await del(`${CHECKPOINT_PREFIX}${docId}`)
  } catch {}
}

