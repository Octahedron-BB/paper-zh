"""TTS 引擎与时间戳估算离线测试"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.build_audio import (
    estimate_sentences_proportional,
    synthesize_siliconflow,
    DEFAULT_SILICONFLOW_MODEL,
    DEFAULT_SILICONFLOW_VOICE,
)


def test_estimate_sentences_proportional():
    text = "这是第一句话。这是第二句话！还有第三句话？最后一句结尾。"
    total_sec = 8.0
    sentences = estimate_sentences_proportional(text, total_sec)

    assert len(sentences) == 4, f"应切分为 4 句话，实际: {len(sentences)}"
    assert sentences[0]["text"] == "这是第一句话。"
    assert sentences[0]["start"] == 0.0

    prev_end = 0.0
    for s in sentences:
        assert s["start"] == prev_end, "时间戳必须连续无空隙"
        assert s["end"] > s["start"], "每句话时长必须为正"
        prev_end = s["end"]

    # 允许 0.01s 的浮点舍入误差
    assert abs(sentences[-1]["end"] - total_sec) <= 0.05, f"结束时间应接近总时长: {sentences[-1]['end']} vs {total_sec}"


def test_siliconflow_requires_api_key():
    old_key = os.environ.get("SILICONFLOW_API_KEY")
    if "SILICONFLOW_API_KEY" in os.environ:
        del os.environ["SILICONFLOW_API_KEY"]
    try:
        err_msg = ""
        try:
            synthesize_siliconflow("测试文本", DEFAULT_SILICONFLOW_VOICE, "+0%")
        except RuntimeError as e:
            err_msg = str(e)
        assert "缺少 SILICONFLOW_API_KEY" in err_msg, f"应该提示缺少 API 密钥，实际: {err_msg}"
    finally:
        if old_key is not None:
            os.environ["SILICONFLOW_API_KEY"] = old_key


def _run() -> int:
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    failed = 0
    print("=" * 68)
    for name, fn in tests:
        try:
            fn()
            print(f"  [PASS] {name}")
        except AssertionError as e:
            failed += 1
            print(f"  [FAIL] {name}\n       {e}")
        except Exception as e:
            failed += 1
            print(f"  [ERR ] {name}\n       {type(e).__name__}: {e}")
    print("=" * 68)
    print(f"{len(tests) - failed}/{len(tests)} 通过")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run())
