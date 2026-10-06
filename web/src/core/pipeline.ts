import type { Document, PipelineProgress, Settings } from './types'
import { LlmClient } from './llm'
import { extractDocAbbreviations } from './abbrev'
import { matchGlossaryTerms, renderPromptBlock, applyHardReplace } from './glossary'
import { cleanForTts } from './polyphone'
import { TRANSLATE_SYSTEM, SCRIPT_SYSTEM } from './prompts'
import { synthesizeEdgeTts } from './edgeTts'
import { generateReaderHtml } from './readerBuilder'
import { savePaperToLibrary } from '../store/library'

export type ProgressCallback = (progress: PipelineProgress) => void

export async function runDocumentPipeline(
  doc: Document,
  settings: Settings,
  onProgress: ProgressCallback
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

    // 构建 LLM 客户端
    const llm = new LlmClient(settings)
    const translations: Record<string, string> = {}
    const scripts: Record<string, string> = {}

    const totalSegs = doc.segments.length

    // 3. 忠实翻译 (Track A)
    emit('translate', 0, totalSegs, '开始执行高精度学术双语忠实翻译...')
    for (let i = 0; i < totalSegs; i++) {
      const seg = doc.segments[i]
      const terms = matchGlossaryTerms(seg.src_text)
      const hints = renderPromptBlock(terms)

      const systemPrompt = TRANSLATE_SYSTEM + (hints ? `\n\n【本段专业术语规范】\n${hints}` : '')
      const userPrompt = `【待译段落 (章节: ${seg.sec_heading})】:\n${seg.src_text}`

      emit('translate', i + 1, totalSegs, `翻译进度 (${i + 1}/${totalSegs}): ${seg.sec_heading}`)

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
        emit('translate', i + 1, totalSegs, `段落 ${seg.sid} 翻译遇阻: ${err.message}`)
        translations[seg.sid] = `[翻译失败: ${err.message}]`
      }
    }

    // 4. 口语化伴读讲稿生成 (Track B: script-v3)
    emit('script', 0, totalSegs, '开始生成自然听感口语伴读讲稿 (自然连词、听觉数字重塑)...')
    for (let i = 0; i < totalSegs; i++) {
      const seg = doc.segments[i]
      const zh = translations[seg.sid] || ''

      const userPrompt = `【章节】${seg.sec_heading}\n【段落序号】${i + 1}/${totalSegs}\n【中文初译】\n${zh}\n\n【英文原文参考】\n${seg.src_text}`

      emit('script', i + 1, totalSegs, `改写讲稿 (${i + 1}/${totalSegs}): ${seg.sec_heading}`)

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
        emit('script', i + 1, totalSegs, `段落 ${seg.sid} 讲稿改写遇阻: ${err.message}`)
        scripts[seg.sid] = zh // fallback
      }
    }

    // 5. 语音合成 (TTS)
    const timeline: any[] = []
    const audioBlobs: Blob[] = []
    let combinedAudioBase64 = ''

    if (settings.enableTts && settings.ttsProvider === 'edge-tts') {
      emit('audio', 0, totalSegs, '正在调用 Edge-TTS 生成沉浸式全篇朗读与时间戳...')
      let cumulativeTimeSec = 0

      for (let i = 0; i < totalSegs; i++) {
        const seg = doc.segments[i]
        const scriptText = scripts[seg.sid] || translations[seg.sid] || ''

        emit('audio', i + 1, totalSegs, `合成语音 (${i + 1}/${totalSegs}): ${seg.sec_heading}`)

        try {
          const ttsRes = await synthesizeEdgeTts(
            scriptText,
            settings.ttsVoice,
            settings.ttsRate
          )

          const segDuration = ttsRes.durationSec > 0 ? ttsRes.durationSec : Math.max(3, scriptText.length * 0.25)
          const startSec = cumulativeTimeSec
          const endSec = startSec + segDuration
          cumulativeTimeSec = endSec

          // 组织句级时间戳
          const sentences = ttsRes.timestamps.map((t) => ({
            text: t.text,
            start_sec: startSec + t.offsetSec,
            end_sec: startSec + t.offsetSec + t.durationSec,
          }))

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

          if (ttsRes.audioBlob && ttsRes.audioBlob.size > 0) {
            audioBlobs.push(ttsRes.audioBlob)
          }
        } catch (err: any) {
          emit('audio', i + 1, totalSegs, `段落 ${seg.sid} TTS 合成受限: ${err.message}，启用浏览器朗读后备`)
          const estDuration = Math.max(3, scriptText.length * 0.25)
          const startSec = cumulativeTimeSec
          const endSec = startSec + estDuration
          cumulativeTimeSec = endSec
          timeline.push({
            sid: seg.sid,
            sec_path: seg.sec_path,
            sec_heading: seg.sec_heading,
            start_sec: startSec,
            end_sec: endSec,
            duration_sec: estDuration,
            script: scriptText,
            sentences: [],
          })
        }
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

    emit('done', 1, 1, '🎉 伴读网页已成功生成并保存至本地书架！')
    return html
  } catch (err: any) {
    emit('error', 0, 0, `流水线执行异常: ${err.message}`)
    throw err
  }
}
