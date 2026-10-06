"""学术文献网页版抓取 CLI。

从配置的机构反代平台（如 Nature 等）直接拉取指定文献的语义 HTML，
并保存至 papers/<doc_id>.html，以便后续通过 run_pipeline.py 进行高保真伴读制作。

用法示例：
  python tools/fetch_paper.py s41572-026-00741-7
  python tools/fetch_paper.py 10.1038/s41572-026-00741-7 --force
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from src.fetcher import fetch_article_html
from src.providers import load_env


def main() -> None:
    parser = argparse.ArgumentParser(description="学术文献网页版抓取 CLI")
    parser.add_argument("doc_id", help="文献 ID 或 DOI (例如 s41572-026-00741-7 或 10.1038/s41572-026-00741-7)")
    parser.add_argument("-o", "--output", help="自定义输出 HTML 路径（默认 papers/<doc_id>.html）")
    parser.add_argument("-f", "--force", action="store_true", help="强制重新下载，覆盖已有文件")
    args = parser.parse_args()

    clean_id = args.doc_id.split("/")[-1].replace(".html", "").replace(".pdf", "").strip()
    out_path = Path(args.output) if args.output else (ROOT / "papers" / f"{clean_id}.html")

    print(f"[*] 准备抓取文献: {clean_id}")
    print(f"[*] 保存目标路径: {out_path.relative_to(ROOT) if out_path.is_relative_to(ROOT) else out_path}")

    env = load_env(ROOT / ".env")
    base_url = env.get("ACADEMIC_PROXY_BASE_URL", "").strip()
    cookie = env.get("ACADEMIC_PROXY_COOKIE", "").strip()

    if not base_url:
        print("[!] 错误: 未在 .env 中配置 ACADEMIC_PROXY_BASE_URL。")
        print("    请在 .env 中设置机构反代基础地址后重试。")
        sys.exit(1)

    try:
        saved = fetch_article_html(clean_id, out_path=out_path, force=args.force)
        size_kb = saved.stat().st_size / 1024
        print(f"[+] 抓取成功！文件大小: {size_kb:.1f} KB -> {saved}")
        print(f"[+] 接下来可直接运行：python tools/run_pipeline.py {clean_id}")
    except RuntimeError as e:
        msg = str(e)
        print(f"\n[!] 抓取失败: {msg}")
        if "401" in msg or "Cookie" in msg:
            print("\n[提示] 机构反代 Cookie 可能已过期。")
            login_helper = ROOT / "tools" / "login_proxy.py"
            if login_helper.exists():
                print("检测到本地凭据助手，您可以运行以下命令刷新：")
                print("    python tools/login_proxy.py")
            else:
                print("请更新 .env 中的 ACADEMIC_PROXY_COOKIE，或直接在浏览器中将网页另存为 papers/<doc_id>.html。")
        sys.exit(1)


if __name__ == "__main__":
    main()
