"""生成自包含双向伴读 HTML 网页 (Web Reader)。

功能特性：
- 真正的单文件自包含（Zero Dependency）：内嵌 MP3 (Base64)、内嵌 CSS 与 JS，断网可用、可 AirDrop 到手机/iPad
- 视图三合一切换：中英交错对照 / 纯口语讲稿 / 忠实全译
- 毫秒级双向联动：音频播放实时高亮段落并平滑居中滚动；点击任意段落瞬间跳转音频
- 移动端后台与锁屏保活：集成 MediaSession API，锁屏显示卡片与快进/快退控制器
- 进度自动记忆：localStorage 记住上次播放进度与偏好设置
- 现代化精美播放器 UI（悬浮毛玻璃胶囊、SVG 图标、暗黑模式）
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
  <title>__TITLE__ - 中文伴读</title>
  <style>
    :root {
      --bg: #f8fafc;
      --surface: #ffffff;
      --surface-glass: rgba(255, 255, 255, 0.90);
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
        --surface-glass: rgba(19, 28, 46, 0.92);
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
      padding-bottom: 150px;
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

    /* Sentence-level Real-time Karaoke Highlight */
    .sentence-span {
      display: inline;
      padding: 1px 3px;
      border-radius: 4px;
      transition: background-color 0.15s ease, color 0.15s ease, box-shadow 0.15s ease;
      cursor: pointer;
    }
    .sentence-span:hover {
      background: var(--primary-light);
      color: var(--primary);
    }
    .sentence-span.active-sentence {
      background: var(--primary);
      color: #ffffff !important;
      font-weight: 500;
      border-radius: 4px;
      box-shadow: 0 1px 6px rgba(37, 99, 235, 0.4);
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

    /* Modern Floating Player Bar */
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
      transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
    }

    /* Desktop Player Layout */
    .player-desktop-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
    }

    /* Controls */
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
      user-select: none;
      -webkit-tap-highlight-color: transparent;
    }
    .btn-circle:hover {
      background: var(--primary-light);
      border-color: var(--primary-border);
      color: var(--primary);
      transform: scale(1.05);
    }
    .btn-circle:active { transform: scale(0.95); }

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
      box-shadow: 0 6px 16px rgba(37, 99, 235, 0.45);
      color: #fff;
      background: linear-gradient(135deg, var(--primary-hover), var(--primary));
    }

    /* Track Status */
    .track-meta {
      flex: 1 1 auto;
      display: flex;
      flex-direction: column;
      overflow: hidden;
      min-width: 0;
      max-width: 100%;
    }
    .track-title {
      font-size: 0.85rem;
      font-weight: 600;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      color: var(--text);
      display: block;
      width: 100%;
      min-width: 0;
    }
    .track-time {
      font-size: 0.74rem;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      font-variant-numeric: tabular-nums;
      color: var(--text-muted);
      white-space: nowrap;
    }

    /* Extra Tools */
    .player-tools {
      display: flex;
      align-items: center;
      gap: 10px;
      flex-shrink: 0;
    }
    .toggle-label {
      font-size: 0.78rem;
      color: var(--text-muted);
      display: flex;
      align-items: center;
      gap: 4px;
      cursor: pointer;
      user-select: none;
      white-space: nowrap;
    }
    .speed-btn {
      background: var(--surface);
      border: 1px solid var(--border);
      color: var(--text);
      padding: 4px 8px;
      border-radius: 8px;
      font-size: 0.78rem;
      font-weight: 600;
      cursor: pointer;
      outline: none;
    }

    /* Progress bar */
    .progress-row {
      display: flex;
      align-items: center;
      gap: 8px;
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
      transition: height 0.15s;
    }
    .seek-slider:hover { height: 7px; }
    .seek-slider::-webkit-slider-thumb {
      -webkit-appearance: none;
      width: 13px;
      height: 13px;
      border-radius: 50%;
      background: var(--primary);
      box-shadow: 0 1px 4px rgba(0,0,0,0.2);
      cursor: pointer;
      transition: transform 0.15s;
    }
    .seek-slider::-webkit-slider-thumb:hover { transform: scale(1.2); }

    /* Mobile Responsive Optimizations */
    @media (max-width: 640px) {
      body {
        padding-bottom: 180px;
      }
      header {
        padding: 10px 14px;
        flex-direction: column;
        align-items: stretch;
        gap: 10px;
      }
      .header-top {
        display: flex;
        justify-content: space-between;
        align-items: center;
        width: 100%;
      }
      .brand {
        font-size: 0.95rem;
      }
      .nav-tools {
        display: flex;
        width: 100%;
        background: var(--surface);
        padding: 3px;
        border-radius: 10px;
        border: 1px solid var(--border);
        gap: 4px;
      }
      .nav-tools .btn-tab {
        flex: 1;
        justify-content: center;
        padding: 7px 4px;
        font-size: 0.82rem;
        border: none;
        background: transparent;
        border-radius: 7px;
        color: var(--text-muted);
        box-shadow: none;
        transform: none !important;
      }
      .nav-tools .btn-tab.active {
        background: var(--primary);
        color: #ffffff;
        font-weight: 600;
        box-shadow: var(--shadow-sm);
      }
      .btn-toc-desktop { display: none; }
      .btn-toc-mobile { display: inline-flex; }

      /* Mobile Player Refined Layout */
      .player-dock {
        bottom: calc(10px + env(safe-area-inset-bottom, 0px));
        padding: 0 10px;
      }
      .player-pill {
        padding: 12px 14px 10px 14px;
        border-radius: 18px;
        gap: 8px;
      }
      .player-desktop-row {
        display: flex;
        flex-direction: column;
        gap: 8px;
      }
      .player-mobile-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 10px;
      }
      .track-meta {
        flex: 1;
        min-width: 0;
      }
      .track-title {
        font-size: 0.82rem;
        font-weight: 600;
      }
      .track-time {
        font-size: 0.72rem;
      }
      .player-tools {
        gap: 8px;
      }
      .toggle-label {
        font-size: 0.74rem;
      }
      .speed-btn {
        padding: 3px 6px;
        font-size: 0.74rem;
      }
      .progress-row {
        margin: 2px 0 4px 0;
      }
      .seek-slider {
        height: 6px;
      }
      .seek-slider::-webkit-slider-thumb {
        width: 15px;
        height: 15px;
      }
      .ctrl-group {
        display: flex;
        justify-content: center;
        align-items: center;
        gap: 28px;
        margin-top: 2px;
      }
      .btn-circle {
        width: 42px;
        height: 42px;
      }
      .btn-play-main {
        width: 50px;
        height: 50px;
      }
    }

    @media (min-width: 641px) {
      .btn-toc-mobile { display: none; }
      .btn-toc-desktop { display: inline-flex; }
      .player-desktop-row {
        display: grid;
        grid-template-columns: auto 1fr auto;
        grid-template-rows: auto auto;
        grid-template-areas:
          "ctrls meta tools"
          "prog  prog prog";
        align-items: center;
        gap: 8px 16px;
      }
      .player-mobile-header {
        display: contents;
      }
      .ctrl-group {
        grid-area: ctrls;
      }
      .track-meta {
        grid-area: meta;
      }
      .player-tools {
        grid-area: tools;
      }
      .progress-row {
        grid-area: prog;
      }
    }

    /* Sidebar Drawer */
    .sidebar {
      position: fixed;
      top: 0;
      right: -340px;
      width: 320px;
      max-width: 85vw;
      height: 100%;
      background: var(--surface);
      border-left: 1px solid var(--border);
      box-shadow: -4px 0 20px rgba(0,0,0,0.15);
      z-index: 300;
      transition: right 0.3s cubic-bezier(0.4, 0, 0.2, 1);
      display: flex;
      flex-direction: column;
    }
    .sidebar.open { right: 0; }
    .sidebar-header {
      padding: 18px 20px;
      border-bottom: 1px solid var(--border);
      display: flex;
      justify-content: space-between;
      align-items: center;
      font-weight: 700;
    }
    .sidebar-list {
      flex: 1;
      overflow-y: auto;
      padding: 12px;
      -webkit-overflow-scrolling: touch;
    }
    .toc-item {
      padding: 10px 12px;
      border-radius: 8px;
      font-size: 0.85rem;
      cursor: pointer;
      margin-bottom: 4px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      color: var(--text);
      transition: background 0.15s;
    }
    .toc-item:hover { background: var(--bg); color: var(--primary); }
    .toc-item.active { background: var(--primary-light); color: var(--primary); font-weight: 600; }
    .overlay {
      position: fixed;
      top: 0; left: 0; right: 0; bottom: 0;
      background: rgba(0,0,0,0.4);
      backdrop-filter: blur(2px);
      z-index: 250;
      display: none;
    }
    .overlay.show { display: block; }

    /* SVG Icons */
    .icon {
      width: 18px;
      height: 18px;
      fill: currentColor;
      display: inline-block;
      vertical-align: middle;
    }
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
      <h1 class="paper-title">__TITLE__</h1>
      <div class="paper-meta">
        <span>📄 ID: __DOC_ID__</span>
        <span>⏱️ 总时长: __DURATION_TEXT__</span>
        <span>🎙️ 音色: __VOICE__</span>
        <span>📊 共 __SEG_COUNT__ 段</span>
      </div>
    </div>

    <main id="content-container">
      __CONTENT_HTML__
    </main>
  </div>

  <!-- Modern Floating Player Bar -->
  <div class="player-dock">
    <div class="player-pill">
      <div class="player-desktop-row">
        <!-- Mobile Top / Desktop Left-Center -->
        <div class="player-mobile-header">
          <div class="track-meta">
            <div class="track-title" id="track-title">第 1 段</div>
            <div class="track-time" id="track-time">00:00 / __DURATION_STR__</div>
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

        <!-- Progress Slider -->
        <div class="progress-row">
          <input type="range" class="seek-slider" id="seek-slider" min="0" max="__TOTAL_SECONDS__" step="0.1" value="0" oninput="onSeekInput()" onchange="onSeekChange()">
        </div>

        <!-- Controls Group -->
        <div class="ctrl-group">
          <!-- Skip Back 15s -->
          <button class="btn-circle" onclick="skipAudio(-15)" title="后退 15 秒">
            <svg class="icon" viewBox="0 0 24 24"><path d="M12.5 8c-2.65 0-5.05 1-6.9 2.6L2 7v9h9l-3.62-3.62c1.39-1.2 3.16-1.88 5.12-1.88 3.54 0 6.55 2.31 7.6 5.5l2.37-.78C21.08 11.03 17.15 8 12.5 8z"/><text x="9" y="16" font-size="7" font-weight="bold" fill="currentColor">15</text></svg>
          </button>
          <!-- Main Play / Pause -->
          <button class="btn-circle btn-play-main" id="play-pause-btn" onclick="togglePlay()" title="播放 / 暂停 (空格键)">
            <svg class="icon" id="icon-play" viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>
            <svg class="icon" id="icon-pause" viewBox="0 0 24 24" style="display: none;"><path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/></svg>
          </button>
          <!-- Skip Forward 15s -->
          <button class="btn-circle" onclick="skipAudio(15)" title="前进 15 秒">
            <svg class="icon" viewBox="0 0 24 24"><path d="M11.5 8c2.65 0 5.05 1 6.9 2.6L22 7v9h-9l3.62-3.62c-1.39-1.2-3.16-1.88-5.12-1.88-3.54 0-6.55 2.31-7.6 5.5l-2.37-.78C2.92 11.03 6.85 8 11.5 8z"/><text x="9" y="16" font-size="7" font-weight="bold" fill="currentColor">15</text></svg>
          </button>
        </div>
      </div>
    </div>
  </div>

  <!-- TOC Sidebar Drawer -->
  <div class="overlay" id="overlay" onclick="toggleSidebar()"></div>
  <aside class="sidebar" id="sidebar">
    <div class="sidebar-header">
      <span>章节目录</span>
      <button class="btn" onclick="toggleSidebar()">✕</button>
    </div>
    <div class="sidebar-list" id="toc-list">
      __TOC_HTML__
    </div>
  </aside>

  <!-- Embedded Audio Element -->
  <audio id="main-audio" preload="auto" src="__AUDIO_SRC__"></audio>

  <script>
    const TIMELINE = __TIMELINE_JSON__;
    const DOC_TITLE = "__TITLE_ESCAPED__";
    const audio = document.getElementById('main-audio');
    const iconPlay = document.getElementById('icon-play');
    const iconPause = document.getElementById('icon-pause');
    const trackTitle = document.getElementById('track-title');
    const trackTime = document.getElementById('track-time');
    const seekSlider = document.getElementById('seek-slider');
    const autoScrollToggle = document.getElementById('auto-scroll-toggle');
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('overlay');

    let currentSegmentIndex = -1;
    let isSeeking = false;

    function formatTime(secs) {
      if (isNaN(secs) || secs < 0) return "00:00";
      const mins = Math.floor(secs / 60);
      const s = Math.floor(secs % 60);
      return `${String(mins).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
    }

    function togglePlay() {
      if (audio.paused) {
        audio.play().catch(e => console.log('Play interrupted:', e));
      } else {
        audio.pause();
      }
    }

    function skipAudio(deltaSecs) {
      audio.currentTime = Math.max(0, Math.min(audio.duration || 0, audio.currentTime + deltaSecs));
    }

    function changeSpeed(val) {
      audio.playbackRate = parseFloat(val);
      localStorage.setItem('paper_playback_rate', val);
    }

    function jumpToSegment(startSec) {
      audio.currentTime = startSec;
      audio.play().catch(e => console.log('Play err:', e));
    }

    function setViewMode(mode) {
      document.body.className = `view-${mode}`;
      document.querySelectorAll('.nav-tools .btn').forEach(b => {
        b.classList.remove('active');
      });
      const activeBtn = document.getElementById(`btn-view-${mode}`);
      if (activeBtn) activeBtn.classList.add('active');
      localStorage.setItem('paper_view_mode', mode);
    }

    function toggleSidebar() {
      sidebar.classList.toggle('open');
      overlay.classList.toggle('show');
    }

    function onSeekInput() {
      isSeeking = true;
      trackTime.innerText = `${formatTime(seekSlider.value)} / ${formatTime(audio.duration || 0)}`;
    }

    function onSeekChange() {
      audio.currentTime = parseFloat(seekSlider.value);
      isSeeking = false;
    }

    // Audio event bindings
    audio.addEventListener('play', () => {
      iconPlay.style.display = 'none';
      iconPause.style.display = 'inline-block';
      setupMediaSession();
    });

    audio.addEventListener('pause', () => {
      iconPlay.style.display = 'inline-block';
      iconPause.style.display = 'none';
    });

    audio.addEventListener('timeupdate', () => {
      const cur = audio.currentTime;
      if (!isSeeking) {
        seekSlider.value = cur;
        trackTime.innerText = `${formatTime(cur)} / ${formatTime(audio.duration || 0)}`;
      }

      // Find active segment
      let foundIdx = -1;
      for (let i = 0; i < TIMELINE.length; i++) {
        if (cur >= TIMELINE[i].start_sec && cur <= TIMELINE[i].end_sec) {
          foundIdx = i;
          break;
        }
      }

      if (foundIdx !== -1 && foundIdx !== currentSegmentIndex) {
        currentSegmentIndex = foundIdx;
        const seg = TIMELINE[foundIdx];
        trackTitle.innerText = `第 ${foundIdx + 1} 段`;
        trackTitle.title = `【${seg.sec_heading}】${seg.script}`;

        // Highlight DOM Segment
        document.querySelectorAll('.segment-card').forEach(c => c.classList.remove('active'));
        const activeCard = document.getElementById(`seg-${seg.sid.replace(/[^a-zA-Z0-9_-]/g, '_')}`);
        if (activeCard) {
          activeCard.classList.add('active');
          if (autoScrollToggle.checked) {
            activeCard.scrollIntoView({ behavior: 'smooth', block: 'center' });
          }
        }

        // Highlight TOC
        document.querySelectorAll('.toc-item').forEach(t => t.classList.remove('active'));
        const activeToc = document.getElementById(`toc-${seg.sec_path}`);
        if (activeToc) activeToc.classList.add('active');
      }

      // Real-time Sentence-level tracking & highlighting
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
      } else {
        document.querySelectorAll('.sentence-span.active-sentence').forEach(el => el.classList.remove('active-sentence'));
      }

      // Save local progress
      localStorage.setItem('paper_progress___DOC_ID__', cur);
    });


    // MediaSession API for mobile background & lock-screen control
    function setupMediaSession() {
      if ('mediaSession' in navigator) {
        navigator.mediaSession.metadata = new MediaMetadata({
          title: DOC_TITLE,
          artist: "Nature Reviews 中文伴读",
          album: "paper-zh",
        });

        navigator.mediaSession.setActionHandler('play', () => audio.play());
        navigator.mediaSession.setActionHandler('pause', () => audio.pause());
        navigator.mediaSession.setActionHandler('seekbackward', () => skipAudio(-15));
        navigator.mediaSession.setActionHandler('seekforward', () => skipAudio(15));
        navigator.mediaSession.setActionHandler('seekto', (details) => {
          if (details.seekTime) audio.currentTime = details.seekTime;
        });
      }
    }

    // Keyboard shortcut (Space = Play/Pause)
    window.addEventListener('keydown', (e) => {
      if (e.code === 'Space' && e.target === document.body) {
        e.preventDefault();
        togglePlay();
      }
    });

    // Initialize state on load
    window.addEventListener('DOMContentLoaded', () => {
      const savedMode = localStorage.getItem('paper_view_mode') || 'interleave';
      setViewMode(savedMode);

      const savedRate = localStorage.getItem('paper_playback_rate');
      if (savedRate) {
        document.getElementById('speed-select').value = savedRate;
        audio.playbackRate = parseFloat(savedRate);
      }

      const savedProgress = localStorage.getItem('paper_progress___DOC_ID__');
      if (savedProgress) {
        audio.currentTime = parseFloat(savedProgress);
      }
    });
  </script>
</body>
</html>
"""


def format_duration(seconds: float) -> str:
    mins = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{mins} 分 {secs} 秒"


def format_duration_str(seconds: float) -> str:
    mins = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{mins:02d}:{secs:02d}"


def build_reader(doc_id: str, embed_audio: bool = True) -> Path:
    segments_path = ROOT / "data" / "segments" / f"{doc_id}.json"
    trans_path = ROOT / "data" / "translation" / f"{doc_id}.json"
    script_path = ROOT / "data" / "script" / f"{doc_id}.json"
    ts_path = ROOT / "data" / "audio" / f"{doc_id}_timestamps.json"
    audio_path = ROOT / "data" / "audio" / f"{doc_id}.mp3"

    if not ts_path.exists():
        raise FileNotFoundError(f"找不到时间戳文件: {ts_path}，请先运行 build_audio.py")
    if not audio_path.exists():
        raise FileNotFoundError(f"找不到音频文件: {audio_path}")

    ts_data = json.loads(ts_path.read_text(encoding="utf-8"))
    trans_data = json.loads(trans_path.read_text(encoding="utf-8")) if trans_path.exists() else {}
    script_data = json.loads(script_path.read_text(encoding="utf-8")) if script_path.exists() else {}
    seg_data = json.loads(segments_path.read_text(encoding="utf-8")) if segments_path.exists() else {}

    timeline = ts_data.get("timeline", [])
    title = ts_data.get("title") or doc_id
    voice = ts_data.get("voice", "zh-TW-HsiaoChenNeural")
    total_sec = ts_data.get("total_duration_sec", 0.0)

    # 关键修复：trans_data 的中文键名为 "zh"，兼顾 "translation"
    trans_map = {}
    for sid, item in trans_data.get("segments", {}).items():
        trans_map[sid] = item.get("zh") or item.get("translation") or item.get("zh_raw") or ""

    script_map = {sid: item.get("script", "") for sid, item in script_data.get("segments", {}).items()}
    source_map = {}
    for sec in seg_data.get("sections", []):
        for seg in sec.get("segments", []):
            source_map[seg.get("sid", "")] = seg.get("src_text", "")

    # 1. 组织文章主体 HTML
    content_blocks: list[str] = []
    toc_blocks: list[str] = []
    seen_sections = set()

    for item in timeline:
        sid = item["sid"]
        sec_path = item.get("sec_path", "")
        sec_heading = item.get("sec_heading", "")
        start_sec = item.get("start_sec", 0.0)
        end_sec = item.get("end_sec", 0.0)

        # 章节标题
        if sec_path not in seen_sections:
            seen_sections.add(sec_path)
            content_blocks.append(f'<h2 class="section-title" id="sec-{sec_path}">📌 {sec_heading}</h2>')
            toc_blocks.append(
                f'<div class="toc-item" id="toc-{sec_path}" onclick="jumpToSegment({start_sec}); toggleSidebar();">'
                f'<span>{sec_heading}</span>'
                f'<span style="color: var(--text-muted); font-size: 0.75rem;">{format_duration_str(start_sec)}</span>'
                f'</div>'
            )

        zh_trans = trans_map.get(sid) or item.get("script", "")
        zh_script = script_map.get(sid, item.get("script", ""))
        en_source = source_map.get(sid, "")
        safe_sid_id = sid.replace("#", "_").replace("/", "_")

        # 构建带句级时间戳的口语讲稿 HTML（支持逐句变色与点击单句跳转）
        sentence_spans = []
        for s in item.get("sentences", []):
            s_text = s.get("text", "")
            s_start = s.get("start_sec", 0.0)
            s_end = s.get("end_sec", 0.0)
            sentence_spans.append(
                f'<span class="sentence-span" data-start="{s_start}" data-end="{s_end}" onclick="event.stopPropagation(); jumpToSegment({s_start});">{s_text}</span>'
            )
        zh_script_html = "".join(sentence_spans) if sentence_spans else zh_script

        card_html = f"""
        <div class="segment-card" id="seg-{safe_sid_id}" onclick="jumpToSegment({start_sec})">
          <div class="card-meta">
            <span class="play-tag">▶ {format_duration_str(start_sec)}</span>
            <span>时长 {item.get('duration_sec', 0):.1f}s</span>
          </div>
          <div class="text-zh-trans"><span class="badge-tag">译文</span>{zh_trans}</div>
          <div class="text-zh-script"><span class="badge-tag">讲稿</span>{zh_script_html}</div>
          <div class="text-en-source"><span class="badge-tag">原文</span>{en_source}</div>
        </div>
        """
        content_blocks.append(card_html)


    # 2. 音频源处理 (Base64 内嵌 vs 相对路径)
    if embed_audio:
        print(f"[打包] 正在将 {audio_path.stat().st_size / (1024*1024):.2f} MB 音频内嵌为 Base64...")
        audio_bytes = audio_path.read_bytes()
        b64_audio = base64.b64encode(audio_bytes).decode("ascii")
        audio_src = f"data:audio/mp3;base64,{b64_audio}"
    else:
        audio_src = f"../audio/{doc_id}.mp3"

    # 3. 渲染模板
    html_out = HTML_TEMPLATE
    html_out = html_out.replace("__TITLE__", title)
    html_out = html_out.replace("__TITLE_ESCAPED__", title.replace('"', '\\"'))
    html_out = html_out.replace("__DOC_ID__", doc_id)
    html_out = html_out.replace("__VOICE__", voice)
    html_out = html_out.replace("__DURATION_TEXT__", format_duration(total_sec))
    html_out = html_out.replace("__DURATION_STR__", format_duration_str(total_sec))
    html_out = html_out.replace("__TOTAL_SECONDS__", str(total_sec))
    html_out = html_out.replace("__SEG_COUNT__", str(len(timeline)))
    html_out = html_out.replace("__CONTENT_HTML__", "\n".join(content_blocks))
    html_out = html_out.replace("__TOC_HTML__", "\n".join(toc_blocks))
    html_out = html_out.replace("__TIMELINE_JSON__", json.dumps(timeline, ensure_ascii=False))
    html_out = html_out.replace("__AUDIO_SRC__", audio_src)

    out_dir = ROOT / "data" / "reader"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{doc_id}.html"
    out_file.write_text(html_out, encoding="utf-8")

    print("=" * 76)
    print(f"[完成] 双向伴读网页生成成功！")
    print(f"[文件] {out_file}")
    print(f"[大小] {out_file.stat().st_size / (1024*1024):.2f} MB")
    return out_file


def main() -> int:
    ap = argparse.ArgumentParser(description="生成自包含双向伴读 HTML 网页")
    ap.add_argument("--doc-id", default="s41575-024-00932-1", help="文档 ID")
    ap.add_argument("--no-embed", action="store_true", help="不内嵌音频(改用相对路径引用)")
    args = ap.parse_args()

    build_reader(doc_id=args.doc_id, embed_audio=not args.no_embed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
