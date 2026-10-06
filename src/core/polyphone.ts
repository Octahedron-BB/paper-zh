/**
 * 多音字与专业医学发音清洗词典（移植自 polyphone.yaml）
 */

export interface PolyphoneRule {
  word: string
  tts: string
  note?: string
}

export const DEFAULT_POLYPHONE_RULES: PolyphoneRule[] = [
  { word: '黏膜', tts: '粘膜', note: '确保读 nián mó' },
  { word: '血栓栓塞', tts: '血栓栓色', note: '确保塞读 sè' },
  { word: '梗塞', tts: '梗色', note: '确保读 sè' },
  { word: '脑梗塞', tts: '脑梗色', note: '确保读 sè' },
  { word: '校正', tts: '矫正', note: '确保读 jiào' },
  { word: '散在', tts: '伞在', note: '确保散读 sǎn' },
  { word: '创伤', tts: 'chuang1 伤', note: '确保读 chuāng' },
  { word: '行剖宫产', tts: '进行剖宫产' },
  { word: '行结扎术', tts: '进行结扎术' },
  { word: '重性抑郁', tts: '仲性抑郁', note: '重读 zhòng' },
  { word: '中型棘状', tts: '中型及状' },
]

export function cleanForTts(text: string, rules: PolyphoneRule[] = DEFAULT_POLYPHONE_RULES): string {
  let cleaned = text
  for (const r of rules) {
    cleaned = cleaned.split(r.word).join(r.tts)
  }
  // 英文大写缩写字母间加空格（如 IBS -> I B S），防止 TTS 连读怪音
  cleaned = cleaned.replace(/\b([A-Z]{2,6})\b/g, (match) => match.split('').join(' '))
  return cleaned
}
