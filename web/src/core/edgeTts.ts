/**
 * 纯前端 Edge-TTS 客户端 (基于浏览器 WebSocket)
 * 能够获取 MP3 音频二进制流并解析词级 / 句级时间戳 (WordBoundary)
 */

export interface WordTimestamp {
  text: string
  offsetSec: number
  durationSec: number
}

export interface TtsResult {
  audioBlob: Blob
  audioBase64: string
  durationSec: number
  timestamps: WordTimestamp[]
}

function generateUuid(): string {
  return 'xxxxxxxxxxxx4xxxyxxxxxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0
    const v = c === 'x' ? r : (r & 0x3) | 0x8
    return v.toString(16)
  })
}

function escapeXml(unsafe: string): string {
  return unsafe.replace(/[<>&'"]/g, (c) => {
    switch (c) {
      case '<': return '&lt;'
      case '>': return '&gt;'
      case '&': return '&amp;'
      case '\'': return '&apos;'
      case '"': return '&quot;'
      default: return c
    }
  })
}

export async function synthesizeEdgeTts(
  text: string,
  voice = 'zh-TW-HsiaoChenNeural',
  rate = '+0%'
): Promise<TtsResult> {
  // 1. 优先调用后端/开发服务器 Edge-TTS 代理 (采用 Node.js 最新 Sec-MS-GEC 签名，确保 100% 真实云端音色)
  try {
    const res = await fetch('/api/edge-tts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, voice, rate }),
    })
    if (res.ok) {
      const data = await res.json()
      if (data && data.audioBase64) {
        const binary = atob(data.audioBase64)
        const bytes = new Uint8Array(binary.length)
        for (let i = 0; i < binary.length; i++) {
          bytes[i] = binary.charCodeAt(i)
        }
        const blob = new Blob([bytes], { type: 'audio/mp3' })
        return {
          audioBlob: blob,
          audioBase64: data.audioBase64,
          durationSec: data.durationSec || Math.max(1, text.length * 0.28),
          timestamps: data.timestamps || [],
        }
      }
    }
  } catch {
    // 代理不可用时继续回退
  }

  // 2. 直接 WebSocket 降级尝试
  const connectionId = generateUuid()
  const requestId = generateUuid()
  const token = '6A5AA1D4EAFF4E9FB37E23D68491D6F4'
  const url = `wss://speech.platform.bing.com/consumer/speech/synthesize/readaloud/edge/v1?TrustedClientToken=${token}&ConnectionId=${connectionId}`

  return new Promise((resolve, reject) => {
    let ws: WebSocket
    try {
      ws = new WebSocket(url)
    } catch (err) {
      return reject(new Error(`无法建立 WebSocket 连接: ${err}`))
    }

    ws.binaryType = 'arraybuffer'

    const audioChunks: Uint8Array[] = []
    const timestamps: WordTimestamp[] = []
    let completed = false
    const timeoutTimer = setTimeout(() => {
      if (!completed) {
        completed = true
        ws.close()
        reject(new Error('Edge-TTS 请求超时 (25s)'))
      }
    }, 25000)

    ws.onopen = () => {
      // 1. 发送 speech.config
      const configMsg =
        `Content-Type:application/json; charset=utf-8\r\nPath:speech.config\r\n\r\n` +
        JSON.stringify({
          context: {
            synthesis: {
              audio: {
                metadataoptions: {
                  sentenceBoundaryEnabled: 'false',
                  wordBoundaryEnabled: 'true',
                },
                outputFormat: 'audio-24khz-48kbitrate-mono-mp3',
              },
            },
          },
        })
      ws.send(configMsg)

      // 2. 发送 SSML
      const timestamp = new Date().toISOString()
      const escapedText = escapeXml(text)
      const ssml =
        `<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='zh-CN'>` +
        `<voice name='${voice}'>` +
        `<prosody pitch='+0Hz' rate='${rate}'>` +
        `${escapedText}` +
        `</prosody></voice></speak>`

      const ssmlMsg =
        `X-Timestamp:${timestamp}\r\n` +
        `Content-Type:application/ssml+xml\r\n` +
        `Path:ssml\r\n` +
        `X-RequestId:${requestId}\r\n\r\n` +
        ssml

      ws.send(ssmlMsg)
    }

    ws.onmessage = (event) => {
      if (typeof event.data === 'string') {
        const msg = event.data
        if (msg.includes('Path:audio.metadata')) {
          const bodyIndex = msg.indexOf('\r\n\r\n')
          if (bodyIndex !== -1) {
            try {
              const bodyJson = JSON.parse(msg.substring(bodyIndex + 4))
              const metaList = bodyJson?.Metadata || []
              for (const m of metaList) {
                if (m.Type === 'WordBoundary') {
                  // 1 tick = 100ns = 1e-7 s
                  const offsetSec = (m.Data?.Offset || 0) / 10000000
                  const durationSec = (m.Data?.Duration || 0) / 10000000
                  const wordText = m.Data?.text?.Text || ''
                  timestamps.push({ text: wordText, offsetSec, durationSec })
                }
              }
            } catch {
              // ignore json parse error
            }
          }
        } else if (msg.includes('Path:turn.end')) {
          completed = true
          clearTimeout(timeoutTimer)
          ws.close()

          const blob = new Blob(audioChunks as any, { type: 'audio/mp3' })
          const reader = new FileReader()
          reader.onloadend = () => {
            const dataUrl = reader.result as string
            const base64 = dataUrl.split(',')[1] || ''

            // 计算总时长
            let durationSec = 0
            if (timestamps.length > 0) {
              const last = timestamps[timestamps.length - 1]
              durationSec = last.offsetSec + last.durationSec
            }

            resolve({
              audioBlob: blob,
              audioBase64: base64,
              durationSec,
              timestamps,
            })
          }
          reader.onerror = () => {
            reject(new Error('转换音频 Base64 失败'))
          }
          reader.readAsDataURL(blob)
        }
      } else if (event.data instanceof ArrayBuffer) {
        // 二进制音频数据
        const view = new DataView(event.data)
        if (event.data.byteLength > 2) {
          const headerLength = view.getUint16(0)
          const audioOffset = headerLength + 2
          if (event.data.byteLength > audioOffset) {
            const audioData = new Uint8Array(event.data.slice(audioOffset))
            audioChunks.push(audioData)
          }
        }
      }
    }

    ws.onerror = (_err) => {
      if (!completed) {
        clearTimeout(timeoutTimer)
        completed = true
        reject(new Error(`Edge-TTS WebSocket 错误: 网络中断或服务不可达`))
      }
    }

    ws.onclose = () => {
      if (!completed) {
        clearTimeout(timeoutTimer)
        completed = true
        if (audioChunks.length > 0) {
          const blob = new Blob(audioChunks as any, { type: 'audio/mp3' })
          const reader = new FileReader()
          reader.onloadend = () => {
            const dataUrl = reader.result as string
            const base64 = dataUrl.split(',')[1] || ''
            resolve({
              audioBlob: blob,
              audioBase64: base64,
              durationSec: 0,
              timestamps,
            })
          }
          reader.readAsDataURL(blob)
        } else {
          reject(new Error('Edge-TTS 连接关闭，未接收到有效音频'))
        }
      }
    }
  })
}
