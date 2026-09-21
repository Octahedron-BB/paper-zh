"""数据结构：文档 / 节 / 段落（Segment）。

设计要点
--------
1. **段落的稳定 ID（sid）必须可复现**：由 文档ID + 节路径 + 段序号 拼成。
   它同时是「音频 ↔ 原文定位」的锚点、翻译缓存的键、以及术语替换的作用目标。
2. **src_hash**：原文内容的指纹。冗余保存，用于检测"同一 sid 的原文变了"
   （PDF 改版、切分规则调整）。sid 相同但 hash 不同 => 缓存必须失效。
3. 三层结构：Document -> Section(可嵌套层级) -> Segment，但对外提供**扁平段列表**，
   因为翻译/TTS 都是按段为单位调度的。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field, asdict
from typing import Any


def sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


_TITLE_QUOTES = re.compile(r"[\u2018\u2019\u201c\u201d]")


def slug(text: str, maxlen: int = 40) -> str:
    """把标题变成可读、稳定的 ASCII slug。

    规则（三个坑都踩过，改这里之前请读完）：

    1. 字母数字原样保留；**ASCII 标点折叠成 `-`**。
       原实现把 `.` `,` 也走"转码点"分支，于是 `Non-antibiotic drugs.` 变成
       `non-antibiotic-drugsu002e`。实测全仓库 176 处（`u002e` 108 / `u002c` 68），
       节路径与音频分段目录名一起被污染：既不可读，又白吃 40 字符预算。
    2. **非 ASCII 转 `uXXXX` 码点**。中文等标题只能靠它保存区分度，不能一刀切丢掉。
    3. 截断**只在完整原子边界发生**。原实现的 `slugged[:maxlen]` 会把 `u002e`
       切成 `u00`：残片不可反解析，而且不同标题可能因此撞成同一条路径。
       顺手还修掉了"单词被拦腰砍断"（`...and-othe` / `...transport-syst`）。
    """
    s = _TITLE_QUOTES.sub("", text.strip().lower())
    # 先把标题拆成原子：单个字母数字 / 单个连字符 / 完整的 uXXXX 转义
    atoms = [
        ch if ch.isascii() and ch.isalnum()
        else "-" if ch.isascii()
        else f"u{ord(ch):04x}"
        for ch in s
    ]
    kept: list[str] = []
    used = 0
    for a in atoms:
        if used + len(a) > maxlen:
            break
        kept.append(a)
        used += len(a)
    out = re.sub(r"-+", "-", "".join(kept)).strip("-")
    if len(kept) < len(atoms) and "-" in out:
        # 确实被截断了：退到最后一个连字符，别把单词砍一半
        out = out[: out.rfind("-")].strip("-")
    return out or "sec"


@dataclass
class Segment:
    sid: str                    # 稳定 ID，如 "s41583-025-00929-y#intro/retrieval-stopping#03"
    doc_id: str
    sec_path: str               # 节路径（slug 串）
    sec_heading: str            # 人类可读的节标题
    sec_level: int              # 所属节的层级
    index: int                  # 节内段序号（1 起）
    page: int                   # 起始页码（用于定位回原文）
    src_text: str               # 原文（英文，已剔除上标引用号）
    n_words: int
    indented: bool = False      # 原版式中该段是否首行缩进（版式溯源）
    col: int = 0                # 原版式中所在栏（0 左 / 1 右）
    in_box: bool = False        # 是否来自 Box（用户已决定：Box 不处理）

    @property
    def src_hash(self) -> str:
        return sha1(self.src_text)

    @property
    def sec_slug(self) -> str:
        return self.sid.split("#", 1)[1].rsplit("#", 1)[0] if "#" in self.sid else ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Segment":
        return cls(**d)


@dataclass
class Section:
    heading: str
    level: int
    page: int
    segments: list[Segment] = field(default_factory=list)


@dataclass
class Document:
    doc_id: str
    title: str
    pdf_path: str
    sections: list[Section] = field(default_factory=list)

    @property
    def segments(self) -> list[Segment]:
        """扁平的段列表（按阅读顺序）。"""
        return [s for sec in self.sections for s in sec.segments]

    def to_dict(self) -> dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "title": self.title,
            "pdf_path": self.pdf_path,
            "sections": [
                {
                    "heading": sec.heading,
                    "level": sec.level,
                    "page": sec.page,
                    "segments": [s.to_dict() for s in sec.segments],
                }
                for sec in self.sections
            ],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Document":
        doc = cls(doc_id=d["doc_id"], title=d["title"], pdf_path=d["pdf_path"])
        for s in d["sections"]:
            doc.sections.append(
                Section(
                    heading=s["heading"],
                    level=s["level"],
                    page=s["page"],
                    segments=[Segment.from_dict(x) for x in s["segments"]],
                )
            )
        return doc

    def stats(self) -> dict[str, Any]:
        segs = self.segments
        w = sorted(x.n_words for x in segs)
        return {
            "sections": len(self.sections),
            "segments": len(segs),
            "words": sum(w),
            "words_median": w[len(w) // 2] if w else 0,
            "words_max": w[-1] if w else 0,
        }


def make_sid(doc_id: str, sec_path: str, index: int) -> str:
    """稳定 ID 的生成规则集中在这里，避免各处手拼不一致。"""
    return f"{doc_id}#{sec_path}#{index:02d}"
