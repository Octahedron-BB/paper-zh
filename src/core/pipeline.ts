import type { Document, PipelineProgress, Settings } from './types'
import { LlmClient } from './llm'
import { extractDocAbbreviations } from './abbrev'
import { matchGlossaryTerms, renderPromptBlock, applyHardReplace } from './glossary'
import { cleanForTts } from './polyphone'
import { TRANSLATE_SYSTEM, SCRIPT_SYSTEM } from './prompts'
import { synthesizeEdgeTts } from './edgeTts'
import { synthesizeSiliconFlowTts } from './siliconflowTts'
import { generateReaderHtml } from './readerBuilder'
import {
  savePaperToLibrary,
  savePipelineCheckpoint,
  getPipelineCheckpoint,
  clearPipelineCheckpoint,
  type PipelineCheckpoint,
} from '../store/library'

export type ProgressCallback = (progress: PipelineProgress) => void

async function runConcurrent<T>(
  items: T[],
  limit: number,
  task: (item: T, index: number) => Promise<void>
): Promise<void> {
  let nextIdx = 0
  const workers = Array.from({ length: Math.min(limit, items.length) }, async () => {
    while (nextIdx < items.length) {
      const idx = nextIdx++
      await task(items[idx], idx)
    }
  })
  await Promise.all(workers)
}

async function getAudioBlobDuration(blob: Blob): Promise<number> {
  // 1. Web Audio API 物理音频解码 (微秒级精确计算)
  try {
    const arrayBuffer = await blob.arrayBuffer()
    const AudioContextClass = window.AudioContext || (window as any).webkitAudioContext
    if (AudioContextClass) {
      const ctx = new AudioContextClass()
      const audioBuffer = await ctx.decodeAudioData(arrayBuffer.slice(0))
      const dur = audioBuffer.duration
      ctx.close()
      if (dur > 0 && isFinite(dur)) return dur
    }
  } catch {
    // 降级使用 HTMLAudioElement metadata
  }

  // 2. HTMLAudioElement 回退
  return new Promise((resolve) => {
    try {
      const url = URL.createObjectURL(blob)
      const audio = new Audio(url)
      audio.onloadedmetadata = () => {
        const d = audio.duration
        URL.revokeObjectURL(url)
        resolve(isFinite(d) && d > 0 ? d : 0)
      }
      audio.onerror = () => {
        URL.revokeObjectURL(url)
        resolve(0)
      }
    } catch {
      resolve(0)
    }
  })
}

function splitTextIntoSentences(text: string): string[] {
  if (!text) return []
  const matches = text.match(/[^。！？；\n]+[。！？；\n]*/g)
  return matches && matches.length > 0 ? matches.map((s) => s.trim()).filter(Boolean) : [text.trim()]
}

function alignSentencesWithTimestamps(
  sentences: string[],
  wordTimestamps: { text: string; offsetSec: number; durationSec: number }[],
  segStartSec: number,
  segDurationSec: number
): { text: string; start_sec: number; end_sec: number }[] {
  if (sentences.length === 0) return []

  const fullText = sentences.join('')
  const totalChars = fullText.length || 1

  // 若无字词时间戳，按句子字数比例平滑均分该段物理时长
  if (!wordTimestamps || wordTimestamps.length === 0) {
    let cur = segStartSec
    return sentences.map((st, idx) => {
      const frac = st.length / totalChars
      const dur = idx === sentences.length - 1 ? (segStartSec + segDurationSec - cur) : (segDurationSec * frac)
      const sStart = cur
      const sEnd = cur + dur
      cur = sEnd
      return { text: st, start_sec: sStart, end_sec: sEnd }
    })
  }

  // 1. 建立各完整自然句在全文中的字符起止区间
  let charCursor = 0
  const sentenceRanges = sentences.map((st) => {
    const startChar = charCursor
    const endChar = charCursor + st.length
    charCursor = endChar
    return { text: st, startChar, endChar }
  })

  // 2. 将 WordBoundary 词/字时间戳顺序对齐到全文字符位置
  let searchPos = 0
  const mappedWords: { startChar: number; endChar: number; offsetSec: number; endSec: number }[] = []
  for (const wt of wordTimestamps) {
    if (!wt.text) continue
    const idx = fullText.indexOf(wt.text, searchPos)
    if (idx !== -1) {
      mappedWords.push({
        startChar: idx,
        endChar: idx + wt.text.length,
        offsetSec: wt.offsetSec,
        endSec: wt.offsetSec + wt.durationSec,
      })
      searchPos = idx + wt.text.length
    }
  }

  // 3. 聚合各句对应的起始与结束时间戳（以完整句为粒度）
  const result: { text: string; start_sec: number; end_sec: number }[] = []

  for (let i = 0; i < sentenceRanges.length; i++) {
    const sr = sentenceRanges[i]
    const matched = mappedWords.filter(
      (w) => (w.startChar >= sr.startChar && w.startChar < sr.endChar) ||
             (w.endChar > sr.startChar && w.endChar <= sr.endChar)
    )

    let relStart = 0
    let relEnd = 0

    if (matched.length > 0) {
      relStart = matched[0].offsetSec
      relEnd = matched[matched.length - 1].endSec
    } else {
      if (i === 0) {
        relStart = 0
      } else {
        relStart = result[i - 1].end_sec - segStartSec
      }
      relEnd = relStart + (sr.text.length / totalChars) * segDurationSec
    }

    result.push({
      text: sr.text,
      start_sec: segStartSec + relStart,
      end_sec: segStartSec + relEnd,
    })
  }

  // 4. 单调平滑校正：消除因朗读微顿或标点停顿造成的时间跳跃或倒退
  for (let i = 0; i < result.length - 1; i++) {
    if (result[i].end_sec < result[i + 1].start_sec) {
      result[i].end_sec = result[i + 1].start_sec
    }
    if (result[i].end_sec > result[i + 1].start_sec) {
      result[i + 1].start_sec = result[i].end_sec
    }
  }

  if (result.length > 0) {
    result[0].start_sec = Math.min(result[0].start_sec, segStartSec)
    result[result.length - 1].end_sec = Math.max(
      result[result.length - 1].end_sec,
      segStartSec + segDurationSec
    )
  }

  return result
}

export interface PipelineOptions {
  resume?: boolean
}

export async function runDocumentPipeline(
  doc: Document,
  settings: Settings,
  onProgress: ProgressCallback,
  options: PipelineOptions = { resume: true }
): Promise<string> {
  const logs: string[] = []
  function emit(stage: PipelineProgress['stage'], current: number, total: number, message: string) {
    const percent = total > 0 ? Math.round((current / total) * 100) : 0
    logs.push(`[${new Date().toLocaleTimeString()}] ${message}`)
    onProgress({
      stage,
      current,
      total,
      percent,
      message,
      logs: [...logs],
    })
  }

  try {
    emit('segment', 1, 1, `文档结构解析完成: 共 ${doc.sections.length} 个章节，${doc.segments.length} 个段落`)

    // 2. 术语与缩写提取
    emit('terms', 0, 1, '正在进行全文缩写与专业术语模式扫描...')
    const abbrevs = extractDocAbbreviations(doc)
    emit('terms', 1, 1, `缩写扫描完成: 捕获到 ${abbrevs.length} 个首字母缩写定义`)

    // 读取已存在的断点数据（若支持断点续跑）
    let ckpt: PipelineCheckpoint | undefined
    if (options.resume !== false) {
      ckpt = await getPipelineCheckpoint(doc.doc_id)
    }

    const translations: Record<string, string> = { ...(ckpt?.translations || {}) }
    const scripts: Record<string, string> = { ...(ckpt?.scripts || {}) }

    interface SegTtsResult {
      audioBlob?: Blob
      durationSec: number
      timestamps: any[]
      scriptText: string
    }
    const ttsResultsMap: Record<string, SegTtsResult> = { ...(ckpt?.ttsResults || {}) }

    const totalSegs = doc.segments.length

    const isValidZh = (zh?: string) => !!(zh && zh.trim() && !zh.startsWith('[翻译失败:'))
    const isValidScript = (s?: string) => !!(s && s.trim() && !s.startsWith('[翻译失败:') && !s.startsWith('[改写失败:'))
    const isValidAudio = (r?: SegTtsResult) => !!(r && r.audioBlob && r.audioBlob.size > 0 && r.durationSec >= 0)

    // 构建 LLM 客户端
    const llm = new LlmClient(settings)

    // 3. 忠实翻译 (Track A) - 4 线程并发加速
    const segsNeedingTrans = doc.segments.filter((s) => !isValidZh(translations[s.sid]))
    const initialTransDone = totalSegs - segsNeedingTrans.length

    if (segsNeedingTrans.length === 0) {
      emit('translate', totalSegs, totalSegs, `已从断点恢复全部 ${totalSegs} 段中文忠实译文 (跳过 LLM 翻译)`)
    } else {
      if (initialTransDone > 0) {
        emit('translate', initialTransDone, totalSegs, `从断点恢复 ${initialTransDone}/${totalSegs} 段译文，继续翻译剩余 ${segsNeedingTrans.length} 段...`)
      } else {
        emit('translate', 0, totalSegs, '开始执行高精度学术双语忠实翻译 (4 线程并发加速)...')
      }

      let completedTrans = initialTransDone
      await runConcurrent(segsNeedingTrans, 4, async (seg) => {
        const terms = matchGlossaryTerms(seg.src_text)
        const hints = renderPromptBlock(terms)

        const systemPrompt = TRANSLATE_SYSTEM + (hints ? `\n\n【本段专业术语规范】\n${hints}` : '')
        const userPrompt = `【待译段落 (章节: ${seg.sec_heading})】:\n${seg.src_text}`

        try {
          const rawZh = await llm.chat(
            [
              { role: 'system', content: systemPrompt },
              { role: 'user', content: userPrompt },
            ],
            0.3
          )

          // 应用硬替换规则
          const finalZh = applyHardReplace(terms, rawZh)
          translations[seg.sid] = finalZh
        } catch (err: any) {
          emit('translate', completedTrans, totalSegs, `段落 ${seg.sid} 翻译遇阻: ${err.message}`)
          translations[seg.sid] = `[翻译失败: ${err.message}]`
        } finally {
          completedTrans++
          emit('translate', completedTrans, totalSegs, `翻译完成 (${completedTrans}/${totalSegs}): ${seg.sec_heading}`)
        }
      })

      // 持久化翻译断点
      await savePipelineCheckpoint({
        doc_id: doc.doc_id,
        updatedAt: new Date().toISOString(),
        translations,
        scripts,
        ttsResults: ttsResultsMap,
      })
    }

    // 4. 口语化伴读讲稿生成 (Track B: script-v3) - 4 线程并发加速
    const segsNeedingScript = doc.segments.filter((s) => !isValidScript(scripts[s.sid]))
    const initialScriptDone = totalSegs - segsNeedingScript.length

    if (segsNeedingScript.length === 0) {
      emit('script', totalSegs, totalSegs, `已从断点恢复全部 ${totalSegs} 段口语伴读讲稿 (跳过 LLM 改写)`)
    } else {
      if (initialScriptDone > 0) {
        emit('script', initialScriptDone, totalSegs, `从断点恢复 ${initialScriptDone}/${totalSegs} 段讲稿，继续改写剩余 ${segsNeedingScript.length} 段...`)
      } else {
        emit('script', 0, totalSegs, '开始生成自然听感口语伴读讲稿 (4 线程并发加速)...')
      }

      let completedScript = initialScriptDone
      await runConcurrent(segsNeedingScript, 4, async (seg) => {
        const segIdx = doc.segments.findIndex((s) => s.sid === seg.sid)
        const zh = translations[seg.sid] || ''

        const userPrompt = `【章节】${seg.sec_heading}\n【段落序号】${segIdx + 1}/${totalSegs}\n【中文初译】\n${zh}\n\n【英文原文参考】\n${seg.src_text}`

        try {
          const rawScript = await llm.chat(
            [
              { role: 'system', content: SCRIPT_SYSTEM },
              { role: 'user', content: userPrompt },
            ],
            0.4
          )

          // 应用多音字发音清洗
          const cleanScript = cleanForTts(rawScript)
          scripts[seg.sid] = cleanScript
        } catch (err: any) {
          emit('script', completedScript, totalSegs, `段落 ${seg.sid} 讲稿改写遇阻: ${err.message}`)
          scripts[seg.sid] = zh // fallback
        } finally {
          completedScript++
          emit('script', completedScript, totalSegs, `改写完成 (${completedScript}/${totalSegs}): ${seg.sec_heading}`)
        }
      })

      // 持久化讲稿断点
      await savePipelineCheckpoint({
        doc_id: doc.doc_id,
        updatedAt: new Date().toISOString(),
        translations,
        scripts,
        ttsResults: ttsResultsMap,
      })
    }

    // 5. 语音合成 (TTS) - 2 线程稳健并发加速与容错对齐
    const timeline: any[] = []
    const audioBlobs: Blob[] = []
    let combinedAudioBase64 = ''

    if (settings.enableTts && (settings.ttsProvider === 'edge-tts' || settings.ttsProvider === 'siliconflow')) {
      const segsNeedingAudio = doc.segments.filter((s) => {
        const scriptText = (scripts[s.sid] || translations[s.sid] || '').trim()
        if (!scriptText) return false
        return !isValidAudio(ttsResultsMap[s.sid])
      })
      const initialAudioDone = totalSegs - segsNeedingAudio.length

      if (initialAudioDone > 0) {
        emit('audio', initialAudioDone, totalSegs, `从断点恢复 ${initialAudioDone}/${totalSegs} 段音频，继续合成剩余 ${segsNeedingAudio.length} 段 (2 线程稳健并发)...`)
      } else {
        emit('audio', 0, totalSegs, '正在调用语音合成生成沉浸式全篇朗读与时间戳 (2 线程稳健并发)...')
      }

      let completedAudio = initialAudioDone
      let checkpointSaveCounter = 0

      // 采用 2 线程稳健并发，有效避免并发激增被微软/反代服务流控限制
      await runConcurrent(segsNeedingAudio, 2, async (seg) => {
        const scriptText = scripts[seg.sid] || translations[seg.sid] || ''
        if (!scriptText.trim()) {
          ttsResultsMap[seg.sid] = { durationSec: 0, timestamps: [], scriptText: '' }
          completedAudio++
          emit('audio', completedAudio, totalSegs, `跳过空白段 (${completedAudio}/${totalSegs})`)
          return
        }

        let res: any = null
        for (let attempt = 1; attempt <= 3; attempt++) {
          try {
            if (settings.ttsProvider === 'siliconflow') {
              res = await synthesizeSiliconFlowTts(
                scriptText,
                settings.siliconflowApiKey || settings.customTtsApiKey || '',
                settings.ttsVoice,
                settings.siliconflowModel,
                settings.ttsRate
              )
            } else {
              res = await synthesizeEdgeTts(
                scriptText,
                settings.ttsVoice,
                settings.ttsRate,
                settings.edgeTtsProxyUrl
              )
            }
            if (res && res.audioBlob && res.audioBlob.size > 0) break
          } catch (e: any) {
            if (attempt === 3) {
              emit('audio', completedAudio, totalSegs, `段落 ${seg.sid} 重试 3 次后受限: ${e?.message || e}`)
            }
            await new Promise((r) => setTimeout(r, 600 * attempt))
          }
        }

        let trueAudioDur = 0
        if (res?.audioBlob && res.audioBlob.size > 0) {
          trueAudioDur = await getAudioBlobDuration(res.audioBlob)
          ttsResultsMap[seg.sid] = {
            audioBlob: res.audioBlob,
            durationSec: trueAudioDur > 0 ? trueAudioDur : (res.durationSec || 0),
            timestamps: res.timestamps || [],
            scriptText,
          }
        }

        completedAudio++
        emit('audio', completedAudio, totalSegs, `语音合成 (${completedAudio}/${totalSegs}): ${seg.sec_heading}`)

        checkpointSaveCounter++
        if (checkpointSaveCounter % 3 === 0 || completedAudio === totalSegs) {
          savePipelineCheckpoint({
            doc_id: doc.doc_id,
            updatedAt: new Date().toISOString(),
            translations,
            scripts,
            ttsResults: ttsResultsMap,
          }).catch(() => {})
        }
      })

      // 持久化当前所有音频断点
      await savePipelineCheckpoint({
        doc_id: doc.doc_id,
        updatedAt: new Date().toISOString(),
        translations,
        scripts,
        ttsResults: ttsResultsMap,
      })

      // 严格按段落顺序拼装音频流与时间戳（绝对杜绝段落缺失引起的级联错位）
      let cumulativeTimeSec = 0
      let failedAudioCount = 0

      for (let i = 0; i < totalSegs; i++) {
        const seg = doc.segments[i]
        const r = ttsResultsMap[seg.sid]
        const scriptText = r?.scriptText || scripts[seg.sid] || translations[seg.sid] || ''
        const hasValidAudio = !!(r?.audioBlob && r.audioBlob.size > 0)

        if (hasValidAudio && r && r.audioBlob) {
          audioBlobs.push(r.audioBlob)
          const segDuration = r.durationSec
          const startSec = cumulativeTimeSec
          const endSec = startSec + segDuration
          cumulativeTimeSec = endSec

          const rawSentences = splitTextIntoSentences(scriptText)
          const sentences = alignSentencesWithTimestamps(
            rawSentences,
            r.timestamps,
            startSec,
            segDuration
          )

          timeline.push({
            sid: seg.sid,
            sec_path: seg.sec_path,
            sec_heading: seg.sec_heading,
            start_sec: startSec,
            end_sec: endSec,
            duration_sec: segDuration,
            script: scriptText,
            sentences,
          })
        } else {
          if (scriptText.trim()) {
            failedAudioCount++
          }
          // 该段语音合成失败或为空：
          // 严禁在音频时间轴上虚借时长！没有物理音频就占用 0 秒，避免后续段落与音频整体偏移错位！
          const rawSentences = splitTextIntoSentences(scriptText)
          timeline.push({
            sid: seg.sid,
            sec_path: seg.sec_path,
            sec_heading: seg.sec_heading,
            start_sec: cumulativeTimeSec,
            end_sec: cumulativeTimeSec,
            duration_sec: 0,
            script: scriptText,
            sentences: rawSentences.map((st) => ({ text: st, start_sec: cumulativeTimeSec, end_sec: cumulativeTimeSec })),
          })
        }
      }

      if (failedAudioCount > 0) {
        emit('audio', totalSegs - failedAudioCount, totalSegs, `⚠️ 提示：有 ${failedAudioCount} 个段落音频合成遇阻，已保留断点数据。您可点击【断点重试补齐】仅对该 ${failedAudioCount} 段重新合成。`)
      }

      // 将所有分段 MP3 合并成单一连续音频
      if (audioBlobs.length > 0) {
        emit('audio', totalSegs, totalSegs, '正在拼接全篇音频数据流...')
        const mergedBlob = new Blob(audioBlobs, { type: 'audio/mp3' })
        combinedAudioBase64 = await new Promise<string>((resolve) => {
          const reader = new FileReader()
          reader.onloadend = () => {
            const res = reader.result as string
            resolve(res.split(',')[1] || '')
          }
          reader.readAsDataURL(mergedBlob)
        })
      }
    } else if (settings.ttsProvider === 'web-speech') {
      emit('audio', totalSegs, totalSegs, '启用浏览器原生 Web Speech API 朗读引擎')
    } else {
      emit('audio', totalSegs, totalSegs, '已跳过音频文件内嵌，启用浏览器原生朗读/纯文稿模式')
    }

    // 6. 打包单文件 HTML
    emit('pack', 1, 1, '正在打包自包含独立双向伴读 Web Reader...')
    const html = generateReaderHtml(
      doc,
      translations,
      scripts,
      timeline,
      combinedAudioBase64,
      settings.ttsVoice
    )

    // 7. 保存到本地书架 (IndexedDB)
    await savePaperToLibrary({
      doc_id: doc.doc_id,
      title: doc.title,
      createdAt: new Date().toISOString(),
      html,
      durationSec: timeline.length > 0 ? timeline[timeline.length - 1].end_sec : 0,
      segCount: totalSegs,
      hasAudio: !!combinedAudioBase64,
    })

    // 检查所有需要音频的段落是否都已成功合成
    const isAllAudioDone =
      !settings.enableTts ||
      (settings.ttsProvider !== 'edge-tts' && settings.ttsProvider !== 'siliconflow') ||
      doc.segments.every((s) => {
        const text = (scripts[s.sid] || translations[s.sid] || '').trim()
        if (!text) return true
        return isValidAudio(ttsResultsMap[s.sid])
      })

    if (isAllAudioDone) {
      await clearPipelineCheckpoint(doc.doc_id)
      emit('done', 1, 1, '🎉 伴读网页已成功生成并保存至本地书架！')
    } else {
      emit('done', 1, 1, '🎉 伴读网页已生成并保存！(部分失败段落已保留断点，可随时再次点击【断点重试补齐】)')
    }

    return html
  } catch (err: any) {
    emit('error', 0, 0, `流水线执行异常: ${err.message}`)
    throw err
  }
}
