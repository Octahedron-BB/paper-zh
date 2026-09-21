"""生成「中英交错」对照文档，用于人工核对译文质量。

为什么要交错而不是双栏同步滚动：
    双栏要解决的是「两份互不相干的文件如何对齐」，而这里的版面是我们自己生成的，
    所以对齐可以直接写进结构里 —— 不存在滚动漂移，也不需要任何 JS。

用法：
    python tools/build_interleave.py --doc-id s41575-024-00932-1
    python tools/build_interleave.py --doc-id vieta2018 --order en   # 英文在前

读的时候：VS Code 里 Ctrl+K V 开侧边预览；用「大纲视图」跳章节。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SEG_ROOT = Path("data/segments")
TR_ROOT = Path("data/translation")


def load(doc_id: str) -> tuple[dict, dict]:
    seg = json.loads((SEG_ROOT / f"{doc_id}.json").read_text(encoding="utf-8"))
    tr = json.loads((TR_ROOT / f"{doc_id}.json").read_text(encoding="utf-8"))
    return seg, tr["segments"]


def render(seg: dict, zh_map: dict, order: str = "zh") -> str:
    """order=zh -> 中文在上、英文在下；order=en -> 反过来。"""
    lines: list[str] = [
        f"# {seg['title']}",
        "",
        f"> 中英对照 ｜ 文档 ID: `{seg['doc_id']}` ｜ 左对齐的数字是段号，"
        f"两侧同一个段号就是同一段。",
        "",
    ]
    missing = 0
    for sec in seg["sections"]:
        # 标题层级 +1：文档标题已占用 `#`
        lines += ["", f"{'#' * (sec['level'] + 1)} {sec['heading']}（p{sec['page']}）", ""]
        for g in sec["segments"]:
            zh = (zh_map.get(g["sid"]) or {}).get("zh", "")
            if not zh:
                missing += 1
                zh = "（未翻译）"
            en = g["src_text"]
            # sid 用 HTML 注释：预览里看不见，但留着当锚点（后续音频定位要用）
            lines.append(f"<!-- {g['sid']} -->")
            zh_line = f"**{g['index']}.** {zh}"
            # 英文用引用块：左边有线、有缩进，读中文时可以整段跳过
            en_block = [f"> {ln}" for ln in en.splitlines()] or ["> "]
            if order == "en":
                lines += en_block + [""] + [zh_line, ""]
            else:
                lines += [zh_line, ""] + en_block + [""]
    text = "\n".join(lines).rstrip() + "\n"
    if missing:
        print(f"  ⚠️ 有 {missing} 段没有译文，已用（未翻译）占位")
    return text


CSS = """\
/* 中英对照阅读的可选样式。
   启用方式：仓库里的 .vscode/settings.json 已经配好了，一般不用管。
   手动启用就在 VS Code settings.json 里加：
     "markdown.styles": ["data/interleave/reader.css"]        // 相对工作区根，跨平台
   （VS Code 的 markdown.styles 支持相对工作区根的路径，所以不必写死绝对路径）

   作用：把英文原文压小、变灰，读中文时它几乎不干扰视线；鼠标悬停才变深，方便核对。
   ⚠️ 选择器直接写 `blockquote`，不依赖 VS Code 预览容器的 class 名（那个名字改过几次）。
      代价：文档顶部那句说明也是引用块，会一起变小 —— 无害。 */

blockquote {
  font-size: 0.82em;
  color: #8a8a8a;
  border-left: 2px solid #d8d8d8;
  margin: 0.2em 0 1em 0;
  padding: 0.1em 0 0.1em 0.7em;
  transition: color 0.15s ease, border-color 0.15s ease;
}

blockquote:hover {
  color: #333333;
  border-left-color: #8a8a8a;
}
"""


def run_build_interleave(doc_id: str, order: str = "zh", out_dir: Path | None = None) -> Path:
    seg, zh_map = load(doc_id)
    n = sum(len(s["segments"]) for s in seg["sections"])
    text = render(seg, zh_map, order)

    out = out_dir or (Path(__file__).resolve().parent.parent / "data" / "interleave")
    out.mkdir(parents=True, exist_ok=True)
    md = out / f"{doc_id}.md"
    md.write_text(text, encoding="utf-8")
    (out / "reader.css").write_text(CSS, encoding="utf-8")

    zh_total = sum(len((zh_map.get(g["sid"]) or {}).get("zh", ""))
                   for s in seg["sections"] for g in s["segments"])
    print(f"[中英对照] {md.relative_to(Path(__file__).resolve().parent.parent)} ｜ {len(seg['sections'])} 节 / {n} 段 / 中文 {zh_total} 字")
    return md


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--doc-id", required=True)
    ap.add_argument("--order", choices=("zh", "en"), default="zh",
                    help="哪一侧在前（默认 zh：中文在上，英文在下）")
    ap.add_argument("--out", default="data/interleave")
    args = ap.parse_args()

    run_build_interleave(args.doc_id, args.order, Path(args.out))
    return 0


def report_density(seg: dict, zh_map: dict) -> None:
    """估算「一个中英配对」要占多少行 —— 用来回答「交错会不会太冗杂」。

    行数用经验折换：中文按每行 46 字（预览面板约 700px 宽、16px 字号），
    英文按每行 88 字符。只是个相对参考，不是精确值。
    """
    pairs = []
    for s in seg["sections"]:
        for g in s["segments"]:
            zh = (zh_map.get(g["sid"]) or {}).get("zh", "")
            pairs.append((len(zh) / 46.0, len(g["src_text"]) / 88.0))
    if not pairs:
        return
    total = [z + e for z, e in pairs]
    total.sort()
    med = total[len(total) // 2]
    over = sum(1 for t in total if t > 30)   # 约一屏
    print(f"       视觉密度: 每个中英配对 中位 {med:.0f} 行 "
          f"(最小 {total[0]:.0f} / 最大 {total[-1]:.0f})；"
          f"超过一屏(≈30行)的有 {over}/{len(total)} 段")


if __name__ == "__main__":
    raise SystemExit(main())
