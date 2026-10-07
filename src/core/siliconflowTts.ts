/**
 * 硅基流动 (SiliconFlow) TTS 客户端 (CosyVoice / ChatTTS)
 * 天然支持浏览器端 CORS 跨域请求，零反代直连
 */
import type { TtsResult } from './edgeTts'

export async function synthesizeSiliconFlowTts(
  text: string,
  apiKey: string,
  voice = 'FunAudioLLM/CosyVoice2-0.5B:alex',
  model = 'FunAudioLLM/CosyVoice2-0.5B',
  rate = '+0%'
): Promise<TtsResult> {
  if (!text || !text.trim()) {
    return {
      audioBlob: new Blob([], { type: 'audio/mp3' }),
      audioBase64: '',
      durationSec: 0,
      timestamps: [],
    }
  }

  if (!apiKey || !apiKey.trim()) {
    throw new Error(
      '未配置硅基流动 API Key。请在【配置与模型 ➔ 伴读语音】中填入您的 SiliconFlow 密钥（可在 cloud.siliconflow.cn 免费获取）。'
    )
  }

  // 转换速率：+0% -> 1.0, +10% -> 1.1, -15% -> 0.85
  const rateNum = parseFloat(rate.replace('%', '')) || 0
  const speed = Math.max(0.5, Math.min(2.0, 1.0 + rateNum / 100))

  const cleanKey = apiKey.trim()
  const payload = {
    model: model || 'FunAudioLLM/CosyVoice2-0.5B',
    input: text.trim(),
    voice: voice || 'FunAudioLLM/CosyVoice2-0.5B:alex',
    response_format: 'mp3',
    sample_rate: 32000,
    speed,
    gain: 0,
  }

  let res: Response
  try {
    res = await fetch('https://api.siliconflow.cn/v1/audio/speech', {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${cleanKey}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
    })
  } catch (err: any) {
    throw new Error(`连接硅基流动服务器失败: ${err.message}`)
  }

  if (!res.ok) {
    let errDetail = ''
    try {
      const errJson = await res.json()
      errDetail = errJson?.message || errJson?.error?.message || JSON.stringify(errJson)
    } catch {
      errDetail = await res.text().catch(() => '')
    }

    if (res.status === 401) {
      throw new Error(`硅基流动 API Key 无效或未授权 (401): ${errDetail}`)
    } else if (res.status === 402) {
      throw new Error(`硅基流动账户余额不足 (402): 请前往 cloud.siliconflow.cn 充值或领取赠送额度`)
    } else {
      throw new Error(`硅基流动 TTS 请求失败 (${res.status}): ${errDetail || res.statusText}`)
    }
  }

  const blob = await res.blob()
  if (!blob || blob.size === 0) {
    throw new Error('硅基流动返回空音频')
  }

  // 转换为 Base64
  const arrayBuffer = await blob.arrayBuffer()
  const bytes = new Uint8Array(arrayBuffer)
  let binary = ''
  const len = bytes.byteLength
  for (let i = 0; i < len; i++) {
    binary += String.fromCharCode(bytes[i])
  }
  const base64 = btoa(binary)

  // 测量真实音频时长（Web Audio API 解码）
  let durationSec = 0
  try {
    const AudioCtx = window.AudioContext || (window as any).webkitAudioContext
    if (AudioCtx) {
      const ctx = new AudioCtx()
      const audioBuffer = await ctx.decodeAudioData(arrayBuffer.slice(0))
      durationSec = audioBuffer.duration
      ctx.close()
    }
  } catch {
    durationSec = Math.max(1, text.length * 0.28)
  }

  if (!durationSec || durationSec <= 0) {
    durationSec = Math.max(1, text.length * 0.28)
  }

  return {
    audioBlob: blob,
    audioBase64: base64,
    durationSec,
    timestamps: [],
  }
}
