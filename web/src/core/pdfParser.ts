import type { Document, Section, Segment } from './types'

let pdfjsLoaded = false

async function loadPdfJs(): Promise<any> {
  if (pdfjsLoaded && (window as any).pdfjsLib) {
    return (window as any).pdfjsLib
  }

  return new Promise((resolve, reject) => {
    if ((window as any).pdfjsLib) {
      pdfjsLoaded = true
      return resolve((window as any).pdfjsLib)
    }

    const script = document.createElement('script')
    script.src = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js'
    script.onload = () => {
      pdfjsLoaded = true
      const pdfjs = (window as any).pdfjsLib
      if (pdfjs) {
        pdfjs.GlobalWorkerOptions.workerSrc =
          'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js'
      }
      resolve(pdfjs)
    }
    script.onerror = () => {
      reject(new Error('无法加载 PDF.js 脚本，请检查网络或直接上传 HTML 文件'))
    }
    document.head.appendChild(script)
  })
}

export async function parsePdf(file: File, docId: string): Promise<Document> {
  const pdfjs = await loadPdfJs()
  const arrayBuffer = await file.arrayBuffer()
  const loadingTask = pdfjs.getDocument({ data: arrayBuffer })
  const pdf = await loadingTask.promise

  const sections: Section[] = []
  const allSegments: Segment[] = []

  let currentHeading = 'Abstract'
  let currentLevel = 2
  let currentSecPath = 'sec-0'
  let currentSecSegments: Segment[] = []
  let globalSegIdx = 0

  function commitSection() {
    if (currentSecSegments.length > 0) {
      sections.push({
        heading: currentHeading,
        level: currentLevel,
        slug: currentSecPath,
        sec_path: currentSecPath,
        segments: [...currentSecSegments],
      })
      currentSecSegments = []
    }
  }

  for (let pageNum = 1; pageNum <= pdf.numPages; pageNum++) {
    const page = await pdf.getPage(pageNum)
    const textContent = await page.getTextContent()
    const items = textContent.items as any[]

    if (!items || items.length === 0) continue

    // 简单分行与按段落聚合
    let currentParagraph = ''

    for (const item of items) {
      const text = item.str.trim()
      if (!text) continue

      // 检测是否为标题：字号明显偏大或特定的段落标题模式
      const fontSize = Math.abs(item.transform[0] || item.transform[3] || 10)
      const isHeading =
        fontSize > 13 ||
        /^(Introduction|Results|Discussion|Methods|References|Abstract|Conclusion)$/i.test(text)

      if (isHeading && text.length < 80) {
        if (currentParagraph.length > 20) {
          const seg: Segment = {
            sid: `${currentSecPath}#p${currentSecSegments.length}`,
            doc_id: docId,
            sec_path: currentSecPath,
            sec_heading: currentHeading,
            sec_level: currentLevel,
            index: globalSegIdx++,
            page: pageNum,
            src_text: currentParagraph.trim(),
            n_words: currentParagraph.trim().split(/\s+/).length,
          }
          currentSecSegments.push(seg)
          allSegments.push(seg)
          currentParagraph = ''
        }

        commitSection()
        currentHeading = text
        currentSecPath = `sec-${sections.length}`
        continue
      }

      currentParagraph += (currentParagraph ? ' ' : '') + item.str
      // 简单句末段落判断
      if (item.str.endsWith('.') && item.str.length > 10 && currentParagraph.length > 300) {
        const seg: Segment = {
          sid: `${currentSecPath}#p${currentSecSegments.length}`,
          doc_id: docId,
          sec_path: currentSecPath,
          sec_heading: currentHeading,
          sec_level: currentLevel,
          index: globalSegIdx++,
          page: pageNum,
          src_text: currentParagraph.trim(),
          n_words: currentParagraph.trim().split(/\s+/).length,
        }
        currentSecSegments.push(seg)
        allSegments.push(seg)
        currentParagraph = ''
      }
    }

    if (currentParagraph.length > 20) {
      const seg: Segment = {
        sid: `${currentSecPath}#p${currentSecSegments.length}`,
        doc_id: docId,
        sec_path: currentSecPath,
        sec_heading: currentHeading,
        sec_level: currentLevel,
        index: globalSegIdx++,
        page: pageNum,
        src_text: currentParagraph.trim(),
        n_words: currentParagraph.trim().split(/\s+/).length,
      }
      currentSecSegments.push(seg)
      allSegments.push(seg)
    }
  }

  commitSection()

  return {
    doc_id: docId,
    title: file.name.replace(/\.[^/.]+$/, ''),
    sections,
    segments: allSegments,
  }
}
