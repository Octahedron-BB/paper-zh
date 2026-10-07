/**
 * 核心数据模型类型定义
 */

export interface Segment {
  sid: string
  doc_id: string
  sec_path: string
  sec_heading: string
  sec_level: number
  index: number
  page: number
  src_text: string
  n_words: number
  indented?: boolean
  col?: number
  in_box?: boolean
}

export interface Section {
  heading: string
  level: number
  slug: string
  sec_path: string
  segments: Segment[]
}

export interface Document {
  doc_id: string
  title: string
  sections: Section[]
  segments: Segment[]
}

export type TermMode = 'hard_replace' | 'prompt_hint'

export interface Term {
  term: string
  zh: string
  mode: TermMode
  note?: string
  aliases?: string[]
  pattern?: string
  full_en?: string
  scope?: string
  status?: 'suggested' | 'approved' | 'rejected'
}

export type TtsProvider = 'edge-tts' | 'web-speech' | 'openai' | 'cosyvoice' | 'siliconflow' | 'none'

export interface Settings {
  llmProvider: 'deepseek' | 'openai' | 'gemini' | 'custom'
  apiKey: string
  model: string
  customBaseUrl?: string
  enableTts: boolean
  ttsProvider: TtsProvider
  ttsVoice: string
  ttsRate: string
  academicProxyUrl?: string
  academicProxyCookie?: string
  edgeTtsProxyUrl?: string
  siliconflowApiKey?: string
  siliconflowModel?: string
  // 预留其他 TTS 供应商配置
  customTtsApiKey?: string
  customTtsModel?: string
}

export interface FeedItem {
  doi: string
  doc_id: string
  title_en: string
  title_zh: string
  journal: string
  pub_date: string
  brief: string
  detail: string
  abstract?: string
  has_reader?: boolean
}

export interface ReaderPayload {
  doc_id: string
  title: string
  created_at: string
  audio_base64?: string
  duration_sec?: number
  sections: Section[]
  translations: Record<string, { text: string; text_raw?: string }>
  scripts: Record<string, { text: string }>
  interleave_html?: string
}

export type PipelineStage = 'idle' | 'segment' | 'terms' | 'translate' | 'script' | 'audio' | 'pack' | 'done' | 'error'

export interface PipelineProgress {
  stage: PipelineStage
  current: number
  total: number
  percent: number
  message: string
  logs: string[]
}
