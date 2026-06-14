"""P6 predictive clustering, prefetch, trend, and signal-writer tests."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ari_os.tools.cortex import db
from ari_os.tools.cortex.predictive.clusterer import run_cluster_sweep
from ari_os.tools.cortex.predictive.prefetch import past_chunks_for_cwd, prefetch_for_cwd
from ari_os.tools.cortex.predictive.signal_writer import render_signals_md, write_signals
from ari_os.tools.cortex.predictive.trend import TrendSignal, cluster_sizes_at, detect_growth_signals


@pytest.fixture
def brain_db(tmp_path: Path) -> Path:
    path = tmp_path / "brain.db"
    db.init_db(path)
    return path


def insert_chunk(db_path: Path, *, text: str, path: str, region: str = "frontoparietal") -> int:
    con = db.connect(db_path)
    try:
        con.execute(
            "INSERT OR IGNORE INTO source(path, layer, workspace, mtime, sha256, last_indexed_at) "
            "VALUES (?, 'semantic', NULL, 0, 'x', 0)",
            (path,),
        )
        source_id = con.execute("SELECT id FROM source WHERE path=?", (path,)).fetchone()[0]
        cur = con.execute(
            "INSERT INTO chunk(source_id, ordinal, text, line_start, line_end, region, "
            "importance, distillation_tier) VALUES (?, 0, ?, 1, 2, ?, 0.5, 0)",
            (source_id, text, region),
        )
        return cur.lastrowid
    finally:
        con.close()


def insert_edge(db_path: Path, from_chunk: int, to_chunk: int, weight: float = 1.0) -> None:
    con = db.connect(db_path)
    try:
        con.execute(
            "INSERT INTO tract_edge(from_chunk, to_chunk, tract, weight, co_activations, last_fired_at) "
            "VALUES (?, ?, 'hebbian', ?, 1, 0)",
            (from_chunk, to_chunk, weight),
        )
        con.commit()
    finally:
        con.close()


def insert_retrieval_event(db_path: Path, cwd: str, chunk_ids: list[int]) -> None:
    con = db.connect(db_path)
    try:
        con.execute(
            "INSERT INTO retrieval_event(ts, query_text, cwd, branch, mode, consumer, chunk_ids) "
            "VALUES (?, ?, ?, 'main', 'default', 'test', ?)",
            (0, "query", cwd, json.dumps(chunk_ids)),
        )
        con.commit()
    finally:
        con.close()


def test_run_cluster_sweep_persists_clusters(brain_db):
    chunks = [
        insert_chunk(brain_db, text=f"chunk {i}", path=f"c{i}.md")
        for i in range(4)
    ]
    # Fully-connected hebbian clique so HDBSCAN groups all chunks.
    for i, a in enumerate(chunks):
        for b in chunks[i + 1 :]:
            insert_edge(brain_db, a, b, weight=1.0)

    run_id = run_cluster_sweep(brain_db, min_cluster_size=3)

    assert run_id > 0
    con = db.connect(brain_db)
    try:
        run = con.execute(
            "SELECT n_chunks, n_clusters, n_noise FROM cluster_run WHERE run_id=?", (run_id,)
        ).fetchone()
        rows = con.execute(
            "SELECT chunk_id, cluster_id, probability FROM chunk_cluster WHERE run_id=?", (run_id,)
        ).fetchall()
    finally:
        con.close()

    assert run is not None
    assert run[0] == len(chunks)
    assert run[1] >= 1
    assert len(rows) == len(chunks)
    assert any(cluster_id != -1 for _, cluster_id, _ in rows)


def test_prefetch_for_cwd_renders_past_chunks_and_empty_when_none(brain_db):
    cwd = "/ari-os/workspaces/demo"
    chunks = [
        insert_chunk(brain_db, text=f"prefetch chunk {i}", path=f"p{i}.md")
        for i in range(3)
    ]
    insert_retrieval_event(brain_db, cwd, chunks)
    # Second event to make one chunk more frequent.
    insert_retrieval_event(brain_db, cwd, [chunks[0]])

    rendered = prefetch_for_cwd(brain_db, cwd, limit=3)

    assert rendered.startswith("## Brain — workspace pre-fetch")
    assert f"chunk_id {chunks[0]}" in rendered
    assert "hits=" in rendered

    assert prefetch_for_cwd(brain_db, "/not/used", limit=3) == ""
    assert prefetch_for_cwd(brain_db, "", limit=3) == ""
    assert past_chunks_for_cwd(brain_db, "") == []


def test_detect_growth_signals_fires_on_doubled_cluster(brain_db):
    # Need real chunk rows because chunk_cluster has a foreign key to chunk(id).
    chunks = [
        insert_chunk(brain_db, text=f"trend chunk {i}", path=f"t{i}.md")
        for i in range(4)
    ]
    con = db.connect(brain_db)
    try:
        # Old run: cluster 7 has one chunk.
        con.execute(
            "INSERT INTO cluster_run(run_id, ts, n_chunks, n_clusters, n_noise, params_json) "
            "VALUES (?, ?, 1, 1, 0, '{}')",
            (1, 1_700_000_000),
        )
        con.execute(
            "INSERT INTO chunk_cluster(run_id, chunk_id, cluster_id, probability) VALUES (?, ?, 7, 1.0)",
            (1, chunks[0]),
        )
        # New run: same cluster 7 now has four chunks (4x growth).
        con.execute(
            "INSERT INTO cluster_run(run_id, ts, n_chunks, n_clusters, n_noise, params_json) "
            "VALUES (?, ?, 4, 1, 0, '{}')",
            (2, 1_700_000_100),
        )
        for cid in chunks:
            con.execute(
                "INSERT INTO chunk_cluster(run_id, chunk_id, cluster_id, probability) "
                "VALUES (?, ?, 7, 1.0)",
                (2, cid),
            )
        con.commit()
    finally:
        con.close()

    old_sizes = cluster_sizes_at(brain_db, 1)
    new_sizes = cluster_sizes_at(brain_db, 2)
    assert old_sizes[7] == 1
    assert new_sizes[7] == 4

    signals = detect_growth_signals(brain_db, growth_threshold=4.0, window_seconds=3600)
    assert len(signals) == 1
    s = signals[0]
    assert s.cluster_id == 7
    assert s.old_size == 1
    assert s.new_size == 4
    assert s.growth_ratio == pytest.approx(4.0)
    assert len(s.sample_chunk_ids) >= 1


def test_render_signals_md_and_write_signals_roundtrip(tmp_path):
    signals = [
        TrendSignal(
            cluster_id=7,
            old_size=1,
            new_size=4,
            growth_ratio=4.0,
            window_seconds=86400,
            sample_chunk_ids=[10, 11, 12],
        )
    ]
    md = render_signals_md(signals)
    assert "Cluster 7" in md
    assert "grew 4.00x" in md
    assert "10, 11, 12" in md

    out_dir = tmp_path / "signals"
    path = write_signals(signals, out_dir=out_dir, date_str="2026-06-14")
    assert path.exists()
    content = path.read_text()
    assert "Predictive signals" in content
    assert path.name == "2026-06-14.md"


def test_render_signals_md_empty():
    md = render_signals_md([])
    assert "No signals at this run" in md
