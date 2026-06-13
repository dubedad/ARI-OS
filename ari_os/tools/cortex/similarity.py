"""ARI-OS Cortex — vector similarity primitives.

Public seam (spec §5.2): ``cosine`` is the only built-in scorer now. Future
pluggable scorers (wave, sequence-coherence, graph-spectral, H3 SSM) swap in
by implementing the :class:`UsageScorer` protocol — no other module changes.
"""
from __future__ import annotations
import math
from typing import Protocol


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity in [-1, 1]. Returns 0.0 for zero-length vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


class UsageScorer(Protocol):
    """Pluggable seam (spec §5.2): cosine now; wave / sequence-coherence /
    graph-spectral / H3 SSM swap in here later by implementing ``overlap``."""
    def overlap(self, chunk_embedding: list[float],
                response_embeddings: list[list[float]]) -> float: ...


class CosineScorer:
    """A retrieved chunk is 'used' if it strongly matches ANY response segment."""
    def overlap(self, chunk_embedding, response_embeddings):
        if not response_embeddings:
            return 0.0
        return max(cosine(chunk_embedding, r) for r in response_embeddings)
