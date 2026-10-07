import type { LlmProvider } from './types'

export interface FetchedModel {
  id: string
  name?: string
  description?: string
}

/**
 * 动态向各 LLM 提供商查询当前 API Key 所支持的模型列表
 */
export async function fetchAvailableModels(
  provider: LlmProvider,
  apiKey: string,
  options?: {
    customBaseUrl?: string
    geminiProxyUrl?: string
  }
): Promise<FetchedModel[]> {
  const trimmedKey = (apiKey || '').trim()

  if (provider === 'gemini') {
    if (!trimmedKey) {
      // 没填 Key 时，尝试通过反代请求模型列表；若 Worker 尚未重新部署 /models 路由，平滑回退
      const proxyUrl = options?.geminiProxyUrl 
        ? (options.geminiProxyUrl.replace(/\/+$/, '') + '/models')
        : 'https://edge-tts-proxy.ryoctahedron1998.workers.dev/api/gemini/models'
      try {
        const resp = await fetch(proxyUrl, { method: 'GET' })
        if (resp.ok) {
          const data = await resp.json()
          const list = data.models || data.data || []
          const parsed = parseGeminiModels(list)
          if (parsed.length > 0) return parsed
        }
      } catch (e) {
        // ignore proxy network error and fallback below
      }

      // 平滑回退：返回当前 Worker 免费层级支持的主流模型
      return [
        { id: 'gemini-3.8-flash', name: 'gemini-3.8-flash (公共试用推荐 · 极速)' },
        { id: 'gemini-2.5-flash', name: 'gemini-2.5-flash (轻量稳定版)' },
        { id: 'gemini-1.5-flash', name: 'gemini-1.5-flash (标准版)' },
      ]
    }

    // 用户填写了自己的 Gemini Key：直接请求 Google AI Studio API
    const url = `https://generativelanguage.googleapis.com/v1beta/models?key=${encodeURIComponent(trimmedKey)}`
    const resp = await fetch(url)
    if (!resp.ok) {
      const errJson = await resp.json().catch(() => null)
      const msg = errJson?.error?.message || `Google API 请求失败 (${resp.status})`
      throw new Error(`Gemini 验证失败: ${msg}`)
    }
    const data = await resp.json()
    const list = data.models || []
    return parseGeminiModels(list)
  }

  if (provider === 'deepseek') {
    if (!trimmedKey) throw new Error('请先填入 DeepSeek API Key')
    const resp = await fetch('https://api.deepseek.com/models', {
      headers: {
        Authorization: `Bearer ${trimmedKey}`,
      },
    })
    if (!resp.ok) {
      const text = await resp.text().catch(() => '')
      throw new Error(`DeepSeek 请求失败 (${resp.status}): ${text || 'API Key 无效或网络异常'}`)
    }
    const data = await resp.json()
    const list = data.data || []
    return list.map((m: any) => ({
      id: m.id,
      name: m.id,
    }))
  }

  if (provider === 'openai') {
    if (!trimmedKey) throw new Error('请先填入 OpenAI API Key')
    const resp = await fetch('https://api.openai.com/v1/models', {
      headers: {
        Authorization: `Bearer ${trimmedKey}`,
      },
    })
    if (!resp.ok) {
      const errJson = await resp.json().catch(() => null)
      throw new Error(`OpenAI 验证失败 (${resp.status}): ${errJson?.error?.message || 'API Key 无效'}`)
    }
    const data = await resp.json()
    const list: any[] = data.data || []
    // 过滤出适合对话/翻译的 gpt / o 系列模型，并按名称排序
    const chatModels = list
      .map((m) => m.id as string)
      .filter((id) => (id.startsWith('gpt-') || id.startsWith('o1') || id.startsWith('o3') || id.startsWith('chatgpt-')) && !id.includes('realtime') && !id.includes('audio') && !id.includes('transcription'))
      .sort((a, b) => a.localeCompare(b))

    return chatModels.map((id) => ({ id, name: id }))
  }

  if (provider === 'custom') {
    const base = (options?.customBaseUrl || 'http://localhost:11434/v1').replace(/\/+$/, '')
    const url = base.endsWith('/models') ? base : `${base}/models`
    const headers: Record<string, string> = {}
    if (trimmedKey) {
      headers['Authorization'] = `Bearer ${trimmedKey}`
    }
    const resp = await fetch(url, { headers })
    if (!resp.ok) {
      throw new Error(`自定义端点请求失败 (${resp.status})`)
    }
    const data = await resp.json()
    const list = data.data || data.models || []
    return list.map((m: any) => ({
      id: m.id || m.name,
      name: m.name || m.id,
    }))
  }

  return []
}

function parseGeminiModels(list: any[]): FetchedModel[] {
  return list
    .filter((m: any) => {
      // 筛选支持 generateContent 的模型（排除纯 embedding 或 aqa 等模型）
      const methods = m.supportedGenerationMethods || []
      const isGenerate = methods.includes('generateContent') || methods.length === 0
      const name = (m.name || m.id || '').replace(/^models\//, '')
      return isGenerate && name.startsWith('gemini-')
    })
    .map((m: any) => {
      const cleanId = (m.name || m.id || '').replace(/^models\//, '')
      return {
        id: cleanId,
        name: m.displayName ? `${cleanId} (${m.displayName})` : cleanId,
        description: m.description,
      }
    })
}
