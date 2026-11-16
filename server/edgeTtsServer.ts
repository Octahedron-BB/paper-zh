import https from 'node:https'
import crypto from 'node:crypto'
import type { IncomingMessage, ServerResponse } from 'node:http'

const TRUSTED_CLIENT_TOKEN = '6A5AA1D4EAFF4E9FB37E23D68491D6F4'
const CHROMIUM_FULL_VERSION = '143.0.3650.75'
const SEC_MS_GEC_VERSION = `2-${CHROMIUM_FULL_VERSION}`

const WIN_EPOCH = 11644473600n
const S_TO_NS = 1000000000n

const _SHA256_INITIAL = [
  0x6A09E667n, 0xBB67AE85n, 0x3C6EF372n, 0xA54FF53An,
  0x510E527Fn, 0x9B05688Cn, 0x1F83D9ABn, 0x5BE0CD19n
]
const _SHA256_STATE = [
  0xFD9FBEA2n, 0x91243CE7n, 0xBE499094n, 0xCD2E1E0An,
  0x6C006F49n, 0x04BD35ABn, 0xFEB0A7E4n, 0x03EFFBD2n
]
const _SHA256_SCHEDULE = [
  0xEB24BF9En, 0x1558691Fn, 0xA0C09EE2n, 0x0CFA32BAn,
  0xA622EE8Cn, 0xD1DD9491n, 0xC0DD25A0n, 0xF9E70AB6n,
  0xF0C31573n, 0x7058CE4En, 0x7188E606n, 0x00E5AB33n,
  0xD258B060n, 0x72766564n
]
const _SHA256_ROUND_CONSTANTS = [
  0x428A2F98n, 0x71374491n, 0xB5C0FBCFn, 0xE9B5DBA5n,
  0x3956C25Bn, 0x59F111F1n, 0x923F82A4n, 0xAB1C5ED5n,
  0xD807AA98n, 0x12835B01n, 0x243185BEn, 0x550C7DC3n,
  0x72BE5D74n, 0x80DEB1FEn, 0x9BDC06A7n, 0xC19BF174n,
  0xE49B69C1n, 0xEFBE4786n, 0x0FC19DC6n, 0x240CA1CCn,
  0x2DE92C6Fn, 0x4A7484AAn, 0x5CB0A9DCn, 0x76F988DAn,
  0x983E5152n, 0xA831C66Dn, 0xB00327C8n, 0xBF597FC7n,
  0xC6E00BF3n, 0xD5A79147n, 0x06CA6351n, 0x14292967n,
  0x27B70A85n, 0x2E1B2138n, 0x4D2C6DFCn, 0x53380D13n,
  0x650A7354n, 0x766A0ABBn, 0x81C2C92En, 0x92722C85n,
  0xA2BFE8A1n, 0xA81A664Bn, 0xC24B8B70n, 0xC76C51A3n,
  0xD192E819n, 0xD6990624n, 0xF40E3585n, 0x106AA070n,
  0x19A4C116n, 0x1E376C08n, 0x2748774Cn, 0x34B0BCB5n,
  0x391C0CB3n, 0x4ED8AA4An, 0x5B9CCA4Fn, 0x682E6FF3n,
  0x748F82EEn, 0x78A5636Fn, 0x84C87814n, 0x8CC70208n,
  0x90BEFFFAn, 0xA4506CEBn, 0xBEF9A3F7n, 0xC67178F2n
]
const _SHA256_ADJUSTMENT = 0xC9DC06A7n
const _SHA256_BLOCK_CONSTANTS = [
  ..._SHA256_ROUND_CONSTANTS.slice(0, 14),
  _SHA256_ADJUSTMENT,
  ..._SHA256_ROUND_CONSTANTS.slice(15)
]
const _SHA256_SIGMA0_ADJUSTMENT = 0x059C0B80n
const _SHA256_SIGMA1_ADJUSTMENT = 0x000B92C0n

const _CS64_COEFFICIENTS = [
  [0xE82E91B1n, 0xB32700D0n],
  [0x44DE24C6n, 0x88DFF51Dn],
  [0x3BEB65BCn, 0x29514038n],
  [0xC89C5933n, 0xB328CBDFn],
  [0x8D1EC211n, 0xD405B4D5n],
  [0x314EF5D5n, 0x26E55F3Cn],
  [0xE92491B1n, 0x607801C6n],
  [0xF0A5B9D5n, 0x82B2C1FBn],
  [0x06064CF3n, 0xFA51A3DAn],
  [0xDA79FA60n, 0x207CC464n],
  [0xBED20560n, 0x3C3C74F3n],
  [0x89F9C9F8n, 0xD2D14B61n],
  [0x35FA38C6n, 0xBB04A2C1n],
  [0xCB49E3C6n, 0xC5626167n]
]
const _CS64_FACTOR = 0x82893933n
const _CS64_ADJUSTMENT0 = 0xF2F90B1An
const _CS64_ADJUSTMENT1 = 0x0B1A0000n

const _U32_MASK = 0xFFFFFFFFn

function _rol16(value: bigint) {
  value = value & _U32_MASK
  return (((value << 16n) | (value >> 16n)) & _U32_MASK)
}

function _words_le4_even(data: Uint8Array) {
  const padLen = (4 - (data.length % 4)) % 4
  const padded = new Uint8Array(data.length + padLen)
  padded.set(data)
  if (padded.length === 0) return []
  const words: bigint[] = []
  const view = new DataView(padded.buffer, padded.byteOffset, padded.byteLength)
  for (let i = 0; i < padded.length; i += 4) {
    words.push(BigInt(view.getUint32(i, true)))
  }
  if (words.length % 2 !== 0) {
    words.push(0n)
  }
  return words
}

function _sigma0(v: bigint) {
  return (((v >> 7n) ^ (v << 25n) ^ (v >> 18n) ^ (v << 14n) ^ (v >> 3n)) & _U32_MASK)
}

function _sigma1(v: bigint) {
  return (((v >> 17n) ^ (v << 15n) ^ (v >> 19n) ^ (v << 13n) ^ (v >> 10n)) & _U32_MASK)
}

function _expand_sha256_schedule(words: bigint[], first_word = 16) {
  for (let idx = first_word; idx < 64; idx++) {
    const x = words[idx - 2]
    const y = words[idx - 15]
    const s1 = ((x >> 17n) ^ (x << 15n) ^ (x >> 19n) ^ (x << 13n) ^ (x >> 10n))
    const s0 = ((y >> 7n) ^ (y << 25n) ^ (y >> 18n) ^ (y << 14n) ^ (y >> 3n))
    words.push((s1 + words[idx - 7] + s0 + words[idx - 16]) & _U32_MASK)
  }
}

function _sha256_rounds(state: bigint[], words: bigint[], first_round = 0) {
  let [a, b, c, d, e, f, g, h] = state
  const constants = (first_round === 14) ? _SHA256_BLOCK_CONSTANTS : _SHA256_ROUND_CONSTANTS
  const aligned = Math.min(64, Math.floor((first_round + 7) / 8) * 8)

  for (let idx = first_round; idx < aligned; idx++) {
    const rot_e = e * 0x100000001n
    const rot_a = a * 0x100000001n
    const t1 = (
      h +
      ((rot_e >> 6n) ^ (rot_e >> 11n) ^ (rot_e >> 25n)) +
      (g ^ (e & (f ^ g))) +
      constants[idx] +
      words[idx]
    )
    const t2 = ((rot_a >> 2n) ^ (rot_a >> 13n) ^ (rot_a >> 22n)) + ((a & b) | (c & (a | b)))
    const new_a = (t1 + t2) & _U32_MASK
    const new_d = (d + t1) & _U32_MASK
    ;[a, b, c, d, e, f, g, h] = [new_a, a, b, c, new_d, e, f, g]
  }

  for (let idx = aligned; idx < 64; idx += 8) {
    let rot_e = e * 0x100000001n
    let rot_a = a * 0x100000001n
    let t1 = (
      h +
      ((rot_e >> 6n) ^ (rot_e >> 11n) ^ (rot_e >> 25n)) +
      (g ^ (e & (f ^ g))) +
      constants[idx] +
      words[idx]
    )
    d = (d + t1) & _U32_MASK
    h = (t1 + ((rot_a >> 2n) ^ (rot_a >> 13n) ^ (rot_a >> 22n)) + ((a & b) | (c & (a | b)))) & _U32_MASK

    rot_e = d * 0x100000001n
    rot_a = h * 0x100000001n
    t1 = (
      g +
      ((rot_e >> 6n) ^ (rot_e >> 11n) ^ (rot_e >> 25n)) +
      (f ^ (d & (e ^ f))) +
      constants[idx + 1] +
      words[idx + 1]
    )
    c = (c + t1) & _U32_MASK
    g = (t1 + ((rot_a >> 2n) ^ (rot_a >> 13n) ^ (rot_a >> 22n)) + ((h & a) | (b & (h | a)))) & _U32_MASK

    rot_e = c * 0x100000001n
    rot_a = g * 0x100000001n
    t1 = (
      f +
      ((rot_e >> 6n) ^ (rot_e >> 11n) ^ (rot_e >> 25n)) +
      (e ^ (c & (d ^ e))) +
      constants[idx + 2] +
      words[idx + 2]
    )
    b = (b + t1) & _U32_MASK
    f = (t1 + ((rot_a >> 2n) ^ (rot_a >> 13n) ^ (rot_a >> 22n)) + ((g & h) | (a & (g | h)))) & _U32_MASK

    rot_e = b * 0x100000001n
    rot_a = f * 0x100000001n
    t1 = (
      e +
      ((rot_e >> 6n) ^ (rot_e >> 11n) ^ (rot_e >> 25n)) +
      (d ^ (b & (c ^ d))) +
      constants[idx + 3] +
      words[idx + 3]
    )
    a = (a + t1) & _U32_MASK
    e = (t1 + ((rot_a >> 2n) ^ (rot_a >> 13n) ^ (rot_a >> 22n)) + ((f & g) | (h & (f | g)))) & _U32_MASK

    rot_e = a * 0x100000001n
    rot_a = e * 0x100000001n
    t1 = (
      d +
      ((rot_e >> 6n) ^ (rot_e >> 11n) ^ (rot_e >> 25n)) +
      (c ^ (a & (b ^ c))) +
      constants[idx + 4] +
      words[idx + 4]
    )
    h = (h + t1) & _U32_MASK
    d = (t1 + ((rot_a >> 2n) ^ (rot_a >> 13n) ^ (rot_a >> 22n)) + ((e & f) | (g & (e | f)))) & _U32_MASK

    rot_e = h * 0x100000001n
    rot_a = d * 0x100000001n
    t1 = (
      c +
      ((rot_e >> 6n) ^ (rot_e >> 11n) ^ (rot_e >> 25n)) +
      (b ^ (h & (a ^ b))) +
      constants[idx + 5] +
      words[idx + 5]
    )
    g = (g + t1) & _U32_MASK
    c = (t1 + ((rot_a >> 2n) ^ (rot_a >> 13n) ^ (rot_a >> 22n)) + ((d & e) | (f & (d | e)))) & _U32_MASK

    rot_e = g * 0x100000001n
    rot_a = c * 0x100000001n
    t1 = (
      b +
      ((rot_e >> 6n) ^ (rot_e >> 11n) ^ (rot_e >> 25n)) +
      (a ^ (g & (h ^ a))) +
      constants[idx + 6] +
      words[idx + 6]
    )
    f = (f + t1) & _U32_MASK
    b = (t1 + ((rot_a >> 2n) ^ (rot_a >> 13n) ^ (rot_a >> 22n)) + ((c & d) | (e & (c | d)))) & _U32_MASK

    rot_e = f * 0x100000001n
    rot_a = b * 0x100000001n
    t1 = (
      a +
      ((rot_e >> 6n) ^ (rot_e >> 11n) ^ (rot_e >> 25n)) +
      (h ^ (f & (g ^ h))) +
      constants[idx + 7] +
      words[idx + 7]
    )
    e = (e + t1) & _U32_MASK
    a = (t1 + ((rot_a >> 2n) ^ (rot_a >> 13n) ^ (rot_a >> 22n)) + ((b & c) | (d & (b | c)))) & _U32_MASK
  }
  return [a, b, c, d, e, f, g, h]
}

function _sha256_init(data: Uint8Array) {
  const words = new Array(14).fill(0n)
  const w14 = (BigInt(data[0]) << 16n) | (BigInt(data[1]) << 8n) | BigInt(data[2])
  const w15 = (BigInt(data[3]) << 24n) | (BigInt(data[4]) << 16n) | (BigInt(data[5]) << 8n) | BigInt(data[6])
  words.push(w14, w15)

  for (let idx = 16; idx < 30; idx++) {
    let val = _SHA256_SCHEDULE[idx - 16]
    if (idx - 2 >= 14) {
      val += (idx === 16 ? (_sigma1(words[idx - 2]) ^ _SHA256_SIGMA1_ADJUSTMENT) : _sigma1(words[idx - 2]))
    }
    if (idx - 7 >= 14) {
      val += words[idx - 7]
    }
    if (idx - 15 >= 14) {
      val += (idx === 29 ? (_sigma0(words[idx - 15]) ^ _SHA256_SIGMA0_ADJUSTMENT) : _sigma0(words[idx - 15]))
    }
    words.push(val & _U32_MASK)
  }

  const w30 = (
    _sigma1(words[28]) +
    words[23] +
    _sigma0(words[15]) +
    words[14] +
    _SHA256_ADJUSTMENT -
    _SHA256_ROUND_CONSTANTS[14]
  ) & _U32_MASK
  words.push(w30)

  _expand_sha256_schedule(words, 31)
  const working = _sha256_rounds(_SHA256_STATE, words, 14)
  return _SHA256_INITIAL.map((x, i) => (x + working[i]) & _U32_MASK)
}

function _sha256_digest(data: Uint8Array) {
  if (data.length < 7) {
    throw new Error('Token salt must contain at least seven bytes')
  }
  const length = 57 + data.length
  const padZerosLen = ((55 - length) % 64 + 64) % 64
  const totalLen = (data.length - 7) + 1 + padZerosLen + 8
  const padded = new Uint8Array(totalLen)
  padded.set(data.subarray(7), 0)
  padded[data.length - 7] = 0x80
  const view = new DataView(padded.buffer, padded.byteOffset, padded.byteLength)
  const bitLen = BigInt(length) * 8n
  view.setBigUint64(totalLen - 8, bitLen, false)

  let state = _sha256_init(data.subarray(0, 7))

  for (let offset = 0; offset < padded.length; offset += 64) {
    const words: bigint[] = []
    for (let i = 0; i < 64; i += 4) {
      words.push(BigInt(view.getUint32(offset + i, false)))
    }
    _expand_sha256_schedule(words, 16)
    const working = _sha256_rounds(state, words, 0)
    state = state.map((x, i) => (x + working[i]) & _U32_MASK)
  }

  const outBytes = new Uint8Array(32)
  const outView = new DataView(outBytes.buffer)
  for (let i = 0; i < 8; i++) {
    outView.setUint32(i * 4, Number(state[i]), false)
  }
  return outBytes
}

function _cs64_digest(data: Uint8Array, digest: Uint8Array) {
  const digestView = new DataView(digest.buffer, digest.byteOffset, digest.byteLength)
  let key_a = BigInt(digestView.getUint32(0, true)) | 1n
  let key_b = BigInt(digestView.getUint32(4, true)) | 1n

  const factors = [
    (key_a * _CS64_FACTOR) & _U32_MASK,
    (key_b * _CS64_FACTOR) & _U32_MASK,
  ]

  const terms = _CS64_COEFFICIENTS.map(([coeff], idx) => (coeff * factors[idx % 2]) & _U32_MASK)
  const offsets = _CS64_COEFFICIENTS.map(([, offset]) => offset)

  const prefixZeroData = new Uint8Array(1 + data.length)
  prefixZeroData[0] = 0
  prefixZeroData.set(data, 1)
  const words = _words_le4_even(prefixZeroData)

  for (let idx = 0; idx < words.length; idx++) {
    const word = words[idx]
    let term = word * (idx % 2 === 0 ? key_a : key_b)
    let offset = _rol16(word) * (idx % 2 === 0 ? 0xEF0569FBn : 0xC31713DBn)
    if (idx === 0) {
      term += _CS64_ADJUSTMENT0 * factors[0]
      offset += _CS64_ADJUSTMENT1
    }
    terms.push(term & _U32_MASK)
    offsets.push(offset & _U32_MASK)
  }

  let swap_acc = 0n
  let swap_last = 0n
  let state = 0n
  let acc = 0n

  for (let idx = 0; idx < terms.length; idx += 2) {
    const x = terms[idx]
    const y = terms[idx + 1]

    let t = _rol16((offsets[idx] + x) & _U32_MASK)
    let q = (t * 0x76F50F34n) & _U32_MASK
    swap_acc = (swap_acc + ((_rol16(q) * 0xC3EFEA97n + q) & _U32_MASK)) & _U32_MASK

    t = _rol16((offsets[idx + 1] + y) & _U32_MASK)
    q = (t * 0x1881CE3Cn) & _U32_MASK
    swap_last = (_rol16(q) * 0x35BD1EC9n + q) & _U32_MASK
    swap_acc = (swap_acc + swap_last) & _U32_MASK

    state = (state * key_a + x) & _U32_MASK
    state = (_rol16(state) * 0xCF98B111n) & _U32_MASK
    state = (_rol16(state) * 0x87085B9Fn) & _U32_MASK
    state = (_rol16(state) * 0x12CEB96Dn) & _U32_MASK
    state = (_rol16(state) * 0x257E1D83n) & _U32_MASK
    acc = (acc + state) & _U32_MASK

    t = (state * key_b + y) & _U32_MASK
    t = (_rol16(t) * 0xA27416F5n) & _U32_MASK
    t = (_rol16(t) * 0xD38396FFn) & _U32_MASK
    state = (_rol16((_rol16(t) * 0x7C932B89n) & _U32_MASK) * 0xBFA49F69n) & _U32_MASK
    acc = (acc + state) & _U32_MASK
  }

  return [(swap_last ^ state) & _U32_MASK, (swap_acc ^ acc) & _U32_MASK]
}

function _token_hash(data: Uint8Array): [string, string] {
  const digest = _sha256_digest(data)
  const [cs_low, cs_high] = _cs64_digest(data, digest)
  const csBytes = new Uint8Array(8)
  const csView = new DataView(csBytes.buffer)
  csView.setUint32(0, Number(cs_low), true)
  csView.setUint32(4, Number(cs_high), true)
  const cs64Hex = Array.from(csBytes).map(b => b.toString(16).padStart(2, '0')).join('').toUpperCase()
  const shaHex = Array.from(digest).map(b => b.toString(16).padStart(2, '0')).join('').toUpperCase()
  return [cs64Hex, shaHex]
}

function generateSecMsGecV2(unixTimestamp?: number): string {
  let ticks = unixTimestamp !== undefined ? BigInt(Math.floor(unixTimestamp)) : BigInt(Math.floor(Date.now() / 1000))
  ticks += WIN_EPOCH
  ticks -= ticks % 300n
  ticks *= S_TO_NS / 100n
  const payloadStr = `${ticks}${TRUSTED_CLIENT_TOKEN}`
  const data = new TextEncoder().encode(payloadStr)
  const [cs64, sha256] = _token_hash(data)
  return `${cs64}-${sha256}`
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
  if (!text || !text.trim()) {
    return Promise.resolve({
      audioBase64: '',
      durationSec: 0,
      timestamps: [],
    })
  }

  return new Promise((resolve, reject) => {
    const connectionId = crypto.randomUUID().replace(/-/g, '')
    const requestId = crypto.randomUUID().replace(/-/g, '')
    const token = '6A5AA1D4EAFF4E9FB37E23D68491D6F4'
    const gec = generateSecMsGecV2()
    const secKey = crypto.randomBytes(16).toString('base64')
    const muid = crypto.randomBytes(16).toString('hex').toUpperCase()

    const path =
      `/consumer/speech/synthesize/readaloud/edge/v1?TrustedClientToken=${token}` +
      `&ConnectionId=${connectionId}` +
      `&Sec-MS-GEC=${gec}` +
      `&Sec-MS-GEC-Version=${SEC_MS_GEC_VERSION}`

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
    // 跨域预检处理
    if (req.method === 'OPTIONS') {
      res.statusCode = 204
      res.setHeader('Access-Control-Allow-Origin', '*')
      res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
      res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization')
      res.end()
      return
    }

    if ((req.url === '/api/edge-tts' || req.url === '/' || req.url === '') && req.method === 'POST') {
      res.setHeader('Access-Control-Allow-Origin', '*')
      res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
      res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization')

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
