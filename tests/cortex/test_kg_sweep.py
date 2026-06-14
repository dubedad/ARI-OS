"""KG population sweeps: gated, retryable, and idempotent."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ari_os.tools.cortex import db
from ari_os.tools.cortex.kg.state import select_unextracted
from ari_os.tools.cortex.kg.sweep import (
    LLMUnavailable,
    _concurrency_from_env,
    populate_kg,
    populate_kg_incremental,
)


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
    layer: str = "semantic",
) -> int:
    con = db.connect(db_path)
    try:
        con.execute(
            "INSERT OR IGNORE INTO source(path, layer, workspace, mtime, sha256, last_indexed_at) "
            "VALUES (?, ?, NULL, 0, 'x', 0)",
            (path, layer),
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


class StubKGLLM:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def extract_entities(self, prompt: str) -> list[str]:
        self.prompts.append(prompt)
        if "subject | predicate | object | confidence" in prompt:
            return ["ARI OS | uses | Cortex | 0.9"]
        return ["ARI OS | project | 0.95", "Cortex | tool | 0.8"]


class DownLLM:
    def extract_entities(self, prompt: str) -> list[str]:
        raise RuntimeError("offline")


def test_populate_kg_upserts_rows_and_rerun_bumps_counts_without_duplicates(brain_db: Path):
    chunk_id = _insert_chunk(
        brain_db,
        text="ARI OS uses Cortex to retrieve useful memory context for local workflows.",
        tier=2,
    )
    llm = StubKGLLM()

    first = populate_kg(brain_db, llm=llm)
    second = populate_kg(brain_db, llm=llm)

    assert first.chunks_processed == 1
    assert first.entities_upserted == 2
    assert first.relations_upserted == 1
    assert second.chunks_processed == 1

    con = db.connect(brain_db)
    try:
        assert con.execute("SELECT COUNT(*) FROM kg_entity").fetchone()[0] == 2
        assert con.execute("SELECT COUNT(*) FROM kg_relation").fetchone()[0] == 1
        assert con.execute(
            "SELECT COUNT(*) FROM kg_entity_chunk WHERE chunk_id=?", (chunk_id,)
        ).fetchone()[0] == 2
        assert con.execute(
            "SELECT mention_count FROM kg_entity WHERE name='ari os'"
        ).fetchone()[0] == 2
        assert con.execute(
            "SELECT evidence_count FROM kg_relation"
        ).fetchone()[0] == 2
    finally:
        con.close()


def test_populate_kg_does_not_consume_incremental_cursor(brain_db: Path):
    _insert_chunk(
        brain_db,
        text="ARI OS uses Cortex to retrieve useful memory context for local workflows.",
        tier=2,
    )

    populate_kg(brain_db, llm=StubKGLLM())

    con = db.connect(brain_db)
    try:
        assert con.execute("SELECT COUNT(*) FROM kg_extract_state").fetchone()[0] == 0
    finally:
        con.close()


def test_populate_kg_incremental_writes_rows_marks_state_and_skips_next_run(brain_db: Path):
    chunk_id = _insert_chunk(
        brain_db,
        text="ARI OS uses Cortex to retrieve useful memory context for local workflows.",
        region="hippocampus",
        tier=0,
    )
    llm = StubKGLLM()

    stats = populate_kg_incremental(brain_db, llm=llm)

    assert stats.chunks_processed == 1
    assert stats.entities_upserted == 2
    assert stats.relations_upserted == 1
    assert stats.skipped == 0
    assert stats.failed == 0

    con = db.connect(brain_db)
    try:
        assert con.execute("SELECT COUNT(*) FROM kg_entity").fetchone()[0] == 2
        assert con.execute("SELECT COUNT(*) FROM kg_relation").fetchone()[0] == 1
        assert con.execute(
            "SELECT COUNT(*) FROM kg_entity_chunk WHERE chunk_id=?", (chunk_id,)
        ).fetchone()[0] == 2
        assert con.execute(
            "SELECT COUNT(*) FROM kg_extract_state WHERE chunk_id=?", (chunk_id,)
        ).fetchone()[0] == 1
    finally:
        con.close()

    stats2 = populate_kg_incremental(brain_db, llm=llm)
    assert stats2.chunks_processed == 0
    assert select_unextracted(brain_db) == []


def test_short_text_is_marked_and_skipped(brain_db: Path):
    _insert_chunk(brain_db, text="too short")

    stats = populate_kg_incremental(brain_db, llm=StubKGLLM())

    assert stats.skipped == 1
    assert select_unextracted(brain_db) == []


def test_llm_none_noops_without_marking_or_network_call(brain_db: Path):
    _insert_chunk(
        brain_db,
        text="ARI OS uses Cortex to retrieve useful memory context for local workflows.",
    )

    stats = populate_kg_incremental(brain_db, llm=None)

    assert stats == stats.__class__()
    assert len(select_unextracted(brain_db)) == 1


def test_kg_toggle_off_noops_without_network_call(brain_db: Path, tmp_path: Path, monkeypatch):
    _insert_chunk(
        brain_db,
        text="ARI OS uses Cortex to retrieve useful memory context for local workflows.",
    )
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"cortex": {"kg": False}}))
    monkeypatch.setenv("ARI_OS_HOME", str(tmp_path))
    llm = StubKGLLM()

    stats = populate_kg_incremental(brain_db, llm=llm)

    assert stats == stats.__class__()
    assert llm.prompts == []
    assert len(select_unextracted(brain_db)) == 1


def test_failed_chunk_left_unmarked_for_retry(brain_db: Path):
    _insert_chunk(
        brain_db,
        text="A long enough memory chunk that the unavailable local model fails on.",
    )

    stats = populate_kg_incremental(brain_db, llm=DownLLM())

    assert stats.failed == 1
    assert len(select_unextracted(brain_db)) == 1


def test_three_consecutive_failures_abort_cleanly(brain_db: Path):
    for i in range(3):
        _insert_chunk(
            brain_db,
            text=f"chunk {i} has enough text to require extraction and fail cleanly",
            path=f"fail-{i}.md",
        )

    with pytest.raises(LLMUnavailable):
        populate_kg_incremental(brain_db, llm=DownLLM())

    con = db.connect(brain_db)
    try:
        assert con.execute("SELECT COUNT(*) FROM kg_entity").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM kg_relation").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM kg_extract_state").fetchone()[0] == 0
    finally:
        con.close()


def test_concurrent_happy_path_matches_serial(brain_db: Path, monkeypatch):
    monkeypatch.setenv("ARI_OS_KG_CONCURRENCY", "4")
    for i in range(5):
        _insert_chunk(
            brain_db,
            text=f"chunk {i}: ARI OS uses Cortex to retrieve useful memory context.",
            path=f"chunk-{i}.md",
        )

    stats = populate_kg_incremental(brain_db, llm=StubKGLLM())

    assert stats.chunks_processed == 5
    assert stats.entities_upserted == 10
    assert stats.relations_upserted == 5
    assert stats.failed == 0
    assert select_unextracted(brain_db) == []


def test_concurrency_env_parsing(monkeypatch):
    monkeypatch.delenv("ARI_OS_KG_CONCURRENCY", raising=False)
    assert _concurrency_from_env() == 12
    monkeypatch.setenv("ARI_OS_KG_CONCURRENCY", "1")
    assert _concurrency_from_env() == 1
    monkeypatch.setenv("ARI_OS_KG_CONCURRENCY", "garbage")
    assert _concurrency_from_env() == 12
