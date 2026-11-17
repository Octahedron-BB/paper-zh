/**
 * 术语管理与智能语境保护硬替换引擎（移植自 src/glossary.py）
 */

import type { Term } from './types'

const ABBR_INTRO_RE = /(?:(?:英文)?(?:缩写|简写|简称)(?:为|是|成)?|(?:代号|代称为|命名为|称作|称为|写作|标记为)|(?:即|或称))\s*$/

const PREFIX_ZH: Record<string, string> = {
  a: '前部', p: '后部', r: '右侧', l: '左侧',
  d: '背侧', v: '腹侧', m: '内侧', c: '尾侧', s: '上',
}

export const DEFAULT_GLOSSARY_TERMS: Term[] = [
  { term: 'retrieval stopping', zh: '检索停止', mode: 'prompt_hint', note: '主动停止记忆提取' },
  { term: 'thought suppression', zh: '思维压抑', mode: 'prompt_hint', note: '与 retrieval stopping 区分' },
  { term: 'transdiagnostic', zh: '跨诊断', mode: 'prompt_hint', note: '跨越多种疾病类别存在' },
  { term: 'intrusive thinking', zh: '侵入性思维', mode: 'hard_replace', aliases: ['闯入性思维', '侵扰性思维'] },
  { term: 'mnemonic capture', zh: '记忆捕获', mode: 'prompt_hint', note: '皮层重激活后劫持海马控制' },
  { term: 'inhibitory control', zh: '抑制控制', mode: 'hard_replace', aliases: ['抑制性控制'] },
  { term: 'hippocampal disinhibition', zh: '海马去抑制', mode: 'hard_replace', aliases: ['海马抑制解除'] },
  { term: 'GABAergic inhibition', zh: 'GABA 能抑制', mode: 'hard_replace' },
  { term: 'irritable bowel syndrome', zh: '肠易激综合征', mode: 'hard_replace', aliases: ['过敏性肠综合征'] },
  { term: 'IBS', zh: '肠易激综合征', mode: 'hard_replace' },
  { term: 'gut-brain axis', zh: '脑-肠轴', mode: 'hard_replace', aliases: ['肠脑轴'] },
  { term: 'visceral hypersensitivity', zh: '内脏高敏感性', mode: 'hard_replace' },
  { term: 'type 2 diabetes', zh: '2型糖尿病', mode: 'hard_replace' },
  { term: 'insulin resistance', zh: '胰岛素抵抗', mode: 'hard_replace' },
  { term: 'MASH', zh: '代谢功能障碍相关脂肪性肝炎', mode: 'hard_replace' },
  { term: 'fibrosis', zh: '纤维化', mode: 'hard_replace' },
  { term: 'reassurance', zh: '消除疑虑与病情安抚', mode: 'hard_replace', aliases: ['消除疑虑', '心理安抚', '安慰', '安抚'] },
  { term: 'multi-omics', zh: '多组学', mode: 'hard_replace' },
]

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function fixParenthetical(text: string, t: Term, lookback = 40): string {
  const pat = new RegExp(`[（(]\\s*[a-z]?${escapeRegExp(t.term)}\\s*[）)]`, 'g')
  return text.replace(pat, (_m, offset) => {
    const before = text.slice(Math.max(0, offset - lookback), offset)
    if (t.zh && before.includes(t.zh)) {
      return `（${t.term}）`
    }
    return `（${t.zh}）`
  })
}

function replaceTermToken(text: string, t: Term): string {
  const pat = new RegExp(`(?<![A-Za-z])${escapeRegExp(t.term)}(?![A-Za-z])`, 'g')

  return text.replace(pat, (match, offset) => {
    const start = offset
    const end = offset + match.length
    const before50 = text.slice(Math.max(0, start - 50), start)
    const after10 = text.slice(end, Math.min(text.length, end + 10))

    // 1. 括号内缩写保护：如「肠易激综合征（IBS）」
    if (
      (before50.endsWith('（') || before50.endsWith('(')) &&
      (after10.startsWith('）') || after10.startsWith(')'))
    ) {
      if (t.zh && before50.includes(t.zh)) {
        return match
      }
    }

    // 2. 引述语境保护：如「英文缩写为 IBS」
    if (ABBR_INTRO_RE.test(before50)) {
      return match
    }

    return t.zh
  })
}

export function matchGlossaryTerms(text: string, terms: Term[] = DEFAULT_GLOSSARY_TERMS): Term[] {
  const matched: Term[] = []
  const lowerText = text.toLowerCase()
  for (const t of terms) {
    if (lowerText.includes(t.term.toLowerCase())) {
      matched.push(t)
    }
  }
  return matched
}

export function applyHardReplace(terms: Term[], translated: string): string {
  let out = translated
  const activeHard = terms
    .filter((t) => t.mode === 'hard_replace' && t.status !== 'rejected')
    .sort((a, b) => b.term.length - a.term.length)

  for (const t of activeHard) {
    out = fixParenthetical(out, t)

    const isAbbr = /^[A-Z][A-Za-z0-9]{0,7}$/.test(t.term)
    const hasCjk = /[\u4e00-\u9fff]/.test(t.zh)
    if (isAbbr && hasCjk) {
      const prefixPat = new RegExp(`(?<![A-Za-z])([a-z])${escapeRegExp(t.term)}(?![A-Za-z])`, 'g')
      out = out.replace(prefixPat, (_, p1) => {
        const pZh = PREFIX_ZH[p1.toLowerCase()] || p1
        return pZh + t.zh
      })
    }

    out = replaceTermToken(out, t)

    if (t.aliases && t.aliases.length > 0) {
      const sortedAliases = [...t.aliases].sort((a, b) => b.length - a.length)
      for (const alias of sortedAliases) {
        if (alias && alias !== t.zh && alias !== t.term) {
          out = out.split(alias).join(t.zh)
        }
      }
    }
  }

  return out
}

export function renderPromptBlock(terms: Term[]): string {
  const lines: string[] = []
  for (const t of terms) {
    if (t.status === 'rejected') continue
    if (t.mode === 'prompt_hint') {
      let s = `- ${t.term} -> 「${t.zh}」`
      if (t.note) s += `（${t.note}）`
      lines.push(s)
    } else {
      lines.push(`- ${t.term} -> 「${t.zh}」（统一用此译名）`)
    }
  }
  return lines.join('\n')
}
