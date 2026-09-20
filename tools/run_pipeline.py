"""流水线 CLI：分段 -> 轨A 翻译 -> 轨B 讲稿。

用法（在项目根目录下）：
  # 先只跑 3 段试水，确认 API 通了、译文质量可接受
  python tools/run_pipeline.py --stage all --limit 3

  # 全篇
  python tools/run_pipeline.py --stage all

  # 只重跑某些段（改了术语之后，只重译受影响的段）
  python tools/run_pipeline.py --stage translate --only 03-inhibitory-control-in-retr

  # 换模型（缓存按模型隔离，不会串味）
  python tools/run_pipeline.py --stage all --model deepseek-reasoner
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from src.cache import Cache  # noqa: E402
from src.glossary import load_glossary_dir  # noqa: E402
from src.providers import build_provider, load_env  # noqa: E402
from src.segment import load_or_segment  # noqa: E402
from src.translate import hard_replace_audit, run_translate, save_translation  # noqa: E402

PDF_DEFAULT = ROOT / "papers" / "s41583-025-00929-y.pdf"


def resolve_pdf(name: str | None) -> Path:
    """找 PDF。支持三种写法，优先级从高到低：
      1. 绝对路径
      2. 相对仓库根的路径（如 papers/xxx.pdf）
      3. **只给文件名或 doc_id**（如 `--pdf s41575-024-00932-1`）—— 在 papers/ 里找，
         自动补 .pdf 后缀。这是操作文档里推荐的写法，最不容易写错。
    """
    if not name:
        return PDF_DEFAULT
    p = Path(name)
    cands = ([p] if p.is_absolute() else []) + [
        ROOT / p,
        ROOT / "papers" / p,
        ROOT / "papers" / f"{p.name}.pdf",
    ]
    for c in cands:
        if c.exists():
            return c
    return ROOT / "papers" / p      # 都不存在 -> 交给下游报“文件不存在”


META_DIR = ROOT / "data" / "meta"


def resolve_field(doc_id: str, cli_field: str | None) -> str | None:
    """把学科域跟着文档记录下来，避免“忘记 --field 就静默少用一批术语”。

    ⚠️ 实测（s41583）：带 `--field neuroscience` 时生效 **30** 条术语，
    不带只剩 **25** 条 —— DLPFC / VLPFC / SSRT 的 scope 都是 `field:neuroscience`，
    全部被丢掉。而 `hard_replace` 类术语**按设计不进缓存键**（这样改译名才免费），
    所以缓存依然 100% 命中、命令也不报错，**产物静默降级**。
    唯一能发现的地方是 QA 的 [E] 项 —— 这个坑就是这么被发现的。

    对策：首次指定时把 field 记到 `data/meta/<doc_id>.json`，以后忘了参数就沿用；
    如果前后不一致则响亮提醒（换一套术语会让同一篇的译文前后不统一）。
    """
    meta = META_DIR / f"{doc_id}.json"
    saved: str | None = None
    if meta.exists():
        try:
            saved = json.loads(meta.read_text(encoding="utf-8")).get("field")
        except (ValueError, OSError):
            saved = None
    if cli_field is None and saved:
        print(f"[field] 本次未指定，沿用记录值 field={saved!r}"
              f"（否则会静默少用 field 级术语）")
        return saved
    if cli_field and saved and cli_field != saved:
        print(f"[field] ⚠️ 本次 field={cli_field!r} 与记录值 {saved!r} 不一致："
              f"术语表会换一套，同一篇的译文可能前后不一致")
    if cli_field:
        META_DIR.mkdir(parents=True, exist_ok=True)
        meta.write_text(json.dumps({"doc_id": doc_id, "field": cli_field},
                                   ensure_ascii=False, indent=1), encoding="utf-8")
    return cli_field if cli_field is not None else saved


def main() -> int:
    ap = argparse.ArgumentParser(description="文献 -> 中文分层伴读 流水线")
    ap.add_argument("--pdf", default=None,
                    help="目标 PDF：可给绝对路径、相对路径，或只给文件名/doc_id（在 papers/ 里找）")
    ap.add_argument("--doc-id", default=None, help="文档 ID（默认取 PDF 文件名）")
    ap.add_argument("--field", default=None,
                    help="学科域，用于 field 级术语（如 neuroscience）。"
                         "⚠️ 带 field 作用域的术语**只有指定了它才生效**；"
                         "首次指定后会记录到 data/meta/，以后可省略")
    ap.add_argument("--stage", choices=["segment", "translate", "script", "all"],
                    default="all")
    ap.add_argument("--provider", default=None, help="deepseek / openai / gemini / mock")
    ap.add_argument("--model", default=None)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--limit", type=int, default=None, help="只处理前 N 段（试水用）")
    ap.add_argument("--only", nargs="*", default=None, help="只处理这些 sid 或 节路径")
    ap.add_argument("--force-segment", action="store_true", help="强制重新分段")
    args = ap.parse_args()

    load_env(ROOT / ".env")
    pdf = resolve_pdf(args.pdf)
    doc_id = args.doc_id or pdf.stem
    field = resolve_field(doc_id, args.field)

    print("=" * 76)
    print(f"[文档] {pdf.name}  doc_id={doc_id}  field={field or '(无)'}")
    doc = load_or_segment(pdf, ROOT / "data" / "segments" / f"{doc_id}.json",
                          doc_id=doc_id, force=args.force_segment)
    st = doc.stats()
    print(f"[分段] {st['sections']} 节 / {st['segments']} 段 / {st['words']:,} 词 "
          f"（每段中位 {st['words_median']} 词）")
    print(f"[标题] {doc.title[:70]}")
    if args.stage == "segment":
        return 0

    terms = load_glossary_dir(ROOT, doc_id=doc_id, field=field)
    print(f"[术语] 生效 {len(terms)} 条（主表 + glossary-d/{doc_id}.yaml）")

    provider = build_provider(args.provider, args.model)
    print(f"[模型] {provider.name} / {provider.model}")
    if provider.name == "mock":
        print("      ⚠️ 用的是 mock provider，不会产生真实译文")

    cache = Cache(ROOT / "data" / "cache")
    translated: dict = {}

    if args.stage in ("translate", "all"):
        print(f"\n--- 轨A：忠实翻译（并发 {args.workers}）---")
        results, stats = run_translate(doc, terms, provider, cache,
                                       workers=args.workers, only=args.only,
                                       limit=args.limit)
        print(f"[轨A] {stats.line()}")
        for sid, err in stats.failed[:5]:
            print(f"      ❌ {sid}: {err}")
        jp, mp = save_translation(doc, results, provider, ROOT / "data" / "translation")
        print(f"[轨A] 产物: {jp.relative_to(ROOT)}  |  {mp.relative_to(ROOT)}")
        problems = hard_replace_audit(doc, terms, results)
        if problems:
            print(f"\n[硬替换体检] {len(problems)} 条需要你复核：")
            for p in problems[:8]:
                print("   " + p)
        translated = results

    if args.stage in ("script", "all"):
        if not translated:
            import json
            p = ROOT / "data" / "translation" / f"{doc_id}.json"
            if not p.exists():
                print("找不到轨A 产物，请先跑 --stage translate")
                return 1
            data = json.loads(p.read_text(encoding="utf-8"))
            # 优先用替换前的原始译文（与轨B 的缓存键一致）
            translated = {sid: {"text": v.get("zh_raw") or v["zh"],
                               "text_raw": v.get("zh_raw") or v["zh"]}
                          for sid, v in data["segments"].items()}
        print(f"\n--- 轨B：口语讲稿（并发 {args.workers}）---")
        from src.rewrite import run_rewrite, save_script
        sresults, sstats = run_rewrite(doc, translated, terms, provider, cache,
                                       workers=args.workers, limit=args.limit)
        print(f"[轨B] {sstats.line()}")
        for sid, err in sstats.failed[:5]:
            print(f"      ❌ {sid}: {err}")
        if sstats.low_preserve:
            print(f"[轨B] ⚠️ 保全率 < 0.80 的段落（最可能是被 LLM 偷偷概括了，优先复核）：")
            for sid, r in sorted(sstats.low_preserve, key=lambda x: x[1])[:10]:
                print(f"      {r:.2f}  {sid}")
        jp, mp = save_script(doc, sresults, provider, ROOT / "data" / "script")
        print(f"[轨B] 产物: {jp.relative_to(ROOT)}  |  {mp.relative_to(ROOT)}")

    print(f"\n[缓存] {cache.stats()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
