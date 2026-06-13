"""ar.t2 substrate tests — config, db, schema, vec_sidecar.

Verifies the public, scrubbed port of the heavy brain's substrate:
- opening a fresh DB creates all tables
- meta.schema_version is set
- FTS5 + sqlite-vec extensions are live
- vec_sidecar capability probe and sidecar-migration are no-ops on a fresh DB
- config honors $ARI_OS_HOME / $ARI_OS_BRAIN_DB overrides
"""
from __future__ import annotations

from pathlib import Path

import pytest

from ari_os.tools.cortex import config, db, vec_sidecar


# ---------- config ----------------------------------------------------------

def test_state_home_default(monkeypatch, tmp_path):
    monkeypatch.delenv("ARI_OS_HOME", raising=False)
    monkeypatch.setattr("os.path.expanduser", lambda p: str(tmp_path) if p == "~/.ari-os" else p)
    assert config.state_home() == tmp_path


def test_state_home_honors_env(monkeypatch, tmp_path):
    monkeypatch.setenv("ARI_OS_HOME", str(tmp_path))
    assert config.state_home() == tmp_path


def test_brain_db_path_default(monkeypatch, tmp_path):
    monkeypatch.setenv("ARI_OS_HOME", str(tmp_path))
    assert config.brain_db_path() == tmp_path / "brain.db"


def test_brain_db_path_honors_env(monkeypatch, tmp_path):
    target = tmp_path / "alt" / "brain.db"
    monkeypatch.setenv("ARI_OS_BRAIN_DB", str(target))
    assert config.brain_db_path() == target


# ---------- db --------------------------------------------------------------

def test_init_db_creates_all_tables(tmp_path):
    db_path = tmp_path / "brain.db"
    db.init_db(db_path)

    con = db.connect(db_path)
    try:
        names = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
        ).fetchall()}
    finally:
        con.close()

    expected_tables = {
        # core
        "source", "chunk", "chunk_vec", "chunk_fts",
        "tract_edge", "retrieval_event", "retrieval_metrics", "chunk_usage",
        # kg
        "kg_entity", "kg_entity_chunk", "kg_relation", "kg_extract_state",
        # fsrs + clustering
        "fsrs_state", "chunk_cluster", "cluster_run",
        # meta
        "meta",
    }
    missing = expected_tables - names
    assert not missing, f"missing tables after init_db: {missing}"


def test_init_db_sets_schema_version_meta(tmp_path):
    db_path = tmp_path / "brain.db"
    db.init_db(db_path)

    con = db.connect(db_path)
    try:
        row = con.execute(
            "SELECT value FROM meta WHERE key='schema_version'"
        ).fetchone()
    finally:
        con.close()

    assert row is not None, "meta.schema_version row missing"
    assert row[0] == str(db.SCHEMA_VERSION)


def test_init_db_sets_user_version(tmp_path):
    db_path = tmp_path / "brain.db"
    db.init_db(db_path)
    con = db.connect(db_path)
    try:
        uv = con.execute("PRAGMA user_version").fetchone()[0]
    finally:
        con.close()
    assert uv == db.SCHEMA_VERSION


def test_init_db_is_idempotent(tmp_path):
    """Running init_db twice on the same path must not raise or duplicate."""
    db_path = tmp_path / "brain.db"
    db.init_db(db_path)
    db.init_db(db_path)  # second call must be safe
    con = db.connect(db_path)
    try:
        n_chunks = con.execute("SELECT count(*) FROM chunk").fetchone()[0]
        uv = con.execute("PRAGMA user_version").fetchone()[0]
    finally:
        con.close()
    assert n_chunks == 0
    assert uv == db.SCHEMA_VERSION


def test_init_db_uses_default_path_under_state_home(tmp_path, monkeypatch):
    monkeypatch.setenv("ARI_OS_HOME", str(tmp_path))
    db.init_db()
    assert (tmp_path / "brain.db").exists()


def test_connect_loads_sqlite_vec_extension(tmp_path):
    """Open a fresh DB and confirm vec0 KNN works (extension is loaded)."""
    db_path = tmp_path / "brain.db"
    db.init_db(db_path)
    con = db.connect(db_path)
    try:
        # An empty KNN should return [] — proves vec0 module is loaded.
        rows = con.execute(
            "SELECT rowid, distance FROM chunk_vec "
            "WHERE embedding MATCH ? AND k = 1",
            (b"\x00" * (768 * 4),),
        ).fetchall()
        assert rows == []
    finally:
        con.close()


def test_meta_get_returns_value(tmp_path):
    db_path = tmp_path / "brain.db"
    db.init_db(db_path)
    con = db.connect(db_path)
    try:
        assert db.meta_get(con, "schema_version") == str(db.SCHEMA_VERSION)
        assert db.meta_get(con, "nope") is None
    finally:
        con.close()


# ---------- vec_sidecar -----------------------------------------------------

def test_vec_sidecar_absent_on_fresh_db(tmp_path):
    db_path = tmp_path / "brain.db"
    db.init_db(db_path)
    con = db.connect(db_path)
    try:
        assert vec_sidecar.has_sidecar(con) is False
    finally:
        con.close()


def test_vec_sidecar_supports_partition_keys(tmp_path):
    """Capability probe — if the installed sqlite-vec lacks partition keys,
    the substrate degrades gracefully (no sidecar, shared-pool split)."""
    db_path = tmp_path / "brain.db"
    db.init_db(db_path)
    con = db.connect(db_path)
    try:
        ok = vec_sidecar.supports_partition_keys(con)
        # Either True (newer sqlite-vec) or False (older build) — both legal.
        assert isinstance(ok, bool)
    finally:
        con.close()


def test_vec_sidecar_drift_zero_on_fresh_db(tmp_path):
    db_path = tmp_path / "brain.db"
    db.init_db(db_path)
    con = db.connect(db_path)
    try:
        # Sidecar absent → drift() short-circuits on the `if n_main == 0` branch.
        assert vec_sidecar.drift(con) == 0.0
    finally:
        con.close()


def test_vec_sidecar_region_knn_returns_none_when_absent(tmp_path):
    """region_knn must degrade (None) when the sidecar hasn't been migrated."""
    db_path = tmp_path / "brain.db"
    db.init_db(db_path)
    out = vec_sidecar.region_knn(db_path, [0.0] * 768, regions=("broca", "wernicke"))
    assert out is None
