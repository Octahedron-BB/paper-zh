"""推送层的离线测试：**不联网、不发送任何消息**。

重点锁三件事：
  1. 多选/单选/`all` 的解析必须稳定（顺序固定，未配置的**跳过而不是报错**）；
  2. 分片不得超出渠道上限，也不得把一条提要切成两半；
  3. **输出里绝不能出现密钥的值**（只允许出现变量名）。

跑法（假设 Python 环境已激活；Windows / macOS 通用）：
    python tests/test_push.py
"""

from __future__ import annotations

import json
import os
import re
import sys
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import src.push as pch  # noqa: E402

SECRET = "SUPER-SECRET-TOKEN-DO-NOT-LEAK-12345"

PUSH_VARS = ("PUSHPLUS_TOKEN", "PUSHPLUS_TOPIC", "PUSHPLUS_TEMPLATE",
             "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "DISCORD_WEBHOOK_URL",
             "DISCORD_BOT_TOKEN", "DISCORD_CHANNEL_ID")


@contextmanager
def clean_env(**kv):
    """把推送相关的环境变量清干净再设值，结束后还原。

    必须"先清空"：否则开发机上真实的 .env 会影响测试结果（这类测试最忌讳
    依赖环境——本地过、换台机器就挂）。
    """
    old = {k: os.environ.get(k) for k in PUSH_VARS}
    for k in PUSH_VARS:
        os.environ.pop(k, None)
    os.environ.update({k: v for k, v in kv.items() if v is not None})
    try:
        yield
    finally:
        for k in PUSH_VARS:
            os.environ.pop(k, None)
        for k, v in old.items():
            if v is not None:
                os.environ[k] = v


def _snap(n: int, brief_len: int = 25) -> dict:
    items = [{
        "n": i,
        "brief": "标" * brief_len,
        "title_zh": f"中文标题{i}",
        "title_en": f"English title {i}",
        "journal": "Nature reviews. Neuroscience",
        "journal_abbr": "Nat Rev Neurosci",
        "doi": "10.1038/s41583-026-01131-8",
        "url_doi": "https://doi.org/10.1038/s41583-026-01131-8",
        "url_pubmed": "https://pubmed.ncbi.nlm.nih.gov/1/",
        "run_command": "python tools/run_pipeline.py x --stage all",
        "doc_id": f"s41583-026-{i:05d}-x",
        "pub_date": "2026-09-18",
        "entrez_date": "2026-09-18",
        "detail": "细" * 100,
        "status": "shown",
    } for i in range(1, n + 1)]
    return {"date": "2026-09-21", "count": n, "items": items}


# --------------------------------------------------------------- 渠道选择

def test_resolve_channels_single_multi_and_all():
    with clean_env(TELEGRAM_BOT_TOKEN="t", TELEGRAM_CHAT_ID="c",
                   DISCORD_WEBHOOK_URL="https://discord.example/hook"):
        assert pch.resolve_channels("telegram") == (["telegram"], []), "单选失败"
        # 顺序固定为注册表顺序，便于输出稳定（与用户输入的先后无关）
        chans, _ = pch.resolve_channels("discord,telegram")
        assert chans == ["telegram", "discord"], f"顺序不稳定：{chans}"
        # 空格等价于逗号 —— 是**两个**渠道，不是一个带空格的名字
        assert pch.resolve_channels("telegram discord")[0] == ["telegram", "discord"], \
            "空格分隔应等同于逗号分隔"
        # all：未配置的**跳过**而不是报错
        chans, skipped = pch.resolve_channels("all")
        assert chans == ["telegram", "discord"], f"all 结果不对：{chans}"
        assert len(skipped) == 1 and "wechat" in skipped[0], f"skipped={skipped}"
        # 重复写同一个渠道不该重复发送
        assert pch.resolve_channels("telegram,telegram")[0] == ["telegram"], "重复项未去重"


def test_resolve_channels_errors_are_actionable():
    with clean_env():
        for bad, needle in [("slack", "slack"), ("", "未指定")]:
            try:
                pch.resolve_channels(bad)
            except pch.PushError as e:
                msg = str(e)
                assert needle in msg, f"{bad!r} 的报错没提到问题本身：{msg}"
                assert "wechat" in msg, "报错应列出可选渠道"
            else:
                raise AssertionError(f"{bad!r} 应当报错")


def test_discord_accepts_webhook_or_bot_token():
    with clean_env(DISCORD_WEBHOOK_URL="https://discord.example/hook"):
        assert pch.missing_keys("discord") == []
    with clean_env(DISCORD_BOT_TOKEN="t", DISCORD_CHANNEL_ID="1"):
        assert pch.missing_keys("discord") == []
    with clean_env(DISCORD_BOT_TOKEN="t"):          # 只有 token 没有频道 → 不算配好
        assert pch.missing_keys("discord"), "缺频道 ID 必须报出来"


def test_missing_keys_reports_names_never_values():
    with clean_env():
        rows = {c: (ready, note) for c, ready, note in pch.channel_status()}
        assert not rows["wechat"][0] and "PUSHPLUS_TOKEN" in rows["wechat"][1]
        assert not rows["telegram"][0] and "TELEGRAM_BOT_TOKEN" in rows["telegram"][1]
        assert not rows["discord"][0] and "DISCORD_WEBHOOK_URL" in rows["discord"][1]
    # 配好之后同样只出现名字
    with clean_env(PUSHPLUS_TOKEN=SECRET):
        rows = {c: (r, n) for c, r, n in pch.channel_status()}
        assert rows["wechat"][0] and SECRET not in rows["wechat"][1]


# --------------------------------------------------------------- 分片

def test_messages_never_exceed_channel_limit():
    snap = _snap(200)                    # 故意塞爆，验证截断路径
    for ch, pol in pch.POLICY.items():
        if pch._fmt_for(ch) == "html":
            msgs = pch.build_messages(snap, ch)
            assert len(msgs) == 1, f"{ch}: html 详情页应合成一条"
            assert len(msgs[0]) <= pch.WECHAT_MAX_CONTENT, \
                f"{ch}: html 全长 {len(msgs[0])} 超出 {pch.WECHAT_MAX_CONTENT}"
            continue
        for style in ("brief", "full"):
            msgs = pch.build_messages(snap, ch, style=style)
            assert len(msgs) <= pol["max_messages"], f"{ch}/{style} 消息数超限"
            for m in msgs:
                assert len(m) <= pol["chunk"], \
                    f"{ch}/{style} 单条 {len(m)} 字，超出上限 {pol['chunk']}"


def test_items_are_never_split_across_messages():
    snap = _snap(40)
    for ch in pch.CHANNELS:
        body = "\n".join(pch.build_messages(snap, ch))
        is_html = pch._fmt_for(ch) == "html"
        for it in snap["items"]:
            # 提要本身必须完整出现（两种格式都成立）
            assert it["brief"] in body, f"{ch}: 第 {it['n']} 条的提要被切断了"
            if is_html:
                # 只断言"序号后面紧跟一个闭合标签"，**不写死标签名** ——
                # 之前写死 </span>，一改 markup（span→b）就挂，属于断言跟着实现走。
                assert f">{it['n']}.</" in body, f"{ch}: 第 {it['n']} 条序号丢了"
            else:
                assert f"{it['n']}. {it['brief']}" in body, f"{ch}: 第 {it['n']} 条被切断了"
        assert "本条截断" not in body, f"{ch}: 正常长度不该触发硬切"
        assert "没显示" not in body, f"{ch}: 40 条不该触发截断"


def test_wechat_never_spams_and_says_what_it_dropped():
    msgs = pch.build_messages(_snap(400), "wechat", style="full")
    assert len(msgs) == 1, "微信是通知，不该刷屏"
    assert ("没显示" in msgs[0]) or ("没发完" in msgs[0]), "截断了却没告诉用户"
    assert len(msgs[0]) <= pch.WECHAT_MAX_CONTENT, "超了微信 2 万字上限"


def test_wechat_html_escapes_untrusted_text():
    """提要是 LLM/PubMed 来的文本，出现 `<` `&` 必须转义 ——
    否则详情页 DOM 会坏，而且症状是"页面显示错乱"而不是报错。"""
    snap = _snap(1)
    snap["items"][0]["brief"] = 'a < b & "c" <script>alert(1)</script>'
    snap["items"][0]["journal"] = "Nature reviews. <b>X</b>"
    snap["items"][0]["journal_abbr"] = "<b>X</b>"
    msg = pch.build_messages(snap, "wechat")[0]
    assert "<script>" not in msg, "未转义，有破版/注入风险"
    assert "&lt;script&gt;" in msg, "尖括号应被转义"
    assert "&amp;" in msg, "& 应被转义"
    assert "&lt;b&gt;" in msg, "刊名里的标签应被转义"


def test_doi_is_a_clickable_link():
    """DOI 要可点，但**标签本身不能被转义**：
    元信息那一行若整体走 html_escape，页面上会直接显示出 <a href=…> 的源码。"""
    msg = pch.build_messages(_snap(1), "wechat")[0]
    assert '<a href="https://doi.org/10.1038/s41583-026-01131-8"' in msg, \
        "DOI 没做成链接"
    assert ">10.1038/s41583-026-01131-8</a>" in msg, "链接文字应该是 DOI 本身"
    assert "&lt;a href" not in msg, "a 标签被转义了，页面上会看到标签源码"
    # 链接必须闭合，否则后面的 DOM 全被吃掉
    assert msg.count("<a ") == msg.count("</a>"), "a 标签数量不匹配"


def test_recent_items_keys_off_entrez_date_and_keeps_unknown():
    """⚠️ 必须按 entrez_date（入库日）筛，不能按 pub_date：
    Nature Reviews 大量是 online-first，pub_date 可能是**未来的期号日期**。
    日期解析不出来时**保留**（宁可多发一条，也不要静默漏）。"""
    today = date.today()
    fresh = (today - timedelta(days=3)).isoformat()
    old = (today - timedelta(days=40)).isoformat()
    future = (today + timedelta(days=20)).isoformat()
    items = [
        {"n": 1, "entrez_date": fresh, "pub_date": future},   # online-first
        {"n": 2, "entrez_date": old, "pub_date": fresh},
        {"n": 3, "entrez_date": "", "pub_date": ""},           # 日期缺失
    ]
    assert [it["n"] for it in pch.recent_items(items, 7)] == [1, 3], \
        f"实际保留 {[it['n'] for it in pch.recent_items(items, 7)]}"
    assert len(pch.recent_items(items, 0)) == 3, "days<=0 表示不筛"


def test_wechat_html_is_single_and_well_formed():
    from contextlib import nullcontext  # noqa: F401
    msg = pch.build_messages(_snap(5), "wechat")[0]
    # css 模式以 <style> 块开头，inline 模式以 <div> 开头 —— 两种都算"html 详情页"
    assert msg.startswith("<style>") or msg.startswith("<div"), "应是 html 详情页"
    assert msg.count("<div") == msg.count("</div>"), "div 未闭合"
    assert msg.count("<p") == msg.count("</p>"), "p 未闭合"
    for i in (1, 5):
        assert f">{i}.</" in msg, f"第 {i} 条的序号丢了"
    assert "共 5 条" in msg


def test_css_and_inline_modes_render_identical_content():
    """两种模式只是"怎么挂样式"不同，**可见文本必须一字不差** ——
    否则共用一份样式表的承诺就破了（会出现"内联版加了字段、css 版忘了"）。"""
    items = _snap(5)["items"]
    css = pch.render_html_digest(items, date="2026-09-21", mode="css", probe=False)
    inline = pch.render_html_digest(items, date="2026-09-21", mode="inline", probe=False)
    assert css.startswith("<style>"), "css 模式应以 <style> 块开头"
    assert "<style>" not in inline, "inline 模式不该有 <style> 块"
    assert len(css) < len(inline), f"css 模式应更短：{len(css)} vs {len(inline)}"
    strip = lambda s: re.sub(r"<[^>]+>", "", re.sub(r"<style>.*?</style>", "", s, flags=re.S))
    assert strip(css) == strip(inline), "两种模式的可见文本必须一致"


def test_probe_is_opt_in_and_carries_no_untrusted_text():
    items = _snap(2)["items"]
    assert "排版自检" not in pch.render_html_digest(items, date="x", probe=False)
    assert "排版自检" in pch.render_html_digest(items, date="x", probe=True)


def test_wechat_template_can_be_overridden_and_falls_back():
    with clean_env(PUSHPLUS_TEMPLATE="markdown"):
        assert pch.wechat_template() == "markdown"
        assert not pch.build_messages(_snap(3), "wechat")[0].startswith("<div"), \
            "指定 markdown 时不该再输出 html"
    with clean_env(PUSHPLUS_TEMPLATE="乱填的"):
        assert pch.wechat_template() == "html", "非法值应回落到 html"
    with clean_env():
        assert pch.wechat_template() == "html", "未设置时默认 html"


def test_small_digest_is_a_single_message_with_footer():
    msgs = pch.build_messages(_snap(5), "telegram")
    assert len(msgs) == 1, f"5 条不该分成 {len(msgs)} 条消息"
    assert "--pick 1 5 9" in msgs[0], "缺少下一步提示"
    assert "没发完" not in msgs[0]


def test_limit_caps_items_and_header_reflects_it():
    body = "\n".join(pch.build_messages(_snap(20), "telegram", limit=3))
    assert "（3 条）" in body, "标题条数应反映 limit"
    assert "4. " not in body, "limit 之外的条目不该出现"


def test_style_full_carries_detail_brief_does_not():
    snap = _snap(3)
    assert "细" not in "\n".join(pch.build_messages(snap, "telegram", style="brief"))
    assert "细" in "\n".join(pch.build_messages(snap, "telegram", style="full"))


def test_falls_back_to_title_when_brief_missing():
    snap = _snap(1)
    snap["items"][0]["brief"] = ""
    body = "\n".join(pch.build_messages(snap, "telegram"))
    assert "中文标题1" in body, "brief 为空时应退回中文标题"


def test_short_journal_strips_prefix():
    assert pch._short_journal("Nature reviews. Neuroscience") == "Neuroscience"
    assert pch._short_journal("Nature reviews bioengineering") == "bioengineering"
    assert pch._short_journal("Cell") == "Cell"


# --------------------------------------------------------------- dry-run

def test_dry_run_sends_nothing_and_never_leaks_secrets():
    with clean_env(PUSHPLUS_TOKEN=SECRET, TELEGRAM_BOT_TOKEN=SECRET,
                   TELEGRAM_CHAT_ID=SECRET,
                   DISCORD_WEBHOOK_URL="https://example.invalid/" + SECRET):
        chans, skipped = pch.resolve_channels("all")
        assert chans == ["wechat", "telegram", "discord"] and not skipped
        res = pch.push_snapshot(_snap(3), chans, dry_run=True, verbose=False)
        blob = json.dumps(res, ensure_ascii=False)
        assert SECRET not in blob, "密钥泄漏到了输出里！"
        for lines in res.values():
            assert lines and all("[dry-run]" in ln for ln in lines), \
                "dry-run 不应对任何渠道真的发出请求"


def test_verbose_false_is_silent(capsys=None):
    """verbose=False 时不该往 stdout 写东西（供 build_digest --push 复用）。"""
    import io
    from contextlib import redirect_stdout
    with clean_env(TELEGRAM_BOT_TOKEN="t", TELEGRAM_CHAT_ID="c"):
        buf = io.StringIO()
        with redirect_stdout(buf):
            pch.push_snapshot(_snap(3), ["telegram"], dry_run=True, verbose=False)
        assert buf.getvalue() == "", f"意外的输出：{buf.getvalue()!r}"


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
