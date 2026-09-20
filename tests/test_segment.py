"""分段器的回归测试（离线，不需要密钥）。

为什么单独一个文件：分段是 bug 最密集的地方（历史上 21 个 bug 里约 10 个在这里），
而 `test_core.py` 只覆盖术语/缓存/后处理，分段器之前**一个测试都没有** ——
每加一篇新期刊都在裸奔。

这里大部分是**结构不变量**而不是写死的数字，因为不变量才是真正该守的东西：
它们能抓到历史上真实发生过的那些 bug（下面每条都注明了对应的历史案例）。

跑法：
    python tests\\test_segment.py            # 正常校验
    python tests\\test_segment.py --update   # 变更后刷新基准数字（只有确认改动是想要的才用）
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from src.segment import segment_pdf  # noqa: E402

CASES = [
    ("s41583-025-00929-y", "neuroscience"),
    ("s41575-024-00932-1", None),
    ("s41574-022-00638-x", None),
    ("vieta2018", None),
]
PAPERS = ROOT / "papers"
BASELINE = Path(__file__).resolve().parent / "segment_baseline.json"

_DOC_CACHE: dict[str, object] = {}


def doc_of(pdf_id: str):
    """同一篇只切一次，多个测试共用。"""
    if pdf_id not in _DOC_CACHE:
        p = PAPERS / f"{pdf_id}.pdf"
        if not p.exists():
            _DOC_CACHE[pdf_id] = None
        else:
            _DOC_CACHE[pdf_id] = segment_pdf(p, doc_id=pdf_id)
    return _DOC_CACHE[pdf_id]


def available() -> list[tuple[str, str | None]]:
    return [(i, f) for i, f in CASES if (PAPERS / f"{i}.pdf").exists()]


# ------------------------------------------------------------ 不变量测试

def test_all_sids_are_unique():
    """sid 必须唯一。

    历史 bug（s41574）：两段的 sid 完全相同 -> dict 静默覆盖 ->
    缓存、译文产物、音频定位三者同时丢掉一段，而且不报错。
    当时是因为 `Medication management in patients with T1DM.` 与 `...T2DM.`
    slug 化后被 40 字符上限截断成同一个路径。
    """
    for pdf_id, _ in available():
        d = doc_of(pdf_id)
        sids = [s.sid for s in d.segments]
        dup = [s for s, n in __import__("collections").Counter(sids).items() if n > 1]
        assert not dup, f"{pdf_id}: sid 撞车 {dup[:3]}"


def test_distinct_headings_do_not_share_sec_path():
    """同一个 sec_path 不能对应两个不同的标题（路径必须能唯一定位一个节）。"""
    for pdf_id, _ in available():
        d = doc_of(pdf_id)
        seen: dict[str, str] = {}
        for sec in d.sections:
            for sg in sec.segments:
                prev = seen.setdefault(sg.sec_path, sec.heading)
                assert prev == sec.heading, (
                    f"{pdf_id}: sec_path {sg.sec_path!r} 同时属于 {prev!r} 与 {sec.heading!r}")


def test_every_segment_is_real_text():
    """不能有空段、碎片段；词数上限防"整页粘连成一段"。

    历史 bug：正文字号判定写死绝对区间 -> 整篇只剩 6 段（43,914 字符全丢）。
    """
    for pdf_id, _ in available():
        d = doc_of(pdf_id)
        for s in d.segments:
            assert len(s.src_text.split()) >= 3, f"{pdf_id}: 段太短 {s.sid} {s.src_text[:60]!r}"
            assert s.n_words <= 420, f"{pdf_id}: 段过长 {s.n_words} 词 {s.sid}"


def test_no_table_residue_in_segments():
    """表格列文字不能混进正文。

    历史 bug（s41574）：表格单元格里混了一个正文体的上标引用，导致整行被判成正文，
    于是 `n= 26, men n= 69, men …` 被拼进段落中间。

    ⚠️ 判据必须认「表格列的重复特征」，不能只认单个 `n = 数字` ——
       正文里正当地引用样本量的写法很常见：
       「estimated to be from 12% (of n = 277) to 14% (of n = 404)」
       初版只匹配 `n = 数字`，第一次跑就对这段话误报了。
    """
    # 表格列特征：`n = 数字` 后面跟着 men/women，且连续出现 >=2 次
    col_pat = re.compile(r"(?:n\s*=\s*\d+\s*,?\s*(?:men|women)\b[\s,]*){2,}", re.IGNORECASE)
    only_pat = re.compile(r"^[\s\d,.()]+$")
    for pdf_id, _ in available():
        d = doc_of(pdf_id)
        for s in d.segments:
            assert not col_pat.search(s.src_text), (
                f"{pdf_id}: 表格列残留 {s.sid} {s.src_text[:90]!r}")
            assert not only_pat.match(s.src_text), f"{pdf_id}: 纯数字段 {s.sid}"


def test_headings_are_not_truncated():
    """标题不能是小写开头或断词（run-in 标题跨行截断的典型症状）。

    历史 bug：`oxidative stress.` -> `dative stress.`、`intermittent fasting.` -> `tent fasting.`
    （前一行以 `oxi-` / `intermit-` 结尾，连字符换行把前半截留在了上一行）
    """
    for pdf_id, _ in available():
        d = doc_of(pdf_id)
        bad = [s.heading for s in d.sections if s.heading[:1].islower()]
        assert not bad, f"{pdf_id}: 疑似被截断的小标题 {bad}"


def test_heading_panel_letters_are_stripped():
    """标题尾部不能粘上图板字母（`anal cancer.a`）。"""
    pat = re.compile(r"[a-z]\.[a-h]$")
    for pdf_id, _ in available():
        d = doc_of(pdf_id)
        bad = [s.heading for s in d.sections if pat.search(s.heading)]
        assert not bad, f"{pdf_id}: 标题粘了图板字母 {bad}"


def test_segmentation_is_deterministic():
    """同样的 PDF 切两次结果必须一致（否则缓存与 sid 锚点全部失去意义）。"""
    for pdf_id, _ in available()[:1]:
        a = doc_of(pdf_id)
        b = segment_pdf(PAPERS / f"{pdf_id}.pdf", doc_id=pdf_id)
        assert [s.sid for s in a.segments] == [s.sid for s in b.segments]
        assert [s.src_text for s in a.segments] == [s.src_text for s in b.segments]


def test_word_count_matches_baseline():
    """总词数不许莫名下降（这是"整篇文字悄悄丢失"的唯一守卫）。

    历史 bug 就是这么发现的：正文 9.2pt 的期刊被判成 6.0pt，
    43,914 字符消失，而**没有任何报错**。
    """
    base = json.loads(BASELINE.read_text(encoding="utf-8")) if BASELINE.exists() else {}
    for pdf_id, _ in available():
        d = doc_of(pdf_id)
        words = sum(s.n_words for s in d.segments)
        b = base.get(pdf_id)
        assert b is not None, f"{pdf_id}: 基准缺失（用 --update 生成）"
        lo, hi = b["words"] * 0.97, b["words"] * 1.03
        assert lo <= words <= hi, (
            f"{pdf_id}: 词数 {words} 偏离基准 {b['words']} 超过 3% —— "
            f"要么你改了分段逻辑（确认无误后用 --update 刷新基准），要么有文字在悄悄丢失")
        assert len(d.sections) >= b["sections_min"], (
            f"{pdf_id}: 节数 {len(d.sections)} 少于基准下限 {b['sections_min']}")


def write_baseline() -> None:
    out = {}
    for pdf_id, _ in available():
        d = doc_of(pdf_id)
        out[pdf_id] = {
            "sections": len(d.sections),
            # 允许 −2：修标题/摘要判据时，极少数伪节被合并是正常的
            "sections_min": max(1, len(d.sections) - 2),
            "segments": len(d.segments),
            "words": sum(s.n_words for s in d.segments),
        }
    BASELINE.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"已写入基准: {BASELINE}")
    for k, v in out.items():
        print(f"  {k}: {v['sections']} 节 / {v['segments']} 段 / {v['words']} 词")


def _run() -> int:
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    failed = 0
    print("=" * 68)
    print(f"可用样本: {[i for i, _ in available()]}")
    for name, fn in tests:
        try:
            fn()
            print(f"  [PASS] {name}")
        except AssertionError as e:
            failed += 1
            print(f"  [FAIL] {name}\n       {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            import traceback
            print(f"  [ERR ] {name}\n       {type(e).__name__}: {e}")
            print("       " + traceback.format_exc().replace("\n", "\n       ")[:600])
    print("=" * 68)
    print(f"{len(tests) - failed}/{len(tests)} 通过")
    return 1 if failed else 0


if __name__ == "__main__":
    if "--update" in sys.argv:
        write_baseline()
    sys.exit(_run())
