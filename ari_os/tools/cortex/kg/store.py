"""UPSERT helpers for ``kg_entity``, ``kg_entity_chunk``, and ``kg_relation``."""
from __future__ import annotations

from pathlib import Path
from typing import Protocol

from ari_os.tools.cortex.db import connect


_MAX_LABEL_LEN = 256


class EntityLike(Protocol):
    name: str
    kind: str
    confidence: float


class RelationLike(Protocol):
    predicate: str
    confidence: float


def sanitize_label(raw: str) -> str:
    """Strip non-printable chars, collapse whitespace, and cap labels."""
    cleaned = "".join(ch if ch.isprintable() else " " for ch in raw)
    cleaned = " ".join(cleaned.split())
    return cleaned[:_MAX_LABEL_LEN]


def _canonical_name(raw: str) -> str:
    return " ".join(raw.strip().split()).lower()


def upsert_entity(db_path: Path, ent: EntityLike, *, now: int) -> int:
    """Insert an entity or bump its mention counters. Returns the entity id."""
    name = _canonical_name(sanitize_label(ent.name))
    if not name:
        raise ValueError("entity name empty after sanitization")

    con = connect(db_path)
    try:
        row = con.execute(
            "SELECT id FROM kg_entity WHERE name=? AND kind=?",
            (name, ent.kind),
        ).fetchone()
        if row is not None:
            entity_id = int(row[0])
            con.execute(
                """UPDATE kg_entity
                   SET mention_count = mention_count + 1,
                       last_seen_at = ?,
                       confidence = MAX(confidence, ?)
                   WHERE id = ?""",
                (now, ent.confidence, entity_id),
            )
            return entity_id

        cur = con.execute(
            """INSERT INTO kg_entity(
                 name, kind, confidence, first_seen_at, last_seen_at, mention_count
               )
               VALUES (?, ?, ?, ?, ?, 1)""",
            (name, ent.kind, ent.confidence, now, now),
        )
        return int(cur.lastrowid)
    finally:
        con.close()


def link_entity_to_chunk(db_path: Path, *, entity_id: int, chunk_id: int, confidence: float) -> None:
    """Link an entity to a chunk, preserving the strongest confidence seen."""
    con = connect(db_path)
    try:
        con.execute(
            """INSERT INTO kg_entity_chunk(entity_id, chunk_id, confidence)
               VALUES (?, ?, ?)
               ON CONFLICT(entity_id, chunk_id) DO UPDATE SET
                 confidence = MAX(confidence, excluded.confidence)""",
            (entity_id, chunk_id, confidence),
        )
    finally:
        con.close()


def upsert_relation(
    db_path: Path,
    rel: RelationLike,
    *,
    subject_id: int,
    object_id: int,
    source_chunk_id: int | None,
    now: int,
) -> int:
    """Insert a relation or bump its evidence counters. Returns the relation id."""
    con = connect(db_path)
    try:
        row = con.execute(
            "SELECT id FROM kg_relation WHERE subject_id=? AND predicate=? AND object_id=?",
            (subject_id, rel.predicate, object_id),
        ).fetchone()
        if row is not None:
            relation_id = int(row[0])
            con.execute(
                """UPDATE kg_relation
                   SET evidence_count = evidence_count + 1,
                       last_seen_at = ?,
                       confidence = MAX(confidence, ?)
                   WHERE id = ?""",
                (now, rel.confidence, relation_id),
            )
            return relation_id

        cur = con.execute(
            """INSERT INTO kg_relation(
                 subject_id, predicate, object_id, confidence,
                 source_chunk_id, first_seen_at, last_seen_at, evidence_count
               )
               VALUES (?, ?, ?, ?, ?, ?, ?, 1)""",
            (
                subject_id,
                rel.predicate,
                object_id,
                rel.confidence,
                source_chunk_id,
                now,
                now,
            ),
        )
        return int(cur.lastrowid)
    finally:
        con.close()
