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
