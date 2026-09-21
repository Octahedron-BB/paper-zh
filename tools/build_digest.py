"""文献速览（digest）：检索 → 生成两级提要 → 产出手机友好的 HTML / Markdown。

**刻意不与 `build_reader.py` 绑定。** build_reader 是"语音播放"特化的
（内嵌 base64 MP3、毫秒级音频联动、MediaSession 锁屏保活），digest 一个都不需要——
它只是"读一眼 + 挑一篇"。两者只在视觉语言上保持一致，架构上完全独立。

产出（都在 `data/feed/digest/`）
--------------------------------
  <日期>.json   **快照**：这一期到底推了哪几条、编号是什么。`--pick` 靠它把编号映射回条目。
  <日期>.html   手机界面：默认只显示 ≤25 字的 brief，点开看 detail / 英文原标题 / 命令。
  <日期>.md     VS Code 里 Ctrl+K V 看的版本。

为什么要有"快照"这一层
----------------------
`--pick 3` 里的"3"是**位置编号**，离开快照就没有意义。所以每期必须落盘，
否则过两天再 picking 就会指到别的条目上——这是那种不会报错、只会让你跑错文献的静默错误。

跑法（假设 Python 环境已激活；Windows / macOS 通用）
----
    python tools/build_digest.py                  # 增量
    python tools/build_digest.py --days 60        # 首次回填
    python tools/build_digest.py --limit 3 --no-llm       # 只看体量、不花钱
    python tools/build_digest.py --pick 3 7       # 挑中第 3、7 条
    python tools/build_digest.py --list           # 终端重看最近一期
    python tools/build_digest.py --render-only    # 用快照重渲染（不调 LLM）
    python tools/build_digest.py --push telegram,discord  # 生成后直接推送

推送的详细用法见 `tools/push_digest.py`（只想重发一次时用它，不必重新检索）。
"""

from __future__ import annotations

import argparse
import html as html_mod
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from src.cache import Cache, key_for_digest  # noqa: E402
from src.feed import (  # noqa: E402
    DEFAULT_DAYS, DEFAULT_TERM, STATUS_PICKED, STATUS_SHOWN,
    FeedItem, gap_days, load_store, pending, retrieve, save_generations,
    save_store, set_status, stats, upsert,
)
from src.glossary import (  # noqa: E402
    TermConflictError, apply_hard_replace, load_glossary, load_glossary_dir,
)
from src.model import sha1  # noqa: E402
from src.prompts import DIGEST_SYSTEM, DIGEST_USER, DIGEST_VERSION  # noqa: E402
from src.providers import build_provider, load_env  # noqa: E402
from src.push import PushError, push_snapshot, resolve_channels  # noqa: E402
from src.runlog import attach as attach_log  # noqa: E402
from src.textnorm import normalize_zh, reading_len  # noqa: E402

OUT_DIR = ROOT / "data" / "feed" / "digest"
CACHE_DIR = ROOT / "data" / "feed" / "cache"


# ----------------------------------------------------------------- 提要生成

def parse_payload(text: str) -> dict[str, str]:
    """把 LLM 输出解析成三字段。**不抛异常**——一条解析失败不该毁掉整期。"""
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.S).strip()
    obj: dict = {}
    try:
        obj = json.loads(t)
    except ValueError:
        m = re.search(r"\{.*\}", t, flags=re.S)
        if m:
            try:
                obj = json.loads(m.group(0))
            except ValueError:
                obj = {}
    if not isinstance(obj, dict):
        obj = {}
    return {
        "title_zh": str(obj.get("title_zh", "")).strip(),
        "brief": str(obj.get("brief", "")).strip(),
        "detail": str(obj.get("detail", "")).strip(),
    }


def terms_for(item: FeedItem, memo: dict[tuple[str, str], list]) -> list:
    """取该条目生效的 `hard_replace` 术语。

    ⚠️ 提要 prompt **故意不带术语块**（见 `key_for_digest` 的说明）：
    术语一律靠译后字符串替换免费修正，这样改术语 = 0 条失效、立刻生效。
    """
    ck = (item.doc_id, item.term_field)
    if ck in memo:
        return memo[ck]
    try:
        terms = load_glossary_dir(ROOT, doc_id=item.doc_id, field=item.term_field)
    except TermConflictError:
        main = ROOT / "glossary.yaml"
        print(f"    [术语] ⚠️ {item.doc_id} 有同名异义冲突，本次只套用主表（先跑 disambiguate 修）")
        terms = load_glossary(main) if main.exists() else []
    memo[ck] = terms
    return terms


def brief_verdict(brief: str) -> tuple[str, str]:
    """按 prompt 里写的那套规则给 brief 定性，返回 (标记, 说明)。

    ⚠️ 检查器**必须与 prompt 用同一套判据**：prompt 说"≤25 字且最多一个逗号"，
    检查器就同时查这两条。否则会出现"看上去都合格"的假象——
    比如「MENA地区肥胖与T2DM负担被低估，海湾国家已高发，北非正快速攀升。」
    计长只有 29（缩写算 1 字），但**有 2 个逗号 / 3 个分句**，是 prompt 明令禁止的。
    """
    if not brief.strip():
        return "❌", "空"
    n = reading_len(brief)   # 缩写算 1 个字，与 prompt 口径一致
    commas = brief.count("，") + brief.count(",")
    issues: list[str] = []
    if n > 32:
        issues.append(f"{n}字超标")
    elif n > 25:
        issues.append(f"{n}字偏长")
    if commas > 1:
        issues.append(f"{commas}个逗号")
    return ("✅", f"{n}字") if not issues else ("⚠️", " ".join(issues))


def triage(items: list[FeedItem], provider, cache: Cache,
           *, refresh: bool = False) -> tuple[int, int]:
    """给每条生成 title_zh / brief / detail。返回 (缓存命中, 实际调用)。"""
    memo: dict[tuple[str, str], list] = {}
    hits = calls = 0
    t0 = time.time()
    for i, it in enumerate(items, 1):
        key = key_for_digest(model_id=f"{provider.name}:{provider.model}",
                             prompt_version=DIGEST_VERSION,
                             src_hash=sha1(it.abstract))
        entry = None if refresh else cache.get(key)
        if entry is not None:
            hits += 1
            got = parse_payload(entry.value)
        else:
            user = DIGEST_USER.format(journal=it.journal, title=it.title_en,
                                      abstract=it.abstract)
            try:
                raw = provider.complete(DIGEST_SYSTEM, user,
                                        temperature=0.2, max_tokens=500)
            except Exception as e:  # noqa: BLE001
                print(f"    [{i}/{len(items)}] ✗ {it.pmid} {type(e).__name__}: {e}")
                continue
            calls += 1
            cache.put(key, raw, meta={"pmid": it.pmid, "doc_id": it.doc_id})
            got = parse_payload(raw)

        # 术语与规范化：**零 API 成本**，改术语立刻生效
        terms = terms_for(it, memo)
        for f in ("title_zh", "brief", "detail"):
            v = got.get(f) or ""
            got[f] = normalize_zh(apply_hard_replace(terms, v)) if v else ""
        it.title_zh, it.brief, it.detail = got["title_zh"], got["brief"], got["detail"]
        mark, why = brief_verdict(it.brief)
        print(f"    [{i}/{len(items)}] {mark} {why:<14} {it.brief or '(空)'}")
    print(f"[提要] 缓存命中 {hits} / 新调用 {calls}，用时 {time.time() - t0:.1f}s")
    return hits, calls


# ----------------------------------------------------------------- 渲染

def _short_journal(j: str) -> str:
    for pref in ("Nature reviews. ", "Nature reviews ", "Nature Reviews. ", "Nature Reviews "):
        if j.startswith(pref):
            return f"Nature Reviews {j[len(pref):]}"
    return j


def snapshot_items(items: list[FeedItem]) -> list[dict]:
    """快照条目 = 事实 + 生成物 + **渲染需要的派生字段**。

    派生字段（URL / 命令）冗余写进快照，是为了 `--render-only` 能独立重渲染；
    而 `--pick` 会**重建 FeedItem** 再生成命令，以免用到快照里的过期格式。
    """
    out = []
    for n, it in enumerate(items, 1):
        d = it.to_dict()
        d["n"] = n
        d["url_pubmed"] = it.url_pubmed
        d["url_doi"] = it.url_doi
        d["run_command"] = it.run_command
        out.append(d)
    return out


def render_markdown(snap: dict) -> str:
    L: list[str] = []
    L.append(f"# Nature Reviews 速览 · {snap['date']}")
    L.append("")
    L.append(f"共 **{snap['count']}** 条 · 检索式 `{snap['term']}` · "
             f"模型 `{snap['model']}` · prompt `{snap['prompt_version']}`")
    L.append("")
    L.append("> 挑好之后：`python tools/build_digest.py --pick 3 7 12`（填编号）")
    L.append("")
    L.append("---")
    L.append("")
    for it in snap["items"]:
        L.append(f"### {it['n']}. {it['title_zh'] or it['title_en']}")
        L.append("")
        L.append(f"`{_short_journal(it['journal'])}` · {it['pub_date']} · "
                 f"`{it['doc_id']}`" + (" · ⭐已选" if it.get("status") == STATUS_PICKED else ""))
        L.append("")
        if it["brief"]:
            L.append(f"**{it['brief']}**")
            L.append("")
        if it["detail"]:
            L.append(it["detail"])
            L.append("")
        L.append(f"<sub>{html_mod.escape(it['title_en'])}</sub>")
        L.append("")
        links = []
        if it["doi"]:
            links.append(f"[DOI]({it['url_doi']})")
        links.append(f"[PubMed]({it['url_pubmed']})")
        L.append(" · ".join(links))
        L.append("")
        L.append("```")
        L.append(it["run_command"])
        L.append("```")
        L.append("")
    return "\n".join(L)


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<title>速览 __SNAP__</title>
<style>
  :root{
    --bg:#f8fafc; --surface:#fff; --text:#0f172a; --muted:#64748b;
    --primary:#2563eb; --primary-soft:#eff6ff; --border:#e2e8f0;
    --chip:#f1f5f9; --ok:#059669;
    --shadow:0 1px 2px 0 rgb(0 0 0/.05), 0 4px 12px -4px rgb(0 0 0/.08);
    --sans:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"PingFang SC",
           "Hiragino Sans GB","Microsoft YaHei",sans-serif;
    --mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  }
  @media (prefers-color-scheme:dark){
    :root{--bg:#090d16; --surface:#131c2e; --text:#f8fafc; --muted:#94a3b8;
      --primary:#60a5fa; --primary-soft:#172554; --border:#1e293b;
      --chip:#1e293b; --ok:#34d399; --shadow:0 1px 2px 0 rgb(0 0 0/.3);}
  }
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:var(--bg);color:var(--text);font-family:var(--sans);
       font-size:16px;line-height:1.6;-webkit-text-size-adjust:100%;
       padding-bottom:88px}
  header{position:sticky;top:0;z-index:10;background:var(--surface);
         border-bottom:1px solid var(--border);padding:12px 16px;
         display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;
         padding-top:calc(12px + env(safe-area-inset-top))}
  header h1{font-size:17px;font-weight:650}
  header .meta{font-size:12.5px;color:var(--muted)}
  main{padding:12px;display:flex;flex-direction:column;gap:10px;max-width:760px;margin:0 auto}
  .card{background:var(--surface);border:1px solid var(--border);
        border-radius:14px;padding:13px 14px;box-shadow:var(--shadow);
        cursor:pointer;transition:border-color .15s,transform .08s}
  .card:active{transform:scale(.994)}
  .card.picked{border-color:var(--ok);box-shadow:0 0 0 2px var(--ok) inset,var(--shadow)}
  .row{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:7px}
  .num{flex:none;width:24px;height:24px;border-radius:50%;background:var(--primary-soft);
       color:var(--primary);font-size:13px;font-weight:700;
       display:flex;align-items:center;justify-content:center}
  .card.picked .num{background:var(--ok);color:#fff}
  .chip{font-size:11.5px;background:var(--chip);color:var(--muted);
        padding:2px 8px;border-radius:999px;white-space:nowrap}
  .date{font-size:11.5px;color:var(--muted);margin-left:auto}
  .card h2{font-size:16.5px;font-weight:640;line-height:1.45;letter-spacing:-.01em}
  .en{font-size:12.5px;color:var(--muted);margin-top:3px;font-style:italic}
  .brief{margin-top:9px;font-size:15px;line-height:1.7}
  details{margin-top:10px}
  summary{font-size:12.5px;color:var(--primary);cursor:pointer;
          list-style:none;user-select:none}
  summary::-webkit-details-marker{display:none}
  summary::before{content:"▸ "}
  details[open] summary::before{content:"▾ "}
  .detail{margin-top:8px;font-size:14.5px;line-height:1.75;color:var(--text);
          border-left:3px solid var(--primary-soft);padding-left:11px}
  .cmd{margin-top:11px;background:var(--bg);border:1px solid var(--border);
       border-radius:9px;padding:9px 10px;font-family:var(--mono);font-size:12px;
       word-break:break-all;line-height:1.5}
  .hint{margin-top:8px;font-size:12px;color:var(--muted);line-height:1.6}
  .hint code{background:var(--chip);padding:1px 5px;border-radius:4px;
             font-family:var(--mono);font-size:11.5px}
  .links{margin-top:10px;font-size:13px;display:flex;gap:14px;flex-wrap:wrap}
  a{color:var(--primary);text-decoration:none}
  .bar{position:fixed;left:0;right:0;bottom:0;z-index:10;background:var(--surface);
       border-top:1px solid var(--border);padding:10px 16px;
       padding-bottom:calc(10px + env(safe-area-inset-bottom));
       display:flex;align-items:center;gap:12px}
  .bar .sel{font-size:13.5px;color:var(--muted);flex:1;min-width:0;
            overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .bar .sel b{color:var(--ok)}
  button{flex:none;background:var(--primary);color:#fff;border:0;border-radius:9px;
         padding:9px 15px;font-size:13.5px;font-weight:600;font-family:inherit;
         cursor:pointer}
  button:disabled{opacity:.4}
  button.ghost{background:transparent;color:var(--primary);
               border:1px solid var(--border)}
</style>
</head>
<body>
<header>
  <h1>Nature Reviews 速览</h1>
  <span class="meta">__DATE__ __TIME__ · __COUNT__ 条</span>
</header>
<main>__CARDS__</main>
<div class="bar">
  <div class="sel" id="sel">点卡片即可标记「要读」</div>
  <button class="ghost" id="clr">清空</button>
  <button id="cp" disabled>复制编号</button>
</div>
<script>
(function(){
  var KEY='paperzh.picked.__SNAP__';
  var picked=new Set(JSON.parse(localStorage.getItem(KEY)||'[]'));
  var selEl=document.getElementById('sel'),cpEl=document.getElementById('cp');
  var clrEl=document.getElementById('clr');
  function paint(){
    var a=[...picked].sort(function(x,y){return x-y});
    document.querySelectorAll('.card').forEach(function(c){
      c.classList.toggle('picked',picked.has(+c.dataset.n));
    });
    if(a.length){selEl.innerHTML='已选 <b>'+a.join(' ')+'</b>（'+a.length+' 条）';}
    else{selEl.textContent='点卡片即可标记「要读」';}
    cpEl.disabled=!a.length;
  }
  document.querySelectorAll('.card').forEach(function(c){
    c.addEventListener('click',function(e){
      if(e.target.closest('button,a,summary,details'))return;
      var n=+c.dataset.n;
      if(picked.has(n)){picked.delete(n);}else{picked.add(n);}
      localStorage.setItem(KEY,JSON.stringify([...picked]));paint();
    });
  });
  cpEl.addEventListener('click',function(){
    var t=[...picked].sort(function(x,y){return x-y}).join(' ');
    navigator.clipboard.writeText(t).then(function(){
      cpEl.textContent='已复制';setTimeout(function(){cpEl.textContent='复制编号';},1400);
    }).catch(function(){alert('请手动记下：'+t);});
  });
  clrEl.addEventListener('click',function(){
    picked.clear();localStorage.removeItem(KEY);paint();
  });
  paint();
})();
</script>
</body>
</html>
"""


def render_html(snap: dict) -> str:
    cards: list[str] = []
    for it in snap["items"]:
        e = html_mod.escape
        picked = " picked" if it.get("status") == STATUS_PICKED else ""
        links = []
        if it["doi"]:
            links.append(f'<a href="{e(it["url_doi"])}" target="_blank" rel="noopener">'
                         f'DOI {e(it["doi"])}</a>')
        links.append(f'<a href="{e(it["url_pubmed"])}" target="_blank" rel="noopener">PubMed</a>')
        detail = (f'<p class="detail">{e(it["detail"]).replace(chr(10), "<br>")}</p>'
                  if it["detail"] else "")
        cards.append(f"""<article class="card{picked}" data-n="{it['n']}" data-doc="{e(it['doc_id'])}">
  <div class="row">
    <span class="num">{it['n']}</span>
    <span class="chip">{e(_short_journal(it['journal']))}</span>
    <span class="date">{e(it['pub_date'] or it['entrez_date'])}</span>
  </div>
  <h2>{e(it['title_zh'] or it['title_en'])}</h2>
  <p class="en">{e(it['title_en'])}</p>
  <p class="brief">{e(it['brief'])}</p>
  <details>
    <summary>展开详情 / 运行命令</summary>
    {detail}
    <div class="links">{' · '.join(links)}</div>
    <div class="cmd">{e(it['run_command'])}</div>
    <p class="hint">把 PDF 存成 <code>{e(it['doc_id'])}.pdf</code> 放进 <code>papers/</code>，然后跑上面的命令。</p>
  </details>
</article>""")
    return (HTML_TEMPLATE
            .replace("__SNAP__", html_mod.escape(snap.get("snapshot", snap["date"])))
            .replace("__DATE__", html_mod.escape(snap["date"]))
            .replace("__TIME__", html_mod.escape(snap.get("generated_at", "")[11:16]))
            .replace("__COUNT__", str(snap["count"]))
            .replace("__CARDS__", "\n".join(cards)))


# ----------------------------------------------------------------- 快照

def unique_stem(base_date: str, when: datetime) -> str:
    """同一日期重复跑时**不覆盖**已有快照，而是追加时刻。

    ⚠️ 为什么不直接覆盖：快照里的编号是 `--pick N` 的**唯一依据**，
    而 HTML 很可能已经被打开、甚至已发到手机上。若同一日期覆盖，
    "手机上看到的第 3 条"与"电脑上 pick 的第 3 条"会变成两篇不同的文章——
    不报错、只跑错文献，属于最难发现的那类错误。
    """
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if not (OUT_DIR / f"{base_date}.json").exists():
        return base_date
    for i in range(1, 100):
        stem = f"{base_date}-{when.strftime('%H%M')}" + (f"-{i}" if i > 1 else "")
        if not (OUT_DIR / f"{stem}.json").exists():
            return stem
    return f"{base_date}-{when.strftime('%H%M%S')}"


def write_snapshot(snap: dict, stem: str, *, markdown: bool = True,
                   html: bool = True) -> dict[str, Path]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out: dict[str, Path] = {}
    p = OUT_DIR / f"{stem}.json"
    p.write_text(json.dumps(snap, ensure_ascii=False, indent=1), encoding="utf-8")
    out["json"] = p
    if markdown:
        out["md"] = OUT_DIR / f"{stem}.md"
        out["md"].write_text(render_markdown(snap), encoding="utf-8")
    if html:
        out["html"] = OUT_DIR / f"{stem}.html"
        out["html"].write_text(render_html(snap), encoding="utf-8")
    return out


def load_snapshot(which: str | None = None) -> tuple[dict, Path]:
    """取一期快照。不指定就取**最新的一期**。

    ⚠️ 绝对不能按文件名 `sorted()[-1]` 取最新的：排序里 `-`(0x2D) < `.`(0x2E)，
    所以 `2026-09-21-0843.json` 排在 `2026-09-21.json` **前面**，
    取最后一个反而拿到**旧的那一期** —— 不报错、只会让你 pick 到另一篇文章。
    因此改为按快照内部的 `generated_at` 排序（内容权威，不依赖文件名）。
    """
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if which:
        cands = [OUT_DIR / f"{which}.json", Path(which)]
        for c in cands:
            if c.exists():
                return json.loads(c.read_text(encoding="utf-8")), c
        raise SystemExit(f"找不到快照：{which}")
    snaps: list[tuple[str, str, dict, Path]] = []
    for p in OUT_DIR.glob("*.json"):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            continue
        snaps.append((str(d.get("generated_at", "")), p.name, d, p))
    if not snaps:
        raise SystemExit("还没有任何一期速览。先跑：python tools/build_digest.py")
    snaps.sort(key=lambda t: (t[0], t[1]))
    _, _, best, path = snaps[-1]
    return best, path


# ----------------------------------------------------------------- 子命令

def cmd_build(args: argparse.Namespace) -> int:
    store = load_store()
    st = stats(store)
    g = gap_days(store)
    print(f"[状态] 库里 {st.get('total', 0)} 条："
          f"未推 {st.get('new', 0)} / 已推 {st.get('shown', 0)} / "
          f"已选 {st.get('picked', 0)} / 完成 {st.get('done', 0)}"
          + (f"，距上次入库 {g} 天" if g is not None else "，首次运行"))

    items = retrieve(args.term, args.days, retmax=args.retmax,
                     report_dropped=args.show_dropped)
    if not items:
        print("没有检索到任何条目。")
        return 0

    fresh = upsert(store, items)
    print(f"[状态] 本次新入库 {len(fresh)} 条")

    all_pending = pending(store)
    todo = all_pending[: args.limit] if args.limit else all_pending
    if not todo:
        print("没有待推的条目（都推过了）。")
        return 0
    print(f"[待推] 本次推 {len(todo)} 条")
    rest = len(all_pending) - len(todo)
    if rest > 0:
        print(f"       库里还有 {rest} 条未推（--limit 只是试水；去掉 --limit 会一次全推）")

    if args.no_llm:
        print("\n--no-llm：只检索、不生成提要。清单：")
        for i, it in enumerate(todo, 1):
            print(f"  {i:>3}. {it.pub_date}  {_short_journal(it.journal)[:30]:<31}"
                  f"{it.title_en[:60]}")
        save_store(store)
        return 0

    load_env(ROOT / ".env")
    provider = build_provider(args.provider, args.model)
    cache = Cache(CACHE_DIR)
    print(f"[模型] {provider.name}:{provider.model}")
    triage(todo, provider, cache, refresh=args.refresh)
    print(f"[缓存] {cache.stats()}")

    now = datetime.now()
    base = now.strftime("%Y-%m-%d")
    stem = unique_stem(base, now)
    snap = {
        "date": base,
        "snapshot": stem,
        "generated_at": now.isoformat(timespec="seconds"),
        "term": args.term,
        "days": args.days,
        "model": f"{provider.name}:{provider.model}",
        "prompt_version": DIGEST_VERSION,
        "count": len(todo),
        "items": snapshot_items(todo),
    }
    paths = write_snapshot(snap, stem)
    # ⚠️ 必须先把生成物写回状态库：`todo` 里是副本，`triage` 改的就是这些副本，
    #    不写回的话 brief/detail 只会留在快照里，状态库那一栏永远是空的。
    saved = save_generations(store, todo)
    n = set_status(store, [i.pmid for i in todo], STATUS_SHOWN, shown_in=stem)
    save_store(store)
    print(f"[落库] {saved} 条的提要已写回状态库；{n} 条置为 shown（下次不会再推）")

    print("\n" + "=" * 70)
    for k, p in paths.items():
        size = p.stat().st_size
        print(f"  {k:<5} {p.relative_to(ROOT)}  ({size / 1024:.1f} KB)")
    print("=" * 70)
    print(f"\n挑好后运行：python tools/build_digest.py --pick 3 7 12")
    if stem != base:
        print(f"（本期快照是 {stem}；要指定就加 --from {stem}）")

    if args.push:
        load_env(ROOT / ".env")
        print()
        try:
            channels, skipped = resolve_channels(args.push)
        except PushError as e:
            print(f"✗ 推送未执行：{e}")
            return 1
        if skipped:
            print("⚠️ 跳过：" + "；".join(skipped))
        if channels:
            print(f"[推送] {', '.join(channels)}")
            results = push_snapshot(snap, channels)
            for ch, lines in results.items():
                for ln in lines:
                    print(f"  [{ch}] {ln}")
    return 0


def cmd_pick(args: argparse.Namespace) -> int:
    snap, path = load_snapshot(args.from_date)
    by_n = {int(it["n"]): it for it in snap["items"]}
    store = load_store()

    chosen: list[dict] = []
    missing: list[int] = []
    for n in args.pick:
        it = by_n.get(n)
        if it is None:
            missing.append(n)
        else:
            chosen.append(it)
    if missing:
        print(f"⚠️ 第 {missing} 条不在 {path.name} 里（该期只有 1–{len(by_n)} 条），已跳过")

    if not chosen:
        return 1

    set_status(store, [c["pmid"] for c in chosen], STATUS_PICKED)
    save_store(store)

    print(f"[来源] {path.relative_to(ROOT)}\n")
    for c in chosen:
        it = FeedItem.from_dict(c)   # 用当下的代码重建，不用快照里的旧命令格式
        print("=" * 70)
        print(f"#{c['n']}  {it.title_zh or it.title_en}")
        print(f"    {_short_journal(it.journal)} · {it.pub_date}")
        print(f"    brief    : {it.brief}")
        print(f"    PDF 存成 : {it.doc_id}.pdf  ->  放进 papers/")
        print(f"    运行     : {it.run_command}")
        print(f"    PubMed   : {it.url_pubmed}")
    print("=" * 70)
    print(f"\n已标记 {len(chosen)} 条为 picked（下次跑 --list 会带 ⭐）。")
    return 0


def cmd_render(args: argparse.Namespace) -> int:
    """用已有快照重新渲染 HTML/MD。不检索、不调 LLM，因此**改样式零成本**。"""
    snap, path = load_snapshot(args.from_date)
    paths = write_snapshot(snap, path.stem)
    print(f"用 {path.relative_to(ROOT)} 重渲染：")
    for k, p in paths.items():
        print(f"  {k:<5} {p.relative_to(ROOT)}  ({p.stat().st_size / 1024:.1f} KB)")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    snap, path = load_snapshot(args.from_date)
    print(f"快照：{path.relative_to(ROOT)}  ({snap['date']}, {snap['count']} 条)\n")
    for it in snap["items"]:
        star = "⭐" if it.get("status") == STATUS_PICKED else "  "
        mark, why = brief_verdict(it["brief"])
        print(f"{star}{it['n']:>3}. {mark}{why:<13} "
              f"{_short_journal(it['journal'])[:26]:<27}"
              f"{it['brief'] or it['title_zh'] or it['title_en'][:40]}")
    print(f"\n共 {snap['count']} 条。挑好后：--pick 3 7 12")
    return 0


# ----------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(
        description="PubMed 文献速览：检索 -> 两级提要 -> 手机友好的 HTML/Markdown")
    ap.add_argument("--term", default=DEFAULT_TERM, help=f'检索式（默认 {DEFAULT_TERM}）')
    ap.add_argument("--days", type=int, default=DEFAULT_DAYS, help="回填窗口天数")
    ap.add_argument("--retmax", type=int, default=300, help="最多取回多少条")
    ap.add_argument("--limit", type=int, default=None, help="本次最多推几条（试水用）")
    ap.add_argument("--show-dropped", action="store_true",
                    help="把被过滤掉的条目标题也打出来（人工复核没误杀综述）")
    ap.add_argument("--no-llm", action="store_true", help="只检索，不调用 LLM")
    ap.add_argument("--refresh", action="store_true", help="忽略缓存，重新生成提要")
    ap.add_argument("--provider", default="deepseek")
    ap.add_argument("--model", default=None)
    ap.add_argument("--pick", type=int, nargs="+", metavar="N",
                    help="把最近一期（或 --from）的第 N 条标记为已选，并打印命令")
    ap.add_argument("--from", dest="from_date", default=None,
                    help="指定快照日期（YYYY-MM-DD）或 .json 路径")
    ap.add_argument("--list", action="store_true", help="终端重看最近一期")
    ap.add_argument("--render-only", action="store_true",
                    help="用已有快照重新渲染 HTML/MD（不检索、不调 LLM）")
    ap.add_argument("--push", default="", metavar="LIST",
                    help="生成后直接推送：如 --push telegram,discord 或 --push all")
    ap.add_argument("--no-log", action="store_true",
                    help="不写运行日志（默认会同时写 data/feed/run-log.txt）")
    args = ap.parse_args()

    # 自写运行日志：定时任务里就**不需要**用 cmd.exe 包一层做重定向，
    # 于是任务参数可以全是相对路径（见 src/runlog.py 里的详细说明）。
    if not args.no_log:
        log = attach_log(ROOT / "data" / "feed" / "run-log.txt", sys.argv[1:])
        if log:
            print(f"[日志] {log.relative_to(ROOT)}")

    if args.render_only:
        return cmd_render(args)
    if args.pick:
        return cmd_pick(args)
    if args.list:
        return cmd_list(args)
    return cmd_build(args)


if __name__ == "__main__":
    sys.exit(main())
