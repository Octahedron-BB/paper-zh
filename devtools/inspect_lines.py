"""新期刊排错的第一把工具：把 PDF 的每一行按版面分析结果打印出来。

为什么单独留这一个：调试期我写了 40 多个探针脚本，但它们几乎都只针对某一篇
PDF 的某一个问题，换一篇就没用了。真正反复被用到的能力只有一个 ——
**"这一行文字，被当成什么了？为什么？"** 这个脚本把它固化了。

换新期刊时，如果分段结果不对，标准动作是：
    1) 先跑 `tools/batch_segment.py` 看整体健康度
    2) 再跑来这个脚本，`--grep` 定位出问题的那一行，看它的 kind / 字号 / 字体 / 列
    3) 对照 `src/segment.py` 的 `_classify()`，就知道是哪条规则判错了

用法：
    python devtools/inspect_lines.py papers/xxx.pdf                  # 概览：版面推断 + 各 kind 计数
    python devtools/inspect_lines.py papers/xxx.pdf --page 4         # 只看第 4 页
    python devtools/inspect_lines.py papers/xxx.pdf --grep "n ="     # 只看含该串的行
    python devtools/inspect_lines.py papers/xxx.pdf --grep "Anal cancer" --around 2
    python devtools/inspect_lines.py papers/xxx.pdf --kind runin,h1,h2
    python devtools/inspect_lines.py papers/xxx.pdf --json           # 供程序消费

⚠️ 它直接调用 `src.segment` 的私有函数（`_gather` / `_detect_layout` / `_classify`）。
   这是故意的：探针要看的正是"内部判定过程"，而不是公开 API 的结果。
   如果以后重构了这些私有函数，这个脚本要跟着改。
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pymupdf  # noqa: E402

from src import segment as S  # noqa: E402


def analyse(pdf: Path):
    doc = pymupdf.open(pdf)
    width = max(doc[i].rect.width for i in range(doc.page_count))
    lines = S._gather(doc, S._region_rects(doc))
    layout = S._detect_layout(lines, width)
    S._classify(lines, layout)
    return doc, S._reorder(lines, layout), layout


def main() -> int:
    ap = argparse.ArgumentParser(description="按版面分析结果逐行打印 PDF（排错用）")
    ap.add_argument("pdf", help="PDF 路径")
    ap.add_argument("--page", type=int, default=None, help="只看这一页（1 起）")
    ap.add_argument("--grep", default=None, help="只看含该子串的行（不区分大小写）")
    ap.add_argument("--around", type=int, default=0, help="grep 命中时额外打印前后 N 行")
    ap.add_argument("--kind", default=None, help="只看这些 kind（逗号分隔），如 body,runin,h1,h2")
    ap.add_argument("--col", type=int, default=None, help="只看这一栏")
    ap.add_argument("--json", action="store_true", help="输出 JSON（供程序消费）")
    args = ap.parse_args()

    pdf = Path(args.pdf)
    if not pdf.exists() and not pdf.is_absolute():
        cand = ROOT / pdf
        pdf = cand if cand.exists() else ROOT / "papers" / Path(args.pdf).name
    doc, ordered, layout = analyse(pdf)

    print(f"[PDF] {pdf}")
    print(f"[版面] 正文号号={layout.body_size}  正文字体={layout.body_font}  "
          f"栏数={layout.n_columns}  栏基线={[round(x, 1) for x in layout.columns]}  "
          f"分界x={round(layout.split_x, 1)}")
    print(f"[kind 分布] {dict(Counter(L.kind for L in ordered).most_common())}")
    print("-" * 100)

    keep = set(args.kind.split(",")) if args.kind else None
    rows = []
    for L in ordered:
        if args.page and L.page + 1 != args.page:
            continue
        if keep and L.kind not in keep:
            continue
        if args.col is not None and L.col != args.col:
            continue
        rows.append(L)

    if args.grep:
        needle = args.grep.lower()
        idx = [i for i, L in enumerate(rows) if needle in L.raw.lower()]
        sel: list[int] = []
        for i in idx:
            sel += list(range(max(0, i - args.around), i + args.around + 1))
        sel = sorted(set(sel))
        print(f"[grep] {args.grep!r} 命中 {len(idx)} 行（含上下文共 {len(sel)} 行）")
        rows = [rows[i] for i in sel]
    elif args.around:
        print("提示：--around 只在配合 --grep 时才有意义")

    if args.json:
        print(json.dumps([
            {"page": L.page + 1, "col": L.col, "y": L.y0, "x0": L.x0,
             "size": max(L.sizes) if L.sizes else None,
             "font": L.dominant_font(), "kind": L.kind,
             "in_rect": L.in_rect, "in_region": L.in_region,
             "bold": L.bold, "all_bold": L.all_bold, "text": L.raw}
            for L in rows], ensure_ascii=False, indent=1))
        return 0

    for L in rows:
        sz = max(L.sizes) if L.sizes else 0.0
        flag = ""
        if L.in_rect:
            flag += "R"          # 中心落在某个矩形里
        if L.in_region:
            flag += "X"          # 因此被判为 region（排除）
        print(f"p{L.page + 1:>3} c{L.col} y={L.y0:6.1f} x0={L.x0:6.1f} "
              f"sz={sz:4.1f} {L.dominant_font()[:20]:20} {L.kind:7} {flag:2} "
              f"{L.raw[:76]!r}")
    print("-" * 100)
    print(f"共 {len(rows)} 行")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
