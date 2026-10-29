"""Ollama LLMClient over its local HTTP API (stdlib only). Used in phase 4."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from remixer.interfaces import LLMClient


class OllamaClient(LLMClient):
    def __init__(self, url: str = "http://127.0.0.1:11434", model: str = "llama3.2:3b", timeout: float = 120):
        self.url = url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def available(self) -> bool:
        try:
            with urllib.request.urlopen(f"{self.url}/api/tags", timeout=2):
                return True
        except (urllib.error.URLError, OSError):
            return False

    def complete(self, prompt: str, system: str | None = None, **kw: Any) -> str:
        body = {"model": kw.pop("model", self.model), "prompt": prompt, "stream": False, "options": kw}
        if system:
            body["system"] = system
        req = urllib.request.Request(f"{self.url}/api/generate", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.loads(r.read())["response"]

    def unload(self) -> None:
        """Free VRAM before a GPU job (spec section 6: LLM and Demucs are serialized)."""
        body = {"model": self.model, "keep_alive": 0}
        req = urllib.request.Request(f"{self.url}/api/generate", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=10).close()
        except (urllib.error.URLError, OSError):
            pass
