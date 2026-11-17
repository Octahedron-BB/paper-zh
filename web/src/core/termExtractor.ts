import { LlmClient } from './llm'
import { settingsState } from '../store/settings'
import type { Term, Document } from './types'
import { extractDocAbbreviations } from './abbrev'

export interface ExtractedTermCandidate extends Term {
  selected: boolean
  isDuplicate?: boolean
  duplicateIn?: 'global' | 'doc' | 'both'
}

export interface ExtractTermsInput {
  doc?: Document
  text?: string
  title?: string
}

export async function extractTermsWithLlm(
  input: ExtractTermsInput,
  customPrompt?: string
): Promise<ExtractedTermCandidate[]> {
  const client = new LlmClient(settingsState)

  let textSample = ''
  let abbrHints = ''
  let docTitle = input.title || input.doc?.title || '学术文献'

  if (input.doc) {
    const segs = input.doc.segments
    const textPieces: string[] = []
    let wordCount = 0

    // 重点截取标题、摘要、引言、讨论等具有高密度核心概念的段落（截取约 4000-5000 词）
    for (const seg of segs) {
      if (wordCount > 5000) break
      textPieces.push(`[${seg.sec_heading || 'Section'}] ${seg.src_text}`)
      wordCount += seg.n_words || 20
    }
    textSample = textPieces.join('\n\n')

    // 运行正则学术缩写识别，作为给 LLM 的高精度参考提示
    try {
      const abbrs = extractDocAbbreviations(input.doc)
      if (abbrs.length > 0) {
        abbrHints = `\n\n【文中已检测到的学术缩写及其全称参考】:\n` +
          abbrs.slice(0, 30).map((a) => `- ${a.abbr}: ${a.full}`).join('\n')
      }
    } catch {}
  } else if (input.text) {
    textSample = input.text.slice(0, 15000)
  }

  if (!textSample.trim()) {
    throw new Error('未提供可供提炼术语的文献内容或文本')
  }

  const systemPrompt = `你是一名资深生物医学与学术文献翻译专家，精通自然科学学术规范与中英专有名词对照标准。
你的任务是从用户提供的学术文献原文片段中，精准提炼出高价值的核心专业术语、学术缩写词、疾病/分子/脑区/机制名称及学科专有名词。

【提炼与筛选准则】
1. 专注高价值学术术语：
   - 提取对学术翻译一致性、专业理解至关重要的专有名词、核心理论、生理机制、技术方法与学术缩写。
   - 严格过滤掉常见通用非术语词汇（如 research, study, data, result, patient, method, level, increase 等无需作为术语）。
2. 提供权威精准规范译名：
   - 翻译必须符合国内权威专业词典（如全国科学技术名词审定委员会）规范。
3. 替换模式 (mode) 判定：
   - "hard_replace"（硬替换 · 默认推荐）：概念名词、专有名词、标准病名、缩写、解剖结构。译后强制全文统一替换，0 token 成本。
   - "prompt_hint"（Prompt 引导）：具有多重语境歧义、首次出现需加解释、或需配合句式重塑的复杂短语。
4. 提供简明注记 (note)：
   - 简短说明该术语的概念内涵、适用语境或英文全称。
5. 提供常见别名 (aliases)：
   - 若国内文献或通用 LLM 经常给出其他易混淆或次选译名，列在 aliases 中以便统一校正。

【严格输出格式】
必须且只能返回纯 JSON 格式数组，不要包含任何 markdown 解释或多余前后缀：
[
  {
    "term": "英文术语原文或缩写",
    "zh": "精准规范中文译名",
    "mode": "hard_replace",
    "note": "简要学术释义或全称",
    "aliases": ["常见别名1", "别名2"]
  }
]`

  const userPrompt = `文献标题: ${docTitle}${abbrHints}

${customPrompt ? `【用户补充要求】: ${customPrompt}\n\n` : ''}【待提炼学术文本片段】:
${textSample}

请从上方文本中精炼提炼出 10-35 条最核心、最值得纳入术语表的专业学术术语，直接返回 JSON 数组：`

  const responseText = await client.chat(
    [
      { role: 'system', content: systemPrompt },
      { role: 'user', content: userPrompt },
    ],
    0.2,
    4096
  )

  let cleaned = responseText.trim()
  if (cleaned.startsWith('```')) {
    cleaned = cleaned.replace(/^```(?:json)?\s*/i, '').replace(/\s*```$/, '')
  }

  const firstBracket = cleaned.indexOf('[')
  const lastBracket = cleaned.lastIndexOf(']')
  if (firstBracket >= 0 && lastBracket > firstBracket) {
    cleaned = cleaned.slice(firstBracket, lastBracket + 1)
  }

  let rawList: any[] = []
  try {
    rawList = JSON.parse(cleaned)
  } catch (err: any) {
    throw new Error(`LLM 输出未能成功解析为有效 JSON 格式: ${err.message}\n原始输出: ${cleaned.slice(0, 200)}...`)
  }

  if (!Array.isArray(rawList)) {
    throw new Error('LLM 返回的术语格式无效，未能解析为列表')
  }

  return rawList
    .map((item: any) => ({
      term: String(item.term || '').trim(),
      zh: String(item.zh || '').trim(),
      mode: (item.mode === 'prompt_hint' ? 'prompt_hint' : 'hard_replace') as 'prompt_hint' | 'hard_replace',
      note: item.note ? String(item.note).trim() : undefined,
      aliases: Array.isArray(item.aliases)
        ? item.aliases.map((a: any) => String(a).trim()).filter((a: string) => a && a !== item.zh)
        : undefined,
      selected: true,
    }))
    .filter((item) => item.term && item.zh)
}
