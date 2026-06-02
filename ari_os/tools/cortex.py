# ari_os/tools/cortex.py
"""Cortex — ARI-OS's local memory + cognition layer ("the light brain").

Local sqlite under ~/.ari-os/cortex.db ($ARI_OS_HOME override). Lexical recall
(FTS5/bm25) works with zero dependencies; an optional embeddings key upgrades it
to hybrid semantic recall. Stdlib only.
"""
from __future__ import annotations
import argparse, json, math, os, sqlite3, sys, time
from pathlib import Path

def _state_home() -> Path:
    return Path(os.environ.get("ARI_OS_HOME") or os.path.expanduser("~/.ari-os"))

def db_path() -> Path:
    return _state_home() / "cortex.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memory (
  id INTEGER PRIMARY KEY,
  ts REAL NOT NULL,
  context TEXT NOT NULL DEFAULT '',
  text TEXT NOT NULL,
  tags TEXT NOT NULL DEFAULT '',
  source TEXT NOT NULL DEFAULT '',
  salience REAL NOT NULL DEFAULT 0.0,
  vector TEXT
);
CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(text, context, tags, tokenize="unicode61 tokenchars '-'");
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS wander_state (session TEXT PRIMARY KEY, count INTEGER, next_at INTEGER);
"""

def connect(db_path_str: str | None = None) -> sqlite3.Connection:
    p = Path(db_path_str) if db_path_str else db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.executescript(_SCHEMA)
    conn.execute("INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', '1')")
    conn.commit()
    return conn

def remember(conn, text, *, context="", tags="", source="", salience=0.0, vector=None) -> int:
    cur = conn.execute(
        "INSERT INTO memory(ts, context, text, tags, source, salience, vector) "
        "VALUES (?,?,?,?,?,?,?)",
        (time.time(), context, text, tags, source, float(salience),
         json.dumps(vector) if vector is not None else None))
    mid = cur.lastrowid
    conn.execute("INSERT INTO memory_fts(rowid, text, context, tags) VALUES (?,?,?,?)",
                 (mid, text, context, tags))
    conn.commit()
    return mid
