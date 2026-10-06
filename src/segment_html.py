"""HTML -> Document 语义网页分段器。

专用于 Nature 等学术期刊网页版 HTML 的精准结构化提取。
相较于 PDF 分段：
1. 0 依赖版式推测，直接利用 HTML 原生语义标签（<section>, <p>, <h3> 等）；
2. 彻底杜绝页眉伪标题与跨页断句；
3. 产出与 PDF 分段完全同构的 Document / Section / Segment 数据结构，下游 100% 兼容。
"""

from __future__ import annotations

import html
import json
import re
from pathlib import Path

from .model import Document, Section, Segment, slug

SKIP_SECTIONS = {
    "inline recommendations",
    "references",
    "author information",
    "ethics declarations",
    "peer review",
    "additional information",
    "rights and permissions",
    "about this article",
}


def clean_paragraph_html(raw: str) -> str:
    """清理段落 HTML：去除参考文献引用、内联标签，转义实体。"""
    # 移除上标引用链接
    s = re.sub(r'<a\b[^>]*data-test=\"citation-ref\"[^>]*>.*?</a>', '', raw, flags=re.DOTALL)
    s = re.sub(r'<a\b[^>]*data-track-action=\"reference anchor\"[^>]*>.*?</a>', '', s, flags=re.DOTALL)
    # 移除其余 HTML 标签
    s = re.sub(r'<[^>]+>', '', s)
    # 还原 HTML 实体
    s = html.unescape(s)
    # 规范化空格与软连字符
    s = s.replace('\xa0', ' ').replace('\u00ad', '')
    return re.sub(r'\s+', ' ', s).strip()


def parse_nature_html(html_text: str, doc_id: str, html_path: Path | str = "") -> Document:
    """解析 Nature 网页版 HTML，生成结构化 Document。"""
    # 1. 标题提取
    title_m = re.search(r'<h1[^>]*class=\"[^\"]*c-article-title[^\"]*\"[^>]*>(.*?)</h1>', html_text, re.DOTALL)
    if title_m:
        title = html.unescape(re.sub(r'<[^>]+>', '', title_m.group(1))).strip()
    else:
        title_m2 = re.search(r'<title>(.*?)</title>', html_text, re.DOTALL)
        raw_title = title_m2.group(1).split('|')[0] if title_m2 else doc_id
        title = html.unescape(raw_title).strip()

    sections: list[Section] = []
    sec_matches = re.findall(r'<section\b[^>]*data-title=\"([^\"]+)\"[^>]*>(.*?)</section>', html_text, re.DOTALL)

    for main_title, body in sec_matches:
        norm_title = main_title.strip()
        if norm_title.lower() in SKIP_SECTIONS:
            continue

        # 剔除插图、表格与侧边框
        body_clean = re.sub(r'<figure\b[^>]*>.*?</figure>', '', body, flags=re.DOTALL)
        body_clean = re.sub(r'<div\b[^>]*class=\"[^\"]*c-article-box[^\"]*\"[^>]*>.*?</div>', '', body_clean, flags=re.DOTALL)
        body_clean = re.sub(r'<table\b[^>]*>.*?</table>', '', body_clean, flags=re.DOTALL)

        # 提取标题与正文段落流（保持原文阅读顺序）
        tokens = re.findall(r'<(h[3-4]|p)\b[^>]*>(.*?)</\1>', body_clean, flags=re.DOTALL)
        if not tokens:
            continue

        main_slug = slug(norm_title)
        active_sec = Section(heading=norm_title, level=1, page=1)
        active_path = main_slug
        sections.append(active_sec)

        for tag, content in tokens:
            if tag in ('h3', 'h4'):
                sub_title = html.unescape(re.sub(r'<[^>]+>', '', content)).strip()
                if not sub_title:
                    continue
                lvl = 2 if tag == 'h3' else 3
                sub_slug = slug(sub_title)
                active_path = f"{main_slug}/{sub_slug}"
                active_sec = Section(heading=sub_title, level=lvl, page=1)
                sections.append(active_sec)
            elif tag == 'p':
                p_text = clean_paragraph_html(content)
                if not p_text or len(p_text.split()) < 3:
                    continue
                idx = len(active_sec.segments) + 1
                sid = f"{doc_id}#{active_path}#{idx:02d}"
                seg = Segment(
                    sid=sid,
                    doc_id=doc_id,
                    sec_path=active_path,
                    sec_heading=active_sec.heading,
                    sec_level=active_sec.level,
                    index=idx,
                    page=1,
                    src_text=p_text,
                    n_words=len(p_text.split()),
                    indented=False,
                    col=0,
                    in_box=False,
                )
                active_sec.segments.append(seg)

    # 移除空节
    valid_sections = [s for s in sections if s.segments]
    return Document(doc_id=doc_id, title=title, pdf_path=str(html_path), sections=valid_sections)


def load_or_segment_html(html_path: str | Path, out_json: str | Path,
                         doc_id: str | None = None, force: bool = False) -> Document:
    """加载已解析的 JSON 缓存，或从 HTML 重新分段并保存。"""
    html_path = Path(html_path)
    out_json = Path(out_json)
    doc_id = doc_id or html_path.stem

    if out_json.exists() and not force:
        try:
            d = json.loads(out_json.read_text(encoding="utf-8"))
            if d.get("doc_id") == doc_id and d.get("sections"):
                secs = []
                for s in d["sections"]:
                    segs = [Segment.from_dict(seg) for seg in s.get("segments", [])]
                    secs.append(Section(heading=s["heading"], level=s["level"], page=s.get("page", 1), segments=segs))
                return Document(doc_id=doc_id, title=d["title"], pdf_path=d.get("pdf_path", str(html_path)), sections=secs)
        except Exception:
            pass

    html_text = html_path.read_text(encoding="utf-8")
    doc = parse_nature_html(html_text, doc_id=doc_id, html_path=html_path)

    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(doc.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8")
    return doc
