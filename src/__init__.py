# -*- coding: utf-8 -*-
"""Nature Reviews 文献 → 中文分层伴读（个人自用）

模块职责
--------
model      数据结构：Document / Section / Segment（含稳定 sid 与 src_hash）
segment    PDF → 分段结构（PyMuPDF 版面规则 + 多信号段落切分）
glossary   术语表：hard_replace（译后零成本替换）/ prompt_hint（进 prompt）
cache      段级缓存与"改一个术语影响哪几段"的失效计算
providers  LLM 接入：DeepSeek / Gemini / ChatGPT / 任意 OpenAI 兼容端点
translate  轨A：逐段忠实翻译（对照译文）
rewrite    轨B：逐段口语讲稿（供听）
"""

__all__ = ["model", "segment", "glossary", "cache", "providers"]
