"""Optional cortex LLM adapters."""
from __future__ import annotations

import os

from ari_os.tools.cortex import config
from ari_os.tools.cortex.llm.base import BrainLLM


def get_llm(spec: str | None = None) -> BrainLLM | None:
    """Return the selected consolidation LLM, or ``None`` when disabled.

    ``spec`` format:
    - ``off`` / ``none`` / ``unavailable`` -> ``None``
    - ``ollama`` or ``ollama:<model>``
    - ``api`` / ``api:<model>`` / ``api:<provider>:<model>``
    """
    if spec is None:
        spec = os.environ.get("ARI_OS_LLM", config.DEFAULT_LLM)

    spec = (spec or "").strip()
    if not spec:
        return None

    provider, _, rest = spec.partition(":")
    provider = provider.strip().lower()
    if provider in {"off", "none", "unavailable"}:
        return None

    if provider == "ollama":
        from ari_os.tools.cortex.llm.ollama import OllamaLLM

        return OllamaLLM(model=rest or "gemma3:4b")

    if provider == "api":
        from ari_os.tools.cortex.llm.api import ApiLLM

        api_provider, api_model = _parse_api_rest(rest)
        return ApiLLM(provider=api_provider, model=api_model)

    return None


def _parse_api_rest(rest: str) -> tuple[str | None, str | None]:
    if not rest:
        return None, None
    provider, sep, model = rest.partition(":")
    if sep:
        return provider or None, model or None
    return None, provider or None


__all__ = ["BrainLLM", "get_llm"]
