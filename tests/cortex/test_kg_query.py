"""Read-only KG query helpers."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from ari_os.tools.cortex import db
from ari_os.tools.cortex.kg.query import (
    chunks_for_entity,
    chunks_for_entity_paged,
    entities_for_chunk,
    find_entity_by_name,
    related_entities,
    traverse,
)
from ari_os.tools.cortex.kg.store import link_entity_to_chunk, upsert_entity, upsert_relation


@pytest.fixture
def brain_db(tmp_path: Path) -> Path:
    p = tmp_path / "brain.db"
    db.init_db(p)
    return p


def _entity(name: str, kind: str = "concept", confidence: float = 0.7):
    return SimpleNamespace(name=name, kind=kind, confidence=confidence)


def _relation(predicate: str, confidence: float = 0.7):
    return SimpleNamespace(predicate=predicate, confidence=confidence)


def _insert_chunk(db_path: Path, *, text: str, path: str, region: str = "hippocampus") -> int:
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
            "VALUES (?, 0, ?, 1, 3, ?, 0.5, 0)",
            (source_id, text, region),
        )
        return int(cur.lastrowid)
    finally:
        con.close()


def test_find_entity_by_name_accepts_mixed_case_and_optional_kind(brain_db: Path):
    entity_id = upsert_entity(brain_db, _entity("Graph Engine", kind="system"), now=100)
    upsert_entity(brain_db, _entity("Graph Engine", kind="project"), now=100)

    hit = find_entity_by_name(brain_db, "  GRAPH   ENGINE  ", kind="system")
    assert hit == {
        "id": entity_id,
        "name": "graph engine",
        "kind": "system",
        "confidence": 0.7,
        "mention_count": 1,
    }
    assert find_entity_by_name(brain_db, "graph engine", kind="missing") is None


def test_chunk_and_entity_lookup_order_by_link_confidence(brain_db: Path):
    entity_id = upsert_entity(brain_db, _entity("Graph Engine"), now=100)
    low = _insert_chunk(brain_db, text="low confidence", path="low.md")
    high = _insert_chunk(brain_db, text="high confidence", path="high.md")
    link_entity_to_chunk(brain_db, entity_id=entity_id, chunk_id=low, confidence=0.2)
    link_entity_to_chunk(brain_db, entity_id=entity_id, chunk_id=high, confidence=0.9)

    assert chunks_for_entity(brain_db, entity_id) == [high, low]

    other_id = upsert_entity(brain_db, _entity("SQLite", kind="tool", confidence=0.5), now=100)
    link_entity_to_chunk(brain_db, entity_id=other_id, chunk_id=high, confidence=0.4)

    assert entities_for_chunk(brain_db, high) == [
        {"id": entity_id, "name": "graph engine", "kind": "concept", "confidence": 0.9},
        {"id": other_id, "name": "sqlite", "kind": "tool", "confidence": 0.4},
    ]


def test_related_entities_returns_outbound_and_inbound_neighbours(brain_db: Path):
    graph = upsert_entity(brain_db, _entity("Graph Engine"), now=100)
    sqlite = upsert_entity(brain_db, _entity("SQLite", kind="tool"), now=100)
    notes = upsert_entity(brain_db, _entity("Notes"), now=100)

    upsert_relation(
        brain_db,
        _relation("uses", confidence=0.8),
        subject_id=graph,
        object_id=sqlite,
        source_chunk_id=None,
        now=100,
    )
    upsert_relation(
        brain_db,
        _relation("feeds", confidence=0.6),
        subject_id=notes,
        object_id=graph,
        source_chunk_id=None,
        now=100,
    )

    assert related_entities(brain_db, graph) == [
        {
            "id": sqlite,
            "name": "sqlite",
            "kind": "tool",
            "predicate": "uses",
            "confidence": 0.8,
            "direction": "out",
        },
        {
            "id": notes,
            "name": "notes",
            "kind": "concept",
            "predicate": "feeds",
            "confidence": 0.6,
            "direction": "in",
        },
    ]


def test_traverse_breadth_first_respects_max_depth(brain_db: Path):
    a = upsert_entity(brain_db, _entity("A"), now=100)
    b = upsert_entity(brain_db, _entity("B"), now=100)
    c = upsert_entity(brain_db, _entity("C"), now=100)
    d = upsert_entity(brain_db, _entity("D"), now=100)

    upsert_relation(brain_db, _relation("to"), subject_id=a, object_id=b, source_chunk_id=None, now=100)
    upsert_relation(brain_db, _relation("to"), subject_id=b, object_id=c, source_chunk_id=None, now=100)
    upsert_relation(brain_db, _relation("to"), subject_id=c, object_id=d, source_chunk_id=None, now=100)

    assert [hit["id"] for hit in traverse(brain_db, a, max_depth=2)] == [b, c]


def test_chunks_for_entity_paged_returns_chunk_metadata_and_ascii_preview(brain_db: Path):
    entity_id = upsert_entity(brain_db, _entity("Graph Engine"), now=100)
    text = "A" * 260
    chunk_id = _insert_chunk(brain_db, text=text, path="note.md", region="wernicke")
    link_entity_to_chunk(brain_db, entity_id=entity_id, chunk_id=chunk_id, confidence=0.8)

    assert chunks_for_entity_paged(brain_db, entity_id, limit=10) == [
        {
            "chunk_id": chunk_id,
            "region": "wernicke",
            "path": "note.md",
            "text_preview": ("A" * 240) + "...",
            "confidence": 0.8,
        }
    ]
