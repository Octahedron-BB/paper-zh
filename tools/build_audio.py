"""音频合成流水线：口语讲稿 -> 文本规范化 -> 分段 TTS -> 音频拼接与精确时间戳生成。

特性：
- 基于 edge-tts，支持高质量中文播客与新闻音色（如 zh-TW-HsiaoChenNeural / zh-CN-YunxiNeural）
- 文本预处理（TN）：自动将医学大写缩写（如 RAI -> R-A-I, HPV -> H-P-V）转为连读，避免误读为单词
- 微调参数：支持 --rate (语速) 与 --pitch (音调)
- 段级缓存：单段规范化文本 + 音色 + 语速 + 音调不变 => 0 重复生成
- 毫秒级时间戳：输出 JSON、LRC（歌词/字幕）与 WebVTT（HTML5 网页播放器专用）
- 自动拼接并插入段间微静音（Silence Padding）防止听感突兀
- 支持 --limit N 试水与 --only 指定段落
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import edge_tts  # noqa: E402
from src.polyphone import load_polyphone_rules, apply_polyphone_rules  # noqa: E402

DEFAULT_VOICE = "zh-TW-HsiaoChenNeural"
AUDIO_DIR = ROOT / "data" / "audio"


def normalize_script_for_tts(
    text: str,
    poly_rules: Sequence[tuple[str, str]] | None = None,
) -> str:
    """文本预处理规范化（专为 TTS 发音优化）

    1. 将 2~6 位大写英文缩写转为单字母连读（如 RAI -> R-A-I，DGBI -> D-G-B-I）
    2. 应用多音字/专有词发音清洗词典（如 黏膜 -> 粘膜, 栓塞 -> 栓色）
    3. 去除多余的重复符号与不规范空格
    """
    if not text:
        return ""

    # 1. 大写字母缩写处理：RAI -> R-A-I (防止被读成单一单词)
    def _abbr_repl(match: re.Match) -> str:
        word = match.group(1)
        return "-".join(list(word))

    # 匹配 2~6 个连续大写字母（前后非字母）
    text = re.sub(r"(?<![A-Za-z0-9\-])([A-Z]{2,6})(?![A-Za-z0-9\-])", _abbr_repl, text)

    # 2. 多音字与发音清洗词典替换
    if poly_rules:
        text = apply_polyphone_rules(text, poly_rules)

    # 3. 标点和空格轻量清理
    text = re.sub(r"[ \t]+", " ", text)
    text = text.replace("——", "，").replace("……", "。")
    return text.strip()


def align_sentences_with_raw(raw_text: str, tts_sentences: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """将 TTS 返回的句子边界对齐回未被发音替换修改的原始 raw_text，确保界面显示纯正专业。"""
    if not tts_sentences or not raw_text:
        return tts_sentences

    pattern = r'([^。！？；\n]+[。！？；\n]*)'
    raw_splits = [s for s in re.findall(pattern, raw_text) if s.strip()]

    if len(raw_splits) == len(tts_sentences):
        aligned = []
        for raw_s, tts_s in zip(raw_splits, tts_sentences):
            aligned.append({
                "text": raw_s,
                "start": tts_s["start"],
                "end": tts_s["end"],
                "duration": tts_s.get("duration", 0.0),
            })
        return aligned

    return tts_sentences


def format_lrc_time(seconds: float) -> str:
    """转换秒数为 LRC 标准格式 [mm:ss.xx]"""
    mins = int(seconds // 60)
    secs = seconds % 60
    return f"[{mins:02d}:{secs:05.2f}]"


def format_vtt_time(seconds: float) -> str:
    """转换秒数为 WebVTT 标准格式 hh:mm:ss.mmm"""
    hours = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours:02d}:{mins:02d}:{secs:06.3f}"


def get_mp3_duration(path: Path) -> float:
    """获取 MP3 文件的精确比特流时长（秒）"""
    if sys.platform == "darwin":
        try:
            import subprocess
            res = subprocess.run(["afinfo", str(path)], capture_output=True, text=True)
            for line in res.stdout.splitlines():
                if "estimated duration:" in line:
                    return float(line.split("estimated duration:")[1].split("sec")[0].strip())
        except Exception:
            pass
    # 纯 Python 帧解析作为跨平台兜底（Edge-TTS 24kHz 48kbps: 每帧 144 字节 = 24ms）
    size = path.stat().st_size
    return round((size / 144.0) * 0.024, 4)


def generate_silence_mp3_frame(duration_ms: int = 300) -> tuple[bytes, float]:
    """生成与 Edge-TTS 完全匹配的 24kHz 48kbps MPEG-2 Layer 3 静音帧"""
    # 每帧 144 字节 = 24ms
    frame = b"\xff\xf3\x64\xc4" + b"\x00" * 140
    n_frames = max(1, round(duration_ms / 24.0))
    exact_sec = round(n_frames * 0.024, 4)
    return frame * n_frames, exact_sec


async def synthesize_segment(
    sid: str,
    raw_text: str,
    voice: str,
    rate: str,
    pitch: str,
    out_mp3: Path,
    out_meta: Path,
    poly_rules: Sequence[tuple[str, str]] | None = None,
) -> dict[str, Any]:
    """合成单段音频并提取句子级时间边界"""
    norm_text = normalize_script_for_tts(raw_text, poly_rules=poly_rules)

    if out_mp3.exists() and out_meta.exists():
        try:
            cached_meta = json.loads(out_meta.read_text(encoding="utf-8"))
            if (
                cached_meta.get("norm_text") == norm_text
                and cached_meta.get("voice") == voice
                and cached_meta.get("rate") == rate
                and cached_meta.get("pitch") == pitch
            ):
                return cached_meta
        except Exception:
            pass

    out_mp3.parent.mkdir(parents=True, exist_ok=True)
    out_meta.parent.mkdir(parents=True, exist_ok=True)

    communicate = edge_tts.Communicate(norm_text, voice, rate=rate, pitch=pitch)
    audio_data = bytearray()
    raw_sentences = []

    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_data.extend(chunk["data"])
        elif chunk["type"] == "SentenceBoundary":
            offset_sec = chunk["offset"] / 10_000_000.0
            duration_sec = chunk["duration"] / 10_000_000.0
            raw_sentences.append({
                "text": chunk["text"],
                "start": round(offset_sec, 3),
                "end": round(offset_sec + duration_sec, 3),
                "duration": round(duration_sec, 3),
            })

    # 将返回的句子切片映射回未被同音字替换修改的原始文本
    sentences = align_sentences_with_raw(raw_text, raw_sentences)

    out_mp3.write_bytes(audio_data)
    exact_duration = get_mp3_duration(out_mp3)

    meta = {
        "sid": sid,
        "voice": voice,
        "rate": rate,
        "pitch": pitch,
        "raw_text": raw_text,
        "norm_text": norm_text,
        "duration_sec": exact_duration,
        "sentences": sentences,
        "bytes": len(audio_data),
    }
    out_meta.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


async def run_audio_pipeline(
    doc_id: str,
    voice: str = DEFAULT_VOICE,
    rate: str = "+0%",
    pitch: str = "+0Hz",
    silence_ms: int = 300,
    limit: int | None = None,
    only: list[str] | None = None,
) -> dict[str, Any]:
    script_path = ROOT / "data" / "script" / f"{doc_id}.json"
    if not script_path.exists():
        raise FileNotFoundError(f"找不到讲稿文件: {script_path}，请先运行 run_pipeline.py 生成讲稿")

    script_data = json.loads(script_path.read_text(encoding="utf-8"))
    segments = script_data.get("segments", {})
    if not segments:
        raise ValueError(f"{script_path} 中没有段落数据")

    doc_audio_dir = AUDIO_DIR / doc_id
    seg_dir = doc_audio_dir / "segments"
    seg_dir.mkdir(parents=True, exist_ok=True)

    items = list(segments.items())
    if only:
        items = [it for it in items if any(o in it[0] for o in only)]
    if limit:
        items = items[:limit]

    print("=" * 76)
    print(f"[音频合成] 文档={doc_id}  音色={voice}  语速={rate}  音调={pitch}")
    print(f"[段落数量] 共 {len(items)} 段待处理")

    poly_rules = load_polyphone_rules(doc_id=doc_id)
    if poly_rules:
        print(f"[发音清洗] 已加载 {len(poly_rules)} 条多音字/专有词发音修正规则")

    timeline: list[dict[str, Any]] = []
    combined_audio = bytearray()
    silence_bytes, silence_sec = generate_silence_mp3_frame(silence_ms) if silence_ms > 0 else (b"", 0.0)
    current_time = 0.0

    sem = asyncio.Semaphore(6)

    async def _worker(item_idx: int, sid: str, seg_info: dict[str, Any]):
        raw_text = seg_info.get("script", "").strip()
        safe_sid = sid.replace("#", "_").replace("/", "_")
        mp3_path = seg_dir / f"{safe_sid}.mp3"
        meta_path = seg_dir / f"{safe_sid}.json"
        async with sem:
            meta = await synthesize_segment(sid, raw_text, voice, rate, pitch, mp3_path, meta_path, poly_rules=poly_rules)
            return item_idx, sid, seg_info, meta, mp3_path

    print(f"--- 并行合成中 (并发 6) ---")
    tasks = [_worker(i, sid, info) for i, (sid, info) in enumerate(items)]
    results = await asyncio.gather(*tasks)

    # 按照原始顺序排序并拼接
    results.sort(key=lambda r: r[0])

    for item_idx, sid, seg_info, meta, mp3_path in results:
        raw_text = seg_info.get("script", "").strip()
        seg_duration = get_mp3_duration(mp3_path)
        seg_bytes = mp3_path.read_bytes()

        start_time = current_time
        end_time = current_time + seg_duration

        timeline.append({
            "sid": sid,
            "sec_path": seg_info.get("sec_path", ""),
            "sec_heading": seg_info.get("sec_heading", ""),
            "page": seg_info.get("page", 1),
            "script": raw_text,
            "norm_script": meta["norm_text"],
            "start_sec": round(start_time, 3),
            "end_sec": round(end_time, 3),
            "duration_sec": round(seg_duration, 3),
            "sentences": [
                {
                    "text": s["text"],
                    "start_sec": round(start_time + s["start"], 3),
                    "end_sec": round(start_time + s["end"], 3),
                }
                for s in meta.get("sentences", [])
            ],
        })

        combined_audio.extend(seg_bytes)
        if silence_bytes and (item_idx + 1) < len(results):
            combined_audio.extend(silence_bytes)
            current_time = end_time + silence_sec
        else:
            current_time = end_time

        if (item_idx + 1) % 10 == 0 or (item_idx + 1) == len(results):
            print(f"  [{item_idx+1:03d}/{len(results):03d}] 累计时长 {current_time/60:4.1f} 分钟 ({current_time:5.1f}s)")



    # 1. 保存完整 MP3
    out_full_mp3 = AUDIO_DIR / f"{doc_id}.mp3" if not limit else AUDIO_DIR / f"{doc_id}_sample_{len(items)}.mp3"
    out_full_mp3.write_bytes(combined_audio)

    # 2. 保存时间戳 JSON (用于播放器/编辑器精确双向跳转)
    out_timestamps = AUDIO_DIR / f"{doc_id}_timestamps.json"
    ts_payload = {
        "doc_id": doc_id,
        "title": script_data.get("title", ""),
        "voice": voice,
        "rate": rate,
        "pitch": pitch,
        "total_duration_sec": round(current_time, 3),
        "total_segments": len(timeline),
        "timeline": timeline,
    }
    out_timestamps.write_text(json.dumps(ts_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # 3. 保存 LRC 标准歌词字幕文件
    out_lrc = AUDIO_DIR / f"{doc_id}.lrc"
    lrc_lines = [
        f"[ti:{script_data.get('title', '')[:50]}]",
        f"[al:Nature Reviews 中文伴读]",
        f"[by:paper-zh]",
    ]
    for item in timeline:
        lrc_lines.append(f"{format_lrc_time(item['start_sec'])}【{item['sec_heading']}】{item['script']}")
    out_lrc.write_text("\n".join(lrc_lines), encoding="utf-8")

    # 4. 保存 WebVTT 文件
    out_vtt = AUDIO_DIR / f"{doc_id}.vtt"
    vtt_lines = ["WEBVTT", ""]
    for i, item in enumerate(timeline, 1):
        vtt_lines.append(f"{i}")
        vtt_lines.append(f"{format_vtt_time(item['start_sec'])} --> {format_vtt_time(item['end_sec'])}")
        vtt_lines.append(f"<b>[{item['sec_heading']}]</b> {item['script']}")
        vtt_lines.append("")
    out_vtt.write_text("\n".join(vtt_lines), encoding="utf-8")

    print("=" * 76)
    print(f"[完成] 总时长: {current_time/60:.2f} 分钟 ({current_time:.1f} 秒)")
    print(f"[音频] {out_full_mp3}")
    print(f"[时间戳] {out_timestamps}")
    print(f"[LRC/VTT] {out_lrc} | {out_vtt}")
    return ts_payload


def main() -> int:
    ap = argparse.ArgumentParser(description="生成讲稿音频与双向定位时间戳")
    ap.add_argument("--doc-id", default="s41575-024-00932-1", help="文档 ID")
    ap.add_argument("--voice", default=DEFAULT_VOICE, help="edge-tts 语音名称")
    ap.add_argument("--rate", default="+0%", help="语速微调，如 +5% / -5%")
    ap.add_argument("--pitch", default="+0Hz", help="音调微调，如 +2Hz / -2Hz")
    ap.add_argument("--silence", type=int, default=300, help="段落间静音时长(ms)")
    ap.add_argument("--limit", type=int, default=None, help="只处理前 N 段（试水用）")
    ap.add_argument("--only", nargs="*", default=None, help="只处理指定 sid")
    args = ap.parse_args()

    asyncio.run(run_audio_pipeline(
        doc_id=args.doc_id,
        voice=args.voice,
        rate=args.rate,
        pitch=args.pitch,
        silence_ms=args.silence,
        limit=args.limit,
        only=args.only,
    ))
    return 0


if __name__ == "__main__":
    sys.exit(main())
