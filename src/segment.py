"""PDF -> Document（把 scratch/segment_v5.py 的实验固化为正式模块）。

版式规则（实测于 Nature Reviews，可迁移到别的期刊靠下面三条，而不是写死字体名）
  1. 正文基准字号 = 字符数加权众数（先排除图表小字与方框区域）
  2. 标题层级 = 加粗 + 字号分层（>基准*1.25 为一级，区间内为二级）+ 左端对齐栏基线
  3. 段落边界 = 行首缩进（主信号）+ 局部右边界是否顶满（辅信号，处理跨栏/跨页续接）
     ⚠️ 该版式**段间没有额外行距**（行距恒定），所以"按空行切段落"必然失败。
  另有三条兜底：
  - 方框/图片区域用**矩形检测**整块排除（Box / Glossary 等，用户已确认不处理）
  - run-in 标题（段首加粗短语 + 同段正文）用 **span 结构**精确切，不用正则猜句号
  - 本行以小写开头且上一行未以终止标点收尾 => 必定是上段的续
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from .model import Document, Section, Segment, make_sid, slug

# ⚠️ **改了切分逻辑就必须递增这个版本号**，否则 data/segments.json 会被当成
#    仍然有效而直接复用（实测就撞过这个坑：改了规则但结果没变，因为读的是旧缓存）。
SEGMENTER_VERSION = "seg-v13-runinwrap"
BODY_MIN_SHARE = 0.15       # 候选字号至少要占这么多字符份额

# ---- 全部改成数据驱动，不再写死字号区间与栏基线 ----
BODY_TOL = 0.7              # 正文字号容差（相对基准字号）
HEADING_MIN_FACTOR = 1.25   # 一级标题 = 加粗且 > 基准 * 此系数
INDENT_MIN = 8.0            # 首行缩进的最小偏移（pt）
RIGHT_TOL = 12.0            # 行右端“顶满”判定的容差
WINDOW = 5                  # 局部右边界的滚动窗口半径（行）
MIN_WIN = 5
REGION_MIN_W, REGION_MIN_H = 110.0, 70.0
REGION_MIN_W, REGION_MIN_H = 110.0, 70.0
# ⚠️ 这里踩过一个两难，值得记下来：
#   靠“面积阈值”区分不了「内容框（要排除）」与「页面装饰背景（不能排除，
#   否则会把整页正文吃掉）」：NRN 的 Box 占页 43%~54%，
#   s41574 的装饰背景占页 50%~59%，面积区间完全重叠。
#   真正的判据是**框内文字是不是正文字体**：
#     NRN Box 内是无衬线 GraphikNaturel，正文是衬线 HardingText -> 排除
#     s41574 背景框内就是正文 MinionPro 本身 -> 不排除
#   所以面积只做一个 95% 的兜底（防整页填色）。
REGION_MAX_AREA = 0.95
SKIP_STRINGS = {"nature reviews neuroscience", "review article"}
LABEL_STRINGS = {"glossary", "key points", "outstanding questions", "sections",
                 "supplementary information", "author information"}
PROSE_MIN_LEN = 50          # 用于推断正文字号的“长行”阈值
PROSE_SIZE_TOL = 0.35       # 筛“正文候选行”的字号容差（必须比 BODY_TOL 更严）
# 页首的**刊物名 / 文章类型标签**，它们不是文章标题，不能拼进 title
# （实测：s41575 的 title 混进了 “nature reviews gastroenterology & hepatology”，
#   s41574 的 title 直接变成了 “Reviews”）
TITLE_SKIP_RE = re.compile(
    r"^(nature reviews|nature\b|reviews?\b|primer|perspective|comment|news|"
    r"review article|article|editorial|correspondence|check for updates)",
    re.IGNORECASE)
# 图注/表注："Fig. 3 | …" / "Figure 1 | …" / "Table 1 | …" / "Box 1 | …"
FIG_CAPTION_RE = re.compile(r"^(Fig\.|Figure|Table|Box|Extended Data)\s*\d", re.IGNORECASE)
# 标题尾部粘上的图板字母（实测 `Anal cancer.a` / 也可能是 `-a`）。
# 只认小写 a–h，避免误伤 `Appendix B` 这类正常标题。
PANEL_SUFFIX_RE = re.compile(r"[.\-\u2013]\s*[a-h]$")
# 图内面板标签：单字母 + 至少两个空格 + 标题（`a    History of present illness…`）
PANEL_LABEL_RE = re.compile(r"^[a-h]\s{2,}\S")


def _clean(s: str) -> str:
    return s.replace("\xa0", " ").replace("\u00ad", "").strip()


def _is_bold(font: str, flags: int) -> bool:
    return any(k in font for k in ("Bold", "Semibold", "Medium")) or bool(flags & 16)


def _family(font: str) -> str:
    """字体家族名，用于区分“正文”与“框内文字”。
    例：HardingText-Regular -> HardingText；GraphikNaturel-Regular3 -> GraphikNaturel
    """
    return re.split(r"[-,_]", font)[0].rstrip("0123456789")


class _Line:
    __slots__ = ("page", "y0", "x0", "x1", "text", "raw", "sizes", "fonts",
                 "font_chars", "bold", "all_bold", "kind", "in_region", "in_rect",
                 "runin_head", "head_text", "rest_text", "col", "is_caption_cont")

    def __init__(self) -> None:
        self.kind = "?"
        self.runin_head = None
        self.head_text = ""
        self.rest_text = ""
        self.col = 0
        self.in_rect = False
        self.in_region = False
        self.is_caption_cont = False
        self.font_chars: Counter[str] = Counter()

    def dominant_font(self) -> str:
        """占字符数最多的字体家族。"""
        return self.font_chars.most_common(1)[0][0] if self.font_chars else ""


@dataclass
class Layout:
    """从数据推断出来的版面结构，替代原先写死的字号区间与栏基线。"""
    body_size: float
    columns: list[float]          # 各栏的基线 x0
    split_x: float                # 栏分界（单栏时无意义）
    n_columns: int
    body_font: str = ""           # 正文字体家族（用于判断框内文字是否算正文）

    def col_of(self, x0: float) -> int:
        if self.n_columns < 2:
            return 0
        return 0 if x0 < self.split_x else 1
    def base_x0(self, col: int) -> float:
        idx = min(col, len(self.columns) - 1)
        return self.columns[idx]


def _detect_layout(lines: list[_Line], page_width: float) -> Layout:
    """两步推断：先定正文字号，再定栏结构。

    ⚠️ 正文字号的推断比看上去难，我踩过两次坑：
      - 写死绝对区间（7.9–8.7）-> 换成 9.2pt 的期刊就全瞎（s41574）
      - 改成“长行里取众数” -> **参考文献列表也是长行**（NRN 的 6.0pt 占 5.5 万字符），
        于是正文被误判成 6.0，整篇崩掉（这是更隐蔽的回归）
    现在的做法：候选字号 = 字符占比 >= 15% 的那几档，**取最大的一档**。
    依据：同一页里，正文的字号总比图注/参考文献大一号（这是学术排版的通行做法）。
    """
    cnt: Counter[float] = Counter()
    for L in lines:
        if L.in_region:
            continue
        for sz in L.sizes:
            if 5.0 <= sz <= 16.0:
                cnt[round(sz, 1)] += len(L.text)
    if cnt:
        total = sum(cnt.values())
        cands = [sz for sz, n in cnt.items() if n >= total * BODY_MIN_SHARE and sz <= 13.0]
        body_size = max(cands) if cands else cnt.most_common(1)[0][0]
    else:
        body_size = 9.0

    # 正文字体家族：与 body_size 同级的行里，字符数最多的那一家
    # （不能统计全部行，否则图注/页眉的无衬线字体可能抢主体）
    fam: Counter[str] = Counter()
    for L in lines:
        if abs(max(L.sizes) - body_size) <= BODY_TOL:
            for f, n in L.font_chars.items():
                fam[f] += n
    body_font = fam.most_common(1)[0][0] if fam else ""
    # ---- 栏结构：正文行的 x0 分桶找簇 ----
    # ⚠️ 这里必须用「同字号 **且** 同字体家族」来筛正文，否则图注会污染栏基线：
    #    s41574 的图注是 DiverdaSansCom 8.5pt，正文是 MinionPro 9.2pt，
    #    字号只差 0.7（恰好落在宽松容差内），但图注跨整页宽（x0=42.5），
    #    于是左栏基线被从 142.3 拉偏到 47.3 —— 所有标题的“对齐栏基线”判定因此全错。
    prose = [L for L in lines
             if not L.in_region and len(L.text) >= PROSE_MIN_LEN
             and abs(max(L.sizes) - body_size) <= PROSE_SIZE_TOL
             and (not body_font or L.dominant_font() == body_font)]
    buckets: Counter[int] = Counter()
    for L in prose:
        buckets[int(L.x0) // 5 * 5] += 1
    total = sum(buckets.values())
    cands = sorted((b, n) for b, n in buckets.items() if n >= max(2, total * 0.08))
    groups: list[list[tuple[int, int]]] = []
    for b, n in cands:
        if groups and b - groups[-1][-1][0] <= 20:
            groups[-1].append((b, n))
        else:
            groups.append([(b, n)])
    centers = []
    for g in groups:
        wsum = sum(n for _, n in g)
        centers.append(sum(b * n for b, n in g) / wsum)
    # ⚠️ 栏基线必须用**真实 x0**（取 5% 分位，抗离群），不能用桶底：
    #    桶底 int(x0)//5*5 会有最多 5pt 的向下偏移（39.7 -> 35），
    #    而标题对齐判定的容差只有 3pt，于是同一栏的标题全被判成"没对齐"而丢失。
    #    这个 bug 很隐蔽：另一栏恰好偏移小于 3pt 时，会表现为"只有一半标题认得出来"。
    if len(centers) >= 2 and (centers[-1] - centers[0]) > page_width * 0.25:
        n_cols = len(centers)
        split = (centers[0] + centers[-1]) / 2
    else:
        n_cols = 1
        split = page_width

    def _col(x: float) -> int:
        return 0 if (n_cols < 2 or x < split) else 1

    xs_by_col: dict[int, list[float]] = {0: [], 1: []}
    for L in prose:
        xs_by_col[_col(L.x0)].append(L.x0)
    bases: list[float] = []
    for c in range(n_cols):
        v = sorted(xs_by_col.get(c, []))
        bases.append(v[max(0, int(len(v) * 0.05))] if v
                     else (centers[c] if c < len(centers) else 40.0))

    return Layout(body_size=body_size, columns=bases, split_x=split,
                  n_columns=n_cols, body_font=body_font)


def _region_rects(doc) -> dict[int, list[tuple[float, float, float, float]]]:
    out: dict[int, list] = {}
    for pno in range(doc.page_count):
        page = doc[pno]
        pr = page.rect
        page_area = pr.width * pr.height
        rects: list = []
        try:
            for d in page.get_drawings():
                r = d.get("rect")
                if r is None or r.width < REGION_MIN_W or r.height < REGION_MIN_H:
                    continue
                if r.width * r.height > page_area * REGION_MAX_AREA:
                    continue
                rects.append((r.x0, r.y0, r.x1, r.y1))
        except Exception:
            pass
        try:
            for info in page.get_image_info():
                r = pymupdf.Rect(info["bbox"])
                if r.width >= REGION_MIN_W and r.height >= REGION_MIN_H:
                    rects.append((r.x0, r.y0, r.x1, r.y1))
        except Exception:
            pass
        out[pno] = rects
    return out


def _gather(doc, regions) -> list[_Line]:
    lines: list[_Line] = []
    for pno in range(doc.page_count):
        rects = regions.get(pno, [])
        for b in doc[pno].get_text("dict")["blocks"]:
            if b.get("type") != 0:
                continue
            for line in b.get("lines", []):
                if line.get("dir") != (1.0, 0.0):
                    continue
                spans = [s for s in line.get("spans", []) if _clean(s["text"])]
                if not spans:
                    continue
                sup = [s for s in spans if (s["flags"] & 1) and s["size"] < 7.0]
                real = [s for s in spans if s not in sup]
                if not real:
                    continue
                raw = _clean("".join(s["text"] for s in spans))
                if raw.lower().strip(" .") in SKIP_STRINGS:
                    continue

                L = _Line()
                L.page, L.raw = pno, raw
                L.text = _clean("".join(s["text"] for s in real))
                L.sizes = [round(s["size"], 1) for s in real]
                L.fonts = sorted({s["font"] for s in real})
                # 逐 span 按字符数统计字体家族。
                # ⚠️ 不能只用“本行出现过哪些字体”（原先是 any(...)）：
                #    s41574 表格单元格 “n= 26, men” 里混了一个正文字体的上标引用，
                #    于是整行被当成正文 → 表格列文字混进段落中间，而且不报错。
                L.font_chars = Counter()
                for s in real:
                    L.font_chars[_family(s["font"])] += len(_clean(s["text"]))
                bolds = [_is_bold(s["font"], s["flags"]) for s in real]
                L.bold, L.all_bold = any(bolds), all(bolds)

                cut = 0
                for b_ in bolds:
                    if b_:
                        cut += 1
                    else:
                        break
                if 0 < cut < len(real):
                    L.head_text = _clean("".join(s["text"] for s in real[:cut]))
                    L.rest_text = _clean("".join(s["text"] for s in real[cut:]))

                bb = line["bbox"]
                L.y0, L.x0, L.x1 = round(bb[1], 1), round(bb[0], 1), round(bb[2], 1)
                cx, cy = (bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2
                # 先只记“落在某个矩形内”；到底算不算 region，要等推出 body_font 后才知道
                L.in_rect = any(x0 - 2 <= cx <= x1 + 2 and y0 - 2 <= cy <= y1 + 2
                                for x0, y0, x1, y1 in rects)
                lines.append(L)
    # 此处只做一个与版面无关的稳定排序；真正的阅读顺序（按栏）
    # 要等 _detect_layout 推出栏边界后再排 —— 否则缩进行会把同一栏拆成两组。
    lines.sort(key=lambda r: (r.page, r.y0, r.x0))
    return lines


def _reorder(lines: list[_Line], layout: Layout) -> list[_Line]:
    """按「页 -> 栏 -> y」重排为真正的阅读顺序。"""
    return sorted(lines, key=lambda L: (L.page, layout.col_of(L.x0), L.y0))


def _classify(lines: list[_Line], layout: Layout) -> None:
    """标注 kind。所有阈值都相对 layout.body_size，不再写死绝对字号。"""
    bs = layout.body_size
    # 同页同栏的物理前一行（lines 已按 y 升序排，所以最后见到的那条就是它）
    last_pc: dict[tuple[int, int], _Line] = {}
    prev_of: dict[int, _Line] = {}
    for L in lines:
        sz = max(L.sizes)
        L.col = layout.col_of(L.x0)
        aligned = abs(L.x0 - layout.base_x0(L.col)) <= 3.0
        n_alpha = len(re.findall(r"[A-Za-z]", L.text))
        p = last_pc.get((L.page, L.col))
        if p is not None:
            prev_of[id(L)] = p
        # ⚠️ 图注/表注**跨行**的续行：pymupdf 把它拆成独立行，续行没有 `Fig. N |` 前缀，
        #    所以 FIG_CAPTION_RE 拦不住它 —— 实测它会被当成小标题：
        #      s41575 `anal cancer.a`（上一行是 `Fig. 6 | …`，同为 7.0pt 图注字号）
        #      s41575 `treatment-related problematic RAI`（上一行是 `Table 2 | …`，同为 9.0pt）
        #    判据：上一行已被判为图注，且本行与它同字号、同字体 -> 本行必是它的续行。
        if p is not None and p.kind == "figure":
            L.is_caption_cont = (abs(sz - max(p.sizes)) <= 0.2
                                 and L.dominant_font() == p.dominant_font())
        # 落在矩形内 **且字体不是正文字体** -> 归为 region（Box / 图注）。
        # 但 **首页例外**：首页的矩形是装饰面板，里面的标题/摘要恰恰是要保留的。
        # （实测：vieta2018 的标题 “Bipolar disorders” 与 s41574 的摘要都在首页面板里，
        #   被当成 region 整块删掉，导致 title 退化成 “(前置)”/“Epidemiology”。）
        # 用 **主导字体** 而不是“出现过就算”：
        # 表格单元格里混一个正文体的上标引用，就足以让 any(...) 判成正文。
        same_font = (not layout.body_font) or L.dominant_font() == layout.body_font
        L.in_region = L.in_rect and not same_font and L.page > 0

        if L.in_region:
            L.kind = "region"
        elif L.text.strip().lower().strip(":") in LABEL_STRINGS:
            L.kind = "label"
        elif L.page == 0 and sz >= bs + 4.5 and not TITLE_SKIP_RE.match(L.text.strip()):
            # 标题：比正文大很多（初版写死 >=20，换一家 16pt 标题就失效）
            L.kind = "title"
        elif L.page == 0 and not L.bold and sz >= bs + 0.7:
            # 摘要：比正文明显大一号、不加粗。
            # （初版写死 size==12.0，换一家排版就失效；s41574 摘要是 10.5）
            L.kind = "abstract"
        elif L.page == 0:
            L.kind = "other"
        elif n_alpha <= 2:
            L.kind = "junk"
        elif FIG_CAPTION_RE.match(L.text):
            # 图注/表注：形如 "Fig. 3 | …" / "Table 1 | …"。
            # 它们常是「加粗前缀 + 正文」，会被下面 run-in 规则误抓成小标题，
            # 在 NRN / s41575 / vieta2018 上都实测出现过。必须挡在最前面。
            L.kind = "figure"
        elif L.is_caption_cont:
            # 图注/表注的跨行续行（见上面 is_caption_cont 的注释）
            L.kind = "figure"
        elif PANEL_LABEL_RE.match(L.text) and sz > bs:
            # 图内面板标签：`a    History of present illness…` / `c  Systemic treatment`。
            # 实测（s41575）：单字母 + 多个空格开头，字号大于正文，同为加粗对齐，
            # 于是被 h2 规则抓成章节标题。要求在多个空格后面还有内容，避免误伤真标题。
            L.kind = "figure"
        elif L.bold and not L.all_bold and (bs - 0.2) <= sz <= (bs + 1.5) \
                and len(L.head_text) >= 8 and L.rest_text:
            L.kind = "runin"
            L.runin_head = _runin_head(L, prev_of)
            L.text = L.rest_text.strip()
        elif L.bold and sz > bs * HEADING_MIN_FACTOR and aligned:
            L.kind = "h1"
        elif L.bold and bs < sz <= bs * HEADING_MIN_FACTOR and aligned \
                and len(L.text) >= 4:
            L.kind = "h2"
        elif abs(sz - bs) <= BODY_TOL and not L.bold and same_font:
            # 正文 = 字号相近 + **字体家族与正文一致** + 不加粗。
            # 加字体判据是为了挡掉图注（如 s41574 的 8.5pt 无衬线图注只比正文小 0.7pt）。
            L.kind = "body"
        elif sz < bs - BODY_TOL:
            L.kind = "figure"
        else:
            L.kind = "other"
        last_pc[(L.page, L.col)] = L


def _runin_head(L: _Line, prev_of: dict[int, _Line]) -> str:
    """拼回跨行的 run-in 小标题。

    ⚠️ 实测两种断行方式，都会只留下后半截：
      A. 断在连字符上（s41574）
         `Effects of intermittent fasting on inflammation and oxi-`  (上一行，整行加粗)
         `dative stress. Inflammation and oxidative stress have …`
         -> 小标题变成 `dative stress.`
      B. 断在普通空格上（vieta2018）
         `Other specified bipolar and unspecified bipolar and`      (上一行，整行加粗)
         `related disorders. These categories replace the 'not …`
         -> 小标题变成 `related disorders.`
    共同点：**上一整行都是加粗的**，它不属于任何已被识别的类型（kind=="other"），
    而本行是「加粗前缀 + 正文」—— 两行本来就是同一个标题。
    所以：只要上一行仍是这种「未被识别的整行加粗」，就继续往前接。
    护栏：上一行不能以句末标点收尾（那说明它是一句完整的话，不是标题前半截）。
    """
    parts = [L.head_text.strip()]
    p = prev_of.get(id(L))
    for _ in range(3):                       # 最多往前找 3 行，防止无限回溯
        if p is None or not p.bold or p.kind != "other":
            break
        if p.raw.rstrip().endswith((".", "!", "?", ":")):
            break
        parts.append(p.raw.strip())
        p = prev_of.get(id(p))
    return _join(list(reversed(parts)))


def _local_right(lines: list[_Line], layout: Layout) -> dict[int, float]:
    """⚠️ 必须用 id(Line) 做键。用列表下标会在过滤行之后全部错位（曾导致 Introduction 炸成 23 段）。"""
    out: dict[int, float] = {}
    body_idx = [i for i, L in enumerate(lines) if L.kind in ("body", "runin")]
    for pos, i in enumerate(body_idx):
        L = lines[i]
        near = []
        for j in body_idx[max(0, pos - WINDOW): pos + WINDOW + 1]:
            o = lines[j]
            if o.page != L.page or o.col != L.col:
                continue
            near.append(o.x1)
        if len(near) >= MIN_WIN:
            near.sort()
            out[id(L)] = near[int(len(near) * 0.85)]
    return out


def _join(ls: list[str]) -> str:
    out = ""
    for i, ln in enumerate(ls):
        t = ln.strip()
        if i == 0:
            out = t
        elif out.endswith("-") and not out.endswith("--"):
            out = out[:-1] + t           # 行尾断词
        else:
            out = out + " " + t
    return re.sub(r"\s+", " ", out).strip()


def _build(lines, lrm, doc_id: str, layout: Layout) -> list[Section]:
    sections: list[Section] = []
    cur: Section | None = None
    path: list[str] = []          # 各级标题栈，用于拼 sec_path
    buf: list[str] = []
    meta: dict = {}
    seen_sids: Counter[str] = Counter()
    used_paths: set[str] = set()

    def flush():
        nonlocal buf
        if buf and cur is not None:
            txt = _join(buf)
            if len(txt.split()) >= 3:
                idx = len(cur.segments) + 1
                sid = make_sid(doc_id, cur_path, idx)
                # ⚠️ 段落 ID 必须唯一。实测 s41574 出现过两段 sid 完全相同
                #    （同一段被切了两次）：若不处理，dict 会静默覆盖 ——
                #    缓存、译文产物、音频定位三者会一起去掉一段，而且不报错。
                seen_sids[sid] += 1
                if seen_sids[sid] > 1:
                    sid = f"{sid}-dup{seen_sids[sid]}"
                cur.segments.append(Segment(
                    sid=sid, doc_id=doc_id,
                    sec_path=cur_path, sec_heading=cur.heading, sec_level=cur.level,
                    index=idx, page=meta.get("page", cur.page), src_text=txt,
                    n_words=len(re.findall(r"[A-Za-z][A-Za-z'\-]*", txt)),
                    indented=bool(meta.get("indented")), col=int(meta.get("col", 0))))
        buf = []

    def new_section(level: int, heading: str, page: int):
        nonlocal cur, cur_path
        # ① 剥掉标题尾部粘上的图板字母（实测 `Anal cancer.a` -> 应是 `Anal cancer`）。
        #    这种字母是图内面板标签，被当成 run-in 标题的一部分吸了进来。
        cleaned = PANEL_SUFFIX_RE.sub("", heading.rstrip()).strip()
        if cleaned:
            heading = cleaned
        del path[level - 1:]
        # ② 路径必须**每节唯一**。slug() 有 40 字符上限，长标题会被截断成同一个路径：
        #    实测 `Medication management in patients with T1DM.` 与 `...T2DM.`
        #    都变成 `medication-management-in-patients-with-t`
        #    -> sec_path 撞车 -> **sid 撞车** -> dict 静默覆盖
        #    -> 缓存 / 译文产物 / 音频定位同时丢掉一段，而且不报错。
        comp, n = slug(heading), 1
        while "/".join(path + [comp]) in used_paths:
            n += 1
            comp = f"{slug(heading)}-{n}"
        path.append(comp)
        cur_path = "/".join(path)
        used_paths.add(cur_path)
        cur = Section(heading=heading, level=level, page=page)
        sections.append(cur)

    cur_path = "preamble"
    prev = None
    for L in lines:
        if L.kind in ("title", "other", "figure", "region", "junk", "label"):
            continue
        if L.kind in ("h1", "h2"):
            flush()
            new_section(1 if L.kind == "h1" else 2, L.text, L.page + 1)
            prev = None
            continue
        if L.kind == "runin":
            flush()
            new_section(3, L.runin_head, L.page + 1)
            meta = {"indented": False, "col": L.col, "page": L.page + 1}
            buf.append(L.text)
            prev = L
            continue
        if L.kind == "abstract":
            if cur is None or cur.heading != "Abstract":
                flush()
                new_section(1, "Abstract", 1)
            buf.append(L.text)
            prev = None
            continue

        col = L.col
        c_base = layout.base_x0(col)
        indented = (L.x0 - c_base) >= INDENT_MIN

        starts_new = True
        if prev is not None:
            pf = lrm.get(id(prev))
            prev_full = pf is not None and (pf - prev.x1) <= RIGHT_TOL
            starts_new = (not prev_full) or indented
            if starts_new and L.text[:1].islower() and not prev.text.rstrip(
                    '"\u201d\u2019)').endswith((".", "?", "!", ":")):
                starts_new = False      # 小写开头且上行未收尾 => 上一段的续
        if cur is None:
            new_section(1, "(前置)", L.page + 1)
        if starts_new:
            flush()
            meta = {"indented": indented, "col": col, "page": L.page + 1}
        buf.append(L.text)
        prev = L

    flush()
    return [s for s in sections if s.segments]


def segment_pdf(pdf_path: str | Path, doc_id: str | None = None) -> Document:
    pdf_path = Path(pdf_path)
    doc_id = doc_id or pdf_path.stem
    doc = pymupdf.open(pdf_path)
    page_width = max(doc[i].rect.width for i in range(doc.page_count))
    lines = _gather(doc, _region_rects(doc))
    layout = _detect_layout(lines, page_width)
    _classify(lines, layout)
    lines = _reorder(lines, layout)          # 按「页 -> 栏 -> y」排成阅读顺序
    lrm = _local_right(lines, layout)
    sections = _build(lines, lrm, doc_id, layout)
    title_lines = [L.text for L in lines if L.kind == "title"]
    title = (" ".join(title_lines)[:200] if title_lines
             else (sections[0].heading if sections else pdf_path.stem))
    return Document(doc_id=doc_id, title=title, pdf_path=str(pdf_path), sections=sections)


def load_or_segment(pdf_path: str | Path, cache_path: str | Path = "data/segments.json",
                    doc_id: str | None = None, force: bool = False) -> Document:
    """带缓存的分段：同一份 PDF 不重复跑（切分结果也会被下游的 sid 依赖，必须稳定）。"""
    pdf_path, cache_path = Path(pdf_path), Path(cache_path)
    doc_id = doc_id or pdf_path.stem
    if cache_path.exists() and not force:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        # ⚠️ 必须比对切分器版本：改了规则却不递增版本号，就会静默复用旧结果
        if (data.get("doc_id") == doc_id
                and data.get("pdf_mtime") == pdf_path.stat().st_mtime
                and data.get("segmenter_version") == SEGMENTER_VERSION):
            return Document.from_dict(data)
    d = segment_pdf(pdf_path, doc_id)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    payload = d.to_dict()
    payload["pdf_mtime"] = pdf_path.stat().st_mtime
    payload["segmenter_version"] = SEGMENTER_VERSION
    cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return d
