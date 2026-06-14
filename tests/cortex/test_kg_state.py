"""KG extraction cursor state."""
from __future__ import annotations

from pathlib import Path

import pytest

from ari_os.tools.cortex import db
from ari_os.tools.cortex.kg.state import KG_MAX_TIER, KG_REGIONS, mark_extracted, select_unextracted


@pytest.fixture
def brain_db(tmp_path: Path) -> Path:
    p = tmp_path / "brain.db"
    db.init_db(p)
    return p


def _insert_chunk(
    db_path: Path,
    *,
    text: str,
    region: str = "hippocampus",
    tier: int = 0,
    path: str = "kg.md",
) -> int:
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
            "VALUES (?, 0, ?, 1, 1, ?, 0.5, ?)",
            (source_id, text, region, tier),
        )
        return int(cur.lastrowid)
    finally:
        con.close()


def test_kg_region_and_tier_defaults_are_public_memory_scope():
    assert KG_REGIONS == ("hippocampus", "wernicke", "vmpfc", "parietal")
    assert KG_MAX_TIER == 1


def test_select_unextracted_filters_region_tier_and_orders_by_chunk_id(brain_db: Path):
    a = _insert_chunk(brain_db, text="alpha note", region="hippocampus", tier=0, path="a.md")
    b = _insert_chunk(brain_db, text="bravo note", region="wernicke", tier=1, path="b.md")
    _insert_chunk(brain_db, text="code note excluded", region="frontoparietal", tier=0, path="c.md")
    _insert_chunk(brain_db, text="too distilled excluded", region="hippocampus", tier=2, path="d.md")

    assert select_unextracted(brain_db) == [(a, "alpha note"), (b, "bravo note")]


def test_select_unextracted_limit_caps_selection(brain_db: Path):
    _insert_chunk(brain_db, text="first", region="hippocampus", tier=0, path="a.md")
    _insert_chunk(brain_db, text="second", region="hippocampus", tier=0, path="b.md")

    assert len(select_unextracted(brain_db, limit=1)) == 1


def test_mark_extracted_removes_chunk_from_selection_and_is_idempotent(brain_db: Path):
    chunk_id = _insert_chunk(brain_db, text="alpha", region="hippocampus", tier=0)

    mark_extracted(brain_db, chunk_id, now=123)
    mark_extracted(brain_db, chunk_id, now=456)

    assert select_unextracted(brain_db) == []

    con = db.connect(brain_db)
    try:
        row = con.execute(
            "SELECT chunk_id, extracted_at, extractor_version FROM kg_extract_state"
        ).fetchone()
    finally:
        con.close()

    assert row == (chunk_id, 456, 1)
