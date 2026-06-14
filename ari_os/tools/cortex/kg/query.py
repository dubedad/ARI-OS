"""Read-only queries over ``kg_entity``, ``kg_entity_chunk``, and ``kg_relation``."""
from __future__ import annotations

from pathlib import Path

from ari_os.tools.cortex.db import connect


def _canonical_name(raw: str) -> str:
    return " ".join(raw.strip().split()).lower()


def find_entity_by_name(db_path: Path, name: str, *, kind: str | None = None) -> dict | None:
    """Find one entity by canonical name, optionally constrained by kind."""
    needle = _canonical_name(name)
    con = connect(db_path)
    try:
        if kind:
            row = con.execute(
                "SELECT id, name, kind, confidence, mention_count FROM kg_entity WHERE name=? AND kind=?",
                (needle, kind),
            ).fetchone()
        else:
            row = con.execute(
                "SELECT id, name, kind, confidence, mention_count FROM kg_entity WHERE name=?",
                (needle,),
            ).fetchone()
        if row is None:
            return None
        return {
            "id": int(row[0]),
            "name": row[1],
            "kind": row[2],
            "confidence": row[3],
            "mention_count": row[4],
        }
    finally:
        con.close()


def chunks_for_entity(db_path: Path, entity_id: int) -> list[int]:
    """Return chunk ids linked to an entity, strongest links first."""
    con = connect(db_path)
    try:
        return [
            int(row[0])
            for row in con.execute(
                "SELECT chunk_id FROM kg_entity_chunk WHERE entity_id=? ORDER BY confidence DESC",
                (entity_id,),
            ).fetchall()
        ]
    finally:
        con.close()


def entities_for_chunk(db_path: Path, chunk_id: int) -> list[dict]:
    """Return entities linked to a chunk, strongest links first."""
    con = connect(db_path)
    try:
        rows = con.execute(
            """SELECT e.id, e.name, e.kind, ec.confidence
               FROM kg_entity_chunk ec
               JOIN kg_entity e ON e.id = ec.entity_id
               WHERE ec.chunk_id=?
               ORDER BY ec.confidence DESC""",
            (chunk_id,),
        ).fetchall()
        return [
            {"id": int(row[0]), "name": row[1], "kind": row[2], "confidence": row[3]}
            for row in rows
        ]
    finally:
        con.close()


def related_entities(db_path: Path, entity_id: int) -> list[dict]:
    """Return outbound and inbound relation neighbours for an entity."""
    con = connect(db_path)
    try:
        rows = con.execute(
            """SELECT e.id, e.name, e.kind, r.predicate, r.confidence, 'out' AS direction
               FROM kg_relation r
               JOIN kg_entity e ON e.id = r.object_id
               WHERE r.subject_id = ?
               UNION ALL
               SELECT e.id, e.name, e.kind, r.predicate, r.confidence, 'in' AS direction
               FROM kg_relation r
               JOIN kg_entity e ON e.id = r.subject_id
               WHERE r.object_id = ?""",
            (entity_id, entity_id),
        ).fetchall()
        return [
            {
                "id": int(row[0]),
                "name": row[1],
                "kind": row[2],
                "predicate": row[3],
                "confidence": row[4],
                "direction": row[5],
            }
            for row in rows
        ]
    finally:
        con.close()


def traverse(db_path: Path, entity_id: int, *, max_depth: int = 2) -> list[dict]:
    """Breadth-first traversal up to ``max_depth`` hops, excluding the root."""
    seen: set[int] = {entity_id}
    frontier: list[int] = [entity_id]
    visited: list[dict] = []

    for _ in range(max_depth):
        next_frontier: list[int] = []
        for current_id in frontier:
            for hit in related_entities(db_path, current_id):
                if hit["id"] in seen:
                    continue
                seen.add(hit["id"])
                visited.append(hit)
                next_frontier.append(hit["id"])
        if not next_frontier:
            break
        frontier = next_frontier

    return visited


def chunks_for_entity_paged(db_path: Path, entity_id: int, *, limit: int = 50) -> list[dict]:
    """Return chunk metadata for an entity, including a compact text preview."""
    con = connect(db_path)
    try:
        rows = con.execute(
            """SELECT c.id, c.text, c.region, s.path, ec.confidence
               FROM kg_entity_chunk ec
               JOIN chunk c ON c.id = ec.chunk_id
               JOIN source s ON s.id = c.source_id
               WHERE ec.entity_id = ?
               ORDER BY ec.confidence DESC
               LIMIT ?""",
            (entity_id, limit),
        ).fetchall()
        out = []
        for row in rows:
            preview = (row[1] or "").strip().split("\n\n", 1)[0]
            if len(preview) > 240:
                preview = preview[:240] + "..."
            out.append(
                {
                    "chunk_id": int(row[0]),
                    "region": row[2],
                    "path": row[3],
                    "text_preview": preview,
                    "confidence": row[4],
                }
            )
        return out
    finally:
        con.close()
