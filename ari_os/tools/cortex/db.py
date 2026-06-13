"""ARI-OS Cortex — single-machine substrate (SQLite + sqlite-vec).

Holds:
- open/connect helper (loads sqlite-vec extension, applies pragmas)
- schema version constant + idempotent column guards
- init_db() that creates all tables on a fresh DB
- embedding-dim compatibility probe
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import sqlite_vec

from .config import brain_db_path

SCHEMA_VERSION = 4  # matches the source brain: FTS5 chunk_fts, brain_meta, retrieval_event.top_distance


class EmbeddingDimMismatch(RuntimeError):
    """brain.db was built with a different embedding model dimensionality."""


def _apply_pragmas(con: sqlite3.Connection) -> None:
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=30000")
    con.execute("PRAGMA synchronous=NORMAL")
    con.execute("PRAGMA foreign_keys=ON")


def connect(db_path: Path) -> sqlite3.Connection:
    """Open a brain DB and load sqlite-vec on the connection."""
    con = sqlite3.connect(db_path, isolation_level=None)
    con.enable_load_extension(True)
    sqlite_vec.load(con)
    con.enable_load_extension(False)
    _apply_pragmas(con)
    return con


def _column_exists(con: sqlite3.Connection, table: str, col: str) -> bool:
    return any(r[1] == col for r in con.execute(f"PRAGMA table_info({table})"))


def _add_col_if_missing(con: sqlite3.Connection, table: str, col: str, decl: str) -> None:
    if not _column_exists(con, table, col):
        con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")


def _migrate_column_guards(con: sqlite3.Connection) -> None:
    """Idempotent column additions — safe to call on any v4 DB."""
    if not _column_exists(con, "retrieval_event", "top_distance"):
        con.execute("ALTER TABLE retrieval_event ADD COLUMN top_distance REAL")
    if not _column_exists(con, "meta", "updated_at"):
        con.execute("ALTER TABLE meta ADD COLUMN updated_at INTEGER NOT NULL DEFAULT 0")
    # Plan B: session linkage columns
    _add_col_if_missing(con, "chunk", "session_id", "TEXT")
    _add_col_if_missing(con, "chunk", "created_ts", "INTEGER")
    _add_col_if_missing(con, "retrieval_event", "session_id", "TEXT")
    # Defensive: retrieval_metrics should exist on every v4 brain.
    con.execute("""CREATE TABLE IF NOT EXISTS retrieval_metrics (
      id INTEGER PRIMARY KEY, retrieval_event_id INTEGER, ts INTEGER NOT NULL,
      intent TEXT, confidence REAL, tokens_budget INTEGER NOT NULL,
      tokens_packed INTEGER NOT NULL, tokens_wasted INTEGER NOT NULL,
      n_zones INTEGER NOT NULL DEFAULT 0, per_zone_json TEXT,
      assembler_on INTEGER NOT NULL DEFAULT 0,
      council_tier TEXT, latency_ms REAL, per_region_json TEXT)""")
    con.execute("""CREATE TABLE IF NOT EXISTS chunk_usage (
      id INTEGER PRIMARY KEY, retrieval_event_id INTEGER, chunk_id INTEGER NOT NULL,
      overlap_score REAL NOT NULL, decided_by TEXT NOT NULL, used INTEGER NOT NULL,
      judged_at INTEGER NOT NULL)""")
    con.execute("CREATE INDEX IF NOT EXISTS idx_chunk_usage_event ON chunk_usage(retrieval_event_id)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_chunk_usage_chunk ON chunk_usage(chunk_id)")


def _set_meta(con: sqlite3.Connection, key: str, value: str) -> None:
    """Upsert into the meta table; matches the schema's PRIMARY KEY on `key`."""
    con.execute(
        "INSERT INTO meta(key, value, updated_at) VALUES(?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        (key, value, int(time.time())),
    )


def init_db(db_path: Path | None = None) -> Path:
    """Create a fresh brain DB at *db_path* (or the default path). Idempotent.

    Returns the resolved db_path.
    """
    p = Path(db_path) if db_path is not None else brain_db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    con = connect(p)
    try:
        existing = con.execute("PRAGMA user_version").fetchone()[0]
        schema_sql = (Path(__file__).parent / "schema.sql").read_text()
        if existing == 0:
            # Fresh DB — run the full schema.
            con.executescript(schema_sql)
        # Either way, run column guards so partial-migration DBs catch up.
        _migrate_column_guards(con)
        # Backfill FTS index from content table (no-op on empty DBs).
        con.execute("INSERT INTO chunk_fts(chunk_fts) VALUES('rebuild')")
        con.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        _set_meta(con, "schema_version", str(SCHEMA_VERSION))
    finally:
        con.close()
    return p


def meta_get(con: sqlite3.Connection, key: str) -> str | None:
    row = con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row[0] if row else None


def check_embedding_compatibility(db_path: Path, expected_dim: int) -> None:
    con = connect(db_path)
    try:
        row = con.execute(
            "SELECT sql FROM sqlite_master WHERE name='chunk_vec'"
        ).fetchone()
    finally:
        con.close()
    if not row or f"float[{expected_dim}]" not in row[0]:
        raise EmbeddingDimMismatch(
            f"brain.db built for different dimensionality (expected float[{expected_dim}], "
            f"found: {row[0] if row else 'no chunk_vec table'}). Run `ari-os cortex index --rebuild`."
        )
