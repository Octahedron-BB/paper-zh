import type { Document } from './types'

function formatDuration(seconds: number): string {
  const mins = Math.floor(seconds / 60)
  const secs = Math.floor(seconds % 60)
  return `${mins} 分 ${secs} 秒`
}

function formatDurationStr(seconds: number): string {
  const mins = Math.floor(seconds / 60)
  const secs = Math.floor(seconds % 60)
  return `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`
}

function splitSentences(text: string): string[] {
  if (!text) return []
  const matches = text.match(/[^。！？；\n]+[。！？；\n]*/g)
  return matches && matches.length > 0 ? matches : [text]
}

export function generateReaderHtml(
  doc: Document,
  translations: Record<string, string>,
  scripts: Record<string, string>,
  timeline: any[] = [],
  audioBase64 = '',
  voice = 'zh-TW-HsiaoChenNeural'
): string {
  const hasAudio = !!audioBase64
  const audioSrc = hasAudio ? `data:audio/mp3;base64,{AUDIO_DATA}` : ''
  const totalSec = timeline.length > 0 ? (timeline[timeline.length - 1].end_sec || 0) : doc.segments.length * 6

  // 组织主体 HTML
  const contentBlocks: string[] = []
  const tocBlocks: string[] = []
  const seenSections = new Set<string>()

  // 建立 source text map
  const sourceMap: Record<string, string> = {}
  for (const sec of doc.sections) {
    for (const seg of sec.segments) {
      sourceMap[seg.sid] = seg.src_text
    }
  }

  // 构建完整 timeline
  const effectiveTimeline = timeline.length > 0 ? timeline : doc.segments.map((seg, idx) => ({
    sid: seg.sid,
    sec_path: seg.sec_path,
    sec_heading: seg.sec_heading,
    start_sec: idx * 6,
    end_sec: (idx + 1) * 6,
    duration_sec: 6,
    script: scripts[seg.sid] || translations[seg.sid] || seg.src_text,
    sentences: []
  }))

  for (let i = 0; i < effectiveTimeline.length; i++) {
    const item = effectiveTimeline[i]
    const sid = item.sid
    const secPath = item.sec_path || 'sec-0'
    const secHeading = item.sec_heading || '正文'
    const startSec = item.start_sec || (i * 6)

    if (!seenSections.has(secPath)) {
      seenSections.add(secPath)
      contentBlocks.push(`<h2 class="section-title" id="sec-${secPath}">📌 ${secHeading}</h2>`)
      tocBlocks.push(
        `<div class="toc-item" id="toc-${secPath}" onclick="jumpToSegment(${startSec}, ${i}); toggleSidebar();">` +
        `<span>${secHeading}</span>` +
        `<span style="color: var(--text-muted); font-size: 0.75rem;">${formatDurationStr(startSec)}</span>` +
        `</div>`
      )
    }

    const zhTrans = translations[sid] || item.script || ''
    const zhScript = scripts[sid] || item.script || ''
    const enSource = sourceMap[sid] || ''
    const safeSidId = sid.replace(/[^a-zA-Z0-9_-]/g, '_')

    // 切分句级 span，支持高亮与“点哪读哪”
    let zhScriptHtml = ''
    if (item.sentences && item.sentences.length > 0) {
      zhScriptHtml = item.sentences.map((s: any, sIdx: number) =>
        `<span class="sentence-span" data-seg="${i}" data-sen="${sIdx}" data-start="${s.start_sec}" data-end="${s.end_sec}" onclick="event.stopPropagation(); jumpToSentence(${i}, ${sIdx}, ${s.start_sec});">${s.text}</span>`
      ).join('')
    } else {
      const sentenceList = splitSentences(zhScript)
      zhScriptHtml = sentenceList.map((st: string, sIdx: number) =>
        `<span class="sentence-span" data-seg="${i}" data-sen="${sIdx}" onclick="event.stopPropagation(); jumpToSentence(${i}, ${sIdx});">${st}</span>`
      ).join('')
    }

    contentBlocks.push(`
      <div class="segment-card" id="seg-${safeSidId}" data-seg-idx="${i}" onclick="jumpToSegment(${startSec}, ${i})">
        <div class="card-meta">
          <span class="play-tag">▶ ${formatDurationStr(startSec)}</span>
          <span>${hasAudio ? `时长 ${(item.duration_sec || 0).toFixed(1)}s` : `第 ${i + 1} 段`}</span>
        </div>
        <div class="text-zh-trans"><span class="badge-tag">译文</span>${zhTrans}</div>
        <div class="text-zh-script"><span class="badge-tag">讲稿</span>${zhScriptHtml}</div>
        <div class="text-en-source"><span class="badge-tag">原文</span>${enSource}</div>
      </div>
    `)
  }

  const safeTitle = doc.title || doc.doc_id

  let htmlTemplate = `<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
  <title>${safeTitle} - 中文伴读</title>
  <style>
    :root {
      --bg: #f8fafc;
      --surface: #ffffff;
      --surface-glass: rgba(255, 255, 255, 0.92);
      --text: #0f172a;
      --text-muted: #64748b;
      --en-text: #64748b;
      --primary: #2563eb;
      --primary-hover: #1d4ed8;
      --primary-light: #eff6ff;
      --primary-border: #bfdbfe;
      --active-border: #3b82f6;
      --border: #e2e8f0;
      --shadow-sm: 0 1px 2px 0 rgb(0 0 0 / 0.05);
      --shadow-md: 0 4px 6px -1px rgb(0 0 0 / 0.1), 0 2px 4px -2px rgb(0 0 0 / 0.1);
      --shadow-lg: 0 10px 25px -3px rgb(0 0 0 / 0.1), 0 4px 6px -4px rgb(0 0 0 / 0.1);
      --player-shadow: 0 12px 36px -4px rgba(0, 0, 0, 0.16), 0 4px 12px -2px rgba(0, 0, 0, 0.08);
      --font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
      --font-serif: "Songti SC", "SimSun", "Noto Serif SC", STSong, Georgia, serif;
    }

    @media (prefers-color-scheme: dark) {
      :root {
        --bg: #090d16;
        --surface: #131c2e;
        --surface-glass: rgba(19, 28, 46, 0.94);
        --text: #f8fafc;
        --text-muted: #94a3b8;
        --en-text: #94a3b8;
        --primary: #3b82f6;
        --primary-hover: #60a5fa;
        --primary-light: #172554;
        --primary-border: #1e3a8a;
        --active-border: #60a5fa;
        --border: #1e293b;
        --shadow-sm: 0 1px 2px 0 rgb(0 0 0 / 0.3);
        --shadow-md: 0 4px 6px -1px rgb(0 0 0 / 0.3);
        --shadow-lg: 0 10px 25px -3px rgb(0 0 0 / 0.4);
        --player-shadow: 0 12px 36px -4px rgba(0, 0, 0, 0.5), 0 4px 12px -2px rgba(0, 0, 0, 0.3);
      }
    }

    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: var(--font-sans);
      background: var(--bg);
      color: var(--text);
      line-height: 1.75;
      padding-bottom: 160px;
      -webkit-font-smoothing: antialiased;
    }

    /* Top Nav */
    header {
      position: sticky;
      top: 0;
      background: var(--surface-glass);
      border-bottom: 1px solid var(--border);
      padding: 10px 20px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      z-index: 100;
      backdrop-filter: blur(16px);
      -webkit-backdrop-filter: blur(16px);
    }
    .header-top {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
    }
    .brand { font-size: 0.95rem; font-weight: 700; color: var(--primary); display: flex; align-items: center; gap: 8px; }
    .nav-tools { display: flex; align-items: center; gap: 8px; }
    .btn {
      background: var(--surface);
      border: 1px solid var(--border);
      color: var(--text);
      padding: 6px 12px;
      border-radius: 8px;
      font-size: 0.82rem;
      font-weight: 500;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
      user-select: none;
      -webkit-tap-highlight-color: transparent;
    }
    .btn:hover { border-color: var(--primary); color: var(--primary); transform: translateY(-1px); }
    .btn:active { transform: translateY(0); }
    .btn.active { background: var(--primary); color: #fff; border-color: var(--primary); }

    /* Layout */
    .container {
      max-width: 860px;
      margin: 0 auto;
      padding: 24px 16px;
    }
    .paper-header {
      margin-bottom: 32px;
      padding-bottom: 20px;
      border-bottom: 1px solid var(--border);
    }
    .paper-title {
      font-size: 1.45rem;
      font-weight: 800;
      line-height: 1.4;
      margin-bottom: 12px;
      letter-spacing: -0.02em;
    }
    .paper-meta {
      font-size: 0.82rem;
      color: var(--text-muted);
      display: flex;
      gap: 16px;
      flex-wrap: wrap;
    }
    .paper-meta span { display: inline-flex; align-items: center; gap: 4px; }

    /* Section Headings */
    .section-title {
      font-size: 1.25rem;
      font-weight: 700;
      color: var(--primary);
      margin: 40px 0 16px 0;
      padding-bottom: 8px;
      border-bottom: 2px solid var(--border);
      display: flex;
      align-items: center;
      gap: 8px;
    }

    /* Segment Card */
    .segment-card {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 20px 22px;
      margin-bottom: 16px;
      transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
      cursor: pointer;
      position: relative;
    }
    .segment-card:hover {
      border-color: var(--primary-border);
      transform: translateY(-2px);
      box-shadow: var(--shadow-md);
    }
    .segment-card.active {
      border-color: var(--active-border);
      background: var(--primary-light);
      box-shadow: 0 0 0 2px var(--active-border), var(--shadow-md);
    }

    .card-meta {
      display: flex;
      justify-content: space-between;
      align-items: center;
      font-size: 0.78rem;
      color: var(--text-muted);
      margin-bottom: 12px;
      user-select: none;
    }
    .card-meta .play-tag {
      color: var(--primary);
      font-weight: 600;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      background: var(--bg);
      padding: 2px 8px;
      border-radius: 6px;
      border: 1px solid var(--border);
    }

    .text-zh-trans, .text-zh-script {
      font-size: 1.05rem;
      font-weight: 450;
      line-height: 1.8;
      margin-bottom: 8px;
      letter-spacing: 0.01em;
    }
    .text-zh-script {
      color: var(--text);
    }
    .text-en-source {
      font-size: 0.88rem;
      color: var(--en-text);
      line-height: 1.6;
      font-family: var(--font-serif);
      border-top: 1px dashed var(--border);
      padding-top: 10px;
      margin-top: 10px;
      opacity: 0.85;
    }

    /* Sentence-level Real-time Highlight (卡拉OK逐句高亮) */
    .sentence-span {
      display: inline;
      padding: 2px 4px;
      margin: 0 1px;
      border-radius: 4px;
      transition: background-color 0.15s ease, color 0.15s ease, box-shadow 0.15s ease;
      cursor: pointer;
    }
    .sentence-span:hover {
      background: rgba(37, 99, 235, 0.15);
      color: var(--primary);
    }
    .sentence-span.active-sentence {
      background: var(--primary);
      color: #ffffff !important;
      font-weight: 500;
      border-radius: 4px;
      box-shadow: 0 1px 6px rgba(37, 99, 235, 0.45);
    }

    .badge-tag {
      display: inline-block;
      font-size: 0.7rem;
      font-weight: 600;
      padding: 1px 6px;
      border-radius: 4px;
      margin-right: 6px;
      vertical-align: middle;
      background: var(--border);
      color: var(--text-muted);
    }

    /* View Mode Toggles */
    .view-interleave .text-zh-trans { display: block; }
    .view-interleave .text-en-source { display: block; }
    .view-interleave .text-zh-script { display: none; }

    .view-script .text-zh-script { display: block; }
    .view-script .text-zh-trans { display: none; }
    .view-script .text-en-source { display: none; }

    .view-trans .text-zh-trans { display: block; }
    .view-trans .text-zh-script { display: none; }
    .view-trans .text-en-source { display: none; }

    /* Modern Floating Player Bar: ALWAYS VISIBLE */
    .player-dock {
      position: fixed;
      bottom: calc(16px + env(safe-area-inset-bottom, 0px));
      left: 0;
      right: 0;
      display: flex;
      justify-content: center;
      z-index: 200;
      padding: 0 16px;
      pointer-events: none;
    }
    .player-pill {
      pointer-events: auto;
      max-width: 860px;
      width: 100%;
      background: var(--surface-glass);
      border: 1px solid var(--border);
      border-radius: 20px;
      padding: 12px 20px;
      box-shadow: var(--player-shadow);
      backdrop-filter: blur(20px);
      -webkit-backdrop-filter: blur(20px);
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    .player-desktop-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
    }
    .ctrl-group {
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .btn-circle {
      background: var(--surface);
      border: 1px solid var(--border);
      color: var(--text);
      width: 38px;
      height: 38px;
      border-radius: 50%;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
    }
    .btn-circle:hover {
      background: var(--primary-light);
      border-color: var(--primary-border);
      color: var(--primary);
      transform: scale(1.05);
    }
    .btn-play-main {
      width: 46px;
      height: 46px;
      background: linear-gradient(135deg, var(--primary), var(--primary-hover));
      color: #fff;
      border: none;
      box-shadow: 0 4px 12px rgba(37, 99, 235, 0.35);
    }
    .btn-play-main:hover {
      transform: scale(1.06);
      color: #fff;
    }
    .track-meta {
      flex: 1 1 auto;
      display: flex;
      flex-direction: column;
      overflow: hidden;
      min-width: 0;
    }
    .track-title {
      font-size: 0.85rem;
      font-weight: 600;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .track-time {
      font-size: 0.74rem;
      font-family: monospace;
      color: var(--text-muted);
    }
    .player-tools {
      display: flex;
      align-items: center;
      gap: 10px;
    }
    .toggle-label {
      font-size: 0.78rem;
      color: var(--text-muted);
      display: flex;
      align-items: center;
      gap: 4px;
      cursor: pointer;
    }
    .speed-btn {
      background: var(--surface);
      border: 1px solid var(--border);
      color: var(--text);
      padding: 4px 8px;
      border-radius: 8px;
      font-size: 0.78rem;
      font-weight: 600;
    }
    .progress-row {
      display: flex;
      align-items: center;
      width: 100%;
    }
    .seek-slider {
      flex: 1;
      height: 5px;
      border-radius: 3px;
      background: var(--border);
      outline: none;
      -webkit-appearance: none;
      cursor: pointer;
    }
    .seek-slider::-webkit-slider-thumb {
      -webkit-appearance: none;
      width: 13px;
      height: 13px;
      border-radius: 50%;
      background: var(--primary);
    }

    /* Mobile Responsive */
    @media (max-width: 640px) {
      body { padding-bottom: 180px; }
      header { padding: 10px 14px; flex-direction: column; align-items: stretch; gap: 10px; }
      .btn-toc-desktop { display: none; }
      .btn-toc-mobile { display: inline-flex; }
      .player-desktop-row { flex-direction: column; gap: 8px; }
      .player-mobile-header { display: flex; justify-content: space-between; align-items: center; width: 100%; }
      .ctrl-group { justify-content: center; gap: 28px; width: 100%; }
    }
    @media (min-width: 641px) {
      .btn-toc-mobile { display: none; }
      .btn-toc-desktop { display: inline-flex; }
      .player-desktop-row {
        display: grid;
        grid-template-columns: auto 1fr auto;
        grid-template-rows: auto auto;
        grid-template-areas: "ctrls meta tools" "prog prog prog";
        align-items: center;
        gap: 8px 16px;
      }
      .player-mobile-header { display: contents; }
      .ctrl-group { grid-area: ctrls; }
      .track-meta { grid-area: meta; }
      .player-tools { grid-area: tools; }
      .progress-row { grid-area: prog; }
    }

    /* Sidebar */
    .sidebar {
      position: fixed;
      top: 0; right: -340px; width: 320px; max-width: 85vw; height: 100%;
      background: var(--surface);
      border-left: 1px solid var(--border);
      box-shadow: -4px 0 20px rgba(0,0,0,0.15);
      z-index: 300;
      transition: right 0.3s cubic-bezier(0.4, 0, 0.2, 1);
      display: flex; flex-direction: column;
    }
    .sidebar.open { right: 0; }
    .sidebar-header {
      padding: 18px 20px;
      border-bottom: 1px solid var(--border);
      display: flex; justify-content: space-between; align-items: center; font-weight: 700;
    }
    .sidebar-list { flex: 1; overflow-y: auto; padding: 12px; }
    .toc-item {
      padding: 10px 12px; border-radius: 8px; font-size: 0.85rem; cursor: pointer;
      margin-bottom: 4px; display: flex; justify-content: space-between; align-items: center;
    }
    .toc-item:hover { background: var(--bg); color: var(--primary); }
    .toc-item.active { background: var(--primary-light); color: var(--primary); font-weight: 600; }
    .overlay {
      position: fixed; top: 0; left: 0; right: 0; bottom: 0;
      background: rgba(0,0,0,0.4); backdrop-filter: blur(2px); z-index: 250; display: none;
    }
    .overlay.show { display: block; }
    .icon { width: 18px; height: 18px; fill: currentColor; display: inline-block; vertical-align: middle; }
  </style>
</head>
<body class="view-interleave">

  <header>
    <div class="header-top">
      <div class="brand">
        <svg class="icon" viewBox="0 0 24 24"><path d="M12 3v10.55c-.59-.34-1.27-.55-2-.55-2.21 0-4 1.79-4 4s1.79 4 4 4 4-1.79 4-4V7h4V3h-6z"/></svg>
        <span>文献中文伴读</span>
      </div>
      <button class="btn btn-toc-mobile" onclick="toggleSidebar()">
        <svg class="icon" viewBox="0 0 24 24"><path d="M3 13h2v-2H3v2zm0 4h2v-2H3v2zm0-8h2V7H3v2zm4 4h14v-2H7v2zm0 4h14v-2H7v2zM7 7v2h14V7H7z"/></svg>
        <span>目录</span>
      </button>
    </div>
    <div class="nav-tools">
      <button class="btn btn-tab active" id="btn-view-interleave" onclick="setViewMode('interleave')">中英对照</button>
      <button class="btn btn-tab" id="btn-view-script" onclick="setViewMode('script')">口语讲稿</button>
      <button class="btn btn-tab" id="btn-view-trans" onclick="setViewMode('trans')">忠实译文</button>
      <button class="btn btn-toc-desktop" onclick="toggleSidebar()">
        <svg class="icon" viewBox="0 0 24 24"><path d="M3 13h2v-2H3v2zm0 4h2v-2H3v2zm0-8h2V7H3v2zm4 4h14v-2H7v2zm0 4h14v-2H7v2zM7 7v2h14V7H7z"/></svg>
        <span>目录</span>
      </button>
    </div>
  </header>

  <div class="container">
    <div class="paper-header">
      <h1 class="paper-title">${safeTitle}</h1>
      <div class="paper-meta">
        <span>📄 ID: ${doc.doc_id}</span>
        <span>⏱️ 总时长: ${formatDuration(totalSec)}</span>
        <span>🎙️ 音色: ${voice}</span>
        <span>📊 共 ${doc.segments.length} 段</span>
      </div>
    </div>

    <main id="content-container">
      ${contentBlocks.join('\n')}
    </main>
  </div>

  <div class="player-dock">
    <div class="player-pill">
      <div class="player-desktop-row">
        <div class="player-mobile-header">
          <div class="track-meta">
            <div class="track-title" id="track-title">第 1 段</div>
            <div class="track-time" id="track-time">00:00 / ${formatDurationStr(totalSec)}</div>
          </div>
          <div class="player-tools">
            <label class="toggle-label" title="播放时自动滚动到当前段落">
              <input type="checkbox" id="auto-scroll-toggle" checked> 自动跟踪
            </label>
            <select class="speed-btn" id="speed-select" onchange="changeSpeed(this.value)">
              <option value="0.75">0.75x</option>
              <option value="1.0" selected>1.0x</option>
              <option value="1.25">1.25x</option>
              <option value="1.5">1.5x</option>
              <option value="1.75">1.75x</option>
              <option value="2.0">2.0x</option>
            </select>
          </div>
        </div>

        <div class="progress-row">
          <input type="range" class="seek-slider" id="seek-slider" min="0" max="${totalSec}" step="0.1" value="0" oninput="onSeekInput()" onchange="onSeekChange()">
        </div>

        <div class="ctrl-group">
          <button class="btn-circle" onclick="skipAudio(-15)" title="后退 15 秒 / 上一段">
            <svg class="icon" viewBox="0 0 24 24"><path d="M12.5 8c-2.65 0-5.05 1-6.9 2.6L2 7v9h9l-3.62-3.62c1.39-1.2 3.16-1.88 5.12-1.88 3.54 0 6.55 2.31 7.6 5.5l2.37-.78C21.08 11.03 17.15 8 12.5 8z"/><text x="9" y="16" font-size="7" font-weight="bold" fill="currentColor">15</text></svg>
          </button>
          <button class="btn-circle btn-play-main" id="play-pause-btn" onclick="togglePlay()" title="播放 / 暂停 (空格键)">
            <svg class="icon" id="icon-play" viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>
            <svg class="icon" id="icon-pause" viewBox="0 0 24 24" style="display: none;"><path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/></svg>
          </button>
          <button class="btn-circle" onclick="skipAudio(15)" title="前进 15 秒 / 下一段">
            <svg class="icon" viewBox="0 0 24 24"><path d="M11.5 8c2.65 0 5.05 1 6.9 2.6L22 7v9h-9l3.62-3.62c-1.39-1.2-3.16-1.88-5.12-1.88-3.54 0-6.55 2.31-7.6 5.5l-2.37-.78C2.92 11.03 6.85 8 11.5 8z"/><text x="9" y="16" font-size="7" font-weight="bold" fill="currentColor">15</text></svg>
          </button>
        </div>
      </div>
    </div>
  </div>

  <div class="overlay" id="overlay" onclick="toggleSidebar()"></div>
  <aside class="sidebar" id="sidebar">
    <div class="sidebar-header">
      <span>章节目录</span>
      <button class="btn" onclick="toggleSidebar()">✕</button>
    </div>
    <div class="sidebar-list" id="toc-list">
      ${tocBlocks.join('\n')}
    </div>
  </aside>

  <audio id="main-audio" preload="auto" src="${audioSrc}"></audio>

  <script>
    const TIMELINE = ${JSON.stringify(effectiveTimeline)};
    const audio = document.getElementById('main-audio');
    const hasAudioTrack = audio && audio.src && audio.src.startsWith('data:audio');
    const TARGET_VOICE_NAME = "${voice}";

    const iconPlay = document.getElementById('icon-play');
    const iconPause = document.getElementById('icon-pause');
    const trackTitle = document.getElementById('track-title');
    const trackTime = document.getElementById('track-time');
    const seekSlider = document.getElementById('seek-slider');
    const autoScrollToggle = document.getElementById('auto-scroll-toggle');
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('overlay');

    let currentSegmentIndex = 0;
    let currentSentenceIndex = 0;
    let isSeeking = false;
    let currentSpeed = 1.0;
    let isWebSpeechPlaying = false;
    let speechSynth = window.speechSynthesis;
    let cachedVoices = [];

    function loadVoices() {
      if (speechSynth) {
        cachedVoices = speechSynth.getVoices();
      }
    }
    loadVoices();
    if (speechSynth && speechSynth.onvoiceschanged !== undefined) {
      speechSynth.onvoiceschanged = loadVoices;
    }

    function getMatchedVoice() {
      if (!cachedVoices || cachedVoices.length === 0) {
        loadVoices();
      }
      // 1. 尝试精确匹配名称
      let found = cachedVoices.find(v => v.name.includes(TARGET_VOICE_NAME) || TARGET_VOICE_NAME.includes(v.name));
      // 2. 尝试按语言匹配 (zh-TW 或 zh-CN)
      if (!found) {
        const langPref = TARGET_VOICE_NAME.includes('TW') ? 'zh-TW' : 'zh';
        found = cachedVoices.find(v => v.lang.replace('_', '-').toLowerCase().startsWith(langPref.toLowerCase()));
      }
      // 3. 任何中文
      if (!found) {
        found = cachedVoices.find(v => v.lang.toLowerCase().includes('zh') || v.lang.toLowerCase().includes('cmn'));
      }
      return found || null;
    }

    function formatTime(secs) {
      if (isNaN(secs) || secs < 0) return "00:00";
      const mins = Math.floor(secs / 60);
      const s = Math.floor(secs % 60);
      return String(mins).padStart(2, '0') + ':' + String(s).padStart(2, '0');
    }

    function updatePlayIcon(isPlaying) {
      if (isPlaying) {
        if (iconPlay) iconPlay.style.display = 'none';
        if (iconPause) iconPause.style.display = 'inline-block';
      } else {
        if (iconPlay) iconPlay.style.display = 'inline-block';
        if (iconPause) iconPause.style.display = 'none';
      }
    }

    function highlightCard(segIdx) {
      if (segIdx < 0 || segIdx >= TIMELINE.length) return;
      currentSegmentIndex = segIdx;
      const seg = TIMELINE[segIdx];
      trackTitle.innerText = '第 ' + (segIdx + 1) + ' / ' + TIMELINE.length + ' 段 · ' + (seg.sec_heading || '正文');
      document.querySelectorAll('.segment-card').forEach(c => c.classList.remove('active'));
      const safeId = (seg.sid || '').replace(/[^a-zA-Z0-9_-]/g, '_');
      const activeCard = document.getElementById('seg-' + safeId);
      if (activeCard) {
        activeCard.classList.add('active');
        if (autoScrollToggle && autoScrollToggle.checked) {
          activeCard.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
      }
      document.querySelectorAll('.toc-item').forEach(t => t.classList.remove('active'));
      const activeToc = document.getElementById('toc-' + seg.sec_path);
      if (activeToc) activeToc.classList.add('active');
    }

    function highlightSentence(segIdx, senIdx) {
      highlightCard(segIdx);
      currentSentenceIndex = senIdx;
      document.querySelectorAll('.sentence-span').forEach(s => s.classList.remove('active-sentence'));
      const targetSpan = document.querySelector('.sentence-span[data-seg="' + segIdx + '"][data-sen="' + senIdx + '"]');
      if (targetSpan) {
        targetSpan.classList.add('active-sentence');
        if (autoScrollToggle && autoScrollToggle.checked) {
          targetSpan.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
      }
    }

    // Web Speech API 句级智能播报 (支持点哪读哪)
    function speakFromSentence(segIdx, senIdx) {
      if (!speechSynth) return;
      speechSynth.cancel();

      if (segIdx >= TIMELINE.length) {
        isWebSpeechPlaying = false;
        updatePlayIcon(false);
        return;
      }

      const seg = TIMELINE[segIdx];
      const safeId = (seg.sid || '').replace(/[^a-zA-Z0-9_-]/g, '_');
      const card = document.getElementById('seg-' + safeId);
      const spans = card ? Array.from(card.querySelectorAll('.sentence-span')) : [];

      if (senIdx >= spans.length) {
        // 进入下一段
        speakFromSentence(segIdx + 1, 0);
        return;
      }

      highlightSentence(segIdx, senIdx);
      const span = spans[senIdx];
      const textToSpeak = span ? span.innerText.trim() : (seg.script || seg.src_text || '');

      const utterance = new SpeechSynthesisUtterance(textToSpeak);
      const matched = getMatchedVoice();
      if (matched) {
        utterance.voice = matched;
        utterance.lang = matched.lang;
      } else {
        utterance.lang = TARGET_VOICE_NAME.includes('TW') ? 'zh-TW' : 'zh-CN';
      }
      utterance.rate = currentSpeed;

      utterance.onstart = () => {
        isWebSpeechPlaying = true;
        updatePlayIcon(true);
        seekSlider.value = seg.start_sec;
        trackTime.innerText = formatTime(seg.start_sec) + ' / ' + formatTime(TIMELINE[TIMELINE.length - 1].end_sec);
      };

      utterance.onend = () => {
        if (isWebSpeechPlaying) {
          speakFromSentence(segIdx, senIdx + 1);
        }
      };

      utterance.onerror = (e) => {
        if (e.error !== 'canceled' && e.error !== 'interrupted') {
          console.warn('Speech error:', e);
        }
        isWebSpeechPlaying = false;
        updatePlayIcon(false);
      };

      speechSynth.speak(utterance);
    }

    function togglePlay() {
      if (hasAudioTrack) {
        if (audio.paused) {
          audio.play().catch(e => console.log('Play interrupted:', e));
        } else {
          audio.pause();
        }
      } else {
        if (isWebSpeechPlaying) {
          if (speechSynth) speechSynth.cancel();
          isWebSpeechPlaying = false;
          updatePlayIcon(false);
        } else {
          speakFromSentence(currentSegmentIndex, currentSentenceIndex);
        }
      }
    }

    function jumpToSentence(segIdx, senIdx, startSec) {
      if (hasAudioTrack && startSec !== undefined) {
        audio.currentTime = startSec;
        audio.play().catch(e => console.log('Play err:', e));
        highlightSentence(segIdx, senIdx);
      } else {
        speakFromSentence(segIdx, senIdx);
      }
    }

    function jumpToSegment(startSec, segIdx) {
      if (hasAudioTrack) {
        audio.currentTime = startSec;
        audio.play().catch(e => console.log('Play err:', e));
        highlightCard(segIdx);
      } else {
        speakFromSentence(segIdx, 0);
      }
    }

    function skipAudio(deltaSecs) {
      if (hasAudioTrack) {
        audio.currentTime = Math.max(0, Math.min(audio.duration || 0, audio.currentTime + deltaSecs));
      } else {
        const nextIdx = deltaSecs > 0 ? currentSegmentIndex + 1 : Math.max(0, currentSegmentIndex - 1);
        if (isWebSpeechPlaying) {
          speakFromSentence(nextIdx, 0);
        } else {
          highlightCard(nextIdx);
        }
      }
    }

    function changeSpeed(val) {
      currentSpeed = parseFloat(val);
      if (hasAudioTrack) {
        audio.playbackRate = currentSpeed;
      } else if (isWebSpeechPlaying) {
        speakFromSentence(currentSegmentIndex, currentSentenceIndex);
      }
      localStorage.setItem('paper_playback_rate', val);
    }

    function setViewMode(mode) {
      document.body.className = 'view-' + mode;
      document.querySelectorAll('.nav-tools .btn').forEach(b => b.classList.remove('active'));
      const activeBtn = document.getElementById('btn-view-' + mode);
      if (activeBtn) activeBtn.classList.add('active');
      localStorage.setItem('paper_view_mode', mode);
    }

    function toggleSidebar() {
      sidebar.classList.toggle('open');
      overlay.classList.toggle('show');
    }

    function onSeekInput() {
      isSeeking = true;
      trackTime.innerText = formatTime(seekSlider.value) + ' / ' + formatTime(TIMELINE[TIMELINE.length - 1].end_sec || 0);
    }

    function onSeekChange() {
      if (hasAudioTrack) {
        audio.currentTime = parseFloat(seekSlider.value);
      } else {
        const targetSec = parseFloat(seekSlider.value);
        let targetIdx = 0;
        for (let i = 0; i < TIMELINE.length; i++) {
          if (targetSec >= TIMELINE[i].start_sec) targetIdx = i;
        }
        speakFromSentence(targetIdx, 0);
      }
      isSeeking = false;
    }

    if (hasAudioTrack) {
      audio.addEventListener('play', () => updatePlayIcon(true));
      audio.addEventListener('pause', () => updatePlayIcon(false));
      audio.addEventListener('timeupdate', () => {
        const cur = audio.currentTime;
        if (!isSeeking && seekSlider) {
          seekSlider.value = cur;
          trackTime.innerText = formatTime(cur) + ' / ' + formatTime(audio.duration || 0);
        }
        let foundIdx = -1;
        for (let i = 0; i < TIMELINE.length; i++) {
          if (cur >= TIMELINE[i].start_sec && cur <= TIMELINE[i].end_sec) {
            foundIdx = i;
            break;
          }
        }
        if (foundIdx !== -1 && foundIdx !== currentSegmentIndex) {
          highlightCard(foundIdx);
        }

        const curCard = document.querySelector('.segment-card.active');
        if (curCard) {
          const spans = curCard.querySelectorAll('.sentence-span');
          let activeSpan = null;
          for (const span of spans) {
            const sStart = parseFloat(span.dataset.start);
            const sEnd = parseFloat(span.dataset.end);
            if (cur >= sStart && cur <= sEnd) {
              activeSpan = span;
              break;
            }
          }
          document.querySelectorAll('.sentence-span.active-sentence').forEach(el => {
            if (el !== activeSpan) el.classList.remove('active-sentence');
          });
          if (activeSpan && !activeSpan.classList.contains('active-sentence')) {
            activeSpan.classList.add('active-sentence');
          }
        }
        localStorage.setItem('paper_progress_${doc.doc_id}', cur);
      });
    }

    // 快捷键支持 (空格键播放/暂停)
    window.addEventListener('keydown', (e) => {
      if (e.code === 'Space' && (e.target === document.body || e.target === document.documentElement)) {
        e.preventDefault();
        togglePlay();
      }
    });

    // 页面卸载或关闭事件：彻底停止朗读
    window.addEventListener('beforeunload', () => {
      if (speechSynth) speechSynth.cancel();
      if (audio) audio.pause();
    });

    window.addEventListener('message', (e) => {
      if (e.data === 'STOP_AUDIO') {
        if (speechSynth) speechSynth.cancel();
        if (audio) audio.pause();
        updatePlayIcon(false);
      }
    });

    window.addEventListener('DOMContentLoaded', () => {
      const savedMode = localStorage.getItem('paper_view_mode') || 'interleave';
      setViewMode(savedMode);
      const savedRate = localStorage.getItem('paper_playback_rate');
      if (savedRate) {
        currentSpeed = parseFloat(savedRate);
        const el = document.getElementById('speed-select');
        if (el) el.value = savedRate;
        if (hasAudioTrack) audio.playbackRate = currentSpeed;
      }
      highlightCard(0);
    });
  </script>
</body>
</html>`

  if (hasAudio) {
    htmlTemplate = htmlTemplate.replace('{AUDIO_DATA}', audioBase64)
  }

  return htmlTemplate
}

export function downloadHtml(filename: string, content: string) {
  const blob = new Blob([content], { type: 'text/html;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}
