"""跨文档 QA：全量翻译后主动挑毛病。

检查项（都能自动判定，不靠人眼）：
  A. 译文完整性   —— 中文/英文词比值，找异常偏短的段（漏译/截断）
  B. 讲稿保全率   —— 轨B/轨A 字数比，找被偷偷概括的段
  C. 未翻译残留   —— 译文里还剩下多少拉丁字母词（大片英文没译）
  D. 数字保真     —— 原文里的数字有没有出现在译文中（医学文献里数字很关键）
  E. 术语落地     —— hard_replace 术语的期望译名是否真的出现
  F. 提示词泄漏   —— 译文里是否混入 prompt 结构、"译文："之类
  G. 前缀变体     —— 译文里是否还残留 aDLPFC / rVLPFC 这类带前缀缩写

跑法：python tools/qa_report.py                  # 自动扫 data/translation/ 下全部文档
      python tools/qa_report.py --doc vieta2018   # 只看指定文献
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

from src.docs import processed_docs  # noqa: E402
from src.glossary import (  # noqa: E402
    MODE_HARD, PREFIX_ZH, hits_for_text, is_abbrev_term, load_glossary_dir,
)
from src.model import Document  # noqa: E402

LATIN_WORD = re.compile(r"[A-Za-z][A-Za-z'\-]{1,}")
# ⚠️ 绝对不能用 \w —— Python 的 \w 在 Unicode 下**匹配汉字**，
#    于是「高达81%」里的 81 前面有个汉字，lookbehind 就失败了，
#    造成大量“数字丢失”假警报。必须显式写成 [A-Za-z0-9.]。
NUM = re.compile(r"(?<![A-Za-z0-9.])(\d+(?:[.,]\d+)?)(?![A-Za-z0-9])")
PRE_TAG = re.compile(r"^(译文|翻译|输出|Answer|Translation)\s*[:：]")
PROMPT_LEAK = ("【", "术语对照", "待翻译", "待改写", "所在章节")
# 带方位前缀的缩写残留：前缀必须是已知方位字母，且后面那截本身是缩写形式
PREFIX_RESIDUE = re.compile(
    r"(?<![A-Za-z])([%s])([A-Z][A-Za-z0-9]{1,7})(?![A-Za-z])" % "".join(PREFIX_ZH))


def loc(sid: str) -> str:
    """可定位的短标识。段序号单独给毫无意义（多个节都有 #01）。"""
    parts = sid.split("#")
    if len(parts) >= 3:
        return f"{parts[1][:34]}…/{parts[-1]}"
    return sid


def ratio_stats(vals: list[float]) -> str:
    if not vals:
        return "—"
    v = sorted(vals)
    return f"最低 {v[0]:.2f} / 中位 {v[len(v)//2]:.2f} / 最高 {v[-1]:.2f}"


def check_doc(doc_id: str, field: str | None) -> None:
    tpath = ROOT / "data" / "translation" / f"{doc_id}.json"
    spath = ROOT / "data" / "script" / f"{doc_id}.json"
    segpath = ROOT / "data" / "segments" / f"{doc_id}.json"
    if not (tpath.exists() and segpath.exists()):
        print(f"\n■ {doc_id}: 缺少产物，跳过")
        return
    tr = json.loads(tpath.read_text(encoding="utf-8"))["segments"]
    sc = json.loads(spath.read_text(encoding="utf-8"))["segments"] if spath.exists() else {}
    doc = Document.from_dict(json.loads(segpath.read_text(encoding="utf-8")))
    terms = load_glossary_dir(ROOT, doc_id=doc_id, field=field)

    print("\n" + "=" * 84)
    print(f"■ {doc_id}   段落 {len(tr)}   生效术语 {len(terms)} 条")

    # A. 完整性
    a = []
    for sid, v in tr.items():
        if not v["zh"]:
            continue
        en = len(LATIN_WORD.findall(v["src"]))
        a.append((len(v["zh"]) / max(en, 1), en, len(v["zh"]), sid))
    a.sort()
    print(f"  [A] 轨A 中文/英文词比: {ratio_stats([x[0] for x in a])}")
    for r, en, zh, sid in a[:3]:
        print(f"      ⚠️ 最低 {r:.2f}  英文{en}词 -> 中文{zh}字  {loc(sid)}")

    # B. 保全率
    if sc:
        b = sorted((v.get("preserve_ratio") or 0, k) for k, v in sc.items()
                   if v.get("preserve_ratio"))
        low = [x for x in b if x[0] < 0.80]
        print(f"  [B] 轨B 保全率: {ratio_stats([x[0] for x in b])}   <0.80 的段: {len(low)}")
        for r, sid in b[:3]:
            if r < 0.95:
                print(f"      {r:.2f}  {loc(sid)}")

    # C. 未翻译残留
    c = []
    for sid, v in tr.items():
        zh = v["zh"]
        if not zh:
            continue
        latin = len(LATIN_WORD.findall(zh))
        cjk = len(re.findall(r"[\u4e00-\u9fff]", zh))
        c.append((latin / max(cjk, 1), latin, cjk, sid))
    c.sort(reverse=True)
    print(f"  [C] 译文里拉丁字母词/汉字比: 最高 {c[0][0]:.3f}（前 3 段）")
    for r, la, cj, sid in c[:3]:
        print(f"      {r:.3f}  拉丁{la} / 汉字{cj}  {loc(sid)}")

    # D. 数字保真
    miss_cnt = 0
    worst = []
    for sid, v in tr.items():
        if not v["zh"]:
            continue
        src_nums = {n for n in NUM.findall(v["src"]) if len(n) >= 2}
        if not src_nums:
            continue
        zh_nums = set(NUM.findall(v["zh"]))
        missing = src_nums - zh_nums
        # 允许格式差异（千分位/小数点）
        norm = {n.replace(",", "").replace(".", "") for n in zh_nums}
        missing = {n for n in missing if n.replace(",", "").replace(".", "") not in norm}
        if missing:
            miss_cnt += 1
            worst.append((len(missing), sid, sorted(missing)[:6]))
    worst.sort(reverse=True)
    print(f"  [D] 数字可能丢失的段: {miss_cnt}/{len(tr)}")
    for n, sid, ex in worst[:4]:
        print(f"      缺 {n} 个: {ex}  {loc(sid)}")

    # E. 术语落地
    hardbad = []
    for t in [x for x in terms if x.mode == MODE_HARD]:
        hit = [s for s in doc.segments if t.hits(s.src_text) and tr.get(s.sid, {}).get("zh")]
        if not hit:
            continue
        bad = [s for s in hit if t.zh not in tr[s.sid]["zh"]]
        if bad:
            hardbad.append((t.term, t.zh, len(bad), len(hit), bad[0].sid))
    print(f"  [E] hard_replace 未落地: {len(hardbad)} 条")
    for term, zh, nb, nh, sid in hardbad[:6]:
        print(f"      {term} -> 「{zh}」 {nb}/{nh} 段未出现  ({loc(sid)})")

    # F. 提示词泄漏 / 带前缀缩写残留
    # ⚠️ 初版用 (?<![A-Za-z])[a-z][A-Z]{2,7} 判定“前缀残留”，把 iPSC、mRNA 这类
    #    名字里本来就带小写字母的缩写全误报了。现在要求：前缀属于已知方位字母，
    #    且后面那截在术语表里有对应条目（即确实是“方位前缀 + 已知缩写”）。
    known_abbrs = {t.term for t in terms if is_abbrev_term(t.term)}
    leaks, pres = [], []
    for sid, v in tr.items():
        zh = v["zh"]
        if any(p in zh for p in PROMPT_LEAK) or PRE_TAG.match(zh):
            leaks.append(sid)
        hits = [m.group(0) for m in PREFIX_RESIDUE.finditer(zh)
                if m.group(2) in known_abbrs]
        if hits:
            pres.append((sorted(set(hits))[:5], sid))
    print(f"  [F] prompt 泄漏: {len(leaks)} 段   |   残留“方位前缀+已知缩写”: {len(pres)} 段")
    for m, sid in pres[:5]:
        print(f"      {m}  {loc(sid)}")


def main() -> int:
    ap = argparse.ArgumentParser(description="跨文档 QA：全量翻译后主动挑毛病。")
    ap.add_argument("--doc", nargs="*", default=None,
                    help="只检查指定 doc_id（默认扫 data/translation/ 下全部文档）")
    args = ap.parse_args()

    docs = processed_docs(ROOT)
    if args.doc:
        wanted = set(args.doc)
        for m in sorted(wanted - {d for d, _ in docs}):
            print(f"[跳过] 找不到 {m} 的轨A 产物（data/translation/{m}.json）")
        docs = [d for d in docs if d[0] in wanted]
    if not docs:
        print("[错误] data/translation/ 下没有任何产物；先跑 tools/run_pipeline.py")
        return 1

    print(f"待检查 {len(docs)} 篇："
          + ", ".join(f"{d}(field={f or '无'})" for d, f in docs))
    for doc_id, field in docs:
        try:
            check_doc(doc_id, field)
        except Exception as e:  # noqa: BLE001
            import traceback
            print(f"\n■ {doc_id}: 检查抛异常 {type(e).__name__}: {e}")
            print("   " + traceback.format_exc().replace("\n", "\n   ")[:500])
    return 0


if __name__ == "__main__":
    sys.exit(main())
