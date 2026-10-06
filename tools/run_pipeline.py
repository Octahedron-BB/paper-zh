"""文献 -> 中文分层伴读 端到端完整流水线 CLI。

完整流程：
1. [PDF 分段] 提取结构化章节与段落 -> data/segments/<doc_id>.json
2. [轨A 翻译] 术语约束下的忠实学术翻译 -> data/translation/<doc_id>.json & .md
3. [轨B 讲稿] 听觉友好、多音字规避的口语科普讲稿 -> data/script/<doc_id>.json & .md
4. [中英对照] 双向对齐的中英交错 Markdown -> data/interleave/<doc_id>.md
5. [语音合成] 多音字清洗、Edge-TTS 异步并发合成、毫秒级时间戳对齐 -> data/audio/
6. [伴读网页] 单文件自包含 Web Reader (含音频/时间戳/逐句高亮) -> data/reader/<doc_id>.html

常用命令：
  # 单篇端到端全流程运行（从 PDF 到最终 HTML 伴读网页）：
  python tools/run_pipeline.py --pdf s41575-024-00932-1

  # 一键批量跑通 papers/ 目录下的所有 PDF：
  python tools/run_pipeline.py --all

  # 试水前 3 段（验证 API 与发音）：
  python tools/run_pipeline.py --pdf s41574-022-00638-x --limit 3

  # 仅运行特定阶段（如只重跑语音与伴读网页）：
  python tools/run_pipeline.py --pdf vieta2018 --stage audio
  python tools/run_pipeline.py --pdf vieta2018 --stage reader

  # 仅处理文本，跳过语音合成：
  python tools/run_pipeline.py --pdf s41575-024-00932-1 --no-audio
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from src.docs import pdf_ids  # noqa: E402
from src.cache import Cache  # noqa: E402
from src.glossary import load_glossary_dir  # noqa: E402
from src.providers import build_provider, load_env  # noqa: E402
from src.segment import load_or_segment  # noqa: E402
from src.translate import hard_replace_audit, run_translate, save_translation  # noqa: E402
from tools.build_interleave import run_build_interleave  # noqa: E402
from tools.build_audio import DEFAULT_VOICE, run_audio_pipeline  # noqa: E402
from tools.build_reader import build_reader  # noqa: E402

META_DIR = ROOT / "data" / "meta"


def resolve_document(target: str | None = None, doc_id: str | None = None,
                     prefer_html: bool = True) -> tuple[Path, str, str]:
    """寻找输入文档（支持 HTML 与 PDF，支持自动反代拉取）。
    返回 (Path, "html" | "pdf", doc_id)。
    """
    raw_id = (doc_id or target or "").replace(".pdf", "").replace(".html", "").strip()

    # 1. 显式给定了本地存在的文件路径
    if target:
        p = Path(target)
        if not p.is_absolute():
            p = ROOT / p if (ROOT / p).exists() else ROOT / "papers" / p
        if p.exists():
            dtype = "html" if p.suffix.lower() == ".html" else "pdf"
            return p, dtype, p.stem

    # 2. 根据 doc_id 在 papers/ 查找
    if raw_id:
        h = ROOT / "papers" / f"{raw_id}.html"
        pdf = ROOT / "papers" / f"{raw_id}.pdf"
        if prefer_html and h.exists():
            return h, "html", raw_id
        if not prefer_html and pdf.exists():
            return pdf, "pdf", raw_id
        if h.exists():
            return h, "html", raw_id
        if pdf.exists():
            return pdf, "pdf", raw_id

        # 3. 本地无文件，尝试通过机构反代自动拉取
        env = load_env(ROOT / ".env")
        if env.get("ACADEMIC_PROXY_BASE_URL"):
            try:
                print(f"[反代抓取] 正在通过机构代理拉取 {raw_id} 的网页版全文...")
                from src.fetcher import fetch_article_html
                fetched = fetch_article_html(raw_id, out_path=h)
                print(f"[反代抓取] 成功获取 HTML: {fetched.relative_to(ROOT)}")
                return fetched, "html", raw_id
            except Exception as e:
                print(f"[反代抓取提示] 自动拉取未成功 ({e})")
                if pdf.exists():
                    print(f"[降级] 自动切回本地已有的 PDF: {pdf.name}")
                    return pdf, "pdf", raw_id

    # 4. 未指定参数：检查 papers/ 目录
    from src.docs import doc_ids
    dids = doc_ids(ROOT)
    if len(dids) == 1:
        did = dids[0]
        h = ROOT / "papers" / f"{did}.html"
        pdf = ROOT / "papers" / f"{did}.pdf"
        if prefer_html and h.exists():
            return h, "html", did
        if pdf.exists():
            return pdf, "pdf", did
        if h.exists():
            return h, "html", did
    if not dids:
        raise SystemExit("[错误] papers/ 下没有任何 PDF 或 HTML 文献")
    raise SystemExit(
        f"[错误] papers/ 下有 {len(dids)} 篇，请显式指定目标文献：{', '.join(dids)}")


def resolve_pdf(name: str | None, doc_id: str | None = None) -> Path:
    """兼容旧接口的 PDF 解析。"""
    p, _, _ = resolve_document(target=name, doc_id=doc_id, prefer_html=False)
    return p


def resolve_field(doc_id: str, cli_field: str | None) -> str | None:
    """自动记忆与校验学科域（如 neuroscience / oncology / psychiatry）。"""
    meta = META_DIR / f"{doc_id}.json"
    saved: str | None = None
    if meta.exists():
        try:
            saved = json.loads(meta.read_text(encoding="utf-8")).get("field")
        except (ValueError, OSError):
            saved = None
    if cli_field is None and saved:
        print(f"[field] 本次未指定，沿用记录值 field={saved!r}")
        return saved
    if cli_field and saved and cli_field != saved:
        print(f"[field] ⚠️ 本次 field={cli_field!r} 与记录值 {saved!r} 不一致")
    if cli_field:
        META_DIR.mkdir(parents=True, exist_ok=True)
        meta.write_text(json.dumps({"doc_id": doc_id, "field": cli_field},
                                   ensure_ascii=False, indent=1), encoding="utf-8")
    return cli_field if cli_field is not None else saved


def process_single_doc(doc_path: Path, doc_type: str, args: argparse.Namespace) -> int:
    """处理单篇文档的全流程（支持 HTML 与 PDF）。"""
    doc_id = args.doc_id or doc_path.stem
    field = resolve_field(doc_id, args.field)

    print("=" * 76)
    print(f"[文档] {doc_path.name}  doc_id={doc_id}  格式={doc_type.upper()}  field={field or '(无)'}")

    # 1. 分段阶段
    if doc_type == "html":
        from src.segment_html import load_or_segment_html
        doc = load_or_segment_html(doc_path, ROOT / "data" / "segments" / f"{doc_id}.json",
                                   doc_id=doc_id, force=args.force_segment)
    else:
        doc = load_or_segment(doc_path, ROOT / "data" / "segments" / f"{doc_id}.json",
                              doc_id=doc_id, force=args.force_segment)
    st = doc.stats()
    print(f"[分段] {st['sections']} 节 / {st['segments']} 段 / {st['words']:,} 词 （每段中位 {st['words_median']} 词）")
    print(f"[标题] {doc.title[:70]}")
    if args.stage == "segment":
        return 0

    terms = load_glossary_dir(ROOT, doc_id=doc_id, field=field)
    print(f"[术语] 生效 {len(terms)} 条（主表 + glossary-d/{doc_id}.yaml）")

    provider = build_provider(args.provider, args.model)
    cache = Cache(ROOT / "data" / "cache")
    translated: dict = {}

    # 2. 轨A 翻译阶段
    if args.stage in ("translate", "all") and not args.stage in ("script", "interleave", "audio", "reader"):
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
            print(f"[硬替换体检] {len(problems)} 条需要复核：")
            for p in problems[:5]:
                print("   " + p)
        translated = results

    # 3. 轨B 口语讲稿阶段
    if args.stage in ("script", "all") and not args.stage in ("interleave", "audio", "reader"):
        if not translated:
            p = ROOT / "data" / "translation" / f"{doc_id}.json"
            if not p.exists():
                print(f"[错误] 找不到轨A 产物: {p}，请先运行 --stage translate")
                return 1
            data = json.loads(p.read_text(encoding="utf-8"))
            translated = {sid: {"text": v.get("zh_raw") or v.get("zh") or v.get("translation", ""),
                               "text_raw": v.get("zh_raw") or v.get("zh") or v.get("translation", "")}
                          for sid, v in data["segments"].items()}
        print(f"\n--- 轨B：口语讲稿（并发 {args.workers}）---")
        from src.rewrite import run_rewrite, save_script
        sresults, sstats = run_rewrite(doc, translated, terms, provider, cache,
                                       workers=args.workers, limit=args.limit)
        print(f"[轨B] {sstats.line()}")
        for sid, err in sstats.failed[:5]:
            print(f"      ❌ {sid}: {err}")
        jp, mp = save_script(doc, sresults, provider, ROOT / "data" / "script")
        print(f"[轨B] 产物: {jp.relative_to(ROOT)}  |  {mp.relative_to(ROOT)}")

    # 4. 中英对照阶段
    if args.stage in ("interleave", "all") and not args.stage in ("audio", "reader"):
        print(f"\n--- 中英交错对照生成 ---")
        run_build_interleave(doc_id)

    # 5. 音频合成阶段 (TTS + 时间戳)
    if (args.stage in ("audio", "all") or args.stage == "reader") and not args.no_audio:
        print(f"\n--- 语音合成流水线 (Edge-TTS) ---")
        asyncio.run(run_audio_pipeline(
            doc_id=doc_id,
            voice=args.voice,
            rate=args.rate,
            pitch=args.pitch,
            silence_ms=args.silence_ms,
            limit=args.limit,
            only=args.only,
        ))

    # 6. 自包含 Web Reader 打包阶段
    if args.stage in ("reader", "all") and not args.no_audio:
        print(f"\n--- 自包含 Web Reader 打包 ---")
        reader_file = build_reader(doc_id=doc_id, embed_audio=not args.no_embed)
        print(f"\n🎉 [全流程完成] 文档 {doc_id} 已就绪！")
        print(f"📄 伴读网页: {reader_file}")

    print(f"\n[缓存统计] {cache.stats()}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="文献 -> 中文分层伴读 端到端完整流水线 CLI")
    ap.add_argument("--pdf", default=None,
                    help="目标 PDF：路径、文件名或 doc_id（默认在 papers/ 里找）")
    ap.add_argument("--html", default=None,
                    help="目标 HTML：路径、文件名或 doc_id（网页版优先，支持自动反代拉取）")
    ap.add_argument("--doc-id", default=None, help="文档 ID（默认取文件名）")
    ap.add_argument("--all", action="store_true", help="一键批量处理 papers/ 目录下的所有 PDF")
    ap.add_argument("--field", default=None, help="学科域，用于 field 级术语（如 neuroscience）")
    ap.add_argument("--stage", choices=["segment", "translate", "script", "interleave", "audio", "reader", "all"],
                    default="all", help="运行阶段（默认 all 全流程）")
    ap.add_argument("--provider", default=None, help="LLM 服务商: deepseek / openai / gemini / mock")
    ap.add_argument("--model", default=None, help="指定 LLM 模型名称")
    ap.add_argument("--workers", type=int, default=6, help="并发工作线程数（默认 6）")
    ap.add_argument("--limit", type=int, default=None, help="只处理前 N 段（试水用）")
    ap.add_argument("--only", nargs="*", default=None, help="只处理特定段落或章节")
    ap.add_argument("--force-segment", action="store_true", help="强制重新分段")

    # 语音与播放器选项
    ap.add_argument("--voice", default=DEFAULT_VOICE, help=f"TTS 音色（默认 {DEFAULT_VOICE}）")
    ap.add_argument("--rate", default="+0%", help="TTS 语速微调（如 +10%%）")
    ap.add_argument("--pitch", default="+0Hz", help="TTS 音调微调（如 -2Hz）")
    ap.add_argument("--silence-ms", type=int, default=300, help="段落间微静音时长(毫秒)")
    ap.add_argument("--no-audio", action="store_true", help="跳过语音合成与 HTML 伴读生成")
    ap.add_argument("--no-embed", action="store_true", help="HTML 播放器改用外部相对路径引用音频")

    args = ap.parse_args()
    load_env(ROOT / ".env")

    if args.all:
        papers_dir = ROOT / "papers"
        pdf_files = sorted(papers_dir.glob("*.pdf"))
        if not pdf_files:
            print(f"[错误] 在 {papers_dir} 目录下未找到任何 PDF 文件")
            return 1
        print("=" * 76)
        print(f"🚀 [批量模式] 共发现 {len(pdf_files)} 篇 PDF 待处理")
        print("=" * 76)
        for i, pdf_path in enumerate(pdf_files, 1):
            print(f"\n\n>>>>>>>>>> [{i}/{len(pdf_files)}] 正在处理: {pdf_path.name} <<<<<<<<<<\n")
            args.doc_id = pdf_path.stem
            process_single_doc(pdf_path, "pdf", args)
        print("\n" + "=" * 76)
        print("🎉 [全部完成] 所有文献已全部处理完毕！")
        print("=" * 76)
        return 0
    else:
        prefer_html = bool(args.html or (not args.pdf and (ROOT / "papers" / f"{args.doc_id or ''}.html").exists()))
        doc_path, doc_type, did = resolve_document(args.html or args.pdf, args.doc_id, prefer_html=prefer_html)
        if not doc_path.exists():
            print(f"[错误] 找不到输入文件: {doc_path}")
            return 1
        args.doc_id = did
        return process_single_doc(doc_path, doc_type, args)


if __name__ == "__main__":
    sys.exit(main())
