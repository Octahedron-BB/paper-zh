"""文献速览（digest）的离线测试：**不联网、不调用 LLM**。

这里锁的都是"不会报错、只会让你做错事"的静默错误——本项目最怕的那一类。
特别是 `test_snapshot_picks_newest_by_content_not_filename`：它的症状是
"手机上看到的是 A 期，电脑上 --pick 3 却指到 B 期的第 3 条"，
中间没有任何报错，只会安静地跑错一篇文献。

跑法（假设 Python 环境已激活；Windows / macOS 通用）：
    python tests/test_digest.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import tools.build_digest as bd  # noqa: E402
from src.feed import FeedItem, doi_to_doc_id, journal_to_field, upsert  # noqa: E402


def _item(**over) -> FeedItem:
    base = dict(pmid="1", doi="10.1038/s41581-026-01131-8",
                doc_id="s41581-026-01131-8", journal="Nature reviews. Nephrology",
                journal_abbr="Nat Rev Nephrol", title_en="T", abstract="A",
                pub_date="2026-09-18", entrez_date="2026-09-18",
                term_field="nephrology")
    base.update(over)
    return FeedItem(**base)


# --------------------------------------------------------------- 快照

def test_snapshot_picks_newest_by_content_not_filename():
    """⚠️ 回归：按文件名 `sorted()[-1]` 取快照是错的。

    排序里 `-`(0x2D) < `.`(0x2E)，于是 `2026-09-21-0843.json` 排在
    `2026-09-21.json` **前面**，取最后一个反而拿到**旧的那一期**。
    """
    old = bd.OUT_DIR
    with tempfile.TemporaryDirectory() as td:
        bd.OUT_DIR = Path(td)
        try:
            def write(name: str, stamp: str, count: int) -> None:
                (Path(td) / f"{name}.json").write_text(json.dumps(
                    {"date": "2026-09-21", "snapshot": name,
                     "generated_at": stamp, "count": count, "items": []},
                    ensure_ascii=False), encoding="utf-8")

            write("2026-09-21", "2026-09-21T08:00:00", 1)
            write("2026-09-21-0843", "2026-09-21T08:43:00", 2)

            snap, p = bd.load_snapshot()
            assert p.name == "2026-09-21-0843.json", f"取到了旧快照：{p.name}"
            assert snap["snapshot"] == "2026-09-21-0843"

            # 顺便证明这个测试是有意义的：文件名排序确实会取错
            naive = sorted(x.name for x in Path(td).glob("*.json"))[-1]
            assert naive == "2026-09-21.json", "文件名排序的假设变了，本测试需重审"
        finally:
            bd.OUT_DIR = old


def test_unique_stem_never_overwrites():
    """同一日期重复跑，必须换名，不能覆盖已发到手机的那一期。"""
    old = bd.OUT_DIR
    with tempfile.TemporaryDirectory() as td:
        bd.OUT_DIR = Path(td)
        try:
            when = datetime(2026, 9, 21, 8, 43)
            assert bd.unique_stem("2026-09-21", when) == "2026-09-21"
            (Path(td) / "2026-09-21.json").write_text("{}", encoding="utf-8")
            assert bd.unique_stem("2026-09-21", when) == "2026-09-21-0843"
            (Path(td) / "2026-09-21-0843.json").write_text("{}", encoding="utf-8")
            assert bd.unique_stem("2026-09-21", when) == "2026-09-21-0843-2"
        finally:
            bd.OUT_DIR = old


def test_load_snapshot_by_name():
    old = bd.OUT_DIR
    with tempfile.TemporaryDirectory() as td:
        bd.OUT_DIR = Path(td)
        try:
            (Path(td) / "2026-09-20.json").write_text(json.dumps(
                {"date": "2026-09-20", "generated_at": "2026-09-20T09:00:00",
                 "count": 5, "items": []}), encoding="utf-8")
            snap, p = bd.load_snapshot("2026-09-20")
            assert snap["count"] == 5 and p.name == "2026-09-20.json"
        finally:
            bd.OUT_DIR = old


# --------------------------------------------------------------- 计长与判据

def test_reading_len_treats_latin_runs_as_one():
    """一串连续拉丁字母/数字算 1 个字——这是与 prompt 一致的口径。"""
    assert bd.reading_len("") == 0
    assert bd.reading_len("铁死亡") == 3
    assert bd.reading_len("T2DM") == 1
    assert bd.reading_len("BRCA1-BARD1") == 1
    assert bd.reading_len("53BP1") == 1, "数字开头的缩写不能被切成两段"
    assert bd.reading_len("与 T2DM 相关") == 4, "与X相关"
    # 用 len() 会把它算成 40（缩写、空格全被当成字）——实测值，不是估的
    good = "BRCA1-BARD1 与 53BP1 轴拮抗决定 HR 或 NHEJ 的选择。"
    assert len(good) == 40, f"实际 len={len(good)}"
    assert bd.reading_len(good) == 15, f"实际 reading_len={bd.reading_len(good)}"


def test_brief_verdict_matches_prompt_rules():
    """检查器必须与 prompt 用同一套判据，否则"看着都合格"是假的。"""
    # 缩写多但读起来短 -> 必须判合格（用 len() 会被误报）
    assert bd.brief_verdict("BRCA1-BARD1 与 53BP1 轴拮抗决定 HR 或 NHEJ 的选择。")[0] == "✅"
    # 字数够短，但有 2 个逗号 / 3 个分句 -> prompt 明令禁止，必须抓到
    mark, why = bd.brief_verdict(
        "MENA地区肥胖与T2DM负担被低估，海湾国家已高发，北非正快速攀升。")
    assert mark == "⚠️" and "逗号" in why, f"分句过多没被抓到：{mark} {why}"
    # 过长
    assert bd.brief_verdict("这是一个很长的提要句子啊" * 6)[0] == "⚠️"
    # 空
    assert bd.brief_verdict("   ")[0] == "❌"


# --------------------------------------------------------------- 归一化

def test_doi_to_doc_id_matches_pipeline_rule():
    """doc_id 必须等于 DOI 后缀，且与本地已有 PDF 的文件名规则一致。"""
    assert doi_to_doc_id("10.1038/s41583-025-00929-y") == "s41583-025-00929-y"
    assert doi_to_doc_id("10.1038/s41575-024-00932-1") == "s41575-024-00932-1"
    assert doi_to_doc_id("10.1038/s41574-022-00638-x") == "s41574-022-00638-x"
    assert doi_to_doc_id("10.1038/nrdp.2018.8") == "nrdp.2018.8"
    assert doi_to_doc_id("") == ""
    # 与 papers/ 里真实的文件名对齐（这才是"跨设备可复现"的意思）
    for stem in ("s41583-025-00929-y", "s41575-024-00932-1", "s41574-022-00638-x"):
        assert doi_to_doc_id(f"10.1038/{stem}") == stem


def test_journal_to_field():
    assert journal_to_field("Nature reviews. Neuroscience") == "neuroscience"
    assert journal_to_field("Nature reviews. Neurology") == "neurology"
    assert journal_to_field("Nature reviews. Endocrinology") == "endocrinology"
    assert journal_to_field("Nature reviews. Immunology") == "immunology"
    assert journal_to_field("Nature reviews bioengineering") == "bioengineering"
    assert journal_to_field("Nature reviews. Gastroenterology & hepatology") \
        == "gastroenterology-hepatology"
    assert journal_to_field("") == "unknown"


def test_run_command_is_copy_pasteable():
    it = _item()
    assert it.run_command == (
        "python tools/run_pipeline.py s41581-026-01131-8 --field nephrology --stage all")
    assert it.url_pubmed == "https://pubmed.ncbi.nlm.nih.gov/1/"
    assert it.url_doi == "https://doi.org/10.1038/s41581-026-01131-8"
    # 没有 field 时不应留下多余空格
    assert "  " not in _item(term_field="").run_command


def test_feeditem_roundtrip_ignores_snapshot_only_keys():
    it = _item()
    d = it.to_dict()
    d["n"] = 7                      # 快照才会加的键
    d["url_pubmed"] = "u"
    d["run_command"] = "c"
    back = FeedItem.from_dict(d)
    assert back.pmid == "1" and back.status == "new" and back.brief == ""


# --------------------------------------------------------------- 状态不变量

def test_upsert_preserves_local_state_and_generations():
    """重跑检索不能把本地状态、已生成的提要冲掉——但 PubMed 侧的事实要更新。"""
    store: dict = {}
    fresh = upsert(store, [_item()])
    assert len(fresh) == 1 and store["1"]["status"] == "new"

    store["1"]["status"] = "picked"
    store["1"]["brief"] = "已生成的提要"
    store["1"]["title_zh"] = "已生成的标题"

    fresh2 = upsert(store, [_item(title_en="更新后的标题", abstract="A2")])
    assert fresh2 == [], "重复检索不该被当成新条目（否则会重复推送）"
    assert store["1"]["status"] == "picked", "本地状态被冲掉了"
    assert store["1"]["brief"] == "已生成的提要", "已生成的提要被冲掉了"
    assert store["1"]["title_zh"] == "已生成的标题"
    assert store["1"]["title_en"] == "更新后的标题", "PubMed 侧的事实应当更新"


def test_pending_returns_copies_so_generations_must_be_written_back():
    """⚠️ 回归：`pending()` 返回的是**副本**，生成物必须显式写回状态库。

    不写回的症状极隐蔽：快照里提要好端端的，只是状态库那一栏永远是空的 ——
    不报错，而且要到"想把某条改回 new 重推"时才会发现。
    """
    from src.feed import pending, save_generations
    store: dict = {}
    upsert(store, [_item()])
    pend = pending(store)
    assert pend, "应有 1 条待推"
    pend[0].brief = "生成的提要"
    pend[0].title_zh = "生成的标题"
    assert store["1"]["brief"] == "", "此刻状态库还不该有 brief（证明 pending 给的是副本）"
    assert save_generations(store, pend) == 1
    assert store["1"]["brief"] == "生成的提要"
    assert store["1"]["title_zh"] == "生成的标题"
    # 状态不能因为写回生成物而被改掉
    assert store["1"]["status"] == "new"


def test_runlog_tees_output_and_rotates():
    """运行日志必须同时写控制台与文件，并在超限时轮转。

    它是"定时任务到底做了什么"的**唯一**证据来源：任务计划里拿不到 stdout，
    `LastTaskResult` 只能说明"进程正常结束"，不说明它推了几条还是什么都没推。
    """
    import src.runlog as rl
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "run-log.txt"
        try:
            rl.detach()
            assert rl.attach(p, ["--self-test"]) == p and p.exists(), "日志文件应被创建"
            print("测试输出-hello-log")
            sys.stdout.flush()
            body = p.read_text(encoding="utf-8")
            assert "--self-test" in body, "应记录命令行参数"
            assert "测试输出-hello-log" in body, "print 的输出应进日志"

            rl.detach()                       # 超限轮转
            p.write_text("x" * (rl.MAX_BYTES + 1), encoding="utf-8")
            rl.attach(p, ["--again"])
            assert (Path(td) / "run-log.1.txt").exists(), "超限时应轮转为 .1.txt"
            assert p.exists() and p.stat().st_size < rl.MAX_BYTES, "轮转后应是新文件"
        finally:
            rl.detach()


def test_runlog_never_breaks_the_run_when_path_is_unwritable():
    """日志写不了**不该**把主流程拖死 —— 定时任务里这会导致整周静默不推。"""
    import src.runlog as rl
    try:
        rl.detach()
        # Windows 上文件名里的 ':' 非法；父目录是文件（不是目录）也能稳定失败
        with tempfile.NamedTemporaryFile() as f:
            bad = Path(f.name) / "sub" / "run-log.txt"
            assert rl.attach(bad, ["--x"]) is None, "写不了应返回 None 而不是抛异常"
            print("仍然要能正常输出")
    finally:
        rl.detach()


def test_store_roundtrip_is_atomic_and_readable(tmpdir: str | None = None):
    from src.feed import load_store, save_store
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "items.json"
        save_store({"1": _item().to_dict()}, p)
        assert load_store(p)["1"]["pmid"] == "1"
        assert not list(Path(td).glob("*.tmp")), "原子写留下了临时文件"


# --------------------------------------------------------------- LLM 输出解析

def test_parse_payload_tolerates_fences_and_garbage():
    d = bd.parse_payload('```json\n{"title_zh":"甲","brief":"乙","detail":"丙"}\n```')
    assert d == {"title_zh": "甲", "brief": "乙", "detail": "丙"}
    d2 = bd.parse_payload('啰嗦的前言 {"title_zh":"甲","brief":"乙","detail":"丙"} 后记')
    assert d2["brief"] == "乙"
    d3 = bd.parse_payload("完全不是 JSON")
    assert d3 == {"title_zh": "", "brief": "", "detail": ""}
    # 缺字段不能抛异常（一条失败不该毁掉整期）
    d4 = bd.parse_payload('{"brief":"只有这一个字段"}')
    assert d4["brief"] == "只有这一个字段" and d4["detail"] == ""


# --------------------------------------------------------------- 跑测试

def _run() -> int:
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    failed = 0
    print("=" * 70)
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
    print("=" * 70)
    print(f"{len(tests) - failed}/{len(tests)} 通过")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run())
