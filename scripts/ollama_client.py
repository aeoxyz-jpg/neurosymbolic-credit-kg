"""Async client for Ollama — SPEC §7.

Architecture:
  - Ollama runs as a local daemon at http://127.0.0.1:11434 (no API key).
  - `:cloud`-suffixed models are routed by the daemon to ollama.com using
    credentials set up via `ollama signin` on the host. Pure local models
    (e.g. `bge-m3:latest`) also work — same endpoint, same API.

Invariants:
  - Hard ceiling of 3 concurrent requests, enforced via `asyncio.Semaphore`.
    For `:cloud` routing this matches the upstream Pro plan; for local models
    it's a sane default to avoid saturating Apple Silicon NEON cores.
  - Ollama API uses `num_predict`, NOT `max_tokens` (SPEC §7.2).
  - "Thinking" models (e.g. `glm-5.1:cloud`) emit reasoning into a separate
    `thinking` field while `response` may be empty if num_predict ran out
    before the thinking phase ended. The client returns response if non-empty,
    else thinking — caller should use ample `num_predict` (~1000+).

Usage:
    async with OllamaCloudClient() as cli:
        out = await cli.call(LLMRequest(model="glm-5.1:cloud", prompt="..."))
        outs = await cli.parallel(req1, req2, req3)

Dependencies: httpx, python-dotenv.
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from typing import Any

import httpx
from dotenv import load_dotenv

load_dotenv()

OLLAMA_CONCURRENCY = 3  # Pro plan ceiling — must match account tier (SPEC §7.2)


@dataclass
class LLMRequest:
    model: str  # must already include `:cloud` suffix (see SPEC §7.1)
    prompt: str
    system: str = ""
    temperature: float = 0.3
    num_predict: int = 2000  # Ollama API field name (NOT max_tokens)
    extra_options: dict[str, Any] = field(default_factory=dict)


def _validate_model_name(name: str) -> None:
    """Sanity-check model names against the local Ollama daemon's registry.

    Cloud-proxied models must carry the `:cloud` suffix; pure-local models
    (e.g. `bge-m3:latest`) don't. We don't enforce a strict pattern — Ollama
    itself returns a clear error if the name is unknown — but we do reject
    obviously empty or whitespace-only names.
    """
    if not name or not name.strip():
        raise ValueError("Model name is empty.")


class OllamaCloudClient:
    """Async client wrapping POST {host}/api/generate.

    Pass an httpx.AsyncClient via `_transport_client` to inject a mock for
    testing (verify_phase_d.py does this).
    """

    def __init__(
        self,
        concurrency: int = OLLAMA_CONCURRENCY,
        host: str | None = None,
        _transport_client: httpx.AsyncClient | None = None,
    ):
        self.host = (host or os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")).rstrip("/")
        self._sem = asyncio.Semaphore(concurrency)
        self._in_flight = 0
        self._max_in_flight = 0  # observability for tests
        self._owns_client = _transport_client is None
        self._client = _transport_client

    async def __aenter__(self):
        if self._owns_client:
            self._client = httpx.AsyncClient(timeout=60.0)
        return self

    async def __aexit__(self, *args):
        if self._owns_client and self._client is not None:
            await self._client.aclose()

    async def call(self, req: LLMRequest) -> str:
        _validate_model_name(req.model)
        body = {
            "model": req.model,
            "prompt": req.prompt,
            "stream": False,
            "options": {
                "temperature": req.temperature,
                "num_predict": req.num_predict,
                **req.extra_options,
            },
        }
        if req.system:
            body["system"] = req.system

        headers = {"Content-Type": "application/json"}

        async with self._sem:
            self._in_flight += 1
            self._max_in_flight = max(self._max_in_flight, self._in_flight)
            try:
                resp = await self._client.post(
                    f"{self.host}/api/generate",
                    content=json.dumps(body),
                    headers=headers,
                )
            finally:
                self._in_flight -= 1

        if resp.status_code != 200:
            raise RuntimeError(f"Ollama API error {resp.status_code}: {resp.text[:500]}")
        payload = resp.json()
        # Thinking models may emit content into `thinking` while `response`
        # is empty if num_predict was exhausted before the thinking phase ended.
        text = payload.get("response", "") or payload.get("thinking", "")
        return text

    async def parallel(self, *reqs: LLMRequest) -> list[str]:
        return await asyncio.gather(*(self.call(r) for r in reqs))


# Convenience: env-driven fast / deep model getters
def fast_model() -> str:
    return os.environ.get("OLLAMA_MODEL_FAST", "gemini-3-flash-preview:cloud")


def deep_model() -> str:
    return os.environ.get("OLLAMA_MODEL_DEEP", "glm-5.1:cloud")


if __name__ == "__main__":
    # Manual smoke test — actually hits the local daemon.
    import sys

    async def _smoke():
        async with OllamaCloudClient() as cli:
            req = LLMRequest(
                model=fast_model(),
                prompt="Reply with exactly the word 'ok' and nothing else.",
                num_predict=10,
            )
            print(await cli.call(req))

    # Probe the daemon first
    try:
        httpx.get(
            (os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/") + "/api/tags"),
            timeout=2.0,
        ).raise_for_status()
    except Exception as exc:
        print(f"Ollama daemon unreachable: {exc}")
        sys.exit(1)
    asyncio.run(_smoke())
