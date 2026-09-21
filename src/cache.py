"""段级缓存：为什么"改一个术语只重译相关段"能成立。

缓存键的设计（这是本项目最重要的技术决策之一）
--------------------------------------------
key = sha256( model_id | prompt_version | src_hash | 该段命中的术语指纹 )

三种错误做法及其后果：
  ❌ key = sha256(src_text)
       改了术语，译文其实已经过期，但缓存仍认为"命中" -> 你改的词没生效。
  ❌ key = sha256(src_text + 整张术语表)
       改 1 个词 -> 全篇 62 段全部失效 -> 正是你想避免的"全跑一遍"。
  ✅ key = sha256(src_text + **该段实际命中的**术语)
       改 1 个词 -> 只有真正含这个词的那几段变脏 -> 精确重译。

附带说明（写给未来的自己）
--------------------------
段落级缓存真正的价值**不是省 token**。一篇 1.4 万词的综述翻译总共约 4 万 token，
按现价折算只有"几分钱"量级 —— 全篇重跑 100 次也就几块钱。
真正的价值是三件事：
  1. 保住**你人工校订过**的段落（这是钱买不到的资源）
  2. 保证术语/语气**一致性**（整篇重跑会漂移）
  3. LLM 输出**非确定性** —— 全重跑会让本来没问题的段落随机变差
所以缓存必须**持久化 + 可 diff + 可回滚**，且要能回答"这一个词影响了哪几段"。
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .glossary import Term, hints_for_text, hits_signature

SEP = "\x1f"


def make_key(*parts: str) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode("utf-8"))
        h.update(SEP.encode("utf-8"))
    return h.hexdigest()


@dataclass
class CacheEntry:
    key: str
    value: str
    meta: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"key": self.key, "value": self.value, "meta": self.meta}


class Cache:
    """落盘缓存。一条记录一个 JSON 文件，便于人工查看/删除/回滚。"""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.hits = 0
        self.misses = 0

    def _path(self, key: str) -> Path:
        # 两级目录，避免单目录文件过多
        return self.root / key[:2] / f"{key}.json"

    def get(self, key: str) -> CacheEntry | None:
        p = self._path(key)
        if not p.exists():
            self.misses += 1
            return None
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            self.misses += 1
            return None
        self.hits += 1
        return CacheEntry(key=d["key"], value=d["value"], meta=d.get("meta", {}))

    def put(self, key: str, value: str, meta: dict[str, Any] | None = None) -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        # 原子写：先写临时文件再 replace，避免中断产生半个 JSON
        fd, tmp = tempfile.mkstemp(dir=str(p.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"key": key, "value": value, "meta": meta or {}},
                          f, ensure_ascii=False, indent=1)
            os.replace(tmp, p)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def stats(self) -> str:
        return f"命中 {self.hits} / 未命中 {self.misses}"


# ---------------------------------------------------------------- 键的计算

def key_for_translation(*, model_id: str, prompt_version: str, src_hash: str,
                        hit_terms: Iterable[Term]) -> str:
    """轨A（对照译文）的缓存键。

    ⚠️ 只允许传入 `prompt_hint` 类术语（调用方用 hints_for_text 过滤）。
    `hard_replace` 类**绝不能进这个键** —— 它是译文生成后的字符串替换，不进 prompt，
    改它必须做到"0 段失效、立刻生效"。如果把它算进键里，这个设计就白费了。
    """
    return make_key("A", model_id, prompt_version, src_hash, hits_signature(hit_terms))


def key_for_script(*, model_id: str, prompt_version: str, translated: str,
                   style_id: str) -> str:
    """轨B（口语讲稿）的缓存键：依赖轨A 的产物 + 风格标识。"""
    return make_key("B", model_id, prompt_version, style_id,
                    hashlib.sha1(translated.encode("utf-8")).hexdigest())


def key_for_digest(*, model_id: str, prompt_version: str, src_hash: str) -> str:
    """文献速览提要（feed digest）的缓存键。

    ⚠️ 与轨A/轨B **故意不同**：这里**不把术语命中算进键**。

    理由：提要只有 20–85 字，术语靠译后的 `apply_hard_replace` 免费修正
    （与 `hard_replace` 类术语"0 段失效、立刻生效"的承诺一致）。
    若把术语算进键，改一个词就要让整批提要重跑 —— 而重跑不仅浪费，
    还会带来 LLM 非确定性的漂移，把本来好好的提要随机改差。

    这也意味着：**不要往提要 prompt 里塞 prompt_hint 术语块**。
    塞了就等于把术语间接写进了键，上面这个设计就白费了。
    """
    return make_key("D", model_id, prompt_version, src_hash)


def dirty_segments(segments: Iterable[Any], terms: list[Term],
                   cache: Cache, *, model_id: str, prompt_version: str) -> list[Any]:
    """给定（可能刚改过的）术语表，算出哪些段的轨A 译文已失效。

    这正是"改一个术语，列出它影响了哪几段"的实现。
    注意关键点：只有 `prompt_hint` 类术语的改动才会造成失效；
    改 `hard_replace` 类术语 -> 这里一个段都不会脏 -> 靠 apply_hard_replace 免费生效。
    """
    out = []
    for seg in segments:
        prompt_terms = hints_for_text(terms, seg.src_text)
        k = key_for_translation(model_id=model_id, prompt_version=prompt_version,
                                src_hash=seg.src_hash, hit_terms=prompt_terms)
        if cache.get(k) is None:
            out.append(seg)
    return out
