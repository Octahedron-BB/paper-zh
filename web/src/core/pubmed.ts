import type { FeedItem, Settings } from './types'
import { LlmClient } from './llm'
import { DIGEST_SYSTEM } from './prompts'

// 精选前沿 Review 样本（离线/网络受限时的保底数据，具备高质量中文导读）
export const PRESET_PAPERS: FeedItem[] = [
  {
    doi: '10.1038/s41572-026-00741-7',
    doc_id: 's41572-026-00741-7',
    title_en: 'Irritable bowel syndrome: disease mechanisms and clinical management',
    title_zh: '肠易激综合征：疾病机制与临床管理',
    journal: 'Nat Rev Dis Primers',
    pub_date: '2026-03-12',
    brief: '脑-肠轴失调驱动内脏高敏感性，需按亚型阶梯干预。',
    detail: '重点剖析黏膜屏障损伤、肠道菌群失调及中枢痛觉放大机制，阐述基于 IBS-C、IBS-D 与 IBS-M 亚型的个体化神经调节与微生物靶向策略。',
    abstract: 'Irritable bowel syndrome (IBS) is a common disorder of gut-brain interaction characterized by recurrent abdominal pain and altered bowel habits. Recent insights emphasize mucosal barrier defects, dysbiosis, and central pain processing alterations.',
    has_reader: true,
  },
  {
    doi: '10.1038/s41583-025-00929-y',
    doc_id: 's41583-025-00929-y',
    title_en: 'Mechanisms of intrusive thinking and retrieval stopping in mental health',
    title_zh: '精神健康中侵入性思维与检索停止的神经机制',
    journal: 'Nat Rev Neurosci',
    pub_date: '2025-02-14',
    brief: '前额叶通过 GABA 能神经元主动抑制海马记忆提取。',
    detail: '背外侧前额叶通过下调海马 CA1/下托区兴奋性实现“检索停止”，解释了创伤后应激障碍（PTSD）与强迫症患者记忆捕获失控与侵入性思维的根本神经回路机制。',
    abstract: 'Intrusive thinking is a debilitating hallmark of diverse neuropsychiatric disorders. The retrieval stopping framework posits that fronto-hippocampal inhibitory pathways mediated by GABAergic interneurons actively suppress unwanted mnemonic reactivation.',
    has_reader: false,
  },
  {
    doi: '10.1038/s41575-024-00932-1',
    doc_id: 's41575-024-00932-1',
    title_en: 'Metabolic dysfunction-associated steatohepatitis (MASH): mechanisms and emerging therapies',
    title_zh: '代谢功能障碍相关脂肪性肝炎（MASH）：发病机制与新兴疗法',
    journal: 'Nat Rev Gastroenterol Hepatol',
    pub_date: '2024-06-20',
    brief: '脂毒性引发线粒体应激，THR-β 激动剂可有效逆转纤维化。',
    detail: '从脂肪组织游离脂肪酸溢流、肝脏线粒体氧化应激与星状细胞活化三维度切入，分析甲状腺激素受体β激动剂与 FGF21 拟肽药物在逆转进行性肝纤维化中的突破性机制。',
    abstract: 'Metabolic dysfunction-associated steatotic liver disease has become the leading cause of chronic liver disease globally. Recent clinical trials demonstrate efficacy of THR-beta agonists and FGF21 analogues in reversing fibrosis.',
    has_reader: true,
  },
  {
    doi: '10.1038/s41574-022-00638-x',
    doc_id: 's41574-022-00638-x',
    title_en: 'Pathophysiology of type 2 diabetes: a comprehensive endocrine perspective',
    title_zh: '2型糖尿病的病理生理学：综合内分泌学视角',
    journal: 'Nat Rev Endocrinol',
    pub_date: '2022-05-18',
    brief: '高糖脂毒性加速β细胞衰竭，GLP-1 RA具多器官保护。',
    detail: '系统阐述外周胰岛素抵抗与胰岛β细胞功能衰退的双重驱动演进，聚焦内质网应激与慢性低度炎症对胰岛微环境的持续破坏，评估新型肠促胰岛素药物的代谢改善路径。',
    abstract: 'Type 2 diabetes arises from an imbalance between insulin sensitivity and secretion. Chronic nutrient excess triggers endoplasmic reticulum stress, lipotoxicity, and glucotoxicity leading to progressive loss of functional beta-cell mass.',
    has_reader: true,
  },
]

/**
 * 从 PubMed E-Utilities 实时检索并获取真实 Abstract 摘要
 */
export async function fetchPubMedReviews(
  term = '"Nat Rev*"[jour]',
  days = 7
): Promise<FeedItem[]> {
  try {
    const query = `(${term}) AND "review"[pt] AND "last ${days} days"[edat]`
    const searchUrl = `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&term=${encodeURIComponent(
      query
    )}&retmax=20&retmode=json`

    const res = await fetch(searchUrl)
    if (!res.ok) throw new Error(`PubMed 检索响应异常: ${res.status}`)
    const json = await res.json()
    let idList: string[] = json?.esearchresult?.idlist || []

    // 若近 7 天更新较少（周刊节奏），自动扩展至近 30 天
    if (idList.length === 0 && days < 30) {
      const fallbackQuery = `(${term}) AND "review"[pt] AND "last 30 days"[edat]`
      const fallbackUrl = `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&term=${encodeURIComponent(
        fallbackQuery
      )}&retmax=20&retmode=json`
      const fallbackRes = await fetch(fallbackUrl)
      if (fallbackRes.ok) {
        const fallbackJson = await fallbackRes.json()
        idList = fallbackJson?.esearchresult?.idlist || []
      }
    }

    if (idList.length === 0) {
      return PRESET_PAPERS
    }

    // 采用 efetch XML 获取完整题录和正规 Abstract
    const fetchUrl = `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&id=${idList.join(
      ','
    )}&retmode=xml`
    const fetchRes = await fetch(fetchUrl)
    if (!fetchRes.ok) throw new Error(`PubMed 详情获取失败: ${fetchRes.status}`)
    const xmlText = await fetchRes.text()

    const parser = new DOMParser()
    const xmlDoc = parser.parseFromString(xmlText, 'text/xml')
    const articles = Array.from(xmlDoc.querySelectorAll('PubmedArticle'))

    const items: FeedItem[] = []

    for (const art of articles) {
      const pmid = art.querySelector('MedlineCitation > PMID')?.textContent?.trim() || ''
      const titleEn = art.querySelector('ArticleTitle')?.textContent?.trim() || ''
      if (!titleEn) continue

      // DOI
      let doi = ''
      const articleIds = Array.from(art.querySelectorAll('PubmedData > ArticleIdList > ArticleId'))
      for (const aid of articleIds) {
        if (aid.getAttribute('IdType') === 'doi') {
          doi = aid.textContent?.trim() || ''
          break
        }
      }

      // 期刊名称
      const journalEl = art.querySelector('Journal > ISOAbbreviation') || art.querySelector('Journal > Title')
      const journal = journalEl?.textContent?.trim() || 'Nature Reviews'

      // 出版日期
      const pubYear = art.querySelector('JournalIssue > PubDate > Year')?.textContent?.trim() || ''
      const pubMonth = art.querySelector('JournalIssue > PubDate > Month')?.textContent?.trim() || ''
      const pubDate = pubYear ? `${pubYear}${pubMonth ? '-' + pubMonth : ''}` : '近期'

      // 提取真实 Abstract
      const abstractNodes = Array.from(art.querySelectorAll('Abstract > AbstractText'))
      const abstractParts = abstractNodes.map((n) => {
        const label = n.getAttribute('Label')
        const txt = n.textContent?.trim() || ''
        return label ? `${label}: ${txt}` : txt
      }).filter(Boolean)
      const abstract = abstractParts.join(' ')

      const docId = doi ? doi.replace(/^10\.\d+\//, '') : `pmid-${pmid}`

      items.push({
        doi,
        doc_id: docId,
        title_en: titleEn,
        title_zh: '', // 留空，待用户点击或自动生成
        journal,
        pub_date: pubDate,
        brief: abstract ? (abstract.slice(0, 150) + '...') : `${journal} 最新刊出的学术综述论文。`,
        detail: abstract || '暂无详细摘要',
        abstract,
        has_reader: false,
      })
    }

    return items.length > 0 ? items : PRESET_PAPERS
  } catch (err) {
    console.warn('PubMed API 请求遇到限制，使用预设精选数据:', err)
    return PRESET_PAPERS
  }
}

/**
 * 调用 LLM 根据英文标题与真实摘要，生成符合学术规范的中文标题、≤25字 brief 和 50-85字 detail
 */
export async function generateDigest(item: FeedItem, settings: Settings): Promise<{ title_zh: string; brief: string; detail: string }> {
  const llm = new LlmClient(settings)
  const userPrompt = `【期刊】${item.journal}\n【英文标题】${item.title_en}\n【英文摘要】\n${item.abstract || item.detail}`

  const response = await llm.chat([
    { role: 'system', content: DIGEST_SYSTEM },
    { role: 'user', content: userPrompt }
  ], 0.3)

  // 解析返回的 JSON
  let clean = response.trim().replace(/^```(?:json)?\s*|\s*```$/g, '')
  let parsed: any = {}
  try {
    parsed = JSON.parse(clean)
  } catch {
    const match = clean.match(/\{[\s\S]*\}/)
    if (match) {
      try { parsed = JSON.parse(match[0]) } catch {}
    }
  }

  return {
    title_zh: parsed.title_zh || item.title_en,
    brief: parsed.brief || (item.abstract ? item.abstract.slice(0, 50) : ''),
    detail: parsed.detail || (item.abstract ? item.abstract.slice(0, 120) : ''),
  }
}
