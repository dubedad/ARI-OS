from __future__ import annotations

import os

import httpx

from ari_os.tools import ask
from ari_os.tools.cortex.llm.base import BrainLLM


_CONSOLIDATE_PROMPT = (
    "You are a memory consolidation system. Merge the following knowledge chunks "
    "into a single coherent summary. Preserve key facts, rules, and decisions. "
    "Be concise.\n\n{body}"
)

_DISTILL_GOALS = {
    0: "Summarize this captured text into key decisions and facts.",
    1: "Synthesize these summaries into recurring patterns and key insights.",
    2: "Extract the core arc and durable principles from these summaries.",
}

_DEFAULT_ENDPOINTS = {
    "moonshot": "https://api.moonshot.cn/v1",
    "minimax": "https://api.minimax.io/v1",
}

_TIMEOUT = 180.0
_MAX_OUTPUT_TOKENS = 512


class ApiLLM(BrainLLM):
    """Generic OpenAI-compatible API backend for cortex consolidation."""

    def __init__(
        self,
        provider: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self.provider = provider or os.environ.get("ARI_OS_LLM_API_PROVIDER", "moonshot")
        self.model = model or os.environ.get("ARI_OS_LLM_API_MODEL", "default")
        self.base_url = (
            base_url
            or os.environ.get("ARI_OS_LLM_API_BASE_URL")
            or _DEFAULT_ENDPOINTS.get(self.provider)
        )
        if not self.base_url:
            raise ValueError(
                "API LLM backend requires ARI_OS_LLM_API_BASE_URL for provider "
                f"{self.provider!r}"
            )
        self.base_url = self.base_url.rstrip("/")

    def _generate(self, prompt: str) -> str:
        key = ask.get_key(self.provider)
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": _MAX_OUTPUT_TOKENS,
        }
        resp = httpx.post(
            f"{self.base_url}/chat/completions",
            json=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {key}",
            },
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        return str(data["choices"][0]["message"]["content"]).strip()

    def consolidate(self, texts: list[str]) -> str:
        body = "\n---\n".join(texts)
        return self._generate(_CONSOLIDATE_PROMPT.format(body=body))

    def distill(self, text: str, tier: int) -> str:
        goal = _DISTILL_GOALS.get(tier, "Distill this text to its essence.")
        return self._generate(f"{goal}\n\n{text}")
