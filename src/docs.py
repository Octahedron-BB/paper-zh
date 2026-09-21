"""文档发现：papers/ 里有哪些 PDF、哪些已经跑到哪一步。

为什么单独一个模块
------------------
"谁是谁"这段逻辑以前被复制成了 **4 份硬编码清单**：
  `tests/test_segment.py` 的 CASES、`tools/qa_report.py` 的 DOCS、
  `devtools/audit_hard_landing.py` 与 `devtools/audit_term_density.py` 的 FIELDS。
后果是新处理的文献**静默漏检** —— 2026-09-21 处理 s41575-026-01258-w
时才发现 QA 报告里根本没有它、分段测试也从没覆盖它（而它当时确实带着 bug）。
**凡是"新文献要人工加一行"的地方，都是同一个坑。**

同样的坑还有一类：`--doc-id` 的 `default="s41575-024-00932-1"`。
忘记传参数时它会**静默对着另一篇文献干活**（不会报错，只是结果全错）。
所以这里统一改成 `resolve_doc_id()`：显式给了就用，没给就自动挑，
挑不出来就报错并列候选 —— **宁可报错，也不要猜错。**

约定
----
- `doc_id` 就是 PDF 的文件名（stem），也是 DOI 后缀（见 src/feed.py 的 doi_to_doc_id）。
- 学科域 `field` 记在 `data/meta/<doc_id>.json`，由 run_pipeline 的 `--field` 写入。
"""

from __future__ import annotations

import json
from pathlib import Path

# 阶段 -> (相对目录, 后缀)。用来判断"这篇跑到哪一步了"。
ARTIFACTS: dict[str, tuple[str, str]] = {
    "segments": ("data/segments", ".json"),
    "translation": ("data/translation", ".json"),
    "script": ("data/script", ".json"),
    "interleave": ("data/interleave", ".md"),
    "audio": ("data/audio", ".mp3"),
    "reader": ("data/reader", ".html"),
}


def papers_dir(root: str | Path) -> Path:
    return Path(root) / "papers"


def pdf_ids(root: str | Path) -> list[str]:
    """`papers/*.pdf` 的 doc_id，按名字排序。

    只看**直接子文件**：`papers/inbox/` 是"手工下载暂存区"，里面的 PDF 还没认领，
    不该被当成已完成文档。
    """
    d = papers_dir(root)
    return sorted(p.stem for p in d.glob("*.pdf")) if d.is_dir() else []


def ids_with(root: str | Path, stage: str) -> list[str]:
    """已经产出 `stage` 阶段产物的 doc_id，按名字排序。"""
    try:
        rel, suffix = ARTIFACTS[stage]
    except KeyError:
        raise ValueError(f"未知阶段 {stage!r}，可选：{sorted(ARTIFACTS)}") from None
    d = Path(root) / rel
    if not d.is_dir():
        return []
    # `--limit N` 试水会产出 <doc_id>_sample_<N>.mp3，那不是独立文档，要排除
    return sorted(p.stem for p in d.glob(f"*{suffix}")
                  if "_sample_" not in p.stem)


def read_field(root: str | Path, doc_id: str) -> str | None:
    """读 `data/meta/<doc_id>.json` 记录的学科域。

    读不到就返回 None，**不报错** —— field 只影响 field 级术语能否生效，
    缺了它顶多是术语少几条，不该让整个体检脚本挂掉。
    """
    p = Path(root) / "data" / "meta" / f"{doc_id}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("field")
    except (ValueError, OSError):
        return None


def processed_docs(root: str | Path,
                   stage: str = "translation") -> list[tuple[str, str | None]]:
    """`(doc_id, field)` 列表，供跨文档体检使用。

    默认以**轨A 产物**为"已处理"的判据（QA 报告的前提就是有译文）。
    """
    return [(d, read_field(root, d)) for d in ids_with(root, stage)]


def resolve_doc_id(root: str | Path, given: str | None, *,
                   stage: str = "translation") -> str:
    """`--doc-id` 的取值：给了就用；没给就自动挑；挑不出来报错并列候选。"""
    if given:
        return given
    cands = ids_with(root, stage)
    if len(cands) == 1:
        return cands[0]
    if not cands:
        raise SystemExit(
            f"[错误] 没有任何文档产出过 {stage} 产物；先跑 tools/run_pipeline.py")
    raise SystemExit(
        f"[错误] 有 {len(cands)} 篇可选，请显式指定 --doc-id：{', '.join(cands)}")
