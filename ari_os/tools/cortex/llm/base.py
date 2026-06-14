from __future__ import annotations

from abc import ABC, abstractmethod


class BrainLLM(ABC):
    """Adapter interface for optional cortex consolidation LLMs."""

    @abstractmethod
    def consolidate(self, texts: list[str]) -> str:
        """Merge multiple memory chunk texts into one concise summary."""
        ...

    @abstractmethod
    def distill(self, text: str, tier: int) -> str:
        """Distill text toward the next memory tier."""
        ...
