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
    """清理段落 HTML：保留规范 [N] 引用标记，去除无关内联标签，转义实体并剔除转载声明。"""
    # 格式化上标引用链接为标准 [N] 占位符，避免标点与数字无缝粘连（例如 ...barrier1. 变成 ...barrier [1].）
    s = re.sub(r'<a\b[^>]*data-test=\"citation-ref\"[^>]*>(\d+(?:[,\s\-–—\d]*))</a>', r' [\1]', raw)
    s = re.sub(r'<a\b[^>]*data-track-action=\"reference anchor\"[^>]*>(\d+(?:[,\s\-–—\d]*))</a>', r' [\1]', s)
    s = re.sub(r'<sup\b[^>]*>([\d,\s\-–—]+)</sup>', r' [\1]', s)
    # 其余未匹配到的引用链接彻底移除
    s = re.sub(r'<a\b[^>]*data-test=\"citation-ref\"[^>]*>.*?</a>', '', s, flags=re.DOTALL)
    s = re.sub(r'<a\b[^>]*data-track-action=\"reference anchor\"[^>]*>.*?</a>', '', s, flags=re.DOTALL)
    # 移除内嵌表格、公式与浮动元素
    s = re.sub(r'<(figure|table|tbody|thead|tr)\b[^>]*>.*?</\1>', '', s, flags=re.DOTALL)
    # 移除其余 HTML 标签
    s = re.sub(r'<[^>]+>', '', s)
    # 还原 HTML 实体
    s = html.unescape(s)
    # 规范化空格与软连字符
    s = s.replace('\xa0', ' ').replace('\u00ad', '')
    s = re.sub(r'\s+', ' ', s).strip()
    # 紧贴标点与引用
    s = re.sub(r'\s+(\[\d+(?:[,\s\-–—\d]*)\])', r'\1', s)
    # 剔除末尾版权声明行（如 Reprinted with permission from ref. 61, Elsevier）
    s = re.sub(r'(?:Reprinted|Adapted)\s+with\s+permission\s+from\s+.*$', '', s, flags=re.IGNORECASE).strip()
    return s


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

        main_slug = slug(norm_title)
        active_sec = Section(heading=norm_title, level=1, page=1)
        active_path = main_slug
        sections.append(active_sec)

        # A. 提取插图说明 (Figure Captions)，标注为 is_figure=True 并提取 Fig 标识
        fig_blocks = re.findall(
            r'<(?:div\b[^>]*class=\"[^\"]*c-article-section__figure[^\"]*\"|figure\b)[^>]*>(.*?)</(?:div|figure)>',
            body, flags=re.DOTALL
        )
        for fig_body in fig_blocks:
            fig_label_m = re.search(r'<(?:figcaption|b\b[^>]*class=\"[^\"]*c-article-section__figure-caption[^\"]*\")[^>]*>(.*?)</(?:figcaption|b)>', fig_body, re.DOTALL)
            fig_label = clean_paragraph_html(fig_label_m.group(1)) if fig_label_m else "Fig 说明"
            fig_ps = re.findall(r'<p\b[^>]*>(.*?)</p>', fig_body, re.DOTALL)
            for fp in fig_ps:
                p_text = clean_paragraph_html(fp)
                if not p_text or len(p_text.split()) < 3:
                    continue
                idx = len(active_sec.segments) + 1
                sid = f"{doc_id}#{active_path}#fig{idx:02d}"
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
                    is_figure=True,
                    fig_label=fig_label,
                )
                active_sec.segments.append(seg)

        # 剔除已处理的插图与表格
        body_clean = re.sub(r'<figure\b[^>]*>.*?</figure>', '', body, flags=re.DOTALL)
        body_clean = re.sub(r'<div\b[^>]*class=\"[^\"]*c-article-section__figure[^\"]*\"[^>]*>.*?</div>', '', body_clean, flags=re.DOTALL)
        body_clean = re.sub(r'<table\b[^>]*>.*?</table>', '', body_clean, flags=re.DOTALL)

        # B. 智能处理 Box 诊断标准与列表清单：将引言句与后面的 <ol>/<ul> 聚合为一体
        # 例如：associated with two or more of the following criteria: 后紧跟的 1. ... 2. ...
        def aggregate_list_match(m: re.Match) -> str:
            intro_p = m.group(1)
            list_content = m.group(2)
            # 提取所有 li
            lis = re.findall(r'<li\b[^>]*>(.*?)</li>', list_content, re.DOTALL)
            items = []
            for li_idx, li in enumerate(lis):
                li_clean = clean_paragraph_html(li)
                if li_clean:
                    if not re.match(r'^\d+\.', li_clean):
                        li_clean = f"{li_idx + 1}. {li_clean}"
                    items.append(li_clean)
            if items:
                joined = "; ".join(items)
                return f"{intro_p} {joined}</p>"
            return m.group(0)

        # 匹配以冒号结尾的段落后紧随列表
        body_clean = re.sub(
            r'(<p\b[^>]*>[^<]*?:)\s*</p>\s*<(?:ol|ul)\b[^>]*>(.*?)</(?:ol|ul)>',
            aggregate_list_match,
            body_clean,
            flags=re.DOTALL
        )

        # 提取标题与正文段落流（保持原文阅读顺序）
        tokens = re.findall(r'<(h[3-4]|p)\b[^>]*>(.*?)</\1>', body_clean, flags=re.DOTALL)
        if not tokens and not active_sec.segments:
            continue

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
                    is_figure=False,
                    fig_label="",
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
