import type { FeedItem } from './types'

// 精选前沿 Review 样本（离线/网络受限时的保底数据）
export const PRESET_PAPERS: FeedItem[] = [
  {
    doi: '10.1038/s41572-026-00741-7',
    doc_id: 's41572-026-00741-7',
    title_en: 'Irritable bowel syndrome: disease mechanisms and clinical management',
    title_zh: '肠易激综合征：疾病机制与临床管理',
    journal: 'Nat Rev Dis Primers',
    pub_date: '2026-03-12',
    brief: '全面综述肠易激综合征（IBS）的最新脑-肠轴病理机制、外周敏感化机制以及靶向肠道菌群与神经调节的临床阶梯治疗策略。',
    detail: '重点剖析内脏高敏感性、黏膜免疫激活及中枢中介痛觉放大，提出基于亚型分类（IBS-C, IBS-D, IBS-M）的个体化联合干预路径。',
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
    brief: '提出前额叶皮层对海马记忆痕迹实施主动“检索停止”抑制控制的双路径神经环路模型。',
    detail: '论证背外侧前额叶（dlPFC）通过GABA能中间神经元下调海马CA1/下托区兴奋性，解释创伤后应激障碍（PTSD）与强迫症患者记忆捕获失控的根本原因。',
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
    brief: '回顾从单纯性肝脂肪变性进展至进行性纤维化与肝硬化的多重打击假说，深度解读抗纤维化靶点新靶药。',
    detail: '从脂肪组织功能障碍游离脂肪酸溢流、肝脏线粒体氧化应激、星状细胞活化三个维度切入，分析甲状腺激素受体β激动剂与FGF21拟肽药物的突破性临床试验。',
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
    brief: '系统阐述胰岛β细胞功能衰竭与外周胰岛素抵抗的双重驱动演进，探讨不同器官间代谢应激网络的恶性循环。',
    detail: '聚焦高血糖毒性、脂毒性以及慢性低度炎症对胰岛微环境的持续破坏，评估肠促胰岛素类似物（GLP-1 RA）与SGLT2抑制剂的多重器官保护益处。',
    abstract: 'Type 2 diabetes arises from an imbalance between insulin sensitivity and secretion. Chronic nutrient excess triggers endoplasmic reticulum stress, lipotoxicity, and glucotoxicity leading to progressive loss of functional beta-cell mass.',
    has_reader: true,
  },
]

/**
 * 从 PubMed E-Utilities 实时检索近 N 天 (默认近 7 天) 的最新 Review 综述文献
 */
export async function fetchPubMedReviews(
  term = '"Nat Rev*"[jour]',
  days = 7
): Promise<FeedItem[]> {
  try {
    // 强制增加 Review 综述类型限制与近 N 天时间窗过滤
    const query = `(${term}) AND "review"[pt] AND "last ${days} days"[edat]`
    const searchUrl = `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&term=${encodeURIComponent(
      query
    )}&retmax=20&retmode=json`

    const res = await fetch(searchUrl)
    if (!res.ok) throw new Error(`PubMed 检索响应异常: ${res.status}`)
    const json = await res.json()
    let idList: string[] = json?.esearchresult?.idlist || []

    // 若近 7 天更新较少（Nature Reviews 周刊节奏），自动平滑回退至近 30 天确保用户总有新文献可读
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

    const summaryUrl = `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=pubmed&id=${idList.join(
      ','
    )}&retmode=json`
    const sumRes = await fetch(summaryUrl)
    if (!sumRes.ok) throw new Error(`PubMed 详情获取失败: ${sumRes.status}`)
    const sumJson = await sumRes.json()
    const result = sumJson?.result || {}

    const items: FeedItem[] = []
    for (const pmid of idList) {
      const doc = result[pmid]
      if (!doc) continue

      let doi = ''
      if (doc.articleids) {
        const dObj = doc.articleids.find((a: any) => a.idtype === 'doi')
        if (dObj) doi = dObj.value
      }

      const docId = doi ? doi.replace(/^10\.\d+\//, '') : `pmid-${pmid}`
      const titleEn = (doc.title || '').replace(/\[.*?\]/g, '').replace(/<.*?>/g, '').trim()

      items.push({
        doi,
        doc_id: docId,
        title_en: titleEn,
        title_zh: titleEn,
        journal: doc.source || 'Nature Reviews',
        pub_date: doc.pubdate || '',
        brief: `${doc.source || 'Nature Reviews'} 本期最新收录综述（Review）。`,
        detail: `PMID: ${pmid} | DOI: ${doi || '暂无'} | 出版日期: ${doc.pubdate || '近期'}`,
        abstract: '',
        has_reader: false,
      })
    }

    return items.length > 0 ? items : PRESET_PAPERS
  } catch (err) {
    console.warn('PubMed API 请求遇到限制，使用预设前沿综述数据:', err)
    return PRESET_PAPERS
  }
}
