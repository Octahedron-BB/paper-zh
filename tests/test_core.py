"""核心逻辑测试：**不需要任何 API 密钥**，用 MockProvider + 合成段落验证设计。

这份测试要证明的三件事（也就是本项目最重要的三个设计承诺）：
  1. 改一个 `prompt_hint` 术语 -> **只有真正命中它的段落**失效
  2. 改一个 `hard_replace` 术语 -> **零段失效**，且译文立刻变对（0 token）
  3. 缓存确实按"段 + 命中术语 + 模型 + prompt 版本"隔离

跑法：
    python tests/test_core.py
（函数名都叫 test_*，所以 pytest 也能直接收集。）
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from src.cache import Cache, key_for_translation, dirty_segments  # noqa: E402
from src.glossary import (  # noqa: E402
    MODE_HARD, MODE_HINT, Term, TermConflictError, apply_hard_replace,
    hits_for_text, load_glossary_dir, resolve_terms, scope_rank,
)
from src.model import Segment, make_sid, sha1  # noqa: E402
from src.providers import MockProvider  # noqa: E402
from src.textnorm import normalize_zh  # noqa: E402

SEC = "intro"
MODEL = "deepseek-chat"
PROMPT_V = "v1"


def seg(i: int, text: str) -> Segment:
    return Segment(sid=make_sid("doc", SEC, i), doc_id="doc", sec_path=SEC,
                   sec_heading="Introduction", sec_level=1, index=i, page=1,
                   src_text=text, n_words=len(text.split()))


SEGS = [
    seg(1, "Inhibitory control is central to retrieval stopping."),
    seg(2, "Transdiagnostic factors underlie intrusive thinking."),
    seg(3, "The hippocampus shows GABAergic inhibition during suppression."),
]

T_IC = Term("inhibitory control", "抑制控制", MODE_HARD, aliases=["抑制性控制"])
T_TD = Term("transdiagnostic", "跨诊断", MODE_HINT, note="强调跨多种疾病类别")
T_GABA = Term("GABAergic inhibition", "GABA 能抑制", MODE_HARD)


# ---------------------------------------------------------------- 1. 命中范围

def test_hit_detection_is_scoped_to_each_segment():
    terms = [T_IC, T_TD, T_GABA]
    assert [t.term for t in hits_for_text(terms, SEGS[0].src_text)] == ["inhibitory control"]
    assert [t.term for t in hits_for_text(terms, SEGS[1].src_text)] == ["transdiagnostic"]
    assert [t.term for t in hits_for_text(terms, SEGS[2].src_text)] == ["GABAergic inhibition"]


def test_hit_detection_handles_case_hyphen_and_plural():
    assert Term("inhibitory control", "x", MODE_HARD).hits("Inhibitory-Control task")
    assert Term("intrusive thought", "x", MODE_HARD).hits("intrusive thoughts")
    # 不能误伤：作为更长单词的一部分时不该命中
    assert not Term("SIF", "x", MODE_HARD).hits("CLASSIFY")
    assert Term("SIF", "x", MODE_HARD, pattern=r"(?<![A-Za-z])SIF(?![A-Za-z])").hits("the SIF effect")


# ------------------------------------------------ 6. 作用域（同名异义）

DOC = "paper-A"
OTHER_DOC = "paper-B"


def test_scope_rank_prefix_lengths():
    """守住一个曾经真实存在的 bug：scope 前缀长度写错会让条目被静默丢弃。"""
    assert scope_rank("global", DOC, "neuroscience") == 0
    assert scope_rank("field:neuroscience", DOC, "neuroscience") == 1
    assert scope_rank("field:immunology", DOC, "neuroscience") == -1
    assert scope_rank(f"doc:{DOC}", DOC, "neuroscience") == 2
    assert scope_rank(f"doc:{OTHER_DOC}", DOC, "neuroscience") == -1


def test_doc_scope_overrides_field_and_global():
    """MSN 的真实案例：全局/学科默认是中棘神经元，但本文指的是内侧隔核。"""
    terms = [
        Term("MSN", "中型棘状神经元", MODE_HARD, scope="global"),
        Term("MSN", "内侧隔核", MODE_HARD, scope=f"doc:{DOC}"),
    ]
    eff, conflicts = resolve_terms(terms, doc_id=DOC, strict=False)
    assert conflicts == []
    assert len(eff) == 1, "同名条目必须被归并成一条"
    assert eff[0].zh == "内侧隔核", f"doc 级应覆盖 global，实际得到 {eff[0].zh}"

    # 换成另一篇文章：doc 覆盖不生效，回落到 global
    other, _ = resolve_terms(terms, doc_id=OTHER_DOC, strict=False)
    assert other[0].zh == "中型棘状神经元"


def test_field_scope_does_not_leak_to_other_fields():
    terms = [
        Term("MTL", "内侧颞叶", MODE_HARD, scope="field:neuroscience"),
        Term("MTL", "膜转运实验室", MODE_HARD, scope="field:cell-biology"),
    ]
    neuro, _ = resolve_terms(terms, doc_id=DOC, field="neuroscience", strict=False)
    assert [t.zh for t in neuro] == ["内侧颞叶"]
    cell, _ = resolve_terms(terms, doc_id=DOC, field="cell-biology", strict=False)
    assert [t.zh for t in cell] == ["膜转运实验室"]


def test_same_rank_conflict_stops_loudly():
    """同级两种译法必须抛错中止，绝不静默挑一个。"""
    bad = [Term("MSN", "内侧隔核", MODE_HARD, scope="global"),
           Term("MSN", "中棘神经元", MODE_HARD, scope="global")]
    try:
        resolve_terms(bad, doc_id=DOC, strict=True)
        raise AssertionError("同级冲突竟然没被拦住")
    except TermConflictError:
        pass
    # strict=False 时要能把冲突报告出来，而不是吞掉
    _eff, conflicts = resolve_terms(bad, doc_id=DOC, strict=False)
    assert len(conflicts) == 1 and conflicts[0].term == "MSN"


def test_load_glossary_dir_applies_doc_override():
    """整体串起来：主表 + glossary-d/<doc>.yaml 覆盖后，本文生效的译法要正确。"""
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    try:
        (tmp / "glossary-d").mkdir()
        (tmp / "glossary.yaml").write_text(
            "terms:\n"
            "  - term: MSN\n    zh: 中棘神经元\n    mode: hard_replace\n"
            "    full_en: medium spiny neurons\n    scope: field:neuroscience\n",
            encoding="utf-8")
        (tmp / "glossary-d" / f"{DOC}.yaml").write_text(
            "terms:\n"
            "  - term: MSN\n    zh: 内侧隔核\n    mode: hard_replace\n"
            f"    full_en: medial septal nucleus\n    scope: doc:{DOC}\n",
            encoding="utf-8")
        got = load_glossary_dir(tmp, doc_id=DOC, field="neuroscience")
        msn = [t for t in got if t.term == "MSN"]
        assert len(msn) == 1 and msn[0].zh == "内侧隔核", f"实际: {[t.zh for t in msn]}"
        assert msn[0].full_en == "medial septal nucleus"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_hard_replace_change_costs_zero_retranslation():
    """改 hard_replace 的译法，不应造成任何段落需要重译。"""
    tmp = Path(tempfile.mkdtemp())
    try:
        cache = Cache(tmp)
        before = [T_IC, T_TD, T_GABA]
        # 假装已经翻译过：按"只含 prompt_hint 命中"的键写入缓存
        for s in SEGS:
            k = key_for_translation(model_id=MODEL, prompt_version=PROMPT_V,
                                    src_hash=s.src_hash,
                                    hit_terms=[t for t in before
                                               if t.mode == MODE_HINT and t.hits(s.src_text)])
            cache.put(k, f"译文 of {s.index}", {"src": s.sid})

        # 现在改 hard_replace 条目的译法（抑制控制 -> 抑制控制力，并加一个新别名）
        changed = [Term("inhibitory control", "抑制控制力", MODE_HARD,
                        aliases=["抑制性控制", "抑制控制"]),
                   T_TD, T_GABA]
        dirty = dirty_segments(SEGS, changed, cache, model_id=MODEL, prompt_version=PROMPT_V)
        assert dirty == [], f"hard_replace 改动不该触发重译，却脏了 {len(dirty)} 段"

        # 而且译文通过纯字符串替换立刻变对：0 token
        old_translation = "本研究表明，抑制性控制对检索停止至关重要。"
        fixed = apply_hard_replace(changed, old_translation)
        assert "抑制控制力" in fixed and "抑制性控制" not in fixed
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_hard_terms_are_excluded_from_cache_key():
    """同一个 hard_replace 术语改译法，缓存键必须完全不变（这是上一条的机制保证）。"""
    a = key_for_translation(model_id=MODEL, prompt_version=PROMPT_V,
                            src_hash="h", hit_terms=[])
    b = key_for_translation(model_id=MODEL, prompt_version=PROMPT_V,
                            src_hash="h", hit_terms=[])
    assert a == b
    # 传进来的只能是 prompt_hint；若混入 hard 术语，键会变化 -> 由 dirty_segments 负责过滤
    c = key_for_translation(model_id=MODEL, prompt_version=PROMPT_V,
                            src_hash="h", hit_terms=[T_IC])
    assert a != c, "控制变量：如果 hard 术语被算进键里，键就会变（所以必须过滤）"


# --------------------------------------- 3. prompt_hint 改动只失效命中的段

def test_prompt_hint_change_invalidates_only_hitting_segments():
    tmp = Path(tempfile.mkdtemp())
    try:
        cache = Cache(tmp)
        base = [T_IC, T_TD, T_GABA]
        for s in SEGS:
            k = key_for_translation(
                model_id=MODEL, prompt_version=PROMPT_V, src_hash=s.src_hash,
                hit_terms=[t for t in base
                           if t.mode == MODE_HINT and t.hits(s.src_text)])
            cache.put(k, f"译文 of {s.index}", {})

        # 改 prompt_hint 术语的 note（transdiagnostic 只出现在第 2 段）
        changed = [T_IC,
                   Term("transdiagnostic", "跨诊断", MODE_HINT, note="改了说明"),
                   T_GABA]
        dirty = dirty_segments(SEGS, changed, cache, model_id=MODEL, prompt_version=PROMPT_V)
        assert [s.index for s in dirty] == [2], \
            f"应该只有第 2 段失效，实际 {[s.index for s in dirty]}"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ------------------------------------------------------------- 4. 缓存与失效

def test_cache_roundtrip_and_model_isolation():
    tmp = Path(tempfile.mkdtemp())
    try:
        cache = Cache(tmp)
        k1 = key_for_translation(model_id="deepseek-chat", prompt_version=PROMPT_V,
                                 src_hash="h1", hit_terms=[])
        k2 = key_for_translation(model_id="gemini-3-flash", prompt_version=PROMPT_V,
                                 src_hash="h1", hit_terms=[])
        assert k1 != k2, "换模型必须导致缓存隔离"
        cache.put(k1, "hello", {"m": "x"})
        hit = cache.get(k1)
        assert hit is not None and hit.value == "hello" and hit.meta["m"] == "x"
        assert cache.get(k2) is None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_prompt_version_bump_invalidates_everything():
    tmp = Path(tempfile.mkdtemp())
    try:
        cache = Cache(tmp)
        for s in SEGS:
            cache.put(key_for_translation(model_id=MODEL, prompt_version="v1",
                                          src_hash=s.src_hash, hit_terms=[]), "旧", {})
        dirty = dirty_segments(SEGS, [T_IC, T_TD, T_GABA], cache,
                               model_id=MODEL, prompt_version="v2")
        assert len(dirty) == len(SEGS), "改 prompt 版本应让全部段落失效"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_changing_source_text_invalidates():
    tmp = Path(tempfile.mkdtemp())
    try:
        cache = Cache(tmp)
        cache.put(key_for_translation(model_id=MODEL, prompt_version=PROMPT_V,
                                      src_hash=SEGS[0].src_hash, hit_terms=[]), "旧", {})
        edited = seg(1, SEGS[0].src_text + " And one more clause.")
        dirty = dirty_segments([edited], [T_IC, T_TD, T_GABA], cache,
                               model_id=MODEL, prompt_version=PROMPT_V)
        assert len(dirty) == 1, "原文变了（PDF 改版/重切）必须让该段失效"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --------------------------------------------------------------- 5. Provider

def test_mock_provider_is_offline_and_deterministic():
    p = MockProvider(script={"retrieval stopping": "预置译文"})
    assert p.complete("sys", "about retrieval stopping") == "预置译文"
    out = p.complete("sys", "some other text")
    assert out.startswith("[MOCK:mock-1]")
    assert len(p.calls) == 2


# ------------------------------------------------------------ 6. 数字格式

def test_number_thousands_separator_is_normalized():
    # 全角逗号做千分位是排版错误，而且 TTS 会读成停顿（「二，三百七十三」）
    assert normalize_zh("共2，373例患者") == "共2,373例患者"
    assert normalize_zh("12，345，678") == "12,345,678"
    assert normalize_zh("２，３７３") == "2,373"


def test_number_normalization_does_not_touch_chinese_punctuation():
    # 中文列举里的顿号/逗号不能改；后面不是正好 3 位数字时也不改
    assert normalize_zh("第一，第二，第三") == "第一，第二，第三"
    assert normalize_zh("包括焦虑、抑郁，以及躁狂") == "包括焦虑、抑郁，以及躁狂"
    assert normalize_zh("分组为1，2，3组") == "分组为1，2，3组"
    assert normalize_zh("") == ""
    # 幂等
    once = normalize_zh("共2，373例")
    assert normalize_zh(once) == once


def test_duplicated_cjk_word_is_collapsed():
    # 实测：口语稿里出现过 "也就是 think/no-think 任务 任务，得到的直接测量之外"
    assert (normalize_zh("也就是 think/no-think 任务 任务，得到的直接测量")
            == "也就是 think/no-think 任务，得到的直接测量")
    assert normalize_zh("另一项任务 任务 里") == "另一项任务 里"


def test_duplicate_collapse_does_not_touch_legit_reduplication():
    # 汉语合法叠词不带空格，不能被改
    assert normalize_zh("慢慢地走") == "慢慢地走"
    assert normalize_zh("许多许多年") == "许多许多年"
    # 不允许跨行合并（否则会把两段粘连）
    assert normalize_zh("这是一个任务\n\n任务到此结束") == "这是一个任务\n\n任务到此结束"
    # 英文重复不管
    assert normalize_zh("the the task") == "the the task"


def _run() -> int:
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    failed = 0
    print("=" * 68)
    for name, fn in tests:
        try:
            fn()
            print(f"  [PASS] {name}")
        except AssertionError as e:
            failed += 1
            print(f"  [FAIL] {name}\n       {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  [ERR ] {name}\n       {type(e).__name__}: {e}")
            import traceback
            print("       " + traceback.format_exc().replace("\n", "\n       ")[:800])
    print("=" * 68)
    print(f"{len(tests) - failed}/{len(tests)} 通过")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run())
