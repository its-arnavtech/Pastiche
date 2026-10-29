"""Ollama LLMClient over its local HTTP API (stdlib only). Used in phase 4."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from remixer.interfaces import LLMClient


class OllamaClient(LLMClient):
    def __init__(self, url: str = "http://127.0.0.1:11434", model: str = "llama3.2:3b", timeout: float = 120,
                 think: bool | None = False):
        self.url = url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.think = think   # thinking models (qwen3) otherwise answer in "thinking" and leave "response" empty

    def available(self) -> bool:
        """True when the server answers and the configured model is pulled (else every call would fail)."""
        try:
            with urllib.request.urlopen(f"{self.url}/api/tags", timeout=2) as r:
                names = {m.get("name") for m in json.loads(r.read()).get("models", [])}
        except (urllib.error.URLError, OSError, ValueError):
            return False
        return self.model in names or f"{self.model}:latest" in names

    def complete(self, prompt: str, system: str | None = None, **kw: Any) -> str:
        """One non-streamed completion. ``response_format="json"`` maps to Ollama's ``format``; the
        remaining keywords (temperature, seed, num_predict...) go to ``options``. HTTP errors raise."""
        fmt = kw.pop("response_format", None)
        body = {"model": kw.pop("model", self.model), "prompt": prompt, "stream": False, "options": kw}
        if fmt == "json":
            body["format"] = "json"
        if self.think is not None:
            body["think"] = self.think
        if system:
            body["system"] = system
        req = urllib.request.Request(f"{self.url}/api/generate", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            out = json.loads(r.read())
        return out.get("response") or out.get("thinking") or ""

    def unload(self) -> None:
        """Free VRAM before a GPU job (spec section 6: LLM and Demucs are serialized)."""
        body = {"model": self.model, "keep_alive": 0}
        req = urllib.request.Request(f"{self.url}/api/generate", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=10).close()
        except (urllib.error.URLError, OSError):
            pass
