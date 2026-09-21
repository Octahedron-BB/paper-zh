"""运行日志：把一次运行的完整输出**同时**写到控制台和文件。

为什么这件事必须由工具自己做，而不是靠任务计划重定向
----------------------------------------------------
1. 在任务计划里做重定向，就必须用 `cmd.exe /c` 包一层。而 cmd 的 `/c` 有已知的
   引号坑：**参数里的引号多于两个时，它会剥掉首尾引号**，把命令拆坏。
   实测症状：任务返回 `1`，日志文件根本没生成 —— 连"错在哪"都看不到。
2. 用 shell 就意味着命令里要写绝对路径，换台机器就得改。
3. 工具自己写日志之后，定时任务的参数可以全是**相对路径**，而且与交互式运行
   走的是**完全同一条代码路径** —— 不会出现"手动能跑、定时跑不了"这种差异。

日志文件在 `data/feed/run-log.txt`（`data/` 已被 .gitignore 忽略）。
超过 `MAX_BYTES` 时轮转成 `run-log.1.txt`，只保留上一代，避免无限增长。
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

MAX_BYTES = 1_000_000

_ORIG: tuple[object, object] | None = None
_FILE = None
_ATTACHED: Path | None = None


class _Tee:
    """把写入同时送到多个流（控制台 + 日志文件）。

    写失败**不抛异常** —— 日志坏了不该把主流程拖死。
    """

    def __init__(self, *streams):
        self._streams = streams

    def write(self, text: str) -> int:
        for s in self._streams:
            try:
                s.write(text)
            except Exception:  # noqa: BLE001
                pass
        return len(text)

    def flush(self) -> None:
        for s in self._streams:
            try:
                s.flush()
            except Exception:  # noqa: BLE001
                pass

    def isatty(self) -> bool:
        return False


def attach(path: str | Path, argv: list[str] | None = None) -> Path | None:
    """开始记录。返回日志路径；**写不了日志时返回 None，但不影响程序继续跑**。"""
    global _ORIG, _FILE, _ATTACHED
    if _ATTACHED is not None:
        return _ATTACHED

    p = Path(path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.exists() and p.stat().st_size > MAX_BYTES:
            p.replace(p.with_suffix(".1.txt"))
        f = open(p, "a", encoding="utf-8")
    except OSError:
        return None

    f.write(f"\n{'=' * 72}\n"
            f"[运行] {datetime.now().isoformat(timespec='seconds')}\n"
            f"[命令] {Path(sys.argv[0]).name} {' '.join(argv or [])}\n"
            f"{'=' * 72}\n")
    f.flush()

    _ORIG = (sys.stdout, sys.stderr)
    _FILE = f
    _ATTACHED = p
    sys.stdout = _Tee(_ORIG[0], f)
    sys.stderr = _Tee(_ORIG[1], f)
    return p


def detach() -> None:
    """恢复原始 stdout/stderr 并关闭文件（测试与嵌套调用用）。"""
    global _ORIG, _FILE, _ATTACHED
    if _ORIG is not None:
        sys.stdout, sys.stderr = _ORIG
    if _FILE is not None:
        try:
            _FILE.close()
        except OSError:
            pass
    _ORIG = None
    _FILE = None
    _ATTACHED = None


def attached() -> Path | None:
    return _ATTACHED
