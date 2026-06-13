"""ARI-OS Cortex — the heavy single-machine brain.

Substrate (ar.t2): config, db, schema, vec_sidecar. Ingest (ar.t3): chunker,
index, transcript_filter. The rest (retrieve, modes, MCP) lands in later
tasks per the heavy-core plan.
"""
from . import chunker, config, db, index, transcript_filter, vec_sidecar  # noqa: F401

__all__ = ["chunker", "config", "db", "index", "transcript_filter", "vec_sidecar"]
