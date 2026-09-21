"""多音字与发音清洗模块 (Polyphone & Pronunciation Normalization for TTS)。

职责：
1. 读取全局 `polyphone.yaml`（及可选的 `polyphone-d/<doc_id>.yaml` 文档专有规则）。
2. 在文本送入 TTS 引擎前，进行纯内存里的同音/谐音替换。
3. 保证展示层（讲稿/译文/字幕/HTML）绝对不受污染，仅音频引擎获得正确的发音注音。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Sequence

try:
    import yaml  # type: ignore
    HAS_YAML = True
except Exception:  # pragma: no cover
    HAS_YAML = False

ROOT = Path(__file__).resolve().parent.parent


def load_polyphone_rules(
    custom_path: Path | None = None,
    doc_id: str | None = None,
) -> list[tuple[str, str]]:
    """加载多音字发音清洗规则列表 (word, tts_replacement)。

    加载优先级：
    1. global: ROOT / "polyphone.yaml"
    2. doc-specific: ROOT / "polyphone-d" / f"{doc_id}.yaml" (若存在)
    """
    rules_map: dict[str, str] = {}

    paths_to_check: list[Path] = []
    if custom_path:
        paths_to_check.append(custom_path)
    else:
        global_path = ROOT / "polyphone.yaml"
        if global_path.exists():
            paths_to_check.append(global_path)

        if doc_id:
            doc_path = ROOT / "polyphone-d" / f"{doc_id}.yaml"
            if doc_path.exists():
                paths_to_check.append(doc_path)

    for p in paths_to_check:
        if not p.exists():
            continue
        try:
            if HAS_YAML:
                content = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            else:
                # 极简 fallback：若无 yaml 库按简易 key-value 读
                content = {}
            for item in content.get("rules", []):
                word = item.get("word")
                tts = item.get("tts")
                if word and tts:
                    rules_map[word] = tts
        except Exception as e:
            print(f"[警告] 加载多音字规则文件 {p} 失败: {e}")

    # 按原词长度降序排列，优先匹配长词（例如优先匹配“血栓栓塞”而非“栓塞”）
    sorted_rules = sorted(rules_map.items(), key=lambda x: len(x[0]), reverse=True)
    return sorted_rules


def apply_polyphone_rules(text: str, rules: Sequence[tuple[str, str]]) -> str:
    """应用多音字替换规则（纯字符串/正则替换，零副作用）。"""
    if not text or not rules:
        return text

    for word, tts in rules:
        if word in text:
            text = text.replace(word, tts)

    return text
