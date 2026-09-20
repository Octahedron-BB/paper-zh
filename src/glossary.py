"""术语表：本项目的核心资产。

为什么它比音频值钱
------------------
音频做一遍就过去了，术语表是**跨文献复利**的：读同领域第二篇、第三篇时直接继承。
半年后你手里有几千条私人医学术语表 —— 那是别人抄不走的护城河。

两类条目（决定改动成本）
------------------------
`hard_replace`（硬替换）
    译文生成之后做的**字符串替换**。改它 **0 token、0 延迟、立刻生效**，
    因为中文没有性/数/格变化，术语替换近乎无损（英文换说法往往要重构句子，中文经常直接换词就行）。
    所以凡是能用纯替换解决的，**绝不进 prompt**。
    条目里可以带 `aliases`：LLM 可能给出的其它译法，一并替换成 `zh`。

`prompt_hint`（上下文注入）
    必须写进 prompt 的：歧义澄清、需要改句子结构、需要首次出现加解释的。
    改它 => **只重译命中该术语的段落**（靠 cache.py 的按键失效实现）。

术语命中检测规则
----------------
- 默认按"词边界 + 可选复数/连字符"匹配英文原文
- 可显式给 `pattern`（正则）覆盖默认规则，例如缩写 "SIF" 容易误伤时
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

try:
    import yaml  # type: ignore
    HAS_YAML = True
except Exception:  # pragma: no cover
    HAS_YAML = False


MODE_HARD = "hard_replace"
MODE_HINT = "prompt_hint"
VALID_MODES = {MODE_HARD, MODE_HINT}

# ---------------------------------------------------------------- 作用域
#
# 解决"同一个词/缩写在不同文章里意思不同"的问题。
# 本质：**「字符串 -> 概念」的映射是文档相关的**，所以术语条目必须带作用域。
#
#   global            个人偏好，永远这么译（如 PFC -> 前额叶皮质）
#   field:<name>      学科域（如 field:neuroscience 里 MTL -> 内侧颞叶）
#   doc:<doc_id>      单篇覆盖（如本文 MSN -> 内侧隔核，覆盖全局的"中型棘状神经元"）
#
# 解析时**就近优先**：doc > field > global。
# 同一优先级出现两个不同译法 => **报冲突并中止**，绝不静默挑一个。
SCOPE_GLOBAL = "global"

# 脑区/结构缩写的方位前缀（aDLPFC = anterior DLPFC）
# 这类写法在神经科学里极常见，必须支持，否则 aDLPFC / rDLPFC / lVLPFC 全都匹配不到。
PREFIX_ZH: dict[str, str] = {
    "a": "前部", "p": "后部", "r": "右侧", "l": "左侧",
    "d": "背侧", "v": "腹侧", "m": "内侧", "c": "尾侧", "s": "上",
}

_ABBREV_RE = re.compile(r"^[A-Z][A-Za-z0-9]{0,7}$")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def is_abbrev_term(s: str) -> bool:
    """判断一个术语是不是「缩写」形式（如 DLPFC / SIF / MTL）。"""
    return bool(_ABBREV_RE.match(s.strip()))


def has_cjk(s: str) -> bool:
    return bool(_CJK_RE.search(s))


def scope_rank(scope: str, doc_id: str, field: str | None) -> int:
    """返回该作用域对当前文档的适用等级；-1 表示不适用。数字越大越优先。

    ⚠️ 前缀长度必须用 len("field:")=6 / len("doc:")=4。
    初版这里写成了 scope[7:]，导致所有 doc: 作用域的条目被**静默丢弃**
    （不会报错，只是少了几条术语 —— 这类 bug 最难发现），已用测试守住。
    """
    scope = (scope or SCOPE_GLOBAL).strip()
    if scope == SCOPE_GLOBAL:
        return 0
    if scope.startswith("field:"):
        return 1 if field and scope[len("field:"):] == field else -1
    if scope.startswith("doc:"):
        return 2 if scope[len("doc:"):] == doc_id else -1
    raise ValueError(f"非法 scope: {scope!r}（应为 global / field:<名> / doc:<文档ID>）")


@dataclass
class TermConflict:
    """同一作用域等级下，同一个 term 出现了不同译法 —— 必须人工裁决。"""
    term: str
    rank: int
    entries: list["Term"]

    def describe(self, doc_id: str) -> str:
        where = {0: "global", 1: "field", 2: "doc"}[self.rank]
        opts = "  vs  ".join(f"「{e.zh}」(scope={e.scope})" for e in self.entries)
        return (f"术语 {self.term!r} 在 {where} 层级存在冲突译法：{opts}\n"
                f"    处理办法：给其中一个加更具体的作用域，例如 "
                f"在 glossary-d/{doc_id}.yaml 里写 scope: doc:{doc_id}")


@dataclass
class Term:
    term: str                       # 英文原文术语
    zh: str                         # 期望的中文译法
    mode: str = MODE_HINT
    note: str = ""                  # 对 LLM 的说明（仅 prompt_hint 有意义）
    aliases: list[str] = field(default_factory=list)   # 其它需要被替换掉的译法
    pattern: str | None = None      # 自定义正则（命中检测用）
    prefix_variants: bool = True    # 缩写是否允许方位前缀变体（aDLPFC / rDLPFC）
    status: str = "suggested"       # suggested | approved | rejected
    scope: str = SCOPE_GLOBAL       # global | field:<名> | doc:<文档ID>
    # 缩写的英文全称（建议填写）—— 有了它才能**精确**检测"同名异义"，
    # 否则只能靠中文译法反推英文，必然误报（详见 abbrev.conflict_report）
    full_en: str = ""

    # ---------- 命中检测 ----------
    def regex(self) -> re.Pattern[str]:
        if self.pattern:
            return re.compile(self.pattern, re.IGNORECASE)
        # 术语内部可能含连字符/空格/斜杠；允许复数与可选连字符变体
        parts = [re.escape(p) for p in re.split(r"[\s\-/]+", self.term) if p]
        core = r"[\s\-/]+".join(parts)
        if is_abbrev_term(self.term):
            # 缩写（DLPFC / LAR / IBS …）：允许一个**小写方位前缀**（aDLPFC），
            # 但 **核心必须大小写敏感**。
            # ⚠️ 初版这里用了 re.IGNORECASE + 可选前缀 + `(?:e?s)?`，导致：
            #     "flares" -> 前缀 f + lar + es -> 误命中 LAR
            #     类似地 "fibs" 会误命中 IBS。这是**静默**的错误命中。
            #     （实测后果：硬替换体检报假失败；若换成应用替换，还会污染译文）
            pre = "(?-i:[a-z])?" if self.prefix_variants else ""
            return re.compile(rf"(?<![A-Za-z]){pre}(?-i:{core})s?(?![A-Za-z])")
        return re.compile(rf"(?<![A-Za-z]){core}(?:e?s)?(?![A-Za-z])", re.IGNORECASE)

    def prefixed_regex(self) -> re.Pattern[str]:
        """只匹配「小写方位前缀 + 缩写」形式，并把前缀放进捕获组。用于译文替换。"""
        core = re.escape(self.term)
        return re.compile(rf"(?<![A-Za-z])(?-i:([a-z]))(?-i:{core})(?![A-Za-z])")

    def hits(self, text: str) -> bool:
        return bool(self.regex().search(text))

    def signature(self) -> str:
        """缓存键的一部分：本条的"内容指纹"。改动 zh/mode/note/aliases 都会变。"""
        return "|".join([self.term, self.zh, self.mode, self.note,
                         ",".join(sorted(self.aliases))])

    def to_dict(self) -> dict:
        d = {"term": self.term, "zh": self.zh, "mode": self.mode}
        if self.note:
            d["note"] = self.note
        if self.aliases:
            d["aliases"] = list(self.aliases)
        if self.pattern:
            d["pattern"] = self.pattern
        if self.status != "suggested":
            d["status"] = self.status
        if self.scope != SCOPE_GLOBAL:
            d["scope"] = self.scope
        if self.full_en:
            d["full_en"] = self.full_en
        if not self.prefix_variants:
            d["prefix_variants"] = False
        return d


def load_glossary(path: str | Path) -> list[Term]:
    p = Path(path)
    if not p.exists():
        return []
    text = p.read_text(encoding="utf-8")
    data: list[dict]
    if HAS_YAML and p.suffix in (".yaml", ".yml"):
        loaded = yaml.safe_load(text) or []
        data = loaded.get("terms", []) if isinstance(loaded, dict) else loaded
    else:
        # 无 pyyaml 时的降级：要求一个极简的 "term | zh | mode | note" 行格式
        data = []
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [x.strip() for x in line.split("|")]
            if len(parts) >= 2:
                data.append({"term": parts[0], "zh": parts[1],
                             "mode": parts[2] if len(parts) > 2 else MODE_HINT,
                             "note": parts[3] if len(parts) > 3 else ""})

    terms: list[Term] = []
    for d in data:
        if not isinstance(d, dict) or "term" not in d or "zh" not in d:
            continue
        mode = d.get("mode", MODE_HINT)
        if mode not in VALID_MODES:
            raise ValueError(f"术语 {d['term']!r} 的 mode 非法: {mode!r}（应为 {VALID_MODES}）")
        terms.append(Term(
            term=str(d["term"]).strip(),
            zh=str(d["zh"]).strip(),
            mode=mode,
            note=str(d.get("note", "") or ""),
            aliases=list(d.get("aliases", []) or []),
            pattern=d.get("pattern"),
            status=d.get("status", "suggested"),
            scope=str(d.get("scope", SCOPE_GLOBAL) or SCOPE_GLOBAL),
            full_en=str(d.get("full_en", "") or ""),
            prefix_variants=bool(d.get("prefix_variants", True)),
        ))
    return terms


def load_glossary_dir(root: str | Path, doc_id: str, field: str | None = None) -> list[Term]:
    """加载术语表：主表 `glossary.yaml` + 单篇覆盖 `glossary-d/<doc_id>.yaml`。

    单篇覆盖文件是**解决同名异义的正道**：主表保持干净、可跨文献复用，
    某篇的特殊含义只写在该篇的覆盖文件里。
    """
    root = Path(root)
    terms: list[Term] = []
    main = root / "glossary.yaml"
    if main.exists():
        terms += load_glossary(main)
    override = root / "glossary-d" / f"{doc_id}.yaml"
    if override.exists():
        terms += load_glossary(override)
    return resolve_terms(terms, doc_id=doc_id, field=field)[0]


def resolve_terms(terms: list[Term], *, doc_id: str, field: str | None = None,
                  strict: bool = True) -> tuple[list[Term], list[TermConflict]]:
    """把带作用域的术语表解析成"本文档真正生效的一份表"。

    规则：同一 `term` 取**适用范围内优先级最高**的那条（doc > field > global）。
    同等优先级出现不同译法 => 冲突（strict=True 时抛错，避免静默用错译法）。
    """
    groups: dict[str, list[tuple[int, Term]]] = {}
    for t in active(terms):
        r = scope_rank(t.scope, doc_id, field)
        if r < 0:
            continue
        groups.setdefault(t.term.strip().lower(), []).append((r, t))

    effective: list[Term] = []
    conflicts: list[TermConflict] = []
    for _key, items in groups.items():
        top = max(r for r, _ in items)
        winners = [t for r, t in items if r == top]
        zh_set = {t.zh for t in winners}
        if len(zh_set) > 1:
            conflicts.append(TermConflict(term=winners[0].term, rank=top, entries=winners))
            effective.append(winners[0])      # 仍然放一条进去，便于下游报告能跑出东西
        else:
            effective.append(winners[0])

    if conflicts and strict:
        msgs = "\n".join("  " + c.describe(doc_id) for c in conflicts)
        raise TermConflictError(
            f"术语表存在 {len(conflicts)} 处同名异义冲突，已中止（避免静默用错译法）：\n{msgs}"
        )
    return effective, conflicts


class TermConflictError(RuntimeError):
    pass


def active(terms: Iterable[Term]) -> list[Term]:
    return [t for t in terms if t.status != "rejected"]


def hits_for_text(terms: Iterable[Term], text: str) -> list[Term]:
    """返回**这一段原文里真正命中**的术语。这是"改一个词只失效相关段"的基础。"""
    return [t for t in active(terms) if t.hits(text)]


def hints_for_text(terms: Iterable[Term], text: str) -> list[Term]:
    return [t for t in hits_for_text(terms, text) if t.mode == MODE_HINT]


def hard_terms_hitting(terms: Iterable[Term], text: str) -> list[Term]:
    return [t for t in hits_for_text(terms, text) if t.mode == MODE_HARD]


def hits_signature(terms: Iterable[Term]) -> str:
    """把某一组命中术语压成一个字符串，作为缓存键的一部分。"""
    return " ;; ".join(sorted(t.signature() for t in terms))


def _fix_parenthetical(text: str, t: "Term", lookback: int = 40) -> str:
    """处理译文里中文括号包裹的缩写。

    规则（顺序即优先级）：
      - 括号前 lookback 字符内**已出现** t.zh  => 括号是冗余的，删掉
        （例：「背外侧前额叶（DLPFC）」 -> 「背外侧前额叶」）
      - 否则 => 括号里是唯一的信息载体，把缩写换成中文，**不能删**
        （例：「动作停止指标（SSRT）」 -> 「动作停止指标（停止信号反应时）」）
    """
    pat = re.compile(rf"[（(]\s*(?-i:[a-z])?{re.escape(t.term)}\s*[）)]")
    pieces: list[str] = []
    last = 0
    for m in pat.finditer(text):
        pieces.append(text[last:m.start()])
        before = text[max(0, m.start() - lookback):m.start()]
        pieces.append("" if (t.zh and t.zh in before) else f"（{t.zh}）")
        last = m.end()
    pieces.append(text[last:])
    return "".join(pieces)


def apply_hard_replace(terms: Iterable[Term], translated: str) -> str:
    """对**译文**做零成本替换。只作用于 `hard_replace` 类条目，所以改这类术语永不重跑 LLM。

    处理四类情况（顺序重要）：
      ① 中文括号里的冗余缩写：`背外侧前额叶（DLPFC）` -> 删掉括号部分，
         否则下一步会变成 `背外侧前额叶（背外侧前额叶）`
      ② 带方位前缀的英文缩写：`aDLPFC` -> `前部背外侧前额叶`
         （仅当 zh 是中文时才加前缀；zh 本身就是缩写则保持原样，避免译出「前部DLPFC」这种别扭写法）
      ③ 英文原词本身：`DLPFC` -> `背外侧前额叶`
         ⚠️ 初版漏了这一步，只替换 aliases —— 于是 LLM 只要保留英文缩写，
            这条 hard_replace 就形同虚设（本文的 DLPFC 就是这么漏的）
      ④ 同义别名：`抑制性控制` -> `抑制控制`

    💡 如果你希望**保留英文缩写不译**（中文医学文献里的常见做法），
       把该条的 zh 直接设成缩写本身即可（如 `zh: DLPFC`），此时 ②③ 变成无操作。
    """
    out = translated
    for t in active(terms):
        if t.mode != MODE_HARD:
            continue

        # ① 处理中文括号里的缩写
        # ⚠️ 初版这里是无条件删除 `（ABBR）`，会**丢信息**：
        #    英文 "Action stopping indices (SSRT)" 译成「动作停止指标（SSRT）」时，
        #    括号前并没有中文译名，删掉就把 SSRT 整个丢了（本文真实踩到过）。
        #    正确规则：**仅当括号前已出现中文译名时才删**，否则把缩写换成中文。
        out = _fix_parenthetical(out, t)

        # ② 带前缀变体
        if t.prefix_variants and is_abbrev_term(t.term) and has_cjk(t.zh):
            def _sub(m, _zh=t.zh):
                return PREFIX_ZH.get(m.group(1).lower(), m.group(1)) + _zh
            out = t.prefixed_regex().sub(_sub, out)

        # ③ 英文原词
        out = re.sub(rf"(?<![A-Za-z]){re.escape(t.term)}(?![A-Za-z])", t.zh, out)

        # ④ 同义别名
        for alias in t.aliases:
            if alias and alias != t.zh:
                out = out.replace(alias, t.zh)
    return out


def render_prompt_block(terms: Iterable[Term], include_hard: bool = True) -> str:
    """把命中的术语渲染成给 LLM 的说明块。

    include_hard=True 时**两类都注入**，这是有意的设计：
    - `prompt_hint` 注入是必须的（它本来就是靠 prompt 生效）
    - `hard_replace` 也注入，是为了让 LLM 第一版就产出正确译名，减少后处理漏网
      但**它不进缓存键** —— 所以改了 hard 术语不会触发重译，
      只是靠 apply_hard_replace 做字符串替换 + 事后的"硬替换体检"发现漏网变体。
    """
    lines = []
    for t in active(terms):
        if t.mode == MODE_HINT:
            seg = f"- {t.term} -> 「{t.zh}」"
            if t.note:
                seg += f"（{t.note}）"
        elif include_hard:
            seg = f"- {t.term} -> 「{t.zh}」（统一用此译名）"
        else:
            continue
        lines.append(seg)
    return "\n".join(lines)
