"""轨A：逐段忠实翻译（对照译文）。

设计要点
--------
- **段级调度**：每段独立一次调用，独立缓存。这样才能做到"改一个术语只重译相关段"。
- **缓存键只含 prompt_hint 类术语**（见 src/cache.py 的说明）——
  hard_replace 类的改动不进键，因此改它 0 段重译。
- **两类术语都注入 prompt**：hard 类也注入，是为了让 LLM 第一版就产出正确译名；
  改它时靠字符串替换 + 事后"硬替换体检"兜底，所以仍然不需要重译。
- **并发**：默认 4 线程。段与段之间互不依赖，可以安全并发。

产物
----
data/translation/<doc_id>.json   机读（供轨B 与 TTS 使用）
data/translation/<doc_id>.md     人读（供你逐段校对）
"""

from __future__ import annotations

import json
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

from . import prompts
from .cache import Cache, key_for_translation
from .glossary import (
    MODE_HARD, MODE_HINT, Term, apply_hard_replace, hits_for_text,
    render_prompt_block,
)
from .model import Document, Segment
from .providers import Provider
from .textnorm import normalize_zh


@dataclass
class TranslateStats:
    total: int = 0
    from_cache: int = 0
    fresh: int = 0
    failed: list[tuple[str, str]] = field(default_factory=list)

    def line(self) -> str:
        return (f"共 {self.total} 段：缓存命中 {self.from_cache}，新翻译 {self.fresh}，"
                f"失败 {len(self.failed)}")


def _segments_to_do(doc: Document, only: list[str] | None, limit: int | None) -> list[Segment]:
    segs = doc.segments
    if only:
        want = set(only)
        segs = [s for s in segs if s.sid in want or s.sec_path in want
                or s.sec_heading in want]
    if limit:
        segs = segs[:limit]
    return segs


def run_translate(doc: Document, terms: list[Term], provider: Provider, cache: Cache,
                  *, workers: int = 4, only: list[str] | None = None,
                  limit: int | None = None, verbose: bool = True) -> tuple[dict, TranslateStats]:
    segs = _segments_to_do(doc, only, limit)
    stats = TranslateStats(total=len(segs))
    results: dict[str, dict] = {}
    lock = threading.Lock()
    done = 0

    def work(seg: Segment) -> tuple[str, dict | None, str | None]:
        hits = hits_for_text(terms, seg.src_text)
        # 缓存键只放 prompt_hint 命中（hard 类靠字符串替换，不进键 -> 改它 0 段重译）
        hint_hits = [t for t in hits if t.mode == MODE_HINT]
        key = key_for_translation(model_id=f"{provider.name}:{provider.model}",
                                  prompt_version=prompts.TRANSLATE_VERSION,
                                  src_hash=seg.src_hash, hit_terms=hint_hits)
        entry = cache.get(key)
        if entry is not None:
            return seg.sid, {"text": entry.value, "raw": entry.value,
                             "cached": True, "hits": [t.term for t in hits]}, None

        user = prompts.TRANSLATE_USER.format(
            term_block=render_prompt_block(hits) or "（无）",
            src=seg.src_text)
        try:
            raw = provider.complete(prompts.TRANSLATE_SYSTEM, user, temperature=0.25)
        except Exception as e:                       # noqa: BLE001
            return seg.sid, None, f"{type(e).__name__}: {e}"
        text = re.sub(r"\s+\n", "\n", raw).strip()
        cache.put(key, text, {"sid": seg.sid, "src_hash": seg.src_hash,
                              "model": provider.model,
                              "prompt_version": prompts.TRANSLATE_VERSION,
                              "hits": [t.term for t in hits]})
        return seg.sid, {"text": text, "raw": raw, "cached": False,
                         "hits": [t.term for t in hits]}, None

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(work, s): s for s in segs}
        for fut in as_completed(futures):
            sid, payload, err = fut.result()
            with lock:
                done += 1
                if err:
                    stats.failed.append((sid, err))
                else:
                    results[sid] = payload
                    if payload["cached"]:
                        stats.from_cache += 1
                    else:
                        stats.fresh += 1
                if verbose and (done % 10 == 0 or done == len(segs)):
                    print(f"  [{done}/{len(segs)}] 缓存 {stats.from_cache} / 新译 {stats.fresh} "
                          f"/ 失败 {len(stats.failed)}", flush=True)

    # 轨A 的后处理：hard_replace 零成本统一译名 + 数字格式规范化
    # ⚠️ 同时保留**替换前**的原始译文（text_raw）：轨B 的缓存键以它为准，
    #    这样改 hard_replace 术语时轨B 也不会失效（两条轨都免费）。
    for sid, payload in results.items():
        payload["text_raw"] = payload["text"]
        payload["text"] = normalize_zh(apply_hard_replace(terms, payload["text"]))
    return results, stats


# --------------------------------------------------------------- 产物输出

def save_translation(doc: Document, results: dict, provider: Provider,
                     root: str | Path = "data/translation") -> tuple[Path, Path]:
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    payload = {
        "doc_id": doc.doc_id,
        "title": doc.title,
        "provider": provider.name,
        "model": provider.model,
        "prompt_version": prompts.TRANSLATE_VERSION,
        "segments": {
            s.sid: {
                "index": s.index, "sec_path": s.sec_path, "sec_heading": s.sec_heading,
                "page": s.page, "n_words": s.n_words,
                "src": s.src_text,
                "zh": results.get(s.sid, {}).get("text", ""),
                "zh_raw": results.get(s.sid, {}).get("text_raw", ""),
                "cached": results.get(s.sid, {}).get("cached"),
                "hits": results.get(s.sid, {}).get("hits", []),
            }
            for s in doc.segments
        },
    }
    json_path = root / f"{doc.doc_id}.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    md_path = root / f"{doc.doc_id}.md"
    md_path.write_text(_render_md(doc, results), encoding="utf-8")
    return json_path, md_path


def _render_md(doc: Document, results: dict) -> str:
    L = [f"# {doc.title}", "",
         f"> 文档 ID: `{doc.doc_id}` ｜ 段落 ID 就是每段前的 `<!-- sid -->`，"
         f"音频定位与术语替换都以它为锚点。", ""]
    cur_sec = None
    for s in doc.segments:
        if s.sec_path != cur_sec:
            cur_sec = s.sec_path
            # ⚠️ 标题层级 = 节层级 + 1（因为文档标题已占了 `#`）。
            #    初版写成 f"## {'#' * s.sec_level} …" —— 既写死 ## 又叠加 #，
            #    结果渲染成 `## # 标题` / `## ## 标题`，全是错的。
            L += ["", f"{'#' * (s.sec_level + 1)} {s.sec_heading}（p{s.page}）", ""]
        t = results.get(s.sid, {})
        L += [f"<!-- {s.sid} -->", f"**{s.index}.** {t.get('text', '（未翻译）')}", ""]
    return "\n".join(L)


# ------------------------------------------------------- 硬替换体检（省 token 的关键）

def hard_replace_audit(doc: Document, terms: list[Term], results: dict) -> list[str]:
    """检查 hard_replace 术语的"期望译名"是否真的出现在译文里。

    目的：`hard_replace` 的零成本依赖"能命中所列 aliases"。若 LLM 用了别名之外的
    第三种写法，替换就漏了 —— 这个体检把它揪出来，并提示你把观察到的变体补进 aliases。
    """
    hard = [t for t in terms if t.mode == MODE_HARD]
    problems: list[str] = []
    for t in hard:
        hit_segs = [s for s in doc.segments if t.hits(s.src_text)]
        # 只检查**已有译文**的段；未翻译的段不算漏网
        hit_segs = [s for s in hit_segs if results.get(s.sid, {}).get("text")]
        if not hit_segs:
            continue
        missing = [s for s in hit_segs if t.zh not in results[s.sid]["text"]]
        if missing:
            problems.append(
                f"{t.term!r} -> 「{t.zh}」：{len(hit_segs)} 个命中段中有 {len(missing)} 段"
                f"没出现该译名（可能 LLM 用了别名之外的写法）。"
                f"建议打开译文搜一下实际写法，补进 aliases。例：{missing[0].sid}")
    return problems
