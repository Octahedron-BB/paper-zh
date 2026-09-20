"""轨B：口语讲解稿（供听）。

为什么需要它
------------
"听着舒服"和"能查证"本质冲突：忠实译文念出来是念稿，播客化又会丢信息。
分层是唯一解 —— 轨A 负责忠实（供看、供查证），轨B 负责好听（供听）。

最大风险与自动防线
------------------
轨B 最大的失败模式不是"不像人话"，而是**LLM 偷偷概括掉内容**。
人耳很难发现漏掉了什么，因为听起来更顺了。
所以本模块加了一道**信息保全率**检查：
    保全率 = len(讲稿) / len(译文)
低于阈值（默认 0.80）就标记出来，让你优先复核这些段。
这不是完美指标，但能抓住最常见的一种失败。
"""

from __future__ import annotations

import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

from . import prompts
from .cache import Cache, key_for_script
from .glossary import Term, apply_hard_replace, hits_for_text, render_prompt_block
from .model import Document
from .providers import Provider
from .textnorm import normalize_zh

STYLE_ID = "spoken-v1"
MIN_PRESERVE_RATIO = 0.80


@dataclass
class ScriptStats:
    total: int = 0
    from_cache: int = 0
    fresh: int = 0
    failed: list[tuple[str, str]] = field(default_factory=list)
    low_preserve: list[tuple[str, float]] = field(default_factory=list)

    def line(self) -> str:
        s = (f"共 {self.total} 段：缓存命中 {self.from_cache}，新生成 {self.fresh}，"
             f"失败 {len(self.failed)}")
        if self.low_preserve:
            s += f"；⚠️ 保全率偏低 {len(self.low_preserve)} 段"
        return s


def run_rewrite(doc: Document, translated: dict, terms: list[Term], provider: Provider,
                cache: Cache, *, workers: int = 4, limit: int | None = None,
                verbose: bool = True) -> tuple[dict, ScriptStats]:
    segs = doc.segments
    if limit:
        segs = segs[:limit]
    stats = ScriptStats(total=len(segs))
    results: dict[str, dict] = {}
    lock = threading.Lock()
    done = 0
    model_id = f"{provider.name}:{provider.model}"

    def work(seg):
        # ⚠️ 用**替换前**的原始译文（text_raw）作输入与缓存键。
        # 这样改 hard_replace 术语时，轨A 和轨B 都无需重跑（两条轨都免费）。
        rec = translated.get(seg.sid, {})
        zh = (rec.get("text_raw") or rec.get("text", "")).strip()
        if not zh:
            return seg.sid, None, "轨A 尚无该段译文"
        hits = hits_for_text(terms, seg.src_text)
        key = key_for_script(model_id=model_id, prompt_version=prompts.SCRIPT_VERSION,
                             translated=zh, style_id=STYLE_ID)
        entry = cache.get(key)
        if entry is not None:
            return seg.sid, {"text": entry.value, "cached": True}, None

        user = prompts.SCRIPT_USER.format(
            section=seg.sec_heading,
            term_block=render_prompt_block(hits) or "（无）",
            translated=zh)
        try:
            raw = provider.complete(prompts.SCRIPT_SYSTEM, user, temperature=0.6)
        except Exception as e:                       # noqa: BLE001
            return seg.sid, None, f"{type(e).__name__}: {e}"
        text = raw.strip()
        cache.put(key, text, {"sid": seg.sid, "style": STYLE_ID, "model": provider.model,
                              "prompt_version": prompts.SCRIPT_VERSION})
        return seg.sid, {"text": text, "cached": False, "source": zh}, None
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(work, s): s for s in segs}
        for fut in as_completed(futures):
            sid, payload, err = fut.result()
            with lock:
                done += 1
                if err:
                    stats.failed.append((sid, err))
                else:
                    if payload["cached"] and "source" not in payload:
                        rec = translated.get(sid, {})
                        payload["source"] = (rec.get("text_raw") or rec.get("text", ""))
                    # 讲稿也做同一套零成本硬替换（歧义/别名统一），保持两条轨术语一致
                    payload["text"] = normalize_zh(
                        apply_hard_replace(terms, payload["text"]))
                    ratio = (len(payload["text"]) / max(len(payload.get("source", "")), 1))
                    payload["preserve_ratio"] = round(ratio, 3)
                    if ratio < MIN_PRESERVE_RATIO:
                        stats.low_preserve.append((sid, round(ratio, 3)))
                    results[sid] = payload
                    if payload["cached"]:
                        stats.from_cache += 1
                    else:
                        stats.fresh += 1
                if verbose and (done % 10 == 0 or done == len(segs)):
                    print(f"  [{done}/{len(segs)}] 缓存 {stats.from_cache} / 新生成 "
                          f"{stats.fresh} / 失败 {len(stats.failed)}", flush=True)
    return results, stats


def save_script(doc: Document, results: dict, provider: Provider,
                root: str | Path = "data/script") -> tuple[Path, Path]:
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    payload = {
        "doc_id": doc.doc_id,
        "title": doc.title,
        "provider": provider.name,
        "model": provider.model,
        "prompt_version": prompts.SCRIPT_VERSION,
        "style": STYLE_ID,
        "segments": {
            s.sid: {
                "index": s.index, "sec_path": s.sec_path, "sec_heading": s.sec_heading,
                "page": s.page,
                "script": results.get(s.sid, {}).get("text", ""),
                "preserve_ratio": results.get(s.sid, {}).get("preserve_ratio"),
            }
            for s in doc.segments
        },
    }
    json_path = root / f"{doc.doc_id}.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    md_path = root / f"{doc.doc_id}.md"
    L = [f"# 讲稿：{doc.title}", ""]
    cur = None
    for s in doc.segments:
        if s.sec_path != cur:
            cur = s.sec_path
            # 与轨A 一致：节层级 + 1（文档标题已占 `#`）
            L += ["", f"{'#' * (s.sec_level + 1)} {s.sec_heading}（p{s.page}）", ""]
        L += [f"<!-- {s.sid} -->",
              f"**{s.index}.** {results.get(s.sid, {}).get('text', '（未生成）')}", ""]
    md_path.write_text("\n".join(L), encoding="utf-8")
    return json_path, md_path
