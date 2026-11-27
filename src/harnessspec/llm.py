"""The one model client shared by the orchestrator and both subagents.

Every call reads its settings from ``pilot/model.json``, so the orchestrator,
the SWE-bench subagent, and the SWE-QA subagent cannot drift apart on model,
digest, context window, or temperature. Standard library only.
"""

from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODEL_PIN = ROOT / "pilot" / "model.json"
DEFAULT_HOST = "http://localhost:11434"

# Ollama 0.40 reports a model's digest as its manifest's config-layer digest;
# Ollama 0.32 (the conda-forge CUDA build used on Ada) reports the SHA-256 of
# the manifest file itself. For the pinned qwen2.5-coder:7b both name one
# manifest: sha256 4aaba1ee... of the manifest whose config layer is dae161e2...
# (checked byte for byte on the pinning Mac and on Ada, 2026-11-27).
EQUIVALENT_DIGESTS = {
    "sha256:4aaba1ee422af93aad53ecbdfc8a159770cf254a9950b7a4304cf9ee3555ef31":
        "sha256:dae161e27b0e90dd1856c8bb3209201fd6736d8eb66298e75ed87571486f4364",
}


@dataclass(frozen=True)
class Reply:
    content: str
    prompt_tokens: int
    output_tokens: int
    seconds: float
    reasoning_tokens: int = 0

    @property
    def tokens(self) -> int:
        return self.prompt_tokens + self.output_tokens + self.reasoning_tokens


def load_pin(path: Path = MODEL_PIN) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class OllamaClient:
    """Chat client for the pinned model.

    ``chat`` passes ``num_ctx`` and ``temperature`` from the pin on every call,
    because Ollama otherwise falls back to a small context window and silently
    drops the start of a long prompt. The run's seed goes in ``options.seed``.
    """

    def __init__(self, pin: dict | None = None, host: str = DEFAULT_HOST, timeout: float = 900.0,
                 check_digest: bool = True):
        self.pin = pin if pin is not None else load_pin()
        self.name = self.pin["name"]
        self.digest = self.pin["digest"]
        self.host = host.rstrip("/")
        self.timeout = timeout
        # Optional cap on one reply's generated tokens (Ollama num_predict). None keeps
        # Ollama's default, as in every run before SWE-bench.
        self.max_output_tokens: int | None = None
        if check_digest:
            self.verify_digest()

    def _post(self, path: str, body: dict | None = None) -> dict:
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            self.host + path, data=data, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read())

    def verify_digest(self) -> None:
        """Refuse to run if the local model is not the pinned build."""
        models = self._post("/api/tags").get("models", [])
        local = next((m for m in models if m.get("name") == self.name), None)
        if local is None:
            raise RuntimeError(f"{self.name} is not pulled; run: ollama pull {self.name}")
        digest = local["digest"] if local["digest"].startswith("sha256:") else "sha256:" + local["digest"]
        if digest != self.digest and EQUIVALENT_DIGESTS.get(digest) != self.digest:
            raise RuntimeError(f"{self.name} digest {digest} does not match pin {self.digest}")

    def chat(self, messages: list[dict], seed: int, json_mode: bool = False) -> Reply:
        body = {
            "model": self.name,
            "messages": messages,
            "stream": False,
            "options": {**self.pin["options"], "seed": seed},
        }
        if self.max_output_tokens is not None:
            body["options"]["num_predict"] = self.max_output_tokens
        if json_mode:
            # Syntax only. A JSON schema here would make the decoder enforce the
            # structure, and the structural errors are what H3 measures.
            body["format"] = "json"
        started = time.monotonic()
        raw = self._post("/api/chat", body)
        return Reply(
            content=raw.get("message", {}).get("content", ""),
            prompt_tokens=int(raw.get("prompt_eval_count") or 0),
            output_tokens=int(raw.get("eval_count") or 0),
            seconds=round(time.monotonic() - started, 3),
        )
