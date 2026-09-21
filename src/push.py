"""推送：把一期速览发到微信（PushPlus）/ Telegram / Discord。

设计要点
--------
1. **推内容，不推链接。** digest 页面和 `build_reader` 一样是**单文件自包含 HTML、没有 URL**，
   所以"发一条链接让他点开"这条路不通。三个渠道都能直接承载正文，那就发正文。
2. **渠道是可多选的插件。** `CHANNELS` 是注册表，加一个新渠道 = 写一个 `push_xxx()` +
   往注册表里加一行，**调用方完全不用改**。
3. **一律用纯文本，不用 Markdown/HTML。** 不是为了省事：
   Telegram 的 MarkdownV2 要求转义 `_*[]()~`>#+-=|{}.!`，漏一个就整条发送失败；
   Discord 用 Markdown，PushPlus 走自己的 md 模板 —— 三套规则互不兼容。
   统一发纯文本，**从根上消灭"转义漏一个字符"这类 bug**，代价只是没有加粗。
4. **缺配置要报清楚缺哪个变量**，而不是抛一个 urllib 的 401。
5. **绝不打印密钥。** 所有输出只出现变量名，不出现值。

渠道配置（写在 `.env`，见 `.env.example`）
----------------------------------------
  wechat    PUSHPLUS_TOKEN            （可选 PUSHPLUS_TOPIC 群组编码）
  telegram  TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID
  discord   DISCORD_WEBHOOK_URL      （或 DISCORD_BOT_TOKEN + DISCORD_CHANNEL_ID）

只用标准库 urllib —— 与 `src/providers.py` 保持一致，不引 requests。
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from datetime import date, timedelta
from html import escape as html_escape
from typing import Any, Iterable

CHANNELS: tuple[str, ...] = ("wechat", "telegram", "discord")

DISPLAY: dict[str, str] = {
    "wechat": "微信（PushPlus）",
    "telegram": "Telegram Bot",
    "discord": "Discord Bot / Webhook",
}

# 每个渠道的分片与刷屏策略。
# ⚠️ `max_messages=1` 是刻意的：微信推送是**通知**，65 条拆成 n 条会把聊天列表刷满。
#    Telegram / Discord 是"频道"，多几条无所谓。
POLICY: dict[str, dict[str, int]] = {
    "wechat": {"chunk": 3500, "max_messages": 1},
    "telegram": {"chunk": 3800, "max_messages": 6},   # 官方上限 4096
    "discord": {"chunk": 1900, "max_messages": 10},   # content 上限 2000
}

TIMEOUT = 30
MAX_RETRY = 3

# 分片预算里为"尾部提示 + 截断说明"预留的字符数。
# 不预留的话最后一条消息会超出渠道上限，而**只有在条目多的时候才触发**。
_NOTE_RESERVE = 180

# 官方免费额度：微信渠道内容上限 **2 万字**（会员 10 万）。留一点余量。
WECHAT_MAX_CONTENT = 19000

_FONT = ("-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,"
         "'PingFang SC','Hiragino Sans GB','Microsoft YaHei',sans-serif")

# 微信渠道可用的 content 格式（= PushPlus 的 template 参数）。
#   html        用 <style> 块 + class（markup 省约四成，但是否被清洗待验证）
#   html-inline 全内联样式（已验证可用，保底方案）
#   markdown / txt  纯文本路径
WECHAT_TEMPLATES: tuple[str, ...] = ("html", "html-inline", "markdown", "txt")

# ------------------------------------------------------------------ HTML 样式表
#
# 样式表是**唯一来源**：inline 模式把它内联到每个元素上，css 模式把它织进一个
# `<style>` 块 + class。两种模式共用同一份定义 —— 否则"改了内联忘了 class"
# 这类漂移迟早会发生。
_HTML_STYLES: dict[str, str] = {
    "d": f"font-family:{_FONT};font-size:16px;line-height:1.65;color:#1f2937",
    "hd": "font-size:13px;color:#8b95a5;margin:0 0 14px",
    "it": "margin:0 0 10px;padding-bottom:8px;border-bottom:1px solid #eee",
    "n": "color:#2563eb",
    "brf": "color:#3f4a5a",
    "mt": "font-size:12px;color:#999",
    "a": "color:#2563eb;text-decoration:none",
    "dt": ("margin:-4px 0 10px;font-size:13.5px;color:#3f4a5a;background:#f7f9fc;"
           "border-left:3px solid #cfe0f5;padding:7px 9px"),
    "ft": "font-size:13px;color:#8b95a5;margin:16px 0 0",
    "cd": "background:#f1f5f9;padding:1px 5px;border-radius:4px;font-size:12px",
    "cut": "margin:12px 0 0;font-size:13px;color:#b45309",
    "pb": ("background:#fff7ed;color:#b45309;font-size:12px;padding:6px 8px;"
           "border-radius:6px;margin:0 0 14px"),
}

# 排版自检探针：打开后会在消息顶部插一行橙底自检，用来确认 PushPlus 是否保留了
# `<style>` 块。**默认关闭** —— 它是诊断工具，不是功能。
# 2026-09-21 实测：`<style>` 块 + class 被完整保留（橙底小字正常显示），故默认用 css 模式。
PROBE_STYLE = False

_PROBE_TEXT = ("【排版自检 · 临时】这一行若为橙底小字 &rarr; &lt;style&gt; 块生效；"
               "若为普通黑字 &rarr; 被 PushPlus 清掉了。确认后即删。")


def _html_attrs(mode: str):
    """返回 (要前置的 `<style>` 块, 把样式挂到元素上的函数)。"""
    if mode == "css":
        block = ("<style>"
                 + "".join(f".{k}{{{v}}}" for k, v in _HTML_STYLES.items())
                 + "</style>")
        return block, (lambda cls: f' class="{cls}"')
    return "", (lambda cls: f' style="{_HTML_STYLES[cls]}"')


def _pushplus_template() -> str:
    """PushPlus 的 `template` 只有 html/markdown/txt；`html-inline` 是本地概念，
    对 PushPlus 来说仍然是 html。"""
    t = wechat_template()
    return "html" if t == "html-inline" else t


def _html_mode() -> str:
    """`html` -> 用 `<style>` 块 + class；`html-inline` -> 全内联（保底）。"""
    return "inline" if wechat_template() == "html-inline" else "css"


class PushError(RuntimeError):
    pass


# ------------------------------------------------------------------ 配置

def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def missing_keys(channel: str) -> list[str]:
    """返回该渠道缺失的环境变量**名字**（只返回名字，绝不返回值）。"""
    if channel == "wechat":
        return [] if _env("PUSHPLUS_TOKEN") else ["PUSHPLUS_TOKEN"]
    if channel == "telegram":
        return [k for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID") if not _env(k)]
    if channel == "discord":
        if _env("DISCORD_WEBHOOK_URL"):
            return []
        if _env("DISCORD_BOT_TOKEN") and _env("DISCORD_CHANNEL_ID"):
            return []
        return ["DISCORD_WEBHOOK_URL（或 DISCORD_BOT_TOKEN + DISCORD_CHANNEL_ID）"]
    raise PushError(f"未知渠道 {channel!r}（可选：{', '.join(CHANNELS)}）")


def resolve_channels(spec: str) -> tuple[list[str], list[str]]:
    """把 `--push` 的值解析成渠道列表。返回 (可用渠道, 被跳过的说明)。

    支持：单选 `telegram` / 多选 `telegram,discord`（逗号或空格分隔）/ `all`。
    `all` 只包含**配置齐全**的渠道 —— 否则 `all` 会天天因为没配 Discord 而报错。
    """
    raw = (spec or "").strip()
    if not raw:
        raise PushError(
            f"未指定推送渠道。可选：{', '.join(CHANNELS)}，或 all（= 所有已配置的渠道）。\n"
            f"想看每个渠道的配置状态：python tools/push_digest.py --list-channels"
        )
    tokens = [t for t in raw.replace(" ", ",").split(",") if t]
    if "all" in tokens:
        want = list(CHANNELS)
    else:
        unknown = [t for t in tokens if t not in CHANNELS]
        if unknown:
            raise PushError(
                f"未知渠道 {unknown}。可选：{', '.join(CHANNELS)}，或 all")
        # 去重且保持 CHANNELS 的固定顺序，便于输出稳定
        want = [c for c in CHANNELS if c in tokens]

    ready: list[str] = []
    skipped: list[str] = []
    for c in want:
        miss = missing_keys(c)
        if miss:
            skipped.append(f"{c}（缺 {' + '.join(miss)}）")
        else:
            ready.append(c)
    return ready, skipped


# ------------------------------------------------------------------ 渲染

def _short_journal(j: str) -> str:
    for pref in ("Nature reviews. ", "Nature reviews ", "Nature Reviews. ", "Nature Reviews "):
        if j.startswith(pref):
            return j[len(pref):]
    return j


def recent_items(items: list[dict], days: int) -> list[dict]:
    """只保留最近 `days` 天内入库的条目。

    ⚠️ 用 `entrez_date`（入库日）而不是 `pub_date`：Nature Reviews 大量是
    online-first，`pub_date` 可能是**未来的期号日期**，用它筛会漏掉刚上线的文章。

    ⚠️ 日期解析不出来时**保留**该条目 —— 宁可多发一条，也不要静默漏掉。
    """
    if days <= 0:
        return list(items)
    cutoff = date.today() - timedelta(days=days)
    out: list[dict] = []
    for it in items:
        raw = str(it.get("entrez_date") or it.get("pub_date") or "")[:10]
        try:
            keep = date.fromisoformat(raw) >= cutoff
        except ValueError:
            keep = True
        if keep:
            out.append(it)
    return out


def wechat_template() -> str:
    """微信渠道用哪种 content 格式（= PushPlus 的 `template` 参数）。

    默认 **html**。理由：PushPlus 微信推送分两层，我们**只能控制第二层** ——
      ① 对话列表里那张卡片 = 微信模板消息，字段经微信审核，官方明确说**不可自定义**；
      ② 点进去之后的详情页 = 我们的 `content`，由 `template` 参数决定渲染方式。
    官方 FAQ 还提到：markdown 换行要用 `<br/>` 或句末 `\`，而 html 用 `<br/>`/块级标签 ——
    只有 html 能做出真正的层级（加粗、灰色元信息、分隔线）。

    想改回 markdown / txt：在 `.env` 里设 `PUSHPLUS_TEMPLATE=markdown`。
    """
    t = _env("PUSHPLUS_TEMPLATE").strip().lower()
    return t if t in WECHAT_TEMPLATES else "html"


def _fmt_for(channel: str) -> str:
    """该渠道的 content 格式：微信走 html/markdown/txt，其他渠道目前发纯文本。"""
    if channel != "wechat":
        return "text"
    t = wechat_template()
    return "html" if t in ("html", "html-inline") else t


def render_html_digest(items: list[dict], *, date: str, style: str = "brief",
                       mode: str = "inline", probe: bool = False) -> str:
    """把条目渲染成一段 HTML，供微信详情页使用。

    结构固定为：序号 + **标题** / 简介 / 期刊·日期·**可点 DOI**
    （`style="full"` 时再加 detail）。

    样式有两种挂法（`mode`）：
      · `css`    —— 一个 `<style>` 块 + class，**markup 省约四成**，但是否被清洗待验证；
      · `inline` —— 每个元素带 `style`，已验证可用，保底方案。
    两者共用同一份 `_HTML_STYLES`，不会出现"改了内联忘了 class"的漂移。

    ⚠️ **每处插值都必须转义**：标题、简介、detail 都是 LLM/PubMed 来的文本，
    里面出现 `<` 或 `&` 会把整个详情页的 DOM 弄坏 —— 而症状是"页面显示错乱"
    而不是报错，属于最难发现的那类问题。
    """
    n = len(items)
    css_block, at = _html_attrs(mode)
    head = (css_block + f'<div{at("d")}>'
            + (f'<p{at("pb")}>{_PROBE_TEXT}</p>' if probe else "")
            + f'<p{at("hd")}>{html_escape(str(date))} · 共 {n} 条</p>')
    tail = (f'<p{at("ft")}>挑好后在电脑上运行：'
            f'<code{at("cd")}>python tools/build_digest.py --pick 1 5 9</code></p></div>')
    # 预算里先扣掉头尾与可能的截断说明，这样**最终总长一定不超微信上限** ——
    # 否则测试只能写成"差不多别超"，那种断言等于没断言。
    budget = WECHAT_MAX_CONTENT - len(head) - len(tail) - 300

    parts = [head]
    used = 0
    for it in items:
        title = it.get("title_zh") or it.get("title_en") or ""
        brief = it.get("brief") or ""
        # 优先用 PubMed 的期刊缩写（"Nat Rev Neurosci"）：元信息那一行要同时塞
        # 期刊 + 日期 + DOI，长度很紧张，全名会把这一行撑成两行。
        jr = it.get("journal_abbr") or _short_journal(str(it.get("journal") or ""))
        ds = str(it.get("pub_date") or it.get("entrez_date") or "")
        doi = str(it.get("doi") or "")
        url = str(it.get("url_doi") or (f"https://doi.org/{doi}" if doi else ""))

        # ⚠️ **必须逐段转义后再拼**，不能把整行交给 html_escape：
        #    否则 <a> 标签本身会被转义成文字，页面上直接显示出标签源码。
        bits = [html_escape(x) for x in (str(jr), ds) if x]
        if doi and url:
            bits.append(f'<a href="{html_escape(url, quote=True)}"{at("a")}>'
                        f'{html_escape(doi)}</a>')
        meta_html = " · ".join(bits)

        lines = [f'<b{at("n")}>{it.get("n")}.</b> <b>{html_escape(str(title))}</b>']
        if brief:
            lines.append(f'<span{at("brf")}>{html_escape(str(brief))}</span>')
        if meta_html:
            lines.append(f'<span{at("mt")}>{meta_html}</span>')
        piece = f'<p{at("it")}>' + "<br>".join(lines) + "</p>"
        detail = it.get("detail") if style == "full" else ""
        if detail:
            piece += f'<p{at("dt")}>{html_escape(str(detail))}</p>'
        if used + len(piece) > budget:
            parts.append(f'<p{at("cut")}>⚠️ 已到微信单条上限，'
                         f'后面还有 {n - int(it["n"]) + 1} 条没显示。</p>')
            break
        parts.append(piece)
        used += len(piece)

    parts.append(tail)
    return "".join(parts)


def build_messages(snap: dict, channel: str, *, style: str = "full",
                   limit: int | None = None) -> list[str]:
    """把一份快照渲染成该渠道要发的若干条消息。

    微信默认走 **html**（单条，详情页排版最好，见 `wechat_template()`）；
    其他渠道走**纯文本**，按**条目边界**切分，绝不切在句子中间 ——
    半句话的提要比没有提要更糟。超出 `max_messages` 时**显式说明截断了多少条**，
    而不是静默丢弃。
    """
    pol = POLICY.get(channel)
    if pol is None:
        raise PushError(f"未知渠道 {channel!r}")
    items = list(snap.get("items") or [])
    if limit:
        items = items[:limit]

    if _fmt_for(channel) == "html":
        return [render_html_digest(items, date=str(snap.get("date") or ""),
                                   style=style, mode=_html_mode(),
                                   probe=PROBE_STYLE and _html_mode() == "css")]

    head = f"Nature Reviews 速览 · {snap.get('date', '')}（{len(items)} 条）"
    tail = "挑好后在电脑上运行：python tools/build_digest.py --pick 1 5 9"

    blocks: list[str] = []
    for it in items:
        line = f"{it['n']}. {it['brief'] or it['title_zh'] or it['title_en']}"
        line += f" · {_short_journal(it['journal'])}"
        if style == "full" and it.get("detail"):
            line += f"\n    {it['detail']}"
        blocks.append(line)

    # 预算里先扣掉尾部提示与可能的截断说明，否则"最后一条消息"会顶穿渠道上限 ——
    # 症状是 Discord / Telegram 直接返回 400，而且**只在内容多的时候才出现**。
    budget = max(200, pol["chunk"] - len(tail) - _NOTE_RESERVE)

    # 装箱：按**条目边界**切分，并记录每包含多少条（用于精确报告截断了几条）
    packs: list[tuple[str, int]] = []
    cur, cur_n = head, 0
    for b in blocks:
        if cur_n and len(cur) + len(b) + 1 > budget:
            packs.append((cur, cur_n))
            cur, cur_n = "", 0
        cur = (cur + "\n" + b) if cur else b
        cur_n += 1
        # 单条本身就超预算的极端情况：硬切，并标注
        while len(cur) > budget:
            packs.append((cur[:budget] + "…（本条截断）", cur_n))
            cur, cur_n = cur[budget:], 0
    if cur:
        packs.append((cur, cur_n))
    if not packs:
        packs = [(head, 0)]
    packs[-1] = (packs[-1][0] + "\n\n" + tail, packs[-1][1])

    if len(packs) > pol["max_messages"]:
        kept = packs[: pol["max_messages"]]
        sent = sum(n for _, n in kept)
        missing = max(0, len(items) - sent)
        text, n = kept[-1]
        text += (f"\n\n⚠️ 还有 {missing} 条没发完（共 {len(items)} 条）。"
                 f"为避免刷屏只发前 {pol['max_messages']} 条消息，"
                 f"完整内容见 data/feed/digest/ 里的 HTML。")
        kept[-1] = (text, n)
        packs = kept
    return [t for t, _ in packs]


# ------------------------------------------------------------------ HTTP

def _request(url: str, payload: dict[str, Any] | None,
             headers: dict[str, str] | None = None,
             *, tries: int = MAX_RETRY, timeout: int = TIMEOUT) -> tuple[int, str]:
    """POST JSON。返回 (HTTP 状态码, 响应正文)。网络失败返回 (0, 原因)。

    重试策略与 `providers._post` 一致：401/403/404 是我们的问题（密钥/地址错），
    重试没有意义；429 与 5xx 退避重试。
    """
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    last = ""
    for attempt in range(tries):
        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:400]
            if e.code in (401, 403, 404, 400):
                return e.code, detail
            last = f"HTTP {e.code}: {detail}"
        except Exception as e:  # noqa: BLE001
            last = f"{type(e).__name__}: {e}"
        if attempt < tries - 1:
            time.sleep(1.5 * (attempt + 1))
    return 0, last


# ------------------------------------------------------------------ 各渠道

def push_wechat(messages: list[str], title: str, *, dry_run: bool = False) -> list[str]:
    """微信（PushPlus）。官方文档 V1.18：POST /send，成功码在 **body** 里而不是 HTTP 状态。

    ⚠️ 文档明确说：`code=200` **只代表服务端收到了请求**，不代表消息已送达
    （接口是异步的，最终结果要拿 `data` 里的流水号去查）。所以这里只能确认"已提交"。
    """
    token = _env("PUSHPLUS_TOKEN")
    if not token and not dry_run:
        raise PushError("缺少 PUSHPLUS_TOKEN。在项目根目录 .env 里加一行："
                        "PUSHPLUS_TOKEN=你的令牌（pushplus.plus 个人中心获取）")
    out: list[str] = []
    for i, msg in enumerate(messages, 1):
        if dry_run:
            out.append(f"[dry-run] wechat 第 {i} 条（{len(msg)} 字）标题={title!r}")
            continue
        body: dict[str, Any] = {"token": token, "title": title,
                                "content": msg, "template": _pushplus_template()}
        topic = _env("PUSHPLUS_TOPIC")
        if topic:
            body["topic"] = topic
        status, resp = _request("https://www.pushplus.plus/send", body)
        code, short = 0, ""
        try:
            obj = json.loads(resp)
            code = int(obj.get("code", 0))
            short = str(obj.get("data", "") or "")
        except (ValueError, TypeError, AttributeError):
            pass
        if status == 200 and code == 200:
            # 流水号务必打出来：PushPlus 是**异步**接口，这里只能确认"已提交"。
            # 出现"已提交但没收到"时，就是靠这个号去查最终发送状态。
            out.append(f"wechat 第 {i} 条：已提交，流水号 {short or '(未返回)'}"
                       f"　—— 送达结果需凭流水号查询（PushPlus 为异步）")
        else:
            out.append(f"wechat 第 {i} 条：✗ HTTP {status} / code {code} —— {resp[:200]}")
    return out


def push_telegram(messages: list[str], title: str, *, dry_run: bool = False) -> list[str]:
    """Telegram Bot。**不设 parse_mode** —— 纯文本，绕开 MarkdownV2 的转义地狱。"""
    token, chat_id = _env("TELEGRAM_BOT_TOKEN"), _env("TELEGRAM_CHAT_ID")
    if not dry_run and not (token and chat_id):
        raise PushError("缺少 TELEGRAM_BOT_TOKEN 或 TELEGRAM_CHAT_ID。"
                        "chat_id 可先给 bot 发条消息，再访问 "
                        "https://api.telegram.org/bot<token>/getUpdates 查看")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    out: list[str] = []
    for i, msg in enumerate(messages, 1):
        if dry_run:
            out.append(f"[dry-run] telegram 第 {i} 条（{len(msg)} 字）")
            continue
        status, resp = _request(url, {
            "chat_id": chat_id,
            "text": msg,
            "disable_web_page_preview": True,
        })
        ok = False
        try:
            ok = bool(json.loads(resp).get("ok"))
        except (ValueError, TypeError):
            ok = False
        if status == 200 and ok:
            out.append(f"telegram 第 {i} 条：✓ 已送达")
        else:
            out.append(f"telegram 第 {i} 条：✗ HTTP {status} —— {resp[:200]}")
    return out


def push_discord(messages: list[str], title: str, *, dry_run: bool = False) -> list[str]:
    """Discord：优先用 Webhook（不需要常驻 bot 进程），否则用 Bot Token 发频道消息。"""
    hook = _env("DISCORD_WEBHOOK_URL")
    token, chan = _env("DISCORD_BOT_TOKEN"), _env("DISCORD_CHANNEL_ID")
    if not dry_run and not hook and not (token and chan):
        raise PushError("配置 Discord 二选一：\n"
                        "  · DISCORD_WEBHOOK_URL=服务器设置 → 整合 → Webhook 的 URL（推荐，无需常驻进程）\n"
                        "  · 或 DISCORD_BOT_TOKEN + DISCORD_CHANNEL_ID")
    if hook:
        url, headers = hook, {}
    else:
        url = f"https://discord.com/api/v10/channels/{chan}/messages"
        headers = {"Authorization": f"Bot {token}"}

    out: list[str] = []
    for i, msg in enumerate(messages, 1):
        if dry_run:
            kind = "webhook" if hook else "bot"
            out.append(f"[dry-run] discord({kind}) 第 {i} 条（{len(msg)} 字）")
            continue
        # ⚠️ content 硬上限 2000 字符，超了 Discord 直接 400。POLICY 已留余量。
        status, resp = _request(url, {"content": msg[:1990]}, headers)
        if status in (200, 204):
            out.append(f"discord 第 {i} 条：✓ 已送达")
        else:
            out.append(f"discord 第 {i} 条：✗ HTTP {status} —— {resp[:200]}")
    return out


_SENDERS = {
    "wechat": push_wechat,
    "telegram": push_telegram,
    "discord": push_discord,
}


# ------------------------------------------------------------------ 入口

def push_snapshot(snap: dict, channels: Iterable[str], *, style: str = "full",
                  limit: int | None = None, dry_run: bool = False,
                  verbose: bool = True) -> dict[str, list[str]]:
    """把一份快照推到多个渠道。返回 {渠道: [结果行]}。

    一个渠道失败**不影响**其他渠道（各自 try/except），最后在结果里如实列出。
    """
    # ⚠️ 标题里的条数必须反映 limit 之后的**实际**条数：
    #    否则通知写"（65 条）"而正文只有 3 条（被 --limit 截了），一眼看去就是错的。
    effective = len(snap.get("items") or [])
    if limit:
        effective = min(effective, limit)
    title = f"Nature Reviews 速览 · {snap.get('date', '')}（{effective} 条）"
    results: dict[str, list[str]] = {}
    for ch in channels:
        sender = _SENDERS.get(ch)
        if sender is None:
            results[ch] = [f"未知渠道 {ch!r}"]
            continue
        try:
            msgs = build_messages(snap, ch, style=style, limit=limit)
        except PushError as e:
            results[ch] = [f"✗ 渲染失败：{e}"]
            continue
        if verbose:
            print(f"  [{ch}] {len(msgs)} 条消息，共 "
                  f"{sum(len(m) for m in msgs)} 字" + ("（dry-run）" if dry_run else ""))
        try:
            results[ch] = sender(msgs, title, dry_run=dry_run)
        except PushError as e:
            results[ch] = [f"✗ {e}"]
        except Exception as e:  # noqa: BLE001
            results[ch] = [f"✗ {type(e).__name__}: {e}"]
    return results


def channel_status() -> list[tuple[str, bool, str]]:
    """给 `--list-channels` 用：每个渠道的 (名字, 是否就绪, 说明)。"""
    rows = []
    for c in CHANNELS:
        miss = missing_keys(c)
        rows.append((c, not miss, "就绪" if not miss else f"缺 {' + '.join(miss)}"))
    return rows
