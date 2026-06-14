"""Per-tool handler functions for the ARI-OS Cortex MCP server.

Each function takes db_path as its first argument and returns plain Python
types (str, dict, list) that FastMCP serialises for the client.

Public port + scrub of the private engine's MCP handlers. Media surfaces
are local-first and default-off so fresh installs stay inert until the
user explicitly enables them.
"""
from __future__ import annotations

import json
from pathlib import Path


def recall(
    db_path: Path,
    query: str,
    *,
    mode: str = "default",
    k: int = 12,
    token_budget: int = 4000,
    session_id: str | None = None,
) -> str:
    """Retrieve relevant context and return as region-grouped markdown."""
    from .retrieve import emit_markdown, retrieve

    result = retrieve(
        db_path,
        query=query,
        mode=mode,
        k_vector=k,
        token_budget=token_budget,
        consumer="mcp",
        session_id=session_id,
    )
    return emit_markdown(result.chunks, mode=mode,
                         sufficiency=result.sufficiency, reason=result.reason)


def lineage(db_path: Path, chunk_id: int) -> dict:
    """Walk parent_chunks back to raw source; return structured tree.

    Returns: {chunk_id, tier, parents: [...same shape...], raw_source_path}
    """
    from .db import connect

    con = connect(db_path)
    try:
        return _lineage_node(con, chunk_id, visited=set())
    finally:
        con.close()


def _lineage_node(con, chunk_id: int, visited: set) -> dict:
    if chunk_id in visited:
        return {"chunk_id": chunk_id, "cycle": True}
    visited.add(chunk_id)

    row = con.execute(
        "SELECT c.id, c.distillation_tier, c.parent_chunks, s.path "
        "FROM chunk c LEFT JOIN source s ON s.id = c.source_id "
        "WHERE c.id = ?",
        (chunk_id,),
    ).fetchone()

    if row is None:
        return {"chunk_id": chunk_id, "not_found": True}

    cid, tier, parents_json, path = row
    parents: list[int] = []
    if parents_json:
        try:
            parents = [int(p) for p in json.loads(parents_json)]
        except (TypeError, ValueError):
            parents = []

    return {
        "chunk_id": cid,
        "tier": tier,
        "raw_source_path": path,
        "parents": [_lineage_node(con, pid, visited) for pid in parents],
    }


def regions(db_path: Path) -> dict:
    """Return {region: count} for all chunks in brain.db."""
    from .db import connect

    con = connect(db_path)
    try:
        rows = con.execute(
            "SELECT region, COUNT(*) FROM chunk GROUP BY region ORDER BY region"
        ).fetchall()
    finally:
        con.close()
    return {r[0]: r[1] for r in rows}


def tracts(db_path: Path, *, n: int = 100) -> list:
    """Return top N Hebbian tract edges ordered by weight descending.

    Each entry: {from_chunk, to_chunk, weight, co_activations}
    """
    from .db import connect

    con = connect(db_path)
    try:
        rows = con.execute(
            """SELECT from_chunk, to_chunk, weight, co_activations
               FROM tract_edge
               WHERE tract = 'hebbian'
               ORDER BY weight DESC
               LIMIT ?""",
            (n,),
        ).fetchall()
    finally:
        con.close()
    return [
        {
            "from_chunk": r[0],
            "to_chunk": r[1],
            "weight": r[2],
            "co_activations": r[3],
        }
        for r in rows
    ]


def modes(db_path: Path) -> list:
    """List mode YAML files from the modes/ directory beside the cortex package.

    Returns list of {name, path} dicts. Tolerates missing or empty directory.
    """
    modes_dir = Path(__file__).parent / "modes"
    if not modes_dir.exists():
        return []
    result = []
    for yaml_file in sorted(modes_dir.glob("*.yaml")):
        result.append({"name": yaml_file.stem, "path": str(yaml_file)})
    return result


def see_image(db_path: Path, image_path: str, *, mode: str = "visual") -> dict:
    """Image captioning + similar brain chunks (bimodal).

    Returns: {caption, similar_chunks: [...], note}

    The ARI-OS public package ships without the private vision bridge /
    image-caption backend, so the surface is preserved for client
    compatibility but always returns a friendly "not supported" note.
    Wire-format clients can detect the note and degrade gracefully.
    """
    return {
        "caption": None,
        "similar_chunks": [],
        "note": (
            "brain.see is not supported in ARI-OS public package. "
            "Image captioning requires the private vision bridge, which "
            "is not part of the scrubbed public surface."
        ),
    }


def lens(db_path: Path, slug: str) -> str:
    """Retrieve a LENS card by slug from the user's local state home."""
    from . import config
    from .media.lens_adapter import find_card

    if not config.lens_enabled():
        return (
            "## brain.lens is off\n\n"
            "Enable it with `ari-os cortex lens on` after adding local "
            "cards under your ARI-OS state home.\n"
        )

    card = find_card(config.state_home() / "lens", slug)
    if card is not None:
        return _format_lens_card(card)

    indexed = _lens_from_indexed_chunks(db_path, slug)
    if indexed is not None:
        return indexed

    return f"## LENS card not found: {slug}\n"


def _format_lens_card(card) -> str:
    title = card.title or card.slug
    body = card.body.strip()
    return f"# {title}\n\n{body}\n" if body else f"# {title}\n"


def _lens_from_indexed_chunks(db_path: Path, slug: str) -> str | None:
    if not db_path.exists():
        return None
    try:
        from .db import connect

        con = connect(db_path)
        try:
            row = con.execute(
                "SELECT c.text FROM chunk c JOIN source s ON s.id = c.source_id "
                "WHERE s.path LIKE ? OR s.path LIKE ? "
                "OR (s.workspace = 'lens' AND s.path LIKE ?) "
                "ORDER BY c.ordinal LIMIT 1",
                (f"%/lens/%/{slug}.md", f"%/lens/{slug}.md", f"%{slug}.md"),
            ).fetchone()
        finally:
            con.close()
    except Exception:
        return None
    if row is None:
        return None
    return f"# {slug}\n\n{row[0].strip()}\n"
