from __future__ import annotations

import sqlite3
import struct
from pathlib import Path


def _pack(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def _vec(dim: int = 768) -> list[float]:
    out = [0.0] * dim
    out[0] = 1.0
    return out


class _StubEmbed:
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [_vec() for _ in texts]


def _seed_light_db(path: Path) -> None:
    con = sqlite3.connect(path)
    try:
        con.executescript(
            """
            CREATE TABLE source (
              id INTEGER PRIMARY KEY,
              path TEXT UNIQUE NOT NULL,
              layer TEXT NOT NULL,
              mtime INTEGER NOT NULL,
              sha256 TEXT NOT NULL,
              last_indexed_at INTEGER NOT NULL
            );
            CREATE TABLE chunk (
              id INTEGER PRIMARY KEY,
              source_id INTEGER NOT NULL REFERENCES source(id) ON DELETE CASCADE,
              ordinal INTEGER NOT NULL,
              text TEXT NOT NULL,
              line_start INTEGER NOT NULL,
              line_end INTEGER NOT NULL
            );
            """
        )
        con.execute(
            """INSERT INTO source(id, path, layer, mtime, sha256, last_indexed_at)
               VALUES (1, 'notes/light.md', 'semantic', 123, 'abc', 456)"""
        )
        con.execute(
            """INSERT INTO chunk(id, source_id, ordinal, text, line_start, line_end)
               VALUES (7, 1, 0, 'The migrated token is ZEBRAFISHMEMORY.', 3, 4)"""
        )
        con.execute("PRAGMA user_version = 1")
        con.commit()
    finally:
        con.close()


def test_migrate_light_brain_to_heavy_schema_without_embedding(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("ARI_OS_HOME", str(tmp_path / ".ari-os"))
    db_path = tmp_path / "light-cortex.db"
    monkeypatch.setenv("ARI_OS_BRAIN_DB", str(db_path))
    _seed_light_db(db_path)

    from ari_os.tools.cortex import db, retrieve

    migrated = db.migrate(db_path)

    assert migrated == db_path
    con = db.connect(db_path)
    try:
        assert con.execute("SELECT id, text FROM chunk").fetchall() == [
            (7, "The migrated token is ZEBRAFISHMEMORY.")
        ]
        assert con.execute("SELECT id, path FROM source").fetchall() == [
            (1, "notes/light.md")
        ]

        tables = {
            row[0]
            for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
            ).fetchall()
        }
        assert {
            "kg_entity",
            "fsrs_state",
            "chunk_cluster",
            "chunk_vec",
            "chunk_fts",
            "meta",
        }.issubset(tables)

        chunk_cols = {row[1] for row in con.execute("PRAGMA table_info(chunk)")}
        assert {
            "region",
            "importance",
            "distillation_tier",
            "session_id",
        }.issubset(chunk_cols)

        assert db.meta_get(con, "schema_version") == str(db.SCHEMA_VERSION)
        assert con.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
        assert con.execute(
            "SELECT rowid FROM chunk_fts WHERE chunk_fts MATCH 'ZEBRAFISHMEMORY'"
        ).fetchall() == [(7,)]

        con.execute(
            "INSERT INTO chunk_vec(rowid, embedding) VALUES (?, ?)",
            (7, _pack(_vec())),
        )
    finally:
        con.close()

    result = retrieve.retrieve(
        db_path,
        query="ZEBRAFISHMEMORY",
        embed_client=_StubEmbed(),
        cwd=str(tmp_path),
        mode="default",
    )
    assert any("ZEBRAFISHMEMORY" in c.text for c in result.chunks)

    db.migrate(db_path)
    con = db.connect(db_path)
    try:
        assert con.execute("SELECT COUNT(*) FROM chunk WHERE id = 7").fetchone()[0] == 1
        assert con.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
        assert db.meta_get(con, "schema_version") == str(db.SCHEMA_VERSION)
    finally:
        con.close()
