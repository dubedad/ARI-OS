"""ARI-OS Cortex — the heavy single-machine brain.

Substrate (ar.t2): config, db, schema, vec_sidecar. Ingest (ar.t3): chunker,
index, transcript_filter. Embeddings (ar.t4): embed, similarity. Region
seeds + task classifier (ar.t5): region_anchors, task_classifier,
task_region_weights. The rest (retrieve, modes, MCP) lands in later tasks
per the heavy-core plan.
"""
from . import (  # noqa: F401
    chunker,
    config,
    db,
    embed,
    index,
    region_anchors,
    similarity,
    task_classifier,
    task_region_weights,
    transcript_filter,
    vec_sidecar,
)

__all__ = [
    "chunker",
    "config",
    "db",
    "embed",
    "index",
    "region_anchors",
    "similarity",
    "task_classifier",
    "task_region_weights",
    "transcript_filter",
    "vec_sidecar",
]
