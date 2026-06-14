"""Per-tool handler functions for the ARI-OS Cortex MCP server.

Each function takes db_path as its first argument and returns plain Python
types (str, dict, list) that FastMCP serialises for the client.

Public port + scrub of the private engine's MCP handlers. Private
implementations (vision_bridge / LENS cards) are replaced with friendly
"not supported" responses — those surfaces are mesh/personal in the
private engine and not part of the ARI-OS public package.
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


def entities(db_path: Path, *, kind: str | None = None, k: int = 50) -> list:
    """Return KG entities ordered by mention count and confidence."""
    from .db import connect

    limit = max(1, int(k))
    con = connect(db_path)
    try:
        if kind:
            rows = con.execute(
                """SELECT id, name, kind, confidence, mention_count
                   FROM kg_entity
                   WHERE kind = ?
                   ORDER BY mention_count DESC, confidence DESC, name ASC
                   LIMIT ?""",
                (kind, limit),
            ).fetchall()
        else:
            rows = con.execute(
                """SELECT id, name, kind, confidence, mention_count
                   FROM kg_entity
                   ORDER BY mention_count DESC, confidence DESC, name ASC
                   LIMIT ?""",
                (limit,),
            ).fetchall()
    finally:
        con.close()
    return [
        {
            "id": int(row[0]),
            "name": row[1],
            "kind": row[2],
            "confidence": row[3],
            "mention_count": row[4],
        }
        for row in rows
    ]


def relations(db_path: Path, *, entity: str | None = None, k: int = 50) -> list:
    """Return KG relations, optionally constrained to one entity name."""
    from .db import connect
    from .kg.query import find_entity_by_name

    limit = max(1, int(k))
    params: tuple[object, ...]
    where = ""
    if entity:
        hit = find_entity_by_name(db_path, entity)
        if hit is None:
            return []
        where = "WHERE r.subject_id = ? OR r.object_id = ?"
        params = (hit["id"], hit["id"], limit)
    else:
        params = (limit,)

    con = connect(db_path)
    try:
        rows = con.execute(
            f"""SELECT r.id, se.name, r.predicate, oe.name,
                      r.confidence, r.evidence_count
                 FROM kg_relation r
                 JOIN kg_entity se ON se.id = r.subject_id
                 JOIN kg_entity oe ON oe.id = r.object_id
                 {where}
                 ORDER BY r.evidence_count DESC, r.confidence DESC, r.id ASC
                 LIMIT ?""",
            params,
        ).fetchall()
    finally:
        con.close()
    return [
        {
            "id": int(row[0]),
            "subject": row[1],
            "predicate": row[2],
            "object": row[3],
            "confidence": row[4],
            "evidence_count": row[5],
        }
        for row in rows
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
    """Retrieve a LENS card by slug.

    The ARI-OS public package ships without the LENS_ card layout used by
    the private engine (LENS_ cards are personal/mesh-authored). The
    surface is preserved for client compatibility; the response always
    says the slug was not found.
    """
    return f"## LENS card not found: {slug}\n"
