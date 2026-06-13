"""ARI-OS Cortex — the heavy single-machine brain.

Substrate (ar.t2): config, db, schema, vec_sidecar. The rest (ingest, retrieve,
modes, MCP) lands in later tasks per the heavy-core plan.
"""
from . import config, db, vec_sidecar  # noqa: F401

__all__ = ["config", "db", "vec_sidecar"]
