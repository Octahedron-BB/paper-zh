"""把某一期速览推送到微信 / Telegram / Discord。

这是**第三个渲染器**：`build_digest.py` 产出结构化快照，本脚本只负责把快照变成各渠道的消息。
独立成脚本而不是塞进 build_digest，是为了"只想重发一次"时**不必重新检索、更不必重新调 LLM**。

跑法
----
    & "E:\\Anaconda\\envs\\workenv\\python.exe" tools\\push_digest.py --list-channels
    ... tools\\push_digest.py --channels all --dry-run      # 先看会发什么，不发
    ... tools\\push_digest.py --channels telegram
    ... tools\\push_digest.py --channels telegram,discord  # 多选
    ... tools\\push_digest.py --channels wechat --limit 10
    ... tools\\push_digest.py --channels discord --from 2026-09-21-0852

渠道配置写在项目根目录的 `.env`（已被 .gitignore 忽略），见 `.env.example`。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from src.providers import load_env  # noqa: E402
from src.push import (  # noqa: E402
    CHANNELS, DISPLAY, PushError, build_messages, channel_status, push_snapshot,
    recent_items, resolve_channels,
)
from tools.build_digest import load_snapshot  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(
        description="把一期文献速览推送到微信(PushPlus) / Telegram / Discord")
    ap.add_argument("--channels", default="", metavar="LIST",
                    help=f"渠道，逗号分隔、可多选：{', '.join(CHANNELS)}；或 all（已配置的都发）")
    ap.add_argument("--from", dest="from_date", default=None,
                    help="快照日期（YYYY-MM-DD）或 .json 路径；不带则用最新一期")
    ap.add_argument("--limit", type=int, default=None, help="只推前 N 条（试水用）")
    ap.add_argument("--days", type=int, default=None,
                    help="只推最近 N 天入库的条目（做周报就写 --days 7）")
    ap.add_argument("--style", choices=("brief", "full"), default="full",
                    help="full（默认）=标题+简介+detail；brief=省掉 detail，条目多时省容量")
    ap.add_argument("--dry-run", action="store_true",
                    help="打印出会发什么，但什么都不发")
    ap.add_argument("--list-channels", action="store_true",
                    help="列出渠道与配置状态，然后退出")
    args = ap.parse_args()

    load_env(ROOT / ".env")

    if args.list_channels:
        print("渠道配置状态（只显示变量**名**，不显示值）：\n")
        for name, ready, note in channel_status():
            # ⚠️ 不要试图用 :<22 对齐中英混排：中文按**字符数**补齐，显示宽度却是两倍，
            #    结果会挤在一起。分两行最稳。
            print(f"  {'OK' if ready else '--'}  {name:<9}{DISPLAY[name]}")
            print(f"      {'已就绪' if ready else '缺：' + note}")
        print("\n用法：--channels telegram,discord   可多选；写 all = 所有已配置的渠道")
        print("配置写在项目根目录的 .env 里，模板见 .env.example")
        return 0

    try:
        channels, skipped = resolve_channels(args.channels)
    except PushError as e:
        print(f"✗ {e}")
        return 2
    if skipped:
        print("⚠️ 跳过：" + "；".join(skipped))
    if not channels:
        print("✗ 没有任何渠道配置齐全。先跑 --list-channels 看看缺什么。")
        return 2

    snap, path = load_snapshot(args.from_date)
    print(f"[快照] {path.relative_to(ROOT)}  {snap.get('count', 0)} 条")
    if args.days:
        before = snap.get("items") or []
        kept = recent_items(before, args.days)
        snap = {**snap, "count": len(kept), "items": kept}
        print(f"[筛选] 近 {args.days} 天：{len(kept)} / {len(before)} 条")
    print(f"[渠道] {', '.join(channels)}"
          + ("　（dry-run：不会真的发送）" if args.dry_run else ""))

    if args.dry_run:
        for ch in channels:
            for m in build_messages(snap, ch, style=args.style, limit=args.limit):
                print("\n" + "=" * 70)
                print(f"--- {ch} ---")
                print(m)

    print()
    results = push_snapshot(snap, channels, style=args.style, limit=args.limit,
                            dry_run=args.dry_run)

    print("=" * 70)
    failed = 0
    for ch, lines in results.items():
        for ln in lines:
            print(f"  [{ch}] {ln}")
            if "✗" in ln:
                failed += 1
    print("=" * 70)
    if args.dry_run:
        print("dry-run 结束，什么都没发。去掉 --dry-run 才会真发。")
    elif failed:
        print(f"有 {failed} 条失败，见上面 ✗。")
    else:
        print("已提交完毕。")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
