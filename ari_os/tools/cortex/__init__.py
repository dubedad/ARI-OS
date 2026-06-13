"""ARI-OS Cortex — the heavy single-machine brain.

Substrate (ar.t2): config, db, schema, vec_sidecar. Ingest (ar.t3): chunker,
index, transcript_filter. Embeddings (ar.t4): embed, similarity. The rest
(retrieve, modes, MCP) lands in later tasks per the heavy-core plan.
"""
from . import (  # noqa: F401
    chunker,
    config,
    db,
    embed,
    index,
    similarity,
    transcript_filter,
    vec_sidecar,
)

__all__ = [
    "chunker",
    "config",
    "db",
    "embed",
    "index",
    "similarity",
    "transcript_filter",
    "vec_sidecar",
]
