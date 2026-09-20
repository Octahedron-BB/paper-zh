"""检查 hard_replace 译名是否把译文"刷"得太啰嗦。

背景：`hard_replace` 是**字符串替换**，译名会被原样插入每一处。
于是「为了首次出现时给个解释」而写进 zh 的括号内容，会**在每一处重复**。
实测线索：SIF 的 zh 是 `SIF（压抑诱发的遗忘）`，而 SIF 在正文用了 24 次。

这类问题机器能算（重复次数），但是不是问题要人判断 —— 所以脚本只**摆事实**。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from src.glossary import MODE_HARD, load_glossary_dir  # noqa: E402

ROOT = Path(".")
FIELDS = {
    "s41583-025-00929-y": "neuroscience",
    "s41575-024-00932-1": None,
    "s41574-022-00638-x": None,
    "vieta2018": None,
}
# 什么算"可能啰嗦"：译名偏长，或自带括号解释
def suspicious(zh: str) -> str:
    if "（" in zh or "(" in zh:
        return "带括号解释（会逐处重复）"
    if len(zh) >= 10:
        return "译名偏长"
    return ""


for doc, field in FIELDS.items():
    p = ROOT / "data" / "translation" / f"{doc}.json"
    if not p.exists():
        continue
    tr = json.loads(p.read_text(encoding="utf-8"))["segments"]
    terms = load_glossary_dir(ROOT, doc_id=doc, field=field)
    rows = []
    for t in terms:
        if t.mode != MODE_HARD or not t.zh:
            continue
        n = sum(g.get("zh", "").count(t.zh) for g in tr.values())
        if n:
            rows.append((n, t.term, t.zh, suspicious(t.zh)))
    rows.sort(reverse=True)
    print("=" * 78)
    print(f"■ {doc}")
    for n, term, zh, why in rows[:8]:
        mark = f"   ⚠️ {why}" if why else ""
        print(f"   {n:4d} 处   {term} -> 「{zh}」{mark}")
