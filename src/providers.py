"""LLM Provider 抽象：可切换 DeepSeek / Gemini / ChatGPT / 任意 OpenAI 兼容端点。

设计约束
--------
- **零第三方依赖**：只用标准库 urllib，不需要额外安装 SDK
  （以后要换 httpx/requests 只需改这一个文件）
- **密钥只从环境变量读**，且**永不打印**。密钥写在项目根目录的 `.env`（已在 .gitignore）
- 每个 provider 只暴露一个方法：`complete(system, user) -> str`

已知各家的 base_url / 默认模型见 PRESETS。
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

DEFAULT_TIMEOUT = 120
MAX_RETRY = 3


class Provider(Protocol):
    name: str
    model: str

    def complete(self, system: str, user: str, *, temperature: float = 0.3,
                 max_tokens: int | None = None) -> str: ...


# --------------------------------------------------------------------- .env

def load_env(path: str | Path = ".env", override: bool = False) -> dict[str, str]:
    """极简 .env 读取（不引第三方库）。已存在的环境变量默认优先。"""
    p = Path(path)
    found: dict[str, str] = {}
    if not p.exists():
        return found
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        found[k] = v
        if override or k not in os.environ:
            os.environ[k] = v
    return found


def require(key: str) -> str:
    v = os.environ.get(key, "").strip()
    if not v:
        raise RuntimeError(
            f"缺少环境变量 {key}。请在项目根目录的 .env 里写一行：{key}=你的密钥\n"
            f"（.env 已被 .gitignore 忽略；密钥不要写进代码或笔记）"
        )
    return v


# --------------------------------------------------------------- 预设与实现

PRESETS: dict[str, dict[str, str]] = {
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "env": "DEEPSEEK_API_KEY",
        "model": "deepseek-chat",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "env": "OPENAI_API_KEY",
        "model": "gpt-5.1-mini",
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "env": "GEMINI_API_KEY",
        "model": "gemini-3-flash",
    },
}


@dataclass
class OpenAICompatProvider:
    """DeepSeek / OpenAI / Groq / 硅基流动 / Ollama … 只要是 OpenAI 兼容接口都能用。"""
    base_url: str
    api_key: str
    model: str
    name: str = "openai-compat"
    timeout: int = DEFAULT_TIMEOUT

    def complete(self, system: str, user: str, *, temperature: float = 0.3,
                 max_tokens: int | None = None) -> str:
        url = self.base_url.rstrip("/") + "/chat/completions"
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "temperature": temperature,
        }
        if max_tokens:
            body["max_tokens"] = max_tokens
        data = self._post(url, body, {"Authorization": f"Bearer {self.api_key}"})
        return data["choices"][0]["message"]["content"]

    def _post(self, url: str, body: dict, headers: dict) -> dict:
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        last: Exception | None = None
        for attempt in range(MAX_RETRY):
            req = urllib.request.Request(url, data=payload, method="POST")
            req.add_header("Content-Type", "application/json")
            for k, v in headers.items():
                req.add_header(k, v)
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", "replace")[:500]
                last = RuntimeError(f"HTTP {e.code}: {detail}")
                # 401/403 是密钥问题，重试没意义
                if e.code in (401, 403):
                    raise last
                if e.code in (429, 500, 502, 503, 504):
                    time.sleep(2 ** attempt)
                    continue
                raise last
            except Exception as e:  # 网络类，可重试
                last = e
                time.sleep(2 ** attempt)
        raise RuntimeError(f"请求失败（重试 {MAX_RETRY} 次）：{last}")


@dataclass
class GeminiProvider:
    """Google Gemini（REST v1beta）。"""
    api_key: str
    model: str
    base_url: str = PRESETS["gemini"]["base_url"]
    name: str = "gemini"
    timeout: int = DEFAULT_TIMEOUT

    def complete(self, system: str, user: str, *, temperature: float = 0.3,
                 max_tokens: int | None = None) -> str:
        url = f"{self.base_url.rstrip('/')}/models/{self.model}:generateContent"
        body: dict[str, Any] = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"temperature": temperature},
        }
        if max_tokens:
            body["generationConfig"]["maxOutputTokens"] = max_tokens
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        last: Exception | None = None
        for attempt in range(MAX_RETRY):
            req = urllib.request.Request(url, data=payload, method="POST")
            req.add_header("Content-Type", "application/json")
            req.add_header("x-goog-api-key", self.api_key)
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                parts = data["candidates"][0]["content"]["parts"]
                return "".join(p.get("text", "") for p in parts)
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", "replace")[:500]
                last = RuntimeError(f"HTTP {e.code}: {detail}")
                if e.code in (400, 401, 403):
                    raise last
                time.sleep(2 ** attempt)
            except Exception as e:
                last = e
                time.sleep(2 ** attempt)
        raise RuntimeError(f"请求失败（重试 {MAX_RETRY} 次）：{last}")


@dataclass
class MockProvider:
    """离线假 provider：让缓存/术语逻辑可以在没有密钥的情况下被完整测试。"""
    model: str = "mock-1"
    name: str = "mock"
    script: dict[str, str] = field(default_factory=dict)
    calls: list[tuple[str, str]] = field(default_factory=list)
    temperature_seen: list[float] = field(default_factory=list)

    def complete(self, system: str, user: str, *, temperature: float = 0.3,
                 max_tokens: int | None = None) -> str:
        self.calls.append((system, user))
        self.temperature_seen.append(temperature)
        for needle, response in self.script.items():
            if needle in user:
                return response
        # 默认行为：可预测的"伪翻译"，便于断言
        return f"[MOCK:{self.model}] " + user.strip().splitlines()[-1][:400]


def build_provider(spec: str | None = None, model: str | None = None) -> Provider:
    """`spec` 取值：deepseek / openai / gemini / mock / 任意 base_url 前缀 openai:。"""
    spec = (spec or os.environ.get("LLM_PROVIDER") or "deepseek").strip()
    if spec == "mock":
        return MockProvider(model=model or "mock-1")

    if spec in PRESETS:
        preset = PRESETS[spec]
        return _make(spec, preset["base_url"], require(preset["env"]),
                     model or os.environ.get("LLM_MODEL") or preset["model"])

    if spec.startswith("openai:"):
        base = spec[len("openai:"):]
        return OpenAICompatProvider(base_url=base, api_key=require("OPENAI_API_KEY"),
                                    model=model or os.environ.get("LLM_MODEL", ""))

    raise ValueError(f"未知的 provider: {spec!r}（可选：{list(PRESETS)} / mock / openai:<base_url>）")


def _make(spec: str, base_url: str, api_key: str, model: str) -> Provider:
    if spec == "gemini":
        return GeminiProvider(api_key=api_key, model=model, base_url=base_url)
    return OpenAICompatProvider(base_url=base_url, api_key=api_key,
                                model=model, name=spec)
