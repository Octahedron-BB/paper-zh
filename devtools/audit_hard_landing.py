"""翻译侧遗留问题体检：hard_replace 到底有没有真正落地？

背景：qa_report 的 [E] 项一直显示 s41583 有 3 条「hard_replace 未落地」
（DLPFC 12/24 段、VLPFC 2/13 段、SSRT 1/7 段），我当时把它当"检查器噪声"放过了。
但"规则静默失效"正是这个项目反复踩的坑，必须回头查实。

判定方法：源文出现了该术语、译文里却找不到期望译名时，
把译文里"疑似替代写法"的上下文打出来 —— 看一眼就知道是
(a) 检查器期望值太窄（实际译得更好），还是
(b) 规则真的没生效。
"""
import json
import re
import sys
from collections import Counter
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
# 想看到"替代写法"时，从译文里找这些线索词（中文部分片段 / 英文缩写本身）
PROBE = re.compile(r"[A-Z]{2,8}|背外侧|腹外侧|额叶|停止信号|反应时|前额叶")


def main() -> None:
    for doc, field in FIELDS.items():
        terms = load_glossary_dir(ROOT, doc_id=doc, field=field)
        hard = [t for t in terms if t.mode == MODE_HARD]
        tr = json.loads(Path(f"data/translation/{doc}.json").read_text(encoding="utf-8"))["segments"]
        print("=" * 78)
        print(f"■ {doc}   生效术语 {len(terms)} 条（其中 hard_replace {len(hard)} 条）")
        missing: Counter[str] = Counter()
        examples: dict[str, list[tuple[str, str]]] = {}
        for sid, g in tr.items():
            src, zh = g.get("src", ""), g.get("zh", "")
            for t in hard:
                if not (t.regex().search(src) or t.prefixed_regex().search(src)):
                    continue
                if t.zh and t.zh in zh:
                    continue
                if any(a and a in zh for a in t.aliases):
                    continue
                missing[t.term] += 1
                examples.setdefault(t.term, [])
                if len(examples[t.term]) < 2:
                    # 抓译文里出现的疑似替代写法
                    hits = [m.group(0) for m in PROBE.finditer(zh)]
                    examples[t.term].append((sid.split("#")[-1], " / ".join(dict.fromkeys(hits))[:150]))
        if not missing:
            print("   ✅ 全部落地")
            continue
        for term, n in missing.most_common():
            t = next(x for x in hard if x.term == term)
            print(f"   ⚠️ {term} -> 「{t.zh}」：{n} 段源文有、译文无此译名")
            for idx, seen in examples[term]:
                print(f"        #{idx}  译文里出现的相关片段: {seen}")


if __name__ == "__main__":
    main()
