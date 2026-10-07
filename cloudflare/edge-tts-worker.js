/**
 * paper-zh: Edge-TTS 免费反代 Cloudflare Worker
 * 
 * 部署方法（零服务器、1分钟完成）：
 * 1. 登录 Cloudflare 控制台 (https://dash.cloudflare.com/)
 * 2. 进入「Compute (Workers) -> Workers & Pages」-> 点击「Create Worker」
 * 3. 命名为如 `edge-tts-proxy`，点击「Deploy」
 * 4. 点击「Edit code」，将本文件所有内容完全覆盖粘贴进去，点击「Deploy」
 * 5. 复制分配的域名（例如 `https://edge-tts-proxy.xxxx.workers.dev`）
 * 6. 在学术伴读 Web 网页右上角「设置」面板的「Edge-TTS 代理 URL」中填入：
 *    `https://edge-tts-proxy.xxxx.workers.dev/api/edge-tts`
 * 7. 保存即可在 GitHub Pages 上永久免费、无视跨域与风控畅听 Edge-TTS！
 */

const TRUSTED_CLIENT_TOKEN = '6A5AA1D4EAFF4E9FB37E23D68491D6F4'
const CHROMIUM_FULL_VERSION = '143.0.3650.75'
const CHROMIUM_MAJOR_VERSION = '143'
const SEC_MS_GEC_VERSION = `1-${CHROMIUM_FULL_VERSION}`

async function generateSecMsGec() {
  const winEpoch = 11644473600
  const secondsToNs = 1e9
  let ticks = Date.now() / 1000
  ticks += winEpoch
  ticks -= ticks % 300
  ticks *= secondsToNs / 100
  const payload = `${ticks.toFixed(0)}${TRUSTED_CLIENT_TOKEN}`
  const digest = await crypto.subtle.digest(
    'SHA-256',
    new TextEncoder().encode(payload)
  )
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('')
    .toUpperCase()
}

function escapeXml(unsafe) {
  return unsafe.replace(/[<>&'"]/g, (c) => {
    switch (c) {
      case '<': return '&lt;'
      case '>': return '&gt;'
      case '&': return '&amp;'
      case "'": return '&apos;'
      case '"': return '&quot;'
      default: return c
    }
  })
}

const CORS_HEADERS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type, Authorization',
}

export default {
  async fetch(request, env, ctx) {
    if (request.method === 'OPTIONS') {
      return new Response(null, { headers: CORS_HEADERS, status: 204 })
    }

    const url = new URL(request.url)

    if (request.method === 'GET' && (url.pathname === '/' || url.pathname === '/health')) {
      return new Response(
        JSON.stringify({
          status: 'ok',
          service: 'paper-zh Edge-TTS Cloudflare Proxy',
          endpoint: '/api/edge-tts',
          usage: 'POST /api/edge-tts with { text, voice, rate }',
        }),
        {
          headers: { ...CORS_HEADERS, 'Content-Type': 'application/json' },
        }
      )
    }

    if (request.method === 'POST') {
      try {
        const body = await request.json()
        const text = body.text?.trim() || ''
        const voice = body.voice || 'zh-TW-HsiaoChenNeural'
        const rate = body.rate || '+0%'

        if (!text) {
          return new Response(JSON.stringify({ error: 'text is required' }), {
            status: 400,
            headers: { ...CORS_HEADERS, 'Content-Type': 'application/json' },
          })
        }

        const result = await synthesizeEdgeTts(text, voice, rate)
        return new Response(JSON.stringify(result), {
          headers: { ...CORS_HEADERS, 'Content-Type': 'application/json' },
        })
      } catch (err) {
        return new Response(JSON.stringify({ error: err.message || String(err) }), {
          status: 500,
          headers: { ...CORS_HEADERS, 'Content-Type': 'application/json' },
        })
      }
    }

    return new Response('Not Found', { status: 404, headers: CORS_HEADERS })
  },
}

async function synthesizeEdgeTts(text, voice, rate) {
  const connectionId = crypto.randomUUID().replace(/-/g, '')
  const requestId = crypto.randomUUID().replace(/-/g, '')
  const gec = await generateSecMsGec()
  const muidBytes = new Uint8Array(16)
  crypto.getRandomValues(muidBytes)
  const muid = Array.from(muidBytes)
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('')
    .toUpperCase()

  const wssUrl =
    `https://speech.platform.bing.com/consumer/speech/synthesize/readaloud/edge/v1?TrustedClientToken=${TRUSTED_CLIENT_TOKEN}` +
    `&ConnectionId=${connectionId}` +
    `&Sec-MS-GEC=${gec}` +
    `&Sec-MS-GEC-Version=${SEC_MS_GEC_VERSION}`

  const resp = await fetch(wssUrl, {
    headers: {
      Upgrade: 'websocket',
      Origin: 'chrome-extension://jdiccldimpdaibmpdkjnbmckianbfold',
      'User-Agent': `Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/${CHROMIUM_MAJOR_VERSION}.0.0.0 Safari/537.36 Edg/${CHROMIUM_MAJOR_VERSION}.0.0.0`,
      'Accept-Language': 'en-US,en;q=0.9',
      Pragma: 'no-cache',
      'Cache-Control': 'no-cache',
      Cookie: `muid=${muid};`,
    },
  })

  const ws = resp.webSocket
  if (!ws) {
    throw new Error('WebSocket 升级失败 (Cloudflare fetch 未能与微软 Bing 建立 WebSocket)')
  }

  ws.accept()

  return new Promise((resolve, reject) => {
    const audioChunks = []
    const timestamps = []
    let completed = false

    const timer = setTimeout(() => {
      if (!completed) {
        completed = true
        try { ws.close() } catch {}
        reject(new Error('Edge-TTS 语音合成超时 (25s)'))
      }
    }, 25000)

    const config =
      'Content-Type:application/json; charset=utf-8\r\nPath:speech.config\r\n\r\n' +
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

    const ssml =
      `<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='zh-CN'>` +
      `<voice name='${voice}'>` +
      `<prosody pitch='+0Hz' rate='${rate}'>` +
      `${escapeXml(text)}` +
      `</prosody></voice></speak>`

    const ssmlMsg =
      `X-Timestamp:${new Date().toISOString()}\r\n` +
      `Content-Type:application/ssml+xml\r\n` +
      `Path:ssml\r\n` +
      `X-RequestId:${requestId}\r\n\r\n` +
      ssml

    ws.send(config)
    ws.send(ssmlMsg)

    ws.addEventListener('message', (event) => {
      if (typeof event.data === 'string') {
        const str = event.data
        if (str.includes('Path:audio.metadata')) {
          const bodyIdx = str.indexOf('\r\n\r\n')
          if (bodyIdx !== -1) {
            try {
              const meta = JSON.parse(str.substring(bodyIdx + 4))
              for (const m of meta?.Metadata || []) {
                if (m.Type === 'WordBoundary') {
                  const offsetSec = (m.Data?.Offset || 0) / 10000000
                  const durationSec = (m.Data?.Duration || 0) / 10000000
                  const wordText = m.Data?.text?.Text || ''
                  timestamps.push({ text: wordText, offsetSec, durationSec })
                }
              }
            } catch {}
          }
        } else if (str.includes('Path:turn.end')) {
          if (!completed) {
            completed = true
            clearTimeout(timer)
            try { ws.close() } catch {}

            const totalLen = audioChunks.reduce((acc, c) => acc + c.byteLength, 0)
            const merged = new Uint8Array(totalLen)
            let offset = 0
            for (const chunk of audioChunks) {
              merged.set(new Uint8Array(chunk), offset)
              offset += chunk.byteLength
            }

            let binary = ''
            const step = 8192
            for (let i = 0; i < merged.length; i += step) {
              binary += String.fromCharCode.apply(null, merged.subarray(i, i + step))
            }
            const base64 = btoa(binary)

            let durationSec = 0
            if (timestamps.length > 0) {
              const last = timestamps[timestamps.length - 1]
              durationSec = last.offsetSec + last.durationSec
            } else {
              durationSec = Math.max(1, text.length * 0.28)
            }

            resolve({
              audioBase64: base64,
              durationSec,
              timestamps,
            })
          }
        }
      } else if (event.data instanceof ArrayBuffer) {
        const view = new DataView(event.data)
        if (view.byteLength > 2) {
          const headerLen = view.getUint16(0)
          const audioOffset = headerLen + 2
          if (view.byteLength > audioOffset) {
            audioChunks.push(event.data.slice(audioOffset))
          }
        }
      }
    })

    ws.addEventListener('error', (err) => {
      if (!completed) {
        completed = true
        clearTimeout(timer)
        reject(new Error('WebSocket 连接或传输错误: ' + (err.message || String(err))))
      }
    })

    ws.addEventListener('close', () => {
      if (!completed) {
        completed = true
        clearTimeout(timer)
        if (audioChunks.length > 0) {
          const totalLen = audioChunks.reduce((acc, c) => acc + c.byteLength, 0)
          const merged = new Uint8Array(totalLen)
          let offset = 0
          for (const chunk of audioChunks) {
            merged.set(new Uint8Array(chunk), offset)
            offset += chunk.byteLength
          }
          let binary = ''
          const step = 8192
          for (let i = 0; i < merged.length; i += step) {
            binary += String.fromCharCode.apply(null, merged.subarray(i, i + step))
          }
          resolve({
            audioBase64: btoa(binary),
            durationSec: Math.max(1, text.length * 0.28),
            timestamps,
          })
        } else {
          reject(new Error('WebSocket 意外断开且未收到音频数据'))
        }
      }
    })
  })
}
