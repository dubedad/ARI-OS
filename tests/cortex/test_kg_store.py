"""KG store primitives for entity, chunk-link, and relation persistence."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from ari_os.tools.cortex import db
from ari_os.tools.cortex.kg.store import (
    link_entity_to_chunk,
    sanitize_label,
    upsert_entity,
    upsert_relation,
)


@pytest.fixture
def brain_db(tmp_path: Path) -> Path:
    p = tmp_path / "brain.db"
    db.init_db(p)
    return p


def _entity(name: str, kind: str = "concept", confidence: float = 0.7):
    return SimpleNamespace(name=name, kind=kind, confidence=confidence)


def _relation(predicate: str, confidence: float = 0.7):
    return SimpleNamespace(predicate=predicate, confidence=confidence)


def _insert_chunk(db_path: Path, *, text: str = "Graph note", path: str = "kg.md") -> int:
    con = db.connect(db_path)
    try:
        con.execute(
            "INSERT OR IGNORE INTO source(path, layer, workspace, mtime, sha256, last_indexed_at) "
            "VALUES (?, 'semantic', NULL, 0, 'x', 0)",
            (path,),
        )
        source_id = con.execute("SELECT id FROM source WHERE path=?", (path,)).fetchone()[0]
        cur = con.execute(
            "INSERT INTO chunk(source_id, ordinal, text, line_start, line_end, region, importance, distillation_tier) "
            "VALUES (?, 0, ?, 1, 1, 'hippocampus', 0.5, 0)",
            (source_id, text),
        )
        return int(cur.lastrowid)
    finally:
        con.close()


def test_sanitize_label_strips_controls_collapses_whitespace_and_caps():
    assert sanitize_label("Graph\x00 Engine\n\t v2") == "Graph Engine v2"
    assert sanitize_label("  spaced   out  ") == "spaced out"
    assert len(sanitize_label("x" * 999)) == 256


def test_upsert_entity_sanitizes_canonicalizes_and_bumps_existing_row(brain_db: Path):
    first = upsert_entity(brain_db, _entity("Graph\x00  Engine", confidence=0.4), now=100)
    second = upsert_entity(brain_db, _entity("graph engine", confidence=0.9), now=120)

    assert second == first

    con = db.connect(brain_db)
    try:
        rows = con.execute(
            "SELECT name, kind, confidence, first_seen_at, last_seen_at, mention_count FROM kg_entity"
        ).fetchall()
    finally:
        con.close()

    assert rows == [("graph engine", "concept", 0.9, 100, 120, 2)]


def test_upsert_entity_rejects_label_that_sanitizes_empty(brain_db: Path):
    with pytest.raises(ValueError, match="empty"):
        upsert_entity(brain_db, _entity("\x00\x01\n"), now=100)


def test_link_entity_to_chunk_is_idempotent_and_keeps_max_confidence(brain_db: Path):
    chunk_id = _insert_chunk(brain_db)
    entity_id = upsert_entity(brain_db, _entity("Graph Engine"), now=100)

    link_entity_to_chunk(brain_db, entity_id=entity_id, chunk_id=chunk_id, confidence=0.3)
    link_entity_to_chunk(brain_db, entity_id=entity_id, chunk_id=chunk_id, confidence=0.8)
    link_entity_to_chunk(brain_db, entity_id=entity_id, chunk_id=chunk_id, confidence=0.4)

    con = db.connect(brain_db)
    try:
        rows = con.execute(
            "SELECT entity_id, chunk_id, confidence FROM kg_entity_chunk"
        ).fetchall()
    finally:
        con.close()

    assert rows == [(entity_id, chunk_id, 0.8)]


def test_upsert_relation_bumps_evidence_count_without_duplicates(brain_db: Path):
    chunk_id = _insert_chunk(brain_db)
    subject_id = upsert_entity(brain_db, _entity("Graph Engine"), now=100)
    object_id = upsert_entity(brain_db, _entity("SQLite", kind="tool"), now=100)

    first = upsert_relation(
        brain_db,
        _relation("uses", confidence=0.4),
        subject_id=subject_id,
        object_id=object_id,
        source_chunk_id=chunk_id,
        now=100,
    )
    second = upsert_relation(
        brain_db,
        _relation("uses", confidence=0.9),
        subject_id=subject_id,
        object_id=object_id,
        source_chunk_id=chunk_id,
        now=130,
    )

    assert second == first

    con = db.connect(brain_db)
    try:
        rows = con.execute(
            "SELECT subject_id, predicate, object_id, confidence, source_chunk_id, first_seen_at, last_seen_at, evidence_count "
            "FROM kg_relation"
        ).fetchall()
    finally:
        con.close()

    assert rows == [(subject_id, "uses", object_id, 0.9, chunk_id, 100, 130, 2)]
