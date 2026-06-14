"""ARI-OS Cortex — the heavy single-machine brain.

Substrate (ar.t2): config, db, schema, vec_sidecar. Ingest (ar.t3): chunker,
index, transcript_filter. Embeddings (ar.t4): embed, similarity. Region
seeds + task classifier (ar.t5): region_anchors, task_classifier,
task_region_weights. Modes (ar.t6): mode_router, mode_routing, mode_state,
modes. Retrieval (ar.t7): retrieve (hybrid FTS+vec, region rerank,
divisive-norm, kg_expand). Context assembly (ar.t8): context_assembler,
context_block. CLI (ar.t9): cortex. MCP (ar.t12): mcp_server, mcp_tools.

The MCP server module is intentionally NOT eagerly imported here — it is
its own runnable (``python -m ari_os.tools.cortex.mcp_server stdio``)
and importing it eagerly would trip runpy's "found in sys.modules" warning
when launched as a subprocess. Import :mod:`ari_os.tools.cortex.mcp_server`
on demand.
"""
from . import (  # noqa: F401
    chunker,
    config,
    context_assembler,
    context_block,
    db,
    embed,
    index,
    mode_router,
    mode_routing,
    mode_state,
    region_anchors,
    retrieve,
    similarity,
    task_classifier,
    task_region_weights,
    transcript_filter,
    vec_sidecar,
)
from .modes import loader as modes_loader  # noqa: F401


def _public_modes() -> tuple[str, ...]:
    """Return the public mode set, including the legacy ``wide`` alias.

    The control panel (``ari_os.tools.arios``) and the CLI's
    ``arios cortex mode <name>`` subcommand both validate against this
    set so users with an existing ``mode: wide`` in ``config.json``
    do not see ``Unknown mode`` after upgrading to the heavy core.
    ``wide`` was a light-cortex posture and is preserved here as a
    thin alias to ``creative`` (its semantic neighbour) so a stored
    config still loads and ``set_mode("wide")`` round-trips.
    """
    live = modes_loader.list_modes()
    return tuple(sorted(set(live) | {"wide"}))


MODES: tuple[str, ...] = _public_modes()


__all__ = [
    "MODES",
    "chunker",
    "config",
    "context_assembler",
    "context_block",
    "db",
    "embed",
    "index",
    "mode_router",
    "mode_routing",
    "mode_state",
    "modes_loader",
    "region_anchors",
    "retrieve",
    "similarity",
    "task_classifier",
    "task_region_weights",
    "transcript_filter",
    "vec_sidecar",
]
