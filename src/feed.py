"""PubMed 文献流：增量检索 → 归一化成 FeedItem → 落盘。

设计要点
--------
1. **增量靠本地状态，不靠时间窗。** `data/feed/items.json` 记录每条见过的 PMID 与其
   状态（new / shown / picked / done），日常只推 `new`。`--days` 只是**首次回填**的窗口。
   这样"跑几次都不会重复"，而且不依赖任何 PubMed 排序语义。

2. **`doc_id` 完全由 DOI 决定**：`10.1038/s41583-025-00929-y` -> `s41583-025-00929-y`，
   与 `run_pipeline.py` 的 `doc_id = pdf.stem` 规则一致（本地 3 篇 PDF 的文件名即为证）。
   → 因此本模块**不需要拿到 PDF**，就能在用户下载之前把将来要跑的命令准备好。
     这是"手工取 PDF 也能接上工作流"的关键。

3. **只保留有摘要的条目。** 实测近 90 天 566 条里 **61% 没有摘要**，且
   「有摘要」与「带 Review 标签」**重合度 98%**（204/209）—— 有摘要 ≈ 是综述。
   Research Highlight / News / 更正启事都会被这一条滤掉，列表从 **44 条/周降到 16 条/周**。
   这正是用户那句"如果有 Abstract 的也显示出来"的意外价值：它不是显示细节，是判别器。

4. ⚠️ XML 解析一律限定到**本条目自己的容器**。用 `.//ArticleId` 会把**参考文献**的 DOI
   也吃进来（`ReferenceList` 里同样有 `ArticleIdList`），字典后写覆盖先写，
   最终拿到的是最后一条参考文献的 DOI。这个坑已经踩过一次并记在笔记里。

5. **不传 `sort`。** 实测 `esearch` 默认排序**已经**是"最新在前"（等价 `edat`/`date`）；
   而看起来最像正解的 `sort=pub_date` 反而给出另一种顺序，会把最新入库的挤下去。
   显式传 `sort` 只会引入风险，所以这里干脆不传。
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
FEED_DIR = ROOT / "data" / "feed"
STORE_PATH = FEED_DIR / "items.json"

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
USER_AGENT = "paper-zh-personal-research/0.1 (personal, non-commercial)"

DEFAULT_TERM = '"Nat Rev*"[jour]'
DEFAULT_DAYS = 30

STATUS_NEW = "new"
STATUS_SHOWN = "shown"
STATUS_PICKED = "picked"
STATUS_DONE = "done"

_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"])}


# ----------------------------------------------------------------- 网络

class PubMedError(RuntimeError):
    pass


def _get(url: str, tries: int = 3, timeout: int = 90) -> str:
    last: Exception | None = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", "replace")
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.5 * (i + 1))
    raise PubMedError(f"请求失败（重试 {tries} 次）：{url}\n  -> {last}")


def esearch(term: str, *, retmax: int = 200, days: int | None = None,
            sort: str | None = None) -> list[str]:
    """检索 PMID 列表。

    ⚠️ 默认**不传 `sort`**，理由见模块 docstring 第 5 条。
    """
    full = term
    if days:
        full = f"{term} AND \"last {days} days\"[edat]"
    params = {"db": "pubmed", "term": full, "retmode": "json", "retmax": retmax}
    if sort:
        params["sort"] = sort
    url = f"{EUTILS}/esearch.fcgi?{urllib.parse.urlencode(params)}"
    data = json.loads(_get(url))
    return list(data["esearchresult"].get("idlist", []))


def efetch(ids: list[str], *, batch: int = 150) -> list[dict[str, Any]]:
    """取条目的完整题录 + 摘要。

    ⚠️ 解析路径全部写成**从 PubmedArticle 出发的显式路径**，不用 `.//`：
    `.//ArticleId` 会捞到参考文献的 DOI，`.//PMID` 会捞到被引用文献的 PMID。
    """
    out: list[dict[str, Any]] = []
    for i in range(0, len(ids), batch):
        chunk = ids[i : i + batch]
        q = urllib.parse.urlencode(
            {"db": "pubmed", "id": ",".join(chunk), "retmode": "xml"})
        root = ET.fromstring(_get(f"{EUTILS}/efetch.fcgi?{q}"))
        for art in root.findall("./PubmedArticle"):
            aa = art.find("MedlineCitation/Article")
            if aa is None:
                continue

            ids_map: dict[str, str] = {}
            for e in art.findall("PubmedData/ArticleIdList/ArticleId"):
                ids_map[(e.get("IdType") or "").strip()] = (e.text or "").strip()

            jr = aa.find("Journal")
            ptypes = [
                (e.text or "").strip()
                for e in aa.findall("PublicationTypeList/PublicationType")
            ]
            chunks: list[str] = []
            for ab in aa.findall("Abstract/AbstractText"):
                label = ab.get("Label")
                body = "".join(ab.itertext()).strip()
                chunks.append(f"{label}: {body}" if label else body)

            out.append({
                "pmid": art.findtext("MedlineCitation/PMID") or "",
                "doi": ids_map.get("doi", ""),
                "pmc": ids_map.get("pmc", ""),
                "journal": (jr.findtext("Title") if jr is not None else "") or "",
                "journal_abbr": (jr.findtext("ISOAbbreviation") if jr is not None else "") or "",
                "title_en": " ".join((aa.findtext("ArticleTitle") or "").split()),
                "abstract": " ".join(" ".join(chunks).split()),
                "pub_date": _journal_date(aa),
                "entrez_date": _history_date(art, "entrez"),
                "ptypes": ptypes,
            })
        if i + batch < len(ids):
            time.sleep(0.4)  # 未带 API key 时限 3 req/s
    return out


def _journal_date(aa: ET.Element) -> str:
    el = aa.find("Journal/JournalIssue/PubDate")
    if el is None:
        return ""
    y = el.findtext("Year") or ""
    m = el.findtext("Month") or ""
    d = el.findtext("Day") or ""
    if not y:
        # 有些条目只有 MedlineDate，形如 "2026 Sep-Oct"
        md = el.findtext("MedlineDate") or ""
        mm = re.match(r"(\d{4})\s*([A-Za-z]{3})?", md)
        return f"{mm.group(1)}-{_MONTHS.get((mm.group(2) or '').lower(), 0):02d}" if mm else md
    mi = _MONTHS.get(m.lower(), 0) or (int(m) if m.isdigit() else 0)
    return f"{y}-{mi:02d}-{int(d) if d.isdigit() else 0:02d}" if mi else f"{y}"


def _history_date(art: ET.Element, status: str) -> str:
    for e in art.findall("PubmedData/History/PubMedPubDate"):
        if (e.get("PubStatus") or "").lower() != status:
            continue
        y, m, d = e.findtext("Year") or "", e.findtext("Month") or "", e.findtext("Day") or ""
        if y:
            return f"{y}-{int(m or 0):02d}-{int(d or 0):02d}"
    return ""


# ----------------------------------------------------------------- 归一化

def doi_to_doc_id(doi: str) -> str:
    """`10.1038/s41583-025-00929-y` -> `s41583-025-00929-y`。

    与 `run_pipeline.py` 的 `doc_id = pdf.stem` 一致：本地已有 3 篇 PDF 的文件名
    正好就是这个后缀。没有 DOI 时退回用 PMID（也能跑，只是文件名不同）。
    """
    d = (doi or "").strip()
    if "/" in d:
        return d.split("/", 1)[1].strip()
    return d


def journal_to_field(journal: str) -> str:
    """把刊名转成术语表的 `field:` 作用域名（如 neuroscience）。

    单字词的刊转换后正好等于常用写法（Neuroscience / Neurology / Immunology /
    Endocrinology）；多词刊会得到 `molecular-cell-biology` 这类 slug —— 命中不到术语
    **也无害**，因为 `resolve_terms` 只是把不适用的 scope 跳过。

    **故意不维护映射表**：映射表会过期（Nature Reviews 年年开新刊），
    而"从刊名推导"永远不会漏掉新刊。
    """
    j = (journal or "").strip()
    for pref in ("Nature reviews. ", "Nature reviews ", "Nature Reviews. ", "Nature Reviews "):
        if j.startswith(pref):
            j = j[len(pref):]
            break
    j = re.sub(r"[^a-z0-9]+", "-", j.lower()).strip("-")
    return j or "unknown"


@dataclass
class FeedItem:
    """一条文献流条目。

    前一段是**来自 PubMed 的事实**，后一段是**本地状态与生成物**。
    分开是为了让"重跑不会改变事实、只会补生成物"这件事一目了然。
    """
    # ---- 事实（来自 PubMed）----
    pmid: str
    doi: str
    doc_id: str
    journal: str
    journal_abbr: str
    title_en: str
    abstract: str
    pub_date: str
    entrez_date: str
    ptypes: list[str] = field(default_factory=list)
    pmc: str = ""
    # ⚠️ 这个名字**不能**叫 `field`：在类体里声明 `field: str = ""` 会把
    # `dataclasses.field` 遮蔽掉，其后的 `field(default_factory=list)` 就会变成
    # 对字符串的调用 -> TypeError: 'str' object is not callable。
    term_field: str = ""

    # ---- 本地状态 ----
    status: str = STATUS_NEW
    first_seen: str = ""
    shown_in: list[str] = field(default_factory=list)   # 出现在哪几期 digest

    # ---- 生成物 ----
    title_zh: str = ""
    brief: str = ""            # ≤25 字，一屏扫 / 推送用
    detail: str = ""           # 50–85 字，展开看

    # ---- 便捷属性 ----
    @property
    def has_abstract(self) -> bool:
        return bool(self.abstract.strip())

    @property
    def url_pubmed(self) -> str:
        return f"https://pubmed.ncbi.nlm.nih.gov/{self.pmid}/"

    @property
    def url_doi(self) -> str:
        return f"https://doi.org/{self.doi}" if self.doi else ""

    @property
    def run_command(self) -> str:
        """用户手工拿到 PDF 之后要跑的确切命令。"""
        f = f" --field {self.term_field}" if self.term_field else ""
        return f"python tools/run_pipeline.py {self.doc_id}{f} --stage all"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "FeedItem":
        known = {f for f in cls.__dataclass_fields__}          # noqa: SLF001
        return cls(**{k: v for k, v in d.items() if k in known})


def build_item(raw: dict[str, Any]) -> FeedItem:
    doi = raw.get("doi", "")
    return FeedItem(
        pmid=raw["pmid"],
        doi=doi,
        doc_id=doi_to_doc_id(doi) or raw["pmid"],
        journal=raw.get("journal", ""),
        journal_abbr=raw.get("journal_abbr", ""),
        title_en=raw.get("title_en", ""),
        abstract=raw.get("abstract", ""),
        pub_date=raw.get("pub_date", ""),
        entrez_date=raw.get("entrez_date", ""),
        ptypes=list(raw.get("ptypes") or []),
        pmc=raw.get("pmc", ""),
        term_field=journal_to_field(raw.get("journal", "")),
    )


# ----------------------------------------------------------------- 落盘

def load_store(path: Path | None = None) -> dict[str, dict[str, Any]]:
    p = path or STORE_PATH
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except ValueError as e:
        raise PubMedError(f"{p} 不是合法 JSON（拒绝了，避免把好数据覆盖掉）：{e}") from e


def save_store(store: dict[str, dict[str, Any]], path: Path | None = None) -> None:
    """原子写：先写临时文件再 replace，避免中断产生半个 JSON。"""
    p = path or STORE_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(store, f, ensure_ascii=False, indent=1, sort_keys=True)
        os.replace(tmp, p)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


# ----------------------------------------------------------------- 主流程

def retrieve(term: str = DEFAULT_TERM, days: int = DEFAULT_DAYS,
             *, limit: int | None = None, keep_no_abstract: bool = False,
             retmax: int = 300, verbose: bool = True,
             report_dropped: bool = False) -> list[FeedItem]:
    """检索并按"有摘要"过滤，返回 FeedItem 列表（未去重）。

    `report_dropped=True` 会把被丢弃的条目标题一并打出来，**用于人工复核过滤器
    没有误杀真正的综述**。这个自检是必要的：过滤判据一旦写错，症状是
    "某一类文章永远不出现"，而不是报错——属于最难发现的那类 bug。
    """
    ids = esearch(term, retmax=retmax, days=days)
    if verbose:
        print(f"[检索] {term}  近 {days} 天 -> {len(ids)} 条")
    if not ids:
        return []
    raws = efetch(ids)
    items = [build_item(r) for r in raws]
    with_abs = [i for i in items if i.has_abstract]
    dropped = [i for i in items if not i.has_abstract]
    if verbose:
        print(f"[过滤] 有摘要 {len(with_abs)} 条，丢弃 {len(dropped)} 条"
              f"（Research Highlight / News / 更正启事等）")
    if report_dropped and dropped:
        print("  被丢弃的（前 15 条，复核用）：")
        for i in dropped[:15]:
            print(f"    {i.pub_date or i.entrez_date}  {i.journal[:30]:<31}{i.title_en[:58]}")
        if len(dropped) > 15:
            print(f"    …还有 {len(dropped) - 15} 条")
    pick = with_abs if not keep_no_abstract else items
    pick.sort(key=lambda i: (i.entrez_date, i.pmid), reverse=True)   # 最新在前
    return pick[:limit] if limit else pick


def upsert(store: dict[str, dict[str, Any]], items: list[FeedItem]) -> list[FeedItem]:
    """把条目并入状态库，返回其中**首次出现**的那些（也就是本次该推的）。"""
    today = date.today().isoformat()
    fresh: list[FeedItem] = []
    for it in items:
        old = store.get(it.pmid)
        if old is None:
            it.first_seen = today
            store[it.pmid] = it.to_dict()
            fresh.append(it)
        else:
            # 已有条目：只补 PubMed 侧的事实更新，**保留本地状态与生成物**
            merged = FeedItem.from_dict(old)
            for k in ("doi", "doc_id", "journal", "journal_abbr", "title_en",
                      "abstract", "pub_date", "entrez_date", "ptypes", "pmc",
                      "term_field"):
                setattr(merged, k, getattr(it, k))
            store[it.pmid] = merged.to_dict()
    return fresh


def save_generations(store: dict[str, dict[str, Any]], items: list[FeedItem]) -> int:
    """把生成物（`title_zh` / `brief` / `detail`）写回状态库。

    ⚠️ **必须有这一步。** `pending()` 返回的是 `FeedItem.from_dict(...)` 造出来的**副本**，
    `triage` 改的是那些副本；不写回的话，生成的提要在落盘时就被丢掉了 ——
    只存在于快照里，而 `upsert` 里"保留本地生成物"那段合并逻辑也永远用不上。
    症状很隐蔽：一切看似正常（快照里提要好端端的），只是状态库那一栏永远是空的。
    """
    n = 0
    for it in items:
        d = store.get(it.pmid)
        if d is None:
            continue
        d["title_zh"], d["brief"], d["detail"] = it.title_zh, it.brief, it.detail
        n += 1
    return n


def pending(store: dict[str, dict[str, Any]]) -> list[FeedItem]:
    """状态库里所有还没进入过任何一期 digest 的条目，最新在前。"""
    out = [FeedItem.from_dict(d) for d in store.values()
           if d.get("status") == STATUS_NEW]
    out.sort(key=lambda i: (i.entrez_date, i.pmid), reverse=True)
    return out


def set_status(store: dict[str, dict[str, Any]], pmids: list[str], status: str,
               shown_in: str | None = None) -> int:
    n = 0
    for p in pmids:
        d = store.get(p)
        if not d:
            continue
        d["status"] = status
        if shown_in and shown_in not in d.setdefault("shown_in", []):
            d["shown_in"].append(shown_in)
        n += 1
    return n


def last_run(store: dict[str, dict[str, Any]]) -> str:
    days = [d.get("first_seen", "") for d in store.values() if d.get("first_seen")]
    return max(days) if days else ""


def gap_days(store: dict[str, dict[str, Any]]) -> int | None:
    lr = last_run(store)
    if not lr:
        return None
    try:
        return (date.today() - datetime.fromisoformat(lr).date()).days
    except ValueError:
        return None


def stats(store: dict[str, dict[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for d in store.values():
        s = d.get("status", STATUS_NEW)
        out[s] = out.get(s, 0) + 1
    out["total"] = len(store)
    return out


if __name__ == "__main__":  # 便于直接跑：python -m src.feed
    store = load_store()
    print(json.dumps(stats(store), ensure_ascii=False, indent=1))
    g = gap_days(store)
    print("距上次入库：", "无记录" if g is None else f"{g} 天")
    sys.exit(0)
