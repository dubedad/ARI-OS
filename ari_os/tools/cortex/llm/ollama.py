from __future__ import annotations

import time

import httpx

from ari_os.tools.cortex.config import OLLAMA_URL
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

MAX_PROMPT_CHARS = 64000
MAX_OUTPUT_TOKENS = 512
_MAX_ATTEMPTS = 3
_TIMEOUT = 180.0


def _bound_prompt(prompt: str, max_chars: int = MAX_PROMPT_CHARS) -> str:
    if len(prompt) <= max_chars:
        return prompt
    return prompt[:max_chars]


class OllamaLLM(BrainLLM):
    """Local Ollama adapter for cortex consolidation."""

    def __init__(self, model: str = "gemma3:4b", url: str = OLLAMA_URL) -> None:
        self.model = model
        self.url = url.rstrip("/")

    def _generate(self, prompt: str) -> str:
        payload = {
            "model": self.model,
            "prompt": _bound_prompt(prompt),
            "stream": False,
            "think": False,
            "options": {"num_predict": MAX_OUTPUT_TOKENS},
        }
        last_exc: Exception | None = None
        for attempt in range(_MAX_ATTEMPTS):
            try:
                resp = httpx.post(
                    f"{self.url}/api/generate", json=payload, timeout=_TIMEOUT
                )
                resp.raise_for_status()
                return str(resp.json().get("response", "")).strip()
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_exc = exc
                if attempt + 1 < _MAX_ATTEMPTS:
                    time.sleep(2 ** attempt)
        if last_exc is not None:
            raise last_exc
        return ""

    def consolidate(self, texts: list[str]) -> str:
        body = "\n---\n".join(texts)
        return self._generate(_CONSOLIDATE_PROMPT.format(body=body))

    def distill(self, text: str, tier: int) -> str:
        goal = _DISTILL_GOALS.get(tier, "Distill this text to its essence.")
        return self._generate(f"{goal}\n\n{text}")
