"""Surprising-connections dream artifact tests."""
from __future__ import annotations

from pathlib import Path

import pytest

from ari_os.tools.cortex import db, dream
from ari_os.tools.cortex.kg.extractor import ExtractedEntity, ExtractedRelation
from ari_os.tools.cortex.kg.store import (
    link_entity_to_chunk,
    upsert_entity,
    upsert_relation,
)


@pytest.fixture
def brain_db(tmp_path: Path) -> Path:
    path = tmp_path / "brain.db"
    db.init_db(path)
    return path


def _insert_chunk(
    db_path: Path,
    *,
    text: str,
    region: str,
    path: str,
) -> int:
    con = db.connect(db_path)
    try:
        con.execute(
            "INSERT OR IGNORE INTO source(path, layer, workspace, mtime, sha256, last_indexed_at) "
            "VALUES (?, 'semantic', 'test', 0, 'x', 0)",
            (path,),
        )
        source_id = con.execute("SELECT id FROM source WHERE path = ?", (path,)).fetchone()[0]
        ordinal = con.execute(
            "SELECT COALESCE(MAX(ordinal), -1) + 1 FROM chunk WHERE source_id = ?",
            (source_id,),
        ).fetchone()[0]
        cur = con.execute(
            """INSERT INTO chunk(
                 source_id, ordinal, text, line_start, line_end, region,
                 importance, distillation_tier
               ) VALUES (?, ?, ?, 1, 1, ?, 0.5, 0)""",
            (source_id, ordinal, text, region),
        )
        return int(cur.lastrowid)
    finally:
        con.close()


def _wire_graph(
    db_path: Path,
    *,
    c_hippo: int,
    c_wernicke: int,
    c_frontal: int,
    c_hippo2: int,
) -> None:
    alpha = upsert_entity(
        db_path, ExtractedEntity("Alpha Tool", "tool", 0.9), now=100
    )
    beta = upsert_entity(
        db_path, ExtractedEntity("Beta Concept", "concept", 0.9), now=100
    )
    delta = upsert_entity(
        db_path, ExtractedEntity("Delta System", "project", 0.9), now=100
    )
    gamma = upsert_entity(
        db_path, ExtractedEntity("Gamma Tool", "tool", 0.9), now=100
    )

    link_entity_to_chunk(db_path, entity_id=alpha, chunk_id=c_hippo, confidence=0.9)
    link_entity_to_chunk(db_path, entity_id=beta, chunk_id=c_wernicke, confidence=0.9)
    link_entity_to_chunk(db_path, entity_id=delta, chunk_id=c_frontal, confidence=0.9)
    link_entity_to_chunk(db_path, entity_id=gamma, chunk_id=c_hippo2, confidence=0.9)

    upsert_relation(
        db_path,
        ExtractedRelation("Alpha Tool", "uses", "Beta Concept", 0.9),
        subject_id=alpha,
        object_id=beta,
        source_chunk_id=c_hippo,
        now=100,
    )
    upsert_relation(
        db_path,
        ExtractedRelation("Alpha Tool", "uses", "Beta Concept", 0.9),
        subject_id=alpha,
        object_id=beta,
        source_chunk_id=c_hippo,
        now=110,
    )
    upsert_relation(
        db_path,
        ExtractedRelation("Alpha Tool", "blocks", "Gamma Tool", 0.9),
        subject_id=alpha,
        object_id=gamma,
        source_chunk_id=c_hippo,
        now=100,
    )
    upsert_relation(
        db_path,
        ExtractedRelation("Alpha Tool", "mentions", "Delta System", 0.6),
        subject_id=alpha,
        object_id=delta,
        source_chunk_id=c_hippo,
        now=100,
    )


def test_write_surprising_connections_reports_cross_region_edges_ranked(
    brain_db: Path, tmp_path: Path
):
    c_hippo = _insert_chunk(
        brain_db,
        text="hippocampus chunk text long enough here",
        region="hippocampus",
        path="a.md",
    )
    c_wernicke = _insert_chunk(
        brain_db,
        text="wernicke chunk text long enough here",
        region="wernicke",
        path="b.md",
    )
    c_frontal = _insert_chunk(
        brain_db,
        text="frontoparietal chunk text long enough here",
        region="frontoparietal",
        path="c.md",
    )
    c_hippo2 = _insert_chunk(
        brain_db,
        text="second hippocampus chunk text long enough here",
        region="hippocampus",
        path="d.md",
    )
    _wire_graph(
        brain_db,
        c_hippo=c_hippo,
        c_wernicke=c_wernicke,
        c_frontal=c_frontal,
        c_hippo2=c_hippo2,
    )

    written = dream.write_surprising_connections(brain_db, tmp_path)

    assert written == 2
    files = list((tmp_path / "kg_reports").glob("*-surprising-connections.md"))
    assert len(files) == 1
    body = files[0].read_text()
    assert body.index("beta concept") < body.index("delta system")
    assert "alpha tool" in body
    assert "EXTRACTED" in body
    assert "INFERRED" in body
    assert "bridges hippocampus to wernicke" in body
    assert "gamma tool" not in body


def test_write_surprising_connections_is_idempotent_and_empty_safe(
    brain_db: Path, tmp_path: Path
):
    assert dream.write_surprising_connections(brain_db, tmp_path) == 0

    c_hippo = _insert_chunk(
        brain_db, text="hippo chunk text long enough here", region="hippocampus", path="a.md"
    )
    c_wernicke = _insert_chunk(
        brain_db,
        text="wernicke chunk text long enough here",
        region="wernicke",
        path="b.md",
    )
    c_frontal = _insert_chunk(
        brain_db,
        text="frontoparietal chunk text long enough here",
        region="frontoparietal",
        path="c.md",
    )
    c_hippo2 = _insert_chunk(
        brain_db,
        text="second hippo chunk text long enough here",
        region="hippocampus",
        path="d.md",
    )
    _wire_graph(
        brain_db,
        c_hippo=c_hippo,
        c_wernicke=c_wernicke,
        c_frontal=c_frontal,
        c_hippo2=c_hippo2,
    )

    assert dream.write_surprising_connections(brain_db, tmp_path) == 2
    assert dream.write_surprising_connections(brain_db, tmp_path) == 0


def test_run_dream_writes_surprising_connections_without_llm(
    brain_db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    c_hippo = _insert_chunk(
        brain_db, text="hippo chunk text long enough here", region="hippocampus", path="a.md"
    )
    c_wernicke = _insert_chunk(
        brain_db,
        text="wernicke chunk text long enough here",
        region="wernicke",
        path="b.md",
    )
    c_frontal = _insert_chunk(
        brain_db,
        text="frontoparietal chunk text long enough here",
        region="frontoparietal",
        path="c.md",
    )
    c_hippo2 = _insert_chunk(
        brain_db,
        text="second hippo chunk text long enough here",
        region="hippocampus",
        path="d.md",
    )
    _wire_graph(
        brain_db,
        c_hippo=c_hippo,
        c_wernicke=c_wernicke,
        c_frontal=c_frontal,
        c_hippo2=c_hippo2,
    )

    def fail_get_llm(spec=None):
        raise AssertionError("surprising-connections must not resolve a backend")

    monkeypatch.setattr("ari_os.tools.cortex.distill.get_llm", fail_get_llm)

    result = dream.run_dream(brain_db, llm=None, output_dir=tmp_path)

    assert result.surprising_connections == 2
    assert len(list((tmp_path / "kg_reports").glob("*-surprising-connections.md"))) == 1
