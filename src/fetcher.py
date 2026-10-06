"""学术机构代理 / 网页版文献自动抓取模块。

支持通过 .env 中配置的 ACADEMIC_PROXY_BASE_URL 和 ACADEMIC_PROXY_COOKIE，
自动拉取 Nature 等期刊的语义网页 HTML。
零外部重度依赖，仅使用标准库 urllib。
"""

from __future__ import annotations

import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

from .providers import load_env

DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


def fetch_article_html(doc_id: str, out_path: Path | None = None,
                       force: bool = False) -> Path:
    """通过配置的机构代理拉取指定 doc_id 的 HTML 全文。

    Parameters
    ----------
    doc_id: 文档 ID（如 s41572-026-00741-7 或 10.1038/s41572-026-00741-7）
    out_path: 目标保存路径（默认 papers/<doc_id>.html）
    force: 是否强制重新下载
    """
    clean_id = doc_id.split("/")[-1].replace(".html", "").replace(".pdf", "")
    target = out_path or (Path("papers") / f"{clean_id}.html")
    if target.exists() and not force:
        return target

    env = load_env()
    base_url = env.get("ACADEMIC_PROXY_BASE_URL", "").strip().rstrip("/")
    cookie = env.get("ACADEMIC_PROXY_COOKIE", "").strip()

    if not base_url:
        raise RuntimeError(
            "未配置 ACADEMIC_PROXY_BASE_URL。请在 .env 中设置机构代理地址，"
            "或直接将 HTML 文件保存至 papers/ 目录。"
        )
    if not cookie:
        raise RuntimeError(
            "未配置 ACADEMIC_PROXY_COOKIE。请在 .env 中填入有效的反代凭据 Cookie。"
        )

    # 规范化 URL（如 https://nature.publinks.top/articles/s41572-026-00741-7）
    if clean_id.startswith("s"):
        url = f"{base_url}/articles/{clean_id}"
    else:
        url = f"{base_url}/articles/{clean_id}"

    req = urllib.request.Request(url, method="GET")
    req.add_header("User-Agent", DEFAULT_UA)
    req.add_header("Cookie", cookie)
    req.add_header("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8")

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            content_type = resp.headers.get("Content-Type", "")
            raw = resp.read()
            html_text = raw.decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise RuntimeError(
                f"反代鉴权失败 (HTTP 401): Cookie 可能已过期，请在 .env 中更新 ACADEMIC_PROXY_COOKIE。"
            ) from e
        raise RuntimeError(f"拉取文献失败 (HTTP {e.code}): {e.reason}") from e
    except Exception as e:
        raise RuntimeError(f"请求反代网络异常: {e}") from e

    if "验证未通过" in html_text or "Authentication failed" in html_text:
        raise RuntimeError("反代网关拦截: 验证未通过，请检查 .env 中的 ACADEMIC_PROXY_COOKIE 是否有效。")

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(html_text, encoding="utf-8")
    return target
