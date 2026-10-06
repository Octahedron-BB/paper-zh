/**
 * 高保真语义 HTML 分段引擎（浏览器原生 DOMParser 实现）。
 * 移植自 Python src/segment_html.py，零第三方依赖。
 */

import type { Document, Section, Segment } from './types'

const SKIP_SECTIONS = new Set([
  'references',
  'acknowledgements',
  'acknowledgments',
  'author information',
  'ethics declarations',
  'additional information',
  'rights and permissions',
  'about this article',
  'peer review information',
  'data availability',
  'code availability',
  'competing interests',
  'supplementary information',
])

function cleanText(text: string): string {
  return text
    .replace(/\u00a0/g, ' ')
    .replace(/\u00ad/g, '')
    .replace(/\s+/g, ' ')
    .trim()
}

function slugify(text: string): string {
  const s = text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
  return s.slice(0, 30) || 'sec'
}

function countWords(text: string): number {
  const matches = text.match(/[A-Za-z0-9\-']+/g)
  return matches ? matches.length : 0
}

function cleanParagraphNode(pNode: HTMLElement): string {
  // 克隆节点避免污染原始 DOM
  const clone = pNode.cloneNode(true) as HTMLElement

  // 移除浮动元素、图注、表格
  const toRemove = clone.querySelectorAll(
    'figure, table, .c-article-table, .c-article-figure, .c-article-equation, [data-component="figure"]'
  )
  toRemove.forEach((el) => el.remove())

  let text = clone.textContent || ''
  text = cleanText(text)
  // 清理行内上标引用残留，如 [1, 2] 或 [1-3]
  text = text.replace(/\[\s*\d+(?:[\s,\-–—\d]*)\s*\]/g, '')
  return cleanText(text)
}

export function parseNatureHtml(htmlContent: string, docId: string): Document {
  const parser = new DOMParser()
  const doc = parser.parseFromString(htmlContent, 'text/html')

  // 1. 提取文章标题
  let title = ''
  const titleEl =
    doc.querySelector('h1.c-article-title') ||
    doc.querySelector("h1[data-test='article-title']") ||
    doc.querySelector('article h1') ||
    doc.querySelector('h1')

  if (titleEl) {
    title = cleanText(titleEl.textContent || '')
  }
  if (!title) {
    title = doc.title || docId
  }

  const sections: Section[] = []
  const allSegments: Segment[] = []
  let secIdx = 0

  function addSection(heading: string, level: number, pNodes: HTMLElement[]) {
    const normHeading = heading.toLowerCase().trim()
    if (SKIP_SECTIONS.has(normHeading)) return

    const slug = slugify(heading)
    const secPath = `s${String(secIdx).padStart(3, '0')}-${slug}`
    secIdx++

    const secSegments: Segment[] = []
    let pIdx = 1

    for (const pNode of pNodes) {
      const txt = cleanParagraphNode(pNode)
      if (txt.length < 20 && !txt.endsWith('.')) continue

      const sid = `${docId}:${secPath}:p${String(pIdx).padStart(2, '0')}`
      pIdx++

      const seg: Segment = {
        sid,
        doc_id: docId,
        sec_path: secPath,
        sec_heading: heading,
        sec_level: level,
        index: allSegments.length,
        page: 1,
        src_text: txt,
        n_words: countWords(txt),
        indented: false,
        col: 0,
        in_box: false,
      }
      secSegments.push(seg)
      allSegments.push(seg)
    }

    if (secSegments.length > 0) {
      sections.push({
        heading,
        level,
        slug,
        sec_path: secPath,
        segments: secSegments,
      })
    }
  }

  // 2. 提取摘要 Abstract
  const absSection =
    doc.querySelector("section[data-title='Abstract']") ||
    doc.querySelector('#Abs1-section') ||
    doc.querySelector("div[data-title='Abstract']")

  if (absSection) {
    const absPs = Array.from(absSection.querySelectorAll('p')) as HTMLElement[]
    if (absPs.length > 0) {
      addSection('Abstract', 1, absPs)
    }
  }

  // 3. 提取各级正文章节
  const mainArticle =
    doc.querySelector("div[data-component='article-body']") ||
    doc.querySelector('.c-article-body') ||
    doc.querySelector('article') ||
    doc.body

  const secElements = Array.from(
    mainArticle.querySelectorAll('section[data-title], div.c-article-section, section')
  ) as HTMLElement[]

  const processedPs = new Set<HTMLElement>()

  for (const sec of secElements) {
    const headingEl = sec.querySelector('h2, h3, h4')
    const heading = headingEl
      ? cleanText(headingEl.textContent || '')
      : cleanText(sec.getAttribute('data-title') || '')

    if (!heading) continue
    if (heading.toLowerCase() === 'abstract' && sections.length > 0) continue

    const level = headingEl && headingEl.tagName.toLowerCase() === 'h3' ? 2 : 1

    // 仅抓取直接子段落或未被其它 section 处理过的段落
    const ps = Array.from(sec.querySelectorAll('p')).filter((p) => {
      const htmlP = p as HTMLElement
      if (processedPs.has(htmlP)) return false
      processedPs.add(htmlP)
      return true
    }) as HTMLElement[]

    if (ps.length > 0) {
      addSection(heading, level, ps)
    }
  }

  // 兜底：若没有任何 section 标签，按扁平 p 标签提取
  if (sections.length === 0) {
    const allPs = Array.from(mainArticle.querySelectorAll('p')) as HTMLElement[]
    if (allPs.length > 0) {
      addSection('Introduction', 1, allPs)
    }
  }

  return {
    doc_id: docId,
    title,
    sections,
    segments: allSegments,
  }
}

export const segmentHtml = parseNatureHtml

