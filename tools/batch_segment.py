"""跨期刊批量体检：版式规则能不能迁移到别的 Nature Reviews 子刊。

用户关注点：新放进来的 3 篇 + 1 个旧文件，用同一套切分规则效果如何。
本脚本只做诊断、不修改任何东西，重点看四件事：
  1. 正文字号是否被正确识别（跨期刊会不会认错）
  2. 栏结构（x0 簇）—— 当前代码把 COL_SPLIT_X 硬编码成 250，单栏/三栏会翻车
  3. 章节标题能不能认出来
  4. 段落粒度是否合理（段落数、每段词数、最长段）

跑法：python tools/batch_segment.py
"""

from __future__ import annotations

import re
import sys
import traceback
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from src.model import slug  # noqa: E402
from src import segment as S  # noqa: E402
import pymupdf  # noqa: E402


def analyze(pdf: Path) -> None:
    print("=" * 82)
    print(f"■ {pdf.name}  ({pdf.stat().st_size / 1e6:.2f} MB)")
    try:
        doc = pymupdf.open(pdf)
        i = min(3, doc.page_count - 1)
        r = doc[i].rect
        print(f"  页数 {doc.page_count} | 页面 {r.width:.0f}x{r.height:.0f}pt")

        regions = S._region_rects(doc)
        lines = S._gather(doc, regions)
        pw = max(doc[i].rect.width for i in range(doc.page_count))
        layout = S._detect_layout(lines, pw)
        S._classify(lines, layout)
        kinds = Counter(L.kind for L in lines)

        print(f"  推断 Layout: 正文字号={layout.body_size}  栏数={layout.n_columns}  "
              f"栏基线={[round(c, 1) for c in layout.columns]}  分界x={layout.split_x:.0f}")
        print(f"  kind 分布 = {dict(kinds.most_common(9))}")

        d = S.segment_pdf(pdf)
        st = d.stats()
        h1 = [s.heading for s in d.sections if s.level == 1]
        print(f"  标题: {d.title[:70]!r}")
        print(f"  切分结果: {st['sections']} 节 / {st['segments']} 段 / {st['words']:,} 词 "
              f"(中位 {st['words_median']} 词/段, 最长 {st['words_max']})")

        # 合理性质疑
        warns = []
        if st["segments"] < 20:
            warns.append(f"段落数偏少({st['segments']}) —— 可能被合并了")
        if st["words_max"] > 600:
            warns.append(f"最长段 {st['words_max']} 词 —— 段边界可能没切开")
        if len([h for h in h1 if h]) < 3:
            warns.append(f"一级标题只有 {len(h1)} 个 —— 可能没识别出章节")
        weird = [h for h in h1 if len(h) < 4 or h.lower().startswith(("fig", "table"))]
        if weird:
            warns.append(f"可疑标题: {weird[:5]}")

        allp = d.segments
        bad_start = [s for s in allp if s.src_text[:1].islower()]
        bad_end = [s for s in allp
                   if not s.src_text.rstrip('"\u2019\u201d)').endswith((".", "?", "!", ":"))]
        clean = 1 - (len(bad_start) + len(bad_end)) / max(2 * len(allp), 1)
        print(f"  段落体检: 干净率 {clean:.0%}  小写开头 {len(bad_start)}  无终止标点 {len(bad_end)}")
        for s in (bad_start + bad_end)[:3]:
            print(f"      可疑: {s.src_text[:80]}")

        print(f"  一级节: {h1[:12]}")
        print(f"  二级节: {[s.heading for s in d.sections if s.level == 2][:8]}")
        print(f"  三级(run-in): {[s.heading for s in d.sections if s.level == 3][:6]}")
        if warns:
            print("  ⚠️ " + "\n  ⚠️ ".join(warns))
        else:
            print("  ✅ 未见明显异常")
    except Exception as e:  # noqa: BLE001
        print(f"  ❌ 抛异常: {type(e).__name__}: {e}")
        print("     " + traceback.format_exc().replace("\n", "\n     ")[:700])


def main() -> None:
    pdfs = sorted(ROOT.glob("papers/*.pdf"))
    print(f"共 {len(pdfs)} 个 PDF\n")
    for p in pdfs:
        analyze(p)


if __name__ == "__main__":
    main()
