"""ARI-OS Cortex — the heavy single-machine brain.

Substrate (ar.t2): config, db, schema, vec_sidecar. Ingest (ar.t3): chunker,
index, transcript_filter. Embeddings (ar.t4): embed, similarity. Region
seeds + task classifier (ar.t5): region_anchors, task_classifier,
task_region_weights. Modes (ar.t6): mode_router, mode_routing, mode_state,
modes. The rest (retrieve, MCP) lands in later tasks per the heavy-core plan.
"""
from . import (  # noqa: F401
    chunker,
    config,
    db,
    embed,
    index,
    mode_router,
    mode_routing,
    mode_state,
    region_anchors,
    similarity,
    task_classifier,
    task_region_weights,
    transcript_filter,
    vec_sidecar,
)
from .modes import loader as modes_loader  # noqa: F401

__all__ = [
    "chunker",
    "config",
    "db",
    "embed",
    "index",
    "mode_router",
    "mode_routing",
    "mode_state",
    "modes_loader",
    "region_anchors",
    "similarity",
    "task_classifier",
    "task_region_weights",
    "transcript_filter",
    "vec_sidecar",
]
