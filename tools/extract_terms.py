"""专业术语与缩写自动化挖掘及沉淀工具。

功能：
1. 自动从文献正文（HTML/PDF/分段JSON）中扫描识别所有的缩写与全称定义（如 IBS -> Irritable bowel syndrome）
2. 调用配置的 LLM 或内置规则库，自动生成权威的中文医学/科学术语翻译与同义别名
3. 自动生成单篇术语表草稿：glossary-d/<doc_id>.yaml，供人工审核
4. 支持将单篇验证通过的高频优质术语一键提升（Promote）至全局术语表 glossary.yaml

用法示例：
  # 自动提取文献中的缩写定义并生成 glossary-d/<doc_id>.yaml
  python tools/extract_terms.py s41572-026-00741-7

  # 将单篇中的某个术语一键提升至全局 glossary.yaml
  python tools/extract_terms.py s41572-026-00741-7 --promote IBS
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import yaml

from src.abbrev import extract_definitions
from src.glossary import load_glossary, Term, MODE_HARD
from src.providers import build_provider, load_env


def get_doc_text(doc_id: str) -> str:
    """获取指定文档的完整文本内容。"""
    clean_id = doc_id.split("/")[-1].replace(".html", "").replace(".pdf", "").strip()

    # 1. 优先从已有的分段 JSON 提取
    seg_file = ROOT / "data" / "segments" / f"{clean_id}.json"
    if seg_file.exists():
        data = json.loads(seg_file.read_text(encoding="utf-8"))
        texts = [seg["src_text"] for sec in data.get("sections", []) for seg in sec.get("segments", [])]
        return "\n".join(texts)

    # 2. 检查 HTML
    html_file = ROOT / "papers" / f"{clean_id}.html"
    if html_file.exists():
        from src.segment_html import parse_nature_html
        doc = parse_nature_html(html_file.read_text(encoding="utf-8"), doc_id=clean_id)
        return "\n".join(seg.src_text for seg in doc.segments)

    # 3. 检查 PDF
    pdf_file = ROOT / "papers" / f"{clean_id}.pdf"
    if pdf_file.exists():
        import pymupdf
        pdoc = pymupdf.open(pdf_file)
        return "\n".join(pdoc[i].get_text() for i in range(pdoc.page_count))

    raise FileNotFoundError(f"找不到文献 {doc_id} 的分段数据或源文件 (HTML/PDF)")


def translate_terms_with_llm(abbr_defs: dict[str, set[str]], provider) -> list[dict]:
    """通过 LLM 批量获取缩写及全称的标准中文医学译名和常见别名。"""
    prompt = (
        "你是权威的医学与生命科学术语审校专家。\n"
        "请将下列英文专有名词/缩写转换为中文权威译名及常见的同义别名（aliases）。\n\n"
        "【待翻译名词列表】\n"
    )
    items = []
    for abbr, fulls in sorted(abbr_defs.items()):
        full = next(iter(fulls))
        items.append((abbr, full))
        prompt += f"- 缩写: {abbr} | 英文全称: {full}\n"

    prompt += (
        "\n【输出要求】\n"
        "仅输出标准的 JSON 数组，每个对象包含以下键：\n"
        "- term: 缩写 (如 IBS)\n"
        "- full_en: 英文全称\n"
        "- zh: 中文权威规范译名\n"
        "- aliases: 常见同义译名列表 (数组，如 [\"肠道易激综合征\", \"IBS\"])\n"
        "不要包含任何 Markdown 代码块标签、不要解释。\n"
    )

    try:
        raw = provider.complete("你是权威医学术语词典工具，严格输出JSON。", prompt, temperature=0.1)
        raw = raw.strip()
        # 清理可能存在的 ```json 标记
        raw = re.sub(r"^```[a-zA-Z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw).strip()
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return parsed
    except Exception as e:
        print(f"[!] LLM 批量翻译术语异常: {e}，将采用备用默认格式")

    # 降级备用输出
    res = []
    for abbr, full in items:
        res.append({
            "term": abbr,
            "full_en": full,
            "zh": f"【待审核: {full}】",
            "aliases": []
        })
    return res


def extract_and_generate_glossary(doc_id: str, use_llm: bool = True) -> Path:
    """扫描提取缩写并生成 glossary-d/<doc_id>.yaml。"""
    clean_id = doc_id.split("/")[-1].replace(".html", "").replace(".pdf", "").strip()
    print(f"[*] 正在从文献 {clean_id} 中挖掘专业缩写与定义...")

    text = get_doc_text(clean_id)
    defs = extract_definitions(text)
    print(f"[+] 成功识别出 {len(defs)} 处权威缩写定义：")
    for abbr, fulls in sorted(defs.items()):
        print(f"    - {abbr:10} -> {', '.join(fulls)}")

    out_file = ROOT / "glossary-d" / f"{clean_id}.yaml"
    out_file.parent.mkdir(parents=True, exist_ok=True)

    existing_terms = []
    if out_file.exists():
        existing_terms = load_glossary(out_file)

    existing_map = {t.term: t for t in existing_terms}

    # 过滤出新缩写
    new_defs = {k: v for k, v in defs.items() if k not in existing_map}

    translated_items = []
    if new_defs:
        if use_llm:
            try:
                env = load_env(ROOT / ".env")
                provider = build_provider(env.get("LLM_PROVIDER"))
                print(f"[*] 正在通过 {provider.name} 获取权威规范中文医学译名...")
                translated_items = translate_terms_with_llm(new_defs, provider)
            except Exception as e:
                print(f"[!] 无法初始化 LLM ({e})，将生成基础草稿模板")
                translated_items = [{"term": k, "full_en": next(iter(v)), "zh": f"待填写", "aliases": []} for k, v in new_defs.items()]
        else:
            translated_items = [{"term": k, "full_en": next(iter(v)), "zh": f"待填写", "aliases": []} for k, v in new_defs.items()]

    term_dicts = [t.to_dict() for t in existing_terms]
    for item in translated_items:
        term_dicts.append({
            "term": item["term"],
            "zh": item["zh"],
            "mode": MODE_HARD,
            "full_en": item.get("full_en", ""),
            "aliases": item.get("aliases", []),
            "scope": f"doc:{clean_id}",
            "status": "suggested"
        })

    yaml_data = {"terms": term_dicts}
    header = (
        f"# 单篇术语表：只对 {clean_id} 生效\n"
        f"# 由 tools/extract_terms.py 自动挖掘生成\n"
        f"# 审核通过后，可运行 `python tools/extract_terms.py {clean_id} --promote <TERM>` 提升至全局主表\n\n"
    )
    out_file.write_text(header + yaml.dump(yaml_data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(f"\n[+] 单篇术语表已保存至: {out_file.relative_to(ROOT)}")
    return out_file


def promote_term_to_global(doc_id: str, term_str: str) -> None:
    """将单篇术语提升至主表 glossary.yaml。"""
    clean_id = doc_id.split("/")[-1].replace(".html", "").replace(".pdf", "").strip()
    doc_yaml = ROOT / "glossary-d" / f"{clean_id}.yaml"
    global_yaml = ROOT / "glossary.yaml"

    if not doc_yaml.exists():
        print(f"[!] 未找到单篇术语表: {doc_yaml}")
        return

    doc_terms = load_glossary(doc_yaml)
    target = None
    remaining = []
    for t in doc_terms:
        if t.term.lower() == term_str.lower():
            target = t
        else:
            remaining.append(t)

    if not target:
        print(f"[!] 在 {doc_yaml.name} 中未找到术语: {term_str}")
        return

    # 读取全局术语表
    global_terms = load_glossary(global_yaml) if global_yaml.exists() else []
    for g in global_terms:
        if g.term.lower() == target.term.lower():
            print(f"[!] 全局术语表已有该术语: {g.term} -> 「{g.zh}」，无需重复提升。")
            return

    # 修改目标术语作用域为全局
    target_dict = target.to_dict()
    target_dict["scope"] = "global"
    target_dict["status"] = "approved"

    # 追加到全局术语表（保留原注释）
    term_yaml = yaml.dump([target_dict], allow_unicode=True, sort_keys=False)
    indented = "\n".join("  " + line if line.strip() else "" for line in term_yaml.strip().splitlines())
    current_content = global_yaml.read_text(encoding="utf-8").rstrip()
    global_yaml.write_text(current_content + "\n" + indented + "\n", encoding="utf-8")

    # 更新单篇文件（移除已提升项）
    header = (
        f"# 单篇术语表：只对 {clean_id} 生效\n"
        f"# 由 tools/extract_terms.py 自动挖掘生成\n\n"
    )
    doc_data = {"terms": [r.to_dict() for r in remaining]}
    doc_yaml.write_text(header + yaml.dump(doc_data, allow_unicode=True, sort_keys=False), encoding="utf-8")

    print(f"[+] 成功将术语 {target.term} (「{target.zh}」) 提升并沉淀至全局主表 {global_yaml.name}！")


def main() -> None:
    ap = argparse.ArgumentParser(description="专业术语自动化挖掘与沉淀工具")
    ap.add_argument("doc_id", help="文献 ID (例如 s41572-026-00741-7)")
    ap.add_argument("--no-llm", action="store_true", help="不使用 LLM，仅提取英文缩写骨架")
    ap.add_argument("--promote", default=None, help="将指定术语从该篇提升至全局术语表 glossary.yaml")
    args = ap.parse_args()

    if args.promote:
        promote_term_to_global(args.doc_id, args.promote)
    else:
        extract_and_generate_glossary(args.doc_id, use_llm=not args.no_llm)


if __name__ == "__main__":
    main()
