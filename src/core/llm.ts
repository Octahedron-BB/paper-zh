import type { Settings } from './types'

export interface ChatMessage {
  role: 'system' | 'user' | 'assistant'
  content: string
}

export class LlmClient {
  private settings: Settings

  constructor(settings: Settings) {
    this.settings = settings
  }

  updateSettings(settings: Settings) {
    this.settings = settings
  }

  private getEndpointAndHeaders(): { url: string; headers: Record<string, string>; model: string } {
    const { llmProvider, apiKey, apiKeys, model, models, customBaseUrl, geminiProxyUrl } = this.settings

    // 获取当前服务商独立保存的 Key 与模型
    const activeKey = (apiKeys?.[llmProvider] || apiKey || '').trim()
    const activeModel = (models?.[llmProvider] || model || '').trim()

    let url = ''
    let reqModel = activeModel
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
    }

    if (llmProvider === 'deepseek') {
      if (!activeKey) {
        throw new Error('请先在设置中填写 DeepSeek API Key')
      }
      url = 'https://api.deepseek.com/chat/completions'
      headers['Authorization'] = `Bearer ${activeKey}`
      reqModel = activeModel || 'deepseek-chat'
    } else if (llmProvider === 'openai') {
      if (!activeKey) {
        throw new Error('请先在设置中填写 OpenAI API Key')
      }
      url = 'https://api.openai.com/v1/chat/completions'
      headers['Authorization'] = `Bearer ${activeKey}`
      reqModel = activeModel || 'gpt-4o-mini'
    } else if (llmProvider === 'gemini') {
      reqModel = activeModel || 'gemini-3.5-flash-lite'
      if (activeKey) {
        // 用户填写了私有 Key：直接调用 Google AI Studio 官方端点
        url = 'https://generativelanguage.googleapis.com/v1beta/openai/chat/completions'
        headers['Authorization'] = `Bearer ${activeKey}`
      } else {
        // 用户未配置 Key：无缝切换为内置公共免费试用代理
        url = geminiProxyUrl || 'https://edge-tts-proxy.ryoctahedron1998.workers.dev/api/gemini'
      }
    } else if (llmProvider === 'custom') {
      const base = (customBaseUrl || '').replace(/\/+$/, '')
      url = base.endsWith('/chat/completions') ? base : `${base}/chat/completions`
      if (activeKey) {
        headers['Authorization'] = `Bearer ${activeKey}`
      }
    }

    return { url, headers, model: reqModel }
  }

  async chat(messages: ChatMessage[], temperature = 0.3, maxTokens = 4096): Promise<string> {
    const { url, headers, model } = this.getEndpointAndHeaders()

    const body = {
      model,
      messages,
      temperature,
      max_tokens: maxTokens,
      stream: false,
    }

    try {
      const response = await fetch(url, {
        method: 'POST',
        headers,
        body: JSON.stringify(body),
      })

      if (!response.ok) {
        let errDetail = ''
        try {
          const errJson = await response.json()
          errDetail = errJson?.error?.message || JSON.stringify(errJson)
        } catch {
          errDetail = await response.text()
        }
        throw new Error(`LLM 请求失败 (${response.status}): ${errDetail}`)
      }

      const data = await response.json()
      const content = data?.choices?.[0]?.message?.content || ''
      return content.trim()
    } catch (err: any) {
      if (err.name === 'TypeError' && err.message.includes('Failed to fetch')) {
        throw new Error('网络请求被阻止或跨域 (CORS) 失败。如果是自定义中转，请确保允许浏览器跨域；或使用支持 CORS 的 API 代理。')
      }
      throw err
    }
  }
}
