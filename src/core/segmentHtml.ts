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

/**
 * 清理段落 DOM：
 * 1. 移除无关浮动图表/表格/公式
 * 2. 将参考文献 <a> 或 <sup> 规范化为 [N] 形式，杜绝无空格粘连
 * 3. 自动剔除末尾的版权转载声明 (Reprinted with permission...)
 */
function cleanParagraphNode(pNode: HTMLElement): string {
  const clone = pNode.cloneNode(true) as HTMLElement

  // 移除浮动元素、嵌套表格、公式
  const toRemove = clone.querySelectorAll(
    'figure, table, .c-article-table, .c-article-equation, [data-component="figure"]'
  )
  toRemove.forEach((el) => el.remove())

  // 处理参考文献上标链接：将 <sup><a data-test="citation-ref">15</a></sup> 规范为 [15]
  const supList = clone.querySelectorAll('sup')
  supList.forEach((sup) => {
    const rawTxt = cleanText(sup.textContent || '')
    if (rawTxt) {
      // 若为纯数字或数字范围 (如 1, 15, 1-3, 1,2)
      if (/^[\d,\s\-–—]+$/.test(rawTxt)) {
        const textNode = document.createTextNode(`[${rawTxt}]`)
        sup.parentNode?.replaceChild(textNode, sup)
      } else {
        const textNode = document.createTextNode(`^${rawTxt}`)
        sup.parentNode?.replaceChild(textNode, sup)
      }
    }
  })

  // 其余未包裹在 sup 内但带 data-test="citation-ref" 的链接
  const citeLinks = clone.querySelectorAll('a[data-test="citation-ref"]')
  citeLinks.forEach((a) => {
    const rawTxt = cleanText(a.textContent || '')
    if (rawTxt && /^[\d,\s\-–—]+$/.test(rawTxt)) {
      const textNode = document.createTextNode(`[${rawTxt}]`)
      a.parentNode?.replaceChild(textNode, a)
    }
  })

  let text = clone.textContent || ''
  text = cleanText(text)

  // 标点前紧贴引用，如 form[1].
  text = text.replace(/\s+(\[\d+(?:[,\s\-–—\d]*)\])/g, '$1')

  // 剔除末尾版权声明行（如 Reprinted with permission from ref. 61, Elsevier）
  text = text.replace(/(?:Reprinted|Adapted)\s+with\s+permission\s+from\s+.*$/i, '').trim()

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

  interface ParagraphItem {
    text: string
    isFigure?: boolean
    figLabel?: string
    inBox?: boolean
  }

  function addSection(heading: string, level: number, items: ParagraphItem[]) {
    const normHeading = heading.toLowerCase().trim()
    if (SKIP_SECTIONS.has(normHeading)) return

    const slug = slugify(heading)
    const secPath = `s${String(secIdx).padStart(3, '0')}-${slug}`
    secIdx++

    const secSegments: Segment[] = []
    let pIdx = 1

    for (const item of items) {
      const txt = item.text
      if (txt.length < 15 && !txt.endsWith('.')) continue

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
        in_box: !!item.inBox,
        is_figure: !!item.isFigure,
        fig_label: item.figLabel,
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
      const items: ParagraphItem[] = absPs
        .map((p) => ({ text: cleanParagraphNode(p) }))
        .filter((it) => it.text.length > 0)
      addSection('Abstract', 1, items)
    }
  }

  // 3. 提取各级正文章节
  const mainArticle =
    doc.querySelector("div.main-content") ||
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

    // 智能提取段落：保留正文、检测插图图注（Figure Caption）、聚合 Box 诊断标准清单
    const items: ParagraphItem[] = []

    // 遍历 section 内的所有段落
    const allPs = Array.from(sec.querySelectorAll('p')) as HTMLElement[]

    for (let pIdx = 0; pIdx < allPs.length; pIdx++) {
      const p = allPs[pIdx]
      if (processedPs.has(p)) continue
      processedPs.add(p)

      // A. 检测是否属于插图说明 (Figure Description)
      const figContainer = p.closest('div.c-article-section__figure, figure') as HTMLElement | null
      if (figContainer) {
        const captionEl = figContainer.querySelector('b.c-article-section__figure-caption, figcaption')
        let figLabel = ''
        if (captionEl) {
          figLabel = cleanText(captionEl.textContent || '')
        }
        const cleanTxt = cleanParagraphNode(p)
        if (cleanTxt) {
          items.push({
            text: cleanTxt,
            isFigure: true,
            figLabel: figLabel || 'Fig',
          })
        }
        continue
      }

      // B. 检测是否属于可折叠框 / Box（如 Box 1 罗马诊断标准）
      const boxContainer = p.closest('div.c-article-box') as HTMLElement | null
      if (boxContainer) {
        let pTxt = cleanParagraphNode(p)
        if (!pTxt) continue

        // 若当前段落以冒号结尾（如 associated with two or more of the following criteria:）
        // 且后面紧跟着列表 <ol> 或 <ul>，智能将其聚合为完整的一段标准准则！
        if (pTxt.endsWith(':')) {
          let nextSibling: Element | null = p.nextElementSibling
          while (nextSibling && nextSibling.tagName.toLowerCase() === 'p' && !cleanText(nextSibling.textContent || '')) {
            nextSibling = nextSibling.nextElementSibling
          }
          if (nextSibling && (nextSibling.tagName.toLowerCase() === 'ol' || nextSibling.tagName.toLowerCase() === 'ul')) {
            const listItems = Array.from(nextSibling.querySelectorAll('li'))
            const formattedItems: string[] = []
            listItems.forEach((li, idx) => {
              const numEl = li.querySelector('.u-custom-list-number')
              let numStr = numEl ? cleanText(numEl.textContent || '') : `${idx + 1}.`
              if (!numStr.endsWith('.')) numStr += '.'

              // 克隆 li 清理内部
              const liClone = li.cloneNode(true) as HTMLElement
              liClone.querySelector('.u-custom-list-number')?.remove()
              const liTxt = cleanParagraphNode(liClone)
              if (liTxt) {
                formattedItems.push(`${numStr} ${liTxt}`)
              }
            })

            if (formattedItems.length > 0) {
              pTxt = `${pTxt} ${formattedItems.join('; ')}`
            }
          }
        }

        // 若当前 p 正好是列表 li 内部的直接子段落，在上面已经被聚合，直接跳过避免孤立成段
        if (p.closest('li')) {
          continue
        }

        items.push({
          text: pTxt,
          inBox: true,
        })
        continue
      }

      // C. 普通正文段落
      const cleanTxt = cleanParagraphNode(p)
      if (cleanTxt) {
        items.push({
          text: cleanTxt,
        })
      }
    }

    if (items.length > 0) {
      addSection(heading, level, items)
    }
  }

  // 兜底：若没有任何 section 标签，按扁平 p 标签提取
  if (sections.length === 0) {
    const allPs = Array.from(mainArticle.querySelectorAll('p')) as HTMLElement[]
    if (allPs.length > 0) {
      const items = allPs.map((p) => ({ text: cleanParagraphNode(p) })).filter((it) => it.text.length > 0)
      addSection('Introduction', 1, items)
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
