import https from 'node:https'
import crypto from 'node:crypto'
import type { IncomingMessage, ServerResponse } from 'node:http'

function generateSecMsGec(): string {
  const S_TO_NS = 1e9
  const WIN_EPOCH = 11644473600
  const TRUSTED_CLIENT_TOKEN = '6A5AA1D4EAFF4E9FB37E23D68491D6F4'
  let ticks = Date.now() / 1000
  ticks += WIN_EPOCH
  ticks -= ticks % 300
  ticks *= S_TO_NS / 100
  const strToHash = `${ticks.toFixed(0)}${TRUSTED_CLIENT_TOKEN}`
  return crypto.createHash('sha256').update(strToHash, 'ascii').digest('hex').toUpperCase()
}

function makeWebSocketFrame(data: Buffer | string, isBinary = false): Buffer {
  const payload = Buffer.isBuffer(data) ? data : Buffer.from(data)
  const length = payload.length
  let header: Buffer
  const mask = crypto.randomBytes(4)

  if (length <= 125) {
    header = Buffer.alloc(6)
    header[0] = isBinary ? 0x82 : 0x81
    header[1] = 0x80 | length
    mask.copy(header, 2)
  } else if (length <= 65535) {
    header = Buffer.alloc(8)
    header[0] = isBinary ? 0x82 : 0x81
    header[1] = 0x80 | 126
    header.writeUInt16BE(length, 2)
    mask.copy(header, 4)
  } else {
    header = Buffer.alloc(14)
    header[0] = isBinary ? 0x82 : 0x81
    header[1] = 0x80 | 127
    header.writeBigUInt64BE(BigInt(length), 2)
    mask.copy(header, 10)
  }

  const maskedPayload = Buffer.alloc(length)
  for (let i = 0; i < length; i++) {
    maskedPayload[i] = payload[i] ^ mask[i % 4]
  }

  return Buffer.concat([header, maskedPayload])
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

export function synthesizeEdgeTtsNode(
  text: string,
  voice = 'zh-TW-HsiaoChenNeural',
  rate = '+0%'
): Promise<{ audioBase64: string; durationSec: number; timestamps: any[] }> {
  return new Promise((resolve, reject) => {
    const connectionId = crypto.randomUUID().replace(/-/g, '')
    const requestId = crypto.randomUUID().replace(/-/g, '')
    const token = '6A5AA1D4EAFF4E9FB37E23D68491D6F4'
    const gec = generateSecMsGec()
    const secKey = crypto.randomBytes(16).toString('base64')
    const muid = crypto.randomBytes(16).toString('hex').toUpperCase()

    const path =
      `/consumer/speech/synthesize/readaloud/edge/v1?TrustedClientToken=${token}` +
      `&ConnectionId=${connectionId}` +
      `&Sec-MS-GEC=${gec}` +
      `&Sec-MS-GEC-Version=1-143.0.3650.75`

    const req = https.request({
      hostname: 'speech.platform.bing.com',
      port: 443,
      path,
      method: 'GET',
      headers: {
        Connection: 'Upgrade',
        Upgrade: 'websocket',
        'Sec-WebSocket-Version': '13',
        'Sec-WebSocket-Key': secKey,
        Origin: 'chrome-extension://jdiccldimpdaibmpdkjnbmckianbfold',
        'User-Agent':
          'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36 Edg/143.0.0.0',
        Pragma: 'no-cache',
        'Cache-Control': 'no-cache',
        'Accept-Encoding': 'gzip, deflate, br, zstd',
        'Accept-Language': 'en-US,en;q=0.9',
        Cookie: `muid=${muid};`,
      },
    })

    const audioBuffers: Buffer[] = []
    const timestamps: { text: string; offsetSec: number; durationSec: number }[] = []
    let bufferAcc = Buffer.alloc(0)
    let completed = false

    const timer = setTimeout(() => {
      if (!completed) {
        completed = true
        req.destroy()
        reject(new Error('Edge-TTS 请求超时 (20s)'))
      }
    }, 20000)

    req.on('upgrade', (_res, socket) => {
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

      socket.write(makeWebSocketFrame(config))
      socket.write(makeWebSocketFrame(ssmlMsg))

      socket.on('data', (chunk: Buffer) => {
        bufferAcc = Buffer.concat([bufferAcc, chunk])

        // 简易 WebSocket 帧解析循环
        while (bufferAcc.length >= 2) {
          const firstByte = bufferAcc[0]
          const secondByte = bufferAcc[1]
          const opcode = firstByte & 0x0f
          const isMasked = (secondByte & 0x80) !== 0
          let payloadLength = secondByte & 0x7f
          let offset = 2

          if (payloadLength === 126) {
            if (bufferAcc.length < 4) break
            payloadLength = bufferAcc.readUInt16BE(2)
            offset = 4
          } else if (payloadLength === 127) {
            if (bufferAcc.length < 10) break
            payloadLength = Number(bufferAcc.readBigUInt64BE(2))
            offset = 10
          }

          let mask: Buffer | null = null
          if (isMasked) {
            if (bufferAcc.length < offset + 4) break
            mask = bufferAcc.subarray(offset, offset + 4)
            offset += 4
          }

          if (bufferAcc.length < offset + payloadLength) {
            // 数据未完整
            break
          }

          let payload = bufferAcc.subarray(offset, offset + payloadLength)
          bufferAcc = bufferAcc.subarray(offset + payloadLength)

          if (mask) {
            const unmasked = Buffer.alloc(payload.length)
            for (let i = 0; i < payload.length; i++) {
              unmasked[i] = payload[i] ^ mask[i % 4]
            }
            payload = unmasked
          }

          if (opcode === 0x01) {
            // Text frame
            const str = payload.toString('utf-8')
            if (str.includes('Path:audio.metadata')) {
              const bodyIdx = str.indexOf('\r\n\r\n')
              if (bodyIdx !== -1) {
                try {
                  const metaJson = JSON.parse(str.substring(bodyIdx + 4))
                  for (const m of metaJson?.Metadata || []) {
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
                socket.destroy()

                const fullBuffer = Buffer.concat(audioBuffers)
                let durationSec = 0
                if (timestamps.length > 0) {
                  const last = timestamps[timestamps.length - 1]
                  durationSec = last.offsetSec + last.durationSec
                } else {
                  durationSec = Math.max(1, text.length * 0.28)
                }

                resolve({
                  audioBase64: fullBuffer.toString('base64'),
                  durationSec,
                  timestamps,
                })
              }
            }
          } else if (opcode === 0x02) {
            // Binary frame
            if (payload.length > 2) {
              const headerLength = payload.readUInt16BE(0)
              const audioOffset = headerLength + 2
              if (payload.length > audioOffset) {
                audioBuffers.push(payload.subarray(audioOffset))
              }
            }
          }
        }
      })

      socket.on('error', (err) => {
        if (!completed) {
          completed = true
          clearTimeout(timer)
          reject(err)
        }
      })

      socket.on('close', () => {
        if (!completed) {
          completed = true
          clearTimeout(timer)
          if (audioBuffers.length > 0) {
            const fullBuffer = Buffer.concat(audioBuffers)
            resolve({
              audioBase64: fullBuffer.toString('base64'),
              durationSec: Math.max(1, text.length * 0.28),
              timestamps,
            })
          } else {
            reject(new Error('WebSocket 意外断开且未收到音频数据'))
          }
        }
      })
    })

    req.on('error', (err) => {
      if (!completed) {
        completed = true
        clearTimeout(timer)
        reject(err)
      }
    })

    req.end()
  })
}

export function edgeTtsMiddleware() {
  return async (req: IncomingMessage, res: ServerResponse, next: () => void) => {
    if (req.url === '/api/edge-tts' && req.method === 'POST') {
      let bodyStr = ''
      req.on('data', (chunk) => {
        bodyStr += chunk
      })
      req.on('end', async () => {
        try {
          const body = JSON.parse(bodyStr || '{}')
          const text = body.text || ''
          const voice = body.voice || 'zh-TW-HsiaoChenNeural'
          const rate = body.rate || '+0%'

          if (!text) {
            res.statusCode = 400
            res.setHeader('Content-Type', 'application/json')
            res.end(JSON.stringify({ error: 'Text is required' }))
            return
          }

          const result = await synthesizeEdgeTtsNode(text, voice, rate)
          res.statusCode = 200
          res.setHeader('Content-Type', 'application/json')
          res.end(JSON.stringify(result))
        } catch (err: any) {
          res.statusCode = 500
          res.setHeader('Content-Type', 'application/json')
          res.end(JSON.stringify({ error: err.message || 'TTS Synthesis failed' }))
        }
      })
      return
    }
    next()
  }
}
