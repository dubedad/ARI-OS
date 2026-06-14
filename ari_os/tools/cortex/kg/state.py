"""Incremental extraction state for KG sweeps."""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from ari_os.tools.cortex.db import connect


EXTRACTOR_VERSION = 1

KG_REGIONS: tuple[str, ...] = ("hippocampus", "wernicke", "vmpfc", "parietal")
KG_MAX_TIER = 1

_DDL = """\
CREATE TABLE IF NOT EXISTS kg_extract_state (
  chunk_id          INTEGER PRIMARY KEY REFERENCES chunk(id) ON DELETE CASCADE,
  extracted_at      INTEGER NOT NULL,
  extractor_version INTEGER NOT NULL DEFAULT 1
)
"""


def ensure_state_table(con: sqlite3.Connection) -> None:
    con.execute(_DDL)


def select_unextracted(
    db_path: Path,
    *,
    regions: tuple[str, ...] = KG_REGIONS,
    max_tier: int = KG_MAX_TIER,
    limit: int | None = None,
) -> list[tuple[int, str]]:
    """Return ``(chunk_id, text)`` pairs not yet extracted, oldest first."""
    con = connect(db_path)
    try:
        ensure_state_table(con)
        if not regions:
            return []
        placeholders = ",".join("?" * len(regions))
        query = (
            "SELECT c.id, c.text FROM chunk c "
            "LEFT JOIN kg_extract_state s ON s.chunk_id = c.id "
            "WHERE s.chunk_id IS NULL "
            f"AND c.region IN ({placeholders}) "
            "AND c.distillation_tier <= ? "
            "ORDER BY c.id"
        )
        params: list[object] = [*regions, max_tier]
        if limit is not None:
            query += " LIMIT ?"
            params.append(int(limit))
        return [(int(row[0]), row[1]) for row in con.execute(query, params).fetchall()]
    finally:
        con.close()


def mark_extracted(db_path: Path, chunk_id: int, *, now: int | None = None) -> None:
    """Mark a chunk successfully extracted. Failed chunks remain retryable."""
    con = connect(db_path)
    try:
        ensure_state_table(con)
        con.execute(
            """INSERT INTO kg_extract_state(chunk_id, extracted_at, extractor_version)
               VALUES (?, ?, ?)
               ON CONFLICT(chunk_id) DO UPDATE SET
                 extracted_at = excluded.extracted_at,
                 extractor_version = excluded.extractor_version""",
            (chunk_id, now if now is not None else int(time.time()), EXTRACTOR_VERSION),
        )
    finally:
        con.close()
