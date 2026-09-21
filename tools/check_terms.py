"""术语体检：拿真实 PDF 跑缩写消歧 / 同名异义审计。

回答用户的问题：**同一个词/缩写在不同文章意思不同，怎么处理？**

用法：
  python tools/check_terms.py                              # 自动挑（多篇会报错）
  python tools/check_terms.py --doc-id s41575-024-00932-1
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from src.docs import read_field, resolve_doc_id  # noqa: E402
from src.abbrev import audit, conflict_report, extract_definitions  # noqa: E402
from src.glossary import (  # noqa: E402
    Term, TermConflictError, load_glossary, load_glossary_dir, resolve_terms,
)

GLOSSARY = ROOT / "glossary.yaml"
# 下面第 [4] 段演示用的常量（演示"同名异义"如何被 doc 级作用域裁决），
# 与真实待检文档无关。⚠️ 以前 DOC_ID/FIELD 兼任 --doc-id 的默认值，
# 不带参数跑就会静默审计另一篇文献；现在 --doc-id 走 resolve_doc_id()。
DEMO_DOC_ID = "s41583-025-00929-y"
DEMO_FIELD = "neuroscience"

def _seg_json(doc_id: str) -> Path:
    return ROOT / "data" / "segments" / f"{doc_id}.json"


def _full_text(doc_id: str) -> str:
    """该文档的全文（含 Box/Glossary），用于抽缩写定义。

    ⚠️ 这里**绝不能回退到别的文档的全文** —— 初版做了回退（找不到就用手写的
    full_text.txt），结果把 NRN 的缩写当成新文档的定义去审计，输出“本文给出
    的缩写定义：13 个”而实际是另一篇的。这种“用错文档”是静默的，极坑。
    现在改为：按需从对应 PDF 现抽并缓存。
    """
    p = ROOT / "data" / "cache" / "fulltext" / f"{doc_id}.txt"
    if p.exists():
        return p.read_text(encoding="utf-8")
    pdf = ROOT / "papers" / f"{doc_id}.pdf"
    if not pdf.exists():
        return ""
    import pymupdf
    doc = pymupdf.open(pdf)
    txt = "\n".join(doc[i].get_text("text") for i in range(doc.page_count))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(txt, encoding="utf-8")
    return txt


def prose_text(doc_id: str) -> str:
    """只用**正文段落**做缩写审计，不用整篇 PDF 文本。

    原因：整篇文本里混着图注、图内坐标轴标签（"PC"、"LOC"、"EM" 之类），
    会产出大量假缩写。正文段落是干净的。
    代价：只在 Box 里出现的缩写会被漏掉 —— 但 Box 本来就不翻译，可以接受。
    """
    p = _seg_json(doc_id)
    if p.exists():
        raw = json.loads(p.read_text(encoding="utf-8"))
        return "\n\n".join(x["src_text"] for sec in raw["sections"]
                            for x in sec["segments"])
    return _full_text(doc_id).read_text(encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="缩写消歧 / 同名异义审计")
    ap.add_argument("--doc-id", default=None,
                    help="文档 ID（省略时自动挑；有多个会报错）")
    ap.add_argument("--field", default=None,
                    help="学科域，如 neuroscience；不传则从 data/meta/ 读，读不到就只有 global 级生效")
    ap.add_argument("--top", type=int, default=30)
    args = ap.parse_args()
    doc_id = resolve_doc_id(ROOT, args.doc_id, stage="segments")
    field = args.field or read_field(ROOT, doc_id)

    prose = prose_text(doc_id)
    if not prose.strip():
        sys.exit("正文文本为空，先跑 tools/run_pipeline.py --stage segment")
    full = _full_text(doc_id) or prose
    # 主表 + 单篇覆盖表，按作用域就近解析（doc > field > global）
    terms = load_glossary_dir(ROOT, doc_id=doc_id, field=field)

    print("=" * 78)
    print(f"文档: {doc_id}   学科域: {field or '(无)'}")
    print(f"  正文（不含图注/Box，用于统计使用）: {len(prose):,} 字符")
    print(f"  全文（含 Box/Glossary，用于抽定义）: {len(full):,} 字符")
    print(f"  生效术语条目: {len(terms)}（主表 + glossary-d/{doc_id}.yaml 覆盖后）")

    # ---------------- 1. 抽本文的缩写定义 ----------------
    defs = extract_definitions(full)
    print(f"\n[1] 从**全文**抽出的「缩写 -> 全称」映射：{len(defs)} 个")
    in_prose = [a for a in defs if re.search(rf"(?<![A-Za-z]){a}(?![A-Za-z])", prose)]
    print(f"    其中在正文里实际被使用过的: {len(in_prose)} 个")
    only_outside = sorted(set(defs) - set(in_prose))
    if only_outside:
        print(f"    ⚠️ 只在 Box/图注里出现、正文没用的: {only_outside}")

    rep = audit(terms, prose, min_count=2, top=30, defs=defs)
    print()
    print(rep.render(top=30))

    # ---------------- 2. 与术语表比对 ----------------
    print("\n[2] 与术语表比对：本文定义的缩写在表里的情况")
    in_table = [h for h in rep.defined if h.in_glossary]
    not_in_table = [h for h in rep.defined if not h.in_glossary]
    print(f"    已在术语表: {len(in_table)} 个")
    print(f"    未在术语表: {len(not_in_table)} 个（出现频繁的建议补进去）")
    for h in not_in_table[:12]:
        print(f"      {h.abbr:<8} x{h.count:<4} {' / '.join(h.full_names)[:70]}")

    # ---------------- 3. 同名异义检测 ----------------
    print("\n[3] 同名异义检测（术语表声明的 full_en vs 本文定义的全称）")
    conflicts, todos = conflict_report(terms, defs)
    if conflicts:
        for c in conflicts:
            print("   ", c)
    else:
        print("    ✅ 未发现冲突")
    if todos:
        print(f"\n    ℹ️ 有 {len(todos)} 条缩写未声明 full_en，无法自动比对（建议补上）：")
        for t in todos:
            print(f"      {t}")

    # ---------------- 3.5 作用域解析的实际效果 ----------------
    print("\n[3.5] 作用域解析效果：本文真正生效的缩写译法")
    for abbr in ["MSN", "MTL", "SIF", "EM", "LOC", "NSW", "BOLD", "OCD", "DMN", "SSRT", "PTSD"]:
        matches = [t for t in terms if t.term.strip().upper() == abbr]
        for t in matches:
            print(f"    {abbr:<6} -> 「{t.zh}」   (scope={t.scope}, full_en={t.full_en or '未填'})")

    # ---------------- 4. 演示：作用域是怎么解决冲突的 ----------------
    print("\n[4] 演示：作用域（scope）如何解决'同名异义'")
    demo = [
        # 假设你的全局表里，MSN 一直是"中型棘状神经元"（这在神经科学里更常见）
        Term("MSN", "中型棘状神经元", "hard_replace", scope="global",
             note="假设的全局译法"),
        # 但本文的 MSN 是 medial septal nucleus -> 用 doc 级覆盖
        Term("MSN", "内侧隔核", "hard_replace", scope=f"doc:{DEMO_DOC_ID}"),
    ]
    eff, conf = resolve_terms(demo, doc_id=DEMO_DOC_ID, field=DEMO_FIELD, strict=False)
    for t in eff:
        print(f"    生效: MSN -> 「{t.zh}」  (来自 scope={t.scope})")
    print("    => 就近优先：doc > field > global，**主表保持干净、可跨文献复用**")

    # 再演示"同级冲突必须报错，不能静默挑一个"
    bad = [Term("MSN", "中型棘状神经元", "hard_replace", scope="global"),
           Term("MSN", "内侧隔核", "hard_replace", scope="global")]
    try:
        resolve_terms(bad, doc_id=DEMO_DOC_ID, field=DEMO_FIELD, strict=True)
        print("    ❌ 同级冲突竟然没被拦住")
    except TermConflictError as e:
        print("\n    ✅ 同级冲突被拦下（避免静默用错译法）：")
        print("       " + str(e).splitlines()[0])

    # ---------------- 5. 本文缩写 vs 术语表中译法的可疑项 ----------------
    print("\n[5] 需要你人工确认的高风险项")
    risky = []
    for h in rep.defined:
        if h.abbr in {"MSN", "MTL", "ACC", "PFC", "SIF", "TNT", "NBR", "SSRT"}:
            risky.append(h)
    if risky:
        for h in risky:
            print(f"    {h.abbr:<6} x{h.count:<4} 本文定义: {' / '.join(h.full_names)}"
                  f"   | 术语表: {h.glossary_zh or '（无）'}")
    else:
        print("    （无）")
    print("\n    说明：MSN / MTL / ACC / SIF / TNT 这类大写缩写是**同名异义高发区**，")
    print("    建议只在 doc 级（或 field 级）定义，不要写进 global。")


if __name__ == "__main__":
    main()
