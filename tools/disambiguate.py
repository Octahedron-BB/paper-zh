"""用**文档自身的缩写定义**自动发现同名异义，并生成单篇覆盖。

要解决的问题
------------
`field` 这种参数本质上是"**靠人记住**"，而人一定会忘（实测踩过：忘记 `--field`
导致术语静默少用一批）。更根本的是：你不知道某篇文献里 MSN 指的是别的东西 ——
事前想不到、事后很难发现、代价还不对称。

为什么可以自动化
----------------
学术论文有强惯例：缩写首次出现必给全称。`src/abbrev.py` 已经能用**纯正则**
抽出「本文档的缩写 -> 全称」映射（首字母校验 + 最短后缀裁剪），不需要 LLM。
于是只要把"本文定义"和"术语表的译名"对一下，冲突就暴露了。

判定与生成（三级，尽量不花钱）
------------------------------
1. 术语表填了 `full_en`：
   - 与本文定义**一致**   -> 没事，跳过（0 成本）
   - 与本文定义**不一致** -> 冲突。若另一条条目的 full_en 与本文定义相同，
                             直接复用它的 zh（0 成本）
2. 术语表**没填** `full_en`（多数条目如此）：
   用**一次极小的 LLM 调用**问"本文定义的含义和表里这个译名一致吗"，
   不一致时顺便给出本文含义的中文标准译名。
3. 冲突已存在单篇覆盖（`full_en` 与本文定义相同）-> 报"已解决"，不重复提议。

用法
----
    python tools/disambiguate.py --doc-id s41583-025-00929-y --field neuroscience
    python tools/disambiguate.py --doc-id xxx --no-llm      # 只做确定性判定
    python tools/disambiguate.py --doc-id xxx --apply       # 写入 glossary-d/
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

import yaml  # noqa: E402

from src.abbrev import extract_definitions  # noqa: E402
from src.glossary import MODE_HARD, load_glossary_dir  # noqa: E402
from src.providers import build_provider, load_env  # noqa: E402

META_DIR = ROOT / "data" / "meta"

LLM_SYSTEM = "你是医学术语翻译专家。只按要求输出，不要解释、不要标点、不要 Markdown。"
LLM_USER = """\
【本文的定义】这篇文献把缩写 {abbr} 定义为：{full}
【现有术语表】把 {abbr} 译作：「{zh}」
请判断这两个含义是否一致：
- 一致      -> 只输出六个字母：SAME
- 不一致    -> 只输出 {full} 在中文医学文献里的标准译名（一个词，不要解释）"""


def seg_text(doc_id: str) -> str:
    p = ROOT / "data" / "segments" / f"{doc_id}.json"
    if not p.exists():
        return ""
    raw = json.loads(p.read_text(encoding="utf-8"))
    return "\n\n".join(x["src_text"] for sec in raw["sections"] for x in sec["segments"])


def full_text(doc_id: str) -> str:
    """全文（含 Box/Glossary）—— 缩写定义常写在 Box 里，正文里反而没有。"""
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


def norm(s: str) -> str:
    return re.sub(r"[\s\-]+", " ", s).strip().lower()


def judge(provider, abbr: str, full: str, zh: str) -> str | None:
    """返回 None 表示"一致"；否则返回新的中文译名。"""
    try:
        out = provider.complete(LLM_SYSTEM, LLM_USER.format(abbr=abbr, full=full, zh=zh))
    except Exception as e:  # noqa: BLE001
        print(f"      LLM 调用失败：{type(e).__name__}: {e}")
        return None
    out = out.strip().strip("。.「」\"' \n")
    if out.upper().startswith("SAME") or "一致" in out[:6]:
        return None
    return out.splitlines()[0].strip()[:24] or None


def main() -> int:
    ap = argparse.ArgumentParser(description="用文档自身定义自动发现同名异义")
    ap.add_argument("--doc-id", required=True)
    ap.add_argument("--field", default=None,
                    help="学科域；不传则沿用 data/meta 里记录的值")
    ap.add_argument("--min-uses", type=int, default=2, help="缩写至少用这么多次才检查")
    ap.add_argument("--no-llm", action="store_true", help="只用确定性判定，不调 LLM")
    ap.add_argument("--apply", action="store_true", help="把提议写入 glossary-d/<doc_id>.yaml")
    args = ap.parse_args()

    doc_id = args.doc_id
    field = args.field
    if field is None:
        meta = META_DIR / f"{doc_id}.json"
        if meta.exists():
            field = json.loads(meta.read_text(encoding="utf-8")).get("field")

    prose, full = seg_text(doc_id), full_text(doc_id)
    if not prose.strip():
        sys.exit(f"没有正文文本；先跑：python tools/run_pipeline.py --pdf {doc_id} --stage segment")
    terms = load_glossary_dir(ROOT, doc_id=doc_id, field=field)
    by_abbr = {t.term: t for t in terms}

    defs = extract_definitions(full or prose)
    print("=" * 78)
    print(f"文档: {doc_id}   学科域: {field or '(无)'}   生效术语: {len(terms)} 条")
    print(f"本文抽出的缩写定义: {len(defs)} 个")

    resolved, conflicts, unknown = [], [], []
    print("\n[检查] 术语表里的缩写 vs 本文自己的定义")
    for abbr, names in sorted(defs.items()):
        t = by_abbr.get(abbr)
        if t is None:
            continue
        uses = len(re.findall(rf"(?<![A-Za-z]){re.escape(abbr)}(?![A-Za-z])", prose))
        if uses < args.min_uses:
            continue
        doc_full = max(names, key=len)          # 最长的定义最可能是真全称
        # 表中“另一条”已声明的 full_en 与本文定义相同 -> 可直接复用它的译名（0 成本）
        same = [x for x in terms if x.full_en and x is not t
                and norm(x.full_en) == norm(doc_full)]
        if t.full_en and norm(t.full_en) == norm(doc_full):
            resolved.append((abbr, uses, doc_full, t.zh, "表里的 full_en 与本文一致"))
        elif t.full_en:
            conflicts.append((abbr, uses, doc_full, t.zh, t.full_en, same))
        else:
            unknown.append((abbr, uses, doc_full, t, same))

    print(f"\n✅ 已一致 / 已被单篇覆盖解决: {len(resolved)} 条")
    for abbr, uses, d, zh, why in resolved:
        print(f"    {abbr} (用 {uses} 次)  本文={d!r}  表={zh!r}  {why}")
    if conflicts:
        print(f"\n❗ 确定性冲突（表里填了 full_en 但与本文不一致）: {len(conflicts)} 条")
        for abbr, uses, d, zh, tbl, same in conflicts:
            print(f"    {abbr} (用 {uses} 次)  本文={d!r} vs 表 full_en={tbl!r}  表译名={zh!r}"
                  + (f"  → 可复用 {same[0].zh!r}" if same else ""))
    print(f"\n⚠️ 无法确定性判定（表里没填 full_en）: {len(unknown)} 条")
    for abbr, uses, d, t, same in unknown:
        print(f"    {abbr} (用 {uses} 次)  本文={d!r}  表={t.zh!r}"
              + (f"  → 可复用 {same[0].zh!r}" if same else ""))

    proposals: list[tuple[str, str, str, int, str]] = []
    need_llm: list[tuple[str, int, str, str]] = []
    for abbr, uses, d, zh, _tbl, same in conflicts:
        (proposals.append((abbr, same[0].zh, d, uses, "复用表中同义条目"))
         if same else need_llm.append((abbr, uses, d, zh)))
    for abbr, uses, d, t, same in unknown:
        if same:
            proposals.append((abbr, same[0].zh, d, uses, "复用表中同义条目"))
        else:
            need_llm.append((abbr, uses, d, t.zh))

    if need_llm and not args.no_llm:
        load_env(ROOT / ".env")
        try:
            provider = build_provider()
        except Exception as e:  # noqa: BLE001
            print(f"\n[LLM] 跳过（{type(e).__name__}: {e}）")
            provider = None
        if provider is not None:
            print(f"\n[LLM] 逐条判定 {len(need_llm)} 个（每条一次极小调用）")
            for abbr, uses, d, zh in need_llm:
                print(f"    {abbr}: 本文={d!r} vs 表={zh!r} ...", end="", flush=True)
                new_zh = judge(provider, abbr, d, zh)
                if new_zh is None:
                    print(" 一致")
                else:
                    print(f" ❗ 不一致 -> 本文应译作「{new_zh}」")
                    proposals.append((abbr, new_zh, d, uses, "LLM 判定"))
    elif need_llm:
        print(f"\n（--no-llm：{len(need_llm)} 条未判定；去掉该开关可用 LLM 逐条判断）")
    print("\n" + "=" * 78)
    if not proposals:
        print("结论：没有发现需要新增单篇覆盖的冲突。")
    else:
        print(f"结论：发现 {len(proposals)} 处需要单篇覆盖的冲突：")
        for abbr, zh, d, uses, how in proposals:
            print(f"    {abbr} -> 「{zh}」   （本文 {d!r}，正文用 {uses} 次；{how}）")
        if args.apply:
            path = ROOT / "glossary-d" / f"{doc_id}.yaml"
            old_have: set[str] = set()
            if path.exists():
                old = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                old_have = {x.get("term") for x in (old.get("terms") or [])}
            block = "".join(
                f"\n  # 自动发现（tools/disambiguate.py）："
                f"本文把 {abbr} 定义为 {d!r}，与主表含义不同。\n"
                f"  - term: {abbr}\n    zh: {zh}\n    mode: {MODE_HARD}\n"
                f"    full_en: {d}\n    scope: doc:{doc_id}\n"
                for abbr, zh, d, _uses, _how in proposals if abbr not in old_have)
            if path.exists():
                if not block.strip():
                    print("     （这些条目已在覆盖表里，没有新增）")
                else:
                    text = path.read_text(encoding="utf-8")
                    path.write_text(text.rstrip("\n") + "\n" + block, encoding="utf-8")
                    print(f"    ✅ 已追加到 {path.relative_to(ROOT)}")
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                head = (f"# 单篇覆盖表：只对 {doc_id} 这一篇生效\n"
                        f"# 由 tools/disambiguate.py 自动发现，可手工修改。\n"
                        f"# 原则：主表（glossary.yaml）保持可跨文献复用，本篇特殊含义只写这里。\n\n"
                        f"terms:\n")
                path.write_text(head + block.lstrip("\n"), encoding="utf-8")
                print(f"    ✅ 已创建 {path.relative_to(ROOT)}")
            print("       ⚠️ 写入后必须重跑流水线才会生效："
                  f"python tools/run_pipeline.py --pdf {doc_id} --stage all")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
