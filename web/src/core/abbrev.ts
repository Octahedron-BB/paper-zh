/**
 * 学术缩写识别与首字母校验（移植自 src/abbrev.py）
 */

import type { Document } from './types'

const STOP_WORDS = new Set([
  'of', 'the', 'in', 'and', 'for', 'to', 'a', 'an', 'on', 'with', 'by',
  'as', 'at', 'from', 'or', 'its', 'their', 'that', 'which',
])

const PAT_FULL_FIRST = /\b((?:[A-Za-z][A-Za-z\-']*\s+){1,6}[A-Za-z][A-Za-z\-']*)\s*\(\s*([A-Z][A-Za-z0-9]{1,7})\s*\)/g
const PAT_ABBR_FIRST = /\b([A-Z][A-Za-z0-9]{1,7})\s*\(\s*([a-z][A-Za-z\-']*(?:\s+[A-Za-z\-']+){0,6})\s*\)/g

function isSubsequence(needle: string, haystack: string): boolean {
  let i = 0
  for (const char of haystack) {
    if (i < needle.length && char === needle[i]) {
      i++
    }
  }
  return i === needle.length
}

export function initialsOk(abbr: string, full: string): boolean {
  const words = (full.match(/[A-Za-z]+/g) || []).filter(
    (w) => !STOP_WORDS.has(w.toLowerCase())
  )
  const inits = words.map((w) => w[0].toUpperCase()).join('')
  const upperAbbr = abbr.toUpperCase()
  return isSubsequence(upperAbbr, inits) || isSubsequence(upperAbbr, full.toUpperCase())
}

export function extractDefinitions(text: string): Record<string, string> {
  const defs: Record<string, string> = {}

  let m: RegExpExecArray | null
  while ((m = PAT_FULL_FIRST.exec(text)) !== null) {
    const full = m[1].trim()
    const abbr = m[2].trim()
    if (initialsOk(abbr, full)) {
      defs[abbr] = full
    }
  }

  while ((m = PAT_ABBR_FIRST.exec(text)) !== null) {
    const abbr = m[1].trim()
    const full = m[2].trim()
    if (initialsOk(abbr, full)) {
      defs[abbr] = full
    }
  }

  return defs
}

export function extractDocAbbreviations(doc: Document): Array<{ abbr: string; full: string }> {
  const map: Record<string, string> = {}
  for (const seg of doc.segments) {
    const local = extractDefinitions(seg.src_text)
    Object.assign(map, local)
  }
  return Object.entries(map).map(([abbr, full]) => ({ abbr, full }))
}
