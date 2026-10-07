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

// 允许调用该反代的白名单域名（防止他人盗刷你的 Worker）
const ALLOWED_ORIGINS = [
  'https://octahedron-bb.github.io',
  'http://localhost:5173',
  'http://localhost:5174',
  'http://localhost:3000',
  'http://127.0.0.1:5173',
  'http://127.0.0.1:5174',
  'http://127.0.0.1:3000',
]

function getCorsHeaders(request) {
  const origin = request.headers.get('Origin') || ''
  const isAllowed =
    ALLOWED_ORIGINS.some((allowed) => origin === allowed || origin.startsWith(allowed + '/')) || !origin
  return {
    'Access-Control-Allow-Origin': isAllowed ? (origin || '*') : 'null',
    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type, Authorization',
  }
}

function uint8ToBase64(uint8) {
  let binary = ''
  const chunkSize = 8192
  for (let i = 0; i < uint8.length; i += chunkSize) {
    const chunk = uint8.subarray(i, i + chunkSize)
    binary += String.fromCharCode.apply(null, chunk)
  }
  return btoa(binary)
}

export default {
  async fetch(request, env, ctx) {
    const origin = request.headers.get('Origin') || ''
    const corsHeaders = getCorsHeaders(request)

    // 1. 跨域预检处理
    if (request.method === 'OPTIONS') {
      if (origin && !ALLOWED_ORIGINS.some((allowed) => origin === allowed || origin.startsWith(allowed + '/'))) {
        return new Response(null, { status: 403, headers: corsHeaders })
      }
      return new Response(null, { headers: corsHeaders, status: 204 })
    }

    // 2. 校验 Origin 来源（防盗刷保护）
    if (origin && !ALLOWED_ORIGINS.some((allowed) => origin === allowed || origin.startsWith(allowed + '/'))) {
      return new Response(
        JSON.stringify({ error: 'Forbidden: Unauthorized Origin (仅供 Octahedron 学术伴读调用)' }),
        { status: 403, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
      )
    }

    const url = new URL(request.url)

    if (request.method === 'GET' && (url.pathname === '/' || url.pathname === '/health')) {
      return new Response(
        JSON.stringify({
          status: 'ok',
          service: 'paper-zh Multi-Service Cloudflare Proxy (Edge-TTS & Gemini AI)',
          endpoints: ['/api/edge-tts', '/api/gemini'],
        }),
        {
          headers: { ...corsHeaders, 'Content-Type': 'application/json' },
        }
      )
    }

    // --- 查询公共 Gemini 可用模型列表 ---
    if (request.method === 'GET' && url.pathname.endsWith('/api/gemini/models')) {
      try {
        const geminiApiKey = env?.GEMINI_API_KEY || ''
        if (!geminiApiKey) {
          return new Response(
            JSON.stringify({
              error: {
                message: 'Cloudflare Worker 尚未绑定 GEMINI_API_KEY 环境变量，请在 Cloudflare 仪表盘设置环境变量，或在网页设置中填入您自己的 API Key。',
                type: 'server_error',
              },
            }),
            { status: 500, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
          )
        }
        const resp = await fetch(`https://generativelanguage.googleapis.com/v1beta/models?key=${geminiApiKey}`)
        const data = await resp.text()
        return new Response(data, {
          status: resp.status,
          headers: { ...corsHeaders, 'Content-Type': 'application/json' },
        })
      } catch (err) {
        return new Response(
          JSON.stringify({ error: { message: err.message || String(err), type: 'proxy_error' } }),
          { status: 500, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
        )
      }
    }

    // --- Gemini LLM 免费试用安全代理 ---
    if (request.method === 'POST' && url.pathname.endsWith('/api/gemini')) {
      try {
        const geminiApiKey = env?.GEMINI_API_KEY || ''
        if (!geminiApiKey) {
          return new Response(
            JSON.stringify({
              error: {
                message: 'Cloudflare Worker 尚未绑定 GEMINI_API_KEY 环境变量，请在 Cloudflare 仪表盘设置环境变量，或在网页设置中填入您自己的 API Key。',
                type: 'server_error',
              },
            }),
            { status: 500, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
          )
        }

        const body = await request.json()
        const messages = body.messages || []
        const totalChars = messages.reduce((acc, m) => acc + (m.content ? m.content.length : 0), 0)

        // 防盗刷长度保护：单次伴读翻译/改写控制在 6000 字符以内
        if (totalChars > 6000) {
          return new Response(
            JSON.stringify({
              error: {
                message: '请求文本过长（超过 6000 字符）。为防止公共试用额度被恶意消耗，长篇翻译请在设置中配置您自己的 API Key。',
                type: 'rate_limit_error',
              },
            }),
            { status: 400, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
          )
        }

        // 转发到 Google 官方兼容 OpenAI 协议的端点
        const targetModel = body.model || 'gemini-1.5-flash'
        const googleResp = await fetch(
          'https://generativelanguage.googleapis.com/v1beta/openai/chat/completions',
          {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'Authorization': `Bearer ${geminiApiKey}`,
            },
            body: JSON.stringify({
              model: targetModel,
              messages: body.messages,
              temperature: body.temperature ?? 0.3,
              max_tokens: body.max_tokens ?? 2048,
            }),
          }
        )

        const respData = await googleResp.text()
        return new Response(respData, {
          status: googleResp.status,
          headers: { ...corsHeaders, 'Content-Type': 'application/json' },
        })
      } catch (err) {
        return new Response(
          JSON.stringify({ error: { message: err.message || String(err), type: 'proxy_error' } }),
          { status: 500, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
        )
      }
    }

    // --- Edge-TTS 语音合成代理 ---
    if (request.method === 'POST') {
      try {
        const body = await request.json()
        const text = body.text?.trim() || ''
        const voice = body.voice || 'zh-TW-HsiaoChenNeural'
        const rate = body.rate || '+0%'

        if (!text) {
          return new Response(JSON.stringify({ error: 'text is required' }), {
            status: 400,
            headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          })
        }

        // 3. 防刷熔断：学术伴读单段通常在 200~800 字，个别超长引言/摘要可达 1000~1500 字，设置 3000 字阈值兼顾防刷与长段落朗读
        if (text.length > 3000) {
          return new Response(
            JSON.stringify({ error: 'Text too long: 单次朗读不得超过 3000 字（防盗刷保护）' }),
            {
              status: 400,
              headers: { ...corsHeaders, 'Content-Type': 'application/json' },
            }
          )
        }

        const result = await synthesizeEdgeTts(text, voice, rate)
        return new Response(JSON.stringify(result), {
          headers: { ...corsHeaders, 'Content-Type': 'application/json' },
        })
      } catch (err) {
        return new Response(JSON.stringify({ error: err.message || String(err) }), {
          status: 500,
          headers: { ...corsHeaders, 'Content-Type': 'application/json' },
        })
      }
    }

    return new Response('Not Found', { status: 404, headers: corsHeaders })
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
  try {
    ws.binaryType = 'arraybuffer'
  } catch {}

  return new Promise((resolve, reject) => {
    const audioChunks = []
    const timestamps = []
    const pendingPromises = []
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

    function extractAudioPayload(uint8) {
      if (uint8 && uint8.length >= 2) {
        const headerLen = (uint8[0] << 8) | uint8[1]
        if (uint8.length >= 2 + headerLen) {
          const body = uint8.slice(2 + headerLen)
          if (body.length > 0) {
            audioChunks.push(body)
          }
        }
      }
    }

    async function finish() {
      if (completed) return
      completed = true
      clearTimeout(timer)
      try { ws.close() } catch {}

      if (pendingPromises.length > 0) {
        await Promise.all(pendingPromises)
      }

      const totalLen = audioChunks.reduce((acc, c) => acc + c.length, 0)
      const merged = new Uint8Array(totalLen)
      let offset = 0
      for (const chunk of audioChunks) {
        merged.set(chunk, offset)
        offset += chunk.length
      }

      const base64 = uint8ToBase64(merged)

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

    ws.addEventListener('message', (event) => {
      const data = event.data

      if (typeof data === 'string') {
        if (data.includes('Path:audio.metadata')) {
          const bodyIdx = data.indexOf('\r\n\r\n')
          if (bodyIdx !== -1) {
            try {
              const meta = JSON.parse(data.substring(bodyIdx + 4))
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
        } else if (data.includes('Path:turn.end')) {
          finish().catch(reject)
        }
        return
      }

      // 处理二进制音频帧（兼容 ArrayBuffer / Uint8Array / Blob）
      if (data instanceof Uint8Array) {
        extractAudioPayload(data)
      } else if (data instanceof ArrayBuffer) {
        extractAudioPayload(new Uint8Array(data))
      } else if (typeof Blob !== 'undefined' && data instanceof Blob) {
        const p = data.arrayBuffer().then((buf) => {
          extractAudioPayload(new Uint8Array(buf))
        })
        pendingPromises.push(p)
      }
    })

    ws.addEventListener('error', (err) => {
      if (!completed) {
        completed = true
        clearTimeout(timer)
        reject(new Error('WebSocket 错误: ' + (err.message || String(err))))
      }
    })

    ws.addEventListener('close', () => {
      finish().catch(reject)
    })
  })
}
