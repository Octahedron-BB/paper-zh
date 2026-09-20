"""缩写消歧：自动发现"同一个缩写在这篇文章里其实是另一个意思"。

为什么需要它
------------
用户提的问题：**同一个词/缩写在不同文章意思可能不同**。
这类冲突最危险，因为：
  - 事前想不到（你不会记得 MSN 在别处是中棘神经元）
  - 事后很难发现（译文看起来完全通顺，只是全篇错了）
  - 代价不对称（改一个术语可能触发 40+ 段重译）

做法：**不猜，找证据。**
学术论文有个强惯例 —— 缩写首次出现时必定给全称，形式是：
    全称 (ABBR)        例如  medial septal nucleus (MSN)
    ABBR (全称)        例如  SIF (suppression-induced forgetting)
这是**纯正则就能抽的**，不需要 LLM。抽出"本文档的缩写 -> 全称"映射后，
再和你的术语表比对，冲突就暴露出来了。

额外的正确性保险：**首字母校验**
抽出的全称，其有效词的首字母必须能拼出该缩写（作为子序列）。
例如 "suppression-induced forgetting" -> S,I,F 能拼出 SIF ✓；
      "medial septal nucleus" -> M,S,N 能拼出 MSN ✓。
这一步把大量误报（例如 "Table 1 (T1)"）过滤掉了。
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Iterable

# 全称里这些词不参与首字母（虚词/冠词/连接词）
STOP = {"of", "the", "in", "and", "for", "to", "a", "an", "on", "with", "by",
        "as", "at", "from", "or", "its", "their", "that", "which"}

# ABBR 的定义样式：2-8 个大写字母（允许数字，如 GABAergic -> 不算；IL6 之类）
_ABBR = r"[A-Z][A-Za-z0-9]{1,7}"

# 全称 (ABBR)
PAT_FULL_FIRST = re.compile(
    rf"\b((?:[A-Za-z][A-Za-z\-']*\s+){{1,6}}[A-Za-z][A-Za-z\-']*)\s*\(\s*({_ABBR})\s*\)"
)
# ABBR (全称)
PAT_ABBR_FIRST = re.compile(
    rf"\b({_ABBR})\s*\(\s*([a-z][A-Za-z\-']*(?:\s+[A-Za-z\-']+){{0,6}})\s*\)"
)


def initials_of(full: str) -> str:
    words = [w for w in re.findall(r"[A-Za-z]+", full) if w.lower() not in STOP]
    return "".join(w[0].upper() for w in words)


def _is_subsequence(needle: str, hay: str) -> bool:
    it = iter(hay)
    return all(c in it for c in needle)


def initials_ok(abbr: str, full: str) -> bool:
    """首字母校验：缩写必须是全称有效词首字母序列的子序列。"""
    a, s = abbr.upper(), initials_of(full)
    if len(a) < 2 or not s:
        return False
    if not _is_subsequence(a, s):
        return False
    # 防止"全称"其实是一整句话：有效词数不应远多于缩写长度
    return len(s) <= len(a) + 3


def _trim_to_shortest(abbr: str, phrase: str) -> str | None:
    """把候选全称裁剪成**最短的、能拼出该缩写的后缀**。

    为什么必须做这一步
    ------------------
    PDF 抽出的文本没有段落边界，正则很容易把整句吃进来：
        "suggests that suppressing the medial septal nucleus (MSN)"
    裁成 "medial septal nucleus" 才对。

    做法：**从右往左贪心**，逐个吃掉首字母等于缩写末位的词（跳过虚词），
    吃完所有字母就停，剩下的左侧词一律丢弃；中途对不上就判定该候选无效。
    这个方法同时修掉了 "as in post-traumatic stress disorder"、
    "measured as stop signal reaction time"、"trials reflects a negative blood oxygenation
    level-dependent" 这几类，效果比加黑名单干净得多。
    """
    abbr = abbr.upper()
    need = list(abbr)[::-1]                     # 从末位开始
    tokens = list(re.finditer(r"[A-Za-z]+", phrase))   # 连字符词会被拆开，便于首字母校验
    if not tokens:
        return None

    k = 0
    start_tok = None
    end_tok = None
    for tok in reversed(tokens):
        if k >= len(need):
            break                                # 字母已吃完 -> 立刻停，别再往后看
        w = tok.group(0)
        if w.lower() in STOP:
            continue
        if w[0].upper() == need[k]:
            if end_tok is None:
                end_tok = tok
            start_tok = tok
            k += 1
        else:
            return None                          # 中断 => 该候选不成立
    if k < len(need):
        return None

    # 用原始字符位置切片，保留 "post-traumatic" 这类连字符写法
    return phrase[start_tok.start(): end_tok.end()].strip()


def _norm(s: str) -> str:
    """归一化：折叠空白 + 转小写。用于"同一个全称因换行/大小写被算成两个"的去重。"""
    return re.sub(r"\s+", " ", s).strip().lower()


def extract_definitions(text: str) -> dict[str, set[str]]:
    """从全文中抽取 缩写 -> {全称}（已裁剪为最短有效后缀，并按归一化去重）。"""
    raw: dict[str, dict[str, str]] = defaultdict(dict)   # abbr -> {norm: display}

    def add(abbr: str, phrase: str) -> None:
        trimmed = _trim_to_shortest(abbr, phrase)
        if trimmed and initials_ok(abbr, trimmed):
            raw[abbr].setdefault(_norm(trimmed), re.sub(r"\s+", " ", trimmed).strip())

    for m in PAT_FULL_FIRST.finditer(text):
        add(m.group(2).strip(), m.group(1).strip())
    for m in PAT_ABBR_FIRST.finditer(text):
        add(m.group(1).strip(), m.group(2).strip())

    return {a: set(v.values()) for a, v in raw.items()}


def count_usage(text: str, abbr: str) -> int:
    return len(re.findall(rf"(?<![A-Za-z]){re.escape(abbr)}(?![A-Za-z])", text))


@dataclass
class AbbrHit:
    abbr: str
    full_names: list[str]
    count: int
    in_glossary: bool = False
    glossary_zh: str = ""


@dataclass
class AuditReport:
    defined: list[AbbrHit] = field(default_factory=list)
    # 术语表里有、但本文没有给出定义的缩写（文章可能假定读者已知）
    glossary_abbrs_without_definition: list[str] = field(default_factory=list)
    # 一个缩写对应多个全称 -> 本文内部就有歧义
    ambiguous_in_doc: list[AbbrHit] = field(default_factory=list)

    def render(self, top: int = 40) -> str:
        L = []
        L.append(f"本文给出的缩写定义：{len(self.defined)} 个")
        L.append(f"{'缩写':<10}{'出现':>5}  {'术语表':<8} 全称")
        for h in self.defined[:top]:
            mark = f"有: {h.glossary_zh}" if h.in_glossary else "—"
            L.append(f"{h.abbr:<10}{h.count:>5}  {mark:<8} {' / '.join(h.full_names)}")
        if len(self.defined) > top:
            L.append(f"...（另有 {len(self.defined) - top} 个，用 --top 调大）")

        if self.ambiguous_in_doc:
            L.append("")
            L.append("⚠️ 本文内部就有歧义的缩写（一个缩写对应多个全称）：")
            for h in self.ambiguous_in_doc:
                L.append(f"    {h.abbr}: {' | '.join(h.full_names)}")

        if self.glossary_abbrs_without_definition:
            L.append("")
            L.append("术语表里是缩写、但本文未给定义（可能假定读者已知，属正常）：")
            L.append("    " + ", ".join(self.glossary_abbrs_without_definition))
        return "\n".join(L)


def audit(terms: Iterable, text: str, *, min_count: int = 2,
          top: int = 40, defs: dict[str, set[str]] | None = None) -> AuditReport:
    """把本文的缩写定义与术语表比对，找出矛盾。

    参数
    ----
    text      **用于统计使用频率**的文本。应当只传正文（不含图注），否则会出现假缩写。
    defs      **缩写定义表**。若为 None 则从 text 现抽。
              最佳实践：defs 从**全文（含 Box/Glossary）**抽，text 只传正文 ——
              因为有些缩写（如本文的 SIF）定义写在 Box 或术语表框里，
              却在正文中被反复使用。只看正文会漏掉它。
    """
    terms = list(terms)
    if defs is None:
        defs = extract_definitions(text)
    rep = AuditReport()

    # 术语表索引：既按 term 本身（缩写形式），也按术语的 term 是否等于全称
    by_lower = {t.term.strip().lower(): t for t in terms}

    for abbr, fulls in defs.items():
        cnt = count_usage(text, abbr)
        if cnt < min_count:
            continue
        hit = AbbrHit(abbr=abbr, full_names=sorted(fulls), count=cnt)
        # 术语表里是否有这个缩写
        t = by_lower.get(abbr.lower())
        if t:
            hit.in_glossary, hit.glossary_zh = True, t.zh
        else:
            # 或者术语表里有对应的全称条目
            for f in fulls:
                t2 = by_lower.get(f.lower())
                if t2:
                    hit.in_glossary, hit.glossary_zh = True, t2.zh
                    break
        rep.defined.append(hit)
        if len(fulls) > 1:
            rep.ambiguous_in_doc.append(hit)

    rep.defined.sort(key=lambda h: -h.count)

    for t in terms:
        tn = t.term.strip()
        if re.fullmatch(_ABBR, tn) and tn not in defs:
            rep.glossary_abbrs_without_definition.append(f"{tn}({t.zh})")
    return rep


def conflict_report(terms: Iterable, doc_defs: dict[str, set[str]]) -> tuple[list[str], list[str]]:
    """找出「术语表里存的含义」与「本文定义的全称」不一致的缩写。

    设计原则：**不猜，靠声明。**
    术语表条目可以填 `full_en`（缩写的英文全称）。填了就能做**精确字符串比对**；
    没填就没法自动判定 —— 此时输出的是"待办"而不是"冲突"，
    因为用中文译法去反推英文全称是不可靠的（初版就是这么做的，全是误报）。

    返回 (冲突列表, 待办列表)。
    """
    conflicts: list[str] = []
    todos: list[str] = []
    for t in terms:
        tn = t.term.strip()
        if not re.fullmatch(_ABBR, tn) or tn not in doc_defs:
            continue
        doc_full = sorted(doc_defs[tn])
        declared = (getattr(t, "full_en", "") or "").strip()
        if declared:
            if _norm(declared) not in {_norm(f) for f in doc_full}:
                conflicts.append(
                    f"⚠️ 同名异义：缩写 {tn} 在术语表里声明为 "
                    f"{declared!r}（译「{t.zh}」），但**本文**把它定义为 "
                    f"{' / '.join(doc_full)}。\n"
                    f"    处理：在 glossary-d/{'{doc_id}'}.yaml 里用 "
                    f"scope: doc:{{doc_id}} 覆盖本文的译法（**不要**改全局表）"
                )
        else:
            todos.append(
                f"{tn}: 术语表未声明英文全称；本文定义为 {' / '.join(doc_full)}。"
                f"建议给这条补 `full_en: ...` 以便以后自动查同名异义"
            )
    return conflicts, todos
