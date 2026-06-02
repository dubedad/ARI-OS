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

def recency_decay(ts, now=None, half_life_days=30.0) -> float:
    now = time.time() if now is None else now
    age_days = max(0.0, (now - ts) / 86400.0)
    return 0.5 ** (age_days / half_life_days)

def _minmax(d: dict) -> dict:
    if not d:
        return {}
    lo, hi = min(d.values()), max(d.values())
    if hi - lo < 1e-12:
        return {k: 1.0 for k in d}
    return {k: (v - lo) / (hi - lo) for k, v in d.items()}

def _fts_query(query: str) -> str:
    # Safe MATCH: quote each term, OR them. Avoids FTS5 syntax errors on punctuation.
    terms = [t for t in "".join(c if c.isalnum() else " " for c in query).split() if t]
    return " OR ".join(f'"{t}"' for t in terms) or '""'

def _lexical_hits(conn, query, scope_ids=None) -> dict:
    rows = conn.execute(
        "SELECT rowid, bm25(memory_fts) FROM memory_fts WHERE memory_fts MATCH ?",
        (_fts_query(query),)).fetchall()
    hits = {rid: -score for rid, score in rows}          # -bm25 → higher is better
    if scope_ids is not None:
        hits = {k: v for k, v in hits.items() if k in scope_ids}
    return hits

def _row(conn, mid) -> dict:
    r = conn.execute(
        "SELECT id, ts, context, text, tags, source, salience FROM memory WHERE id=?",
        (mid,)).fetchone()
    keys = ("id", "ts", "context", "text", "tags", "source", "salience")
    return dict(zip(keys, r))

def _scope_ids(conn, context, wide):
    if wide or not context:
        return None                       # no scoping
    rows = conn.execute("SELECT id FROM memory WHERE context=?", (context,)).fetchall()
    return {r[0] for r in rows}

def thin_coverage(results, floor=3) -> bool:
    return len(results) < floor

def recall(conn, query, *, context="", mode="default", wide=False, limit=10, embedder=None):
    now = time.time()
    scope = _scope_ids(conn, context, wide)
    lex = _minmax(_lexical_hits(conn, query, scope_ids=scope))
    base = {}
    for mid, lex_n in lex.items():
        r = _row(conn, mid)
        base[mid] = lex_n * (1.0 + r["salience"]) * recency_decay(r["ts"], now=now)
    ranked = sorted(base, key=base.get, reverse=True)[:limit]
    out = []
    for mid in ranked:
        r = _row(conn, mid); r["score"] = base[mid]; out.append(r)
    return out

def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="cortex")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("remember"); r.add_argument("text")
    r.add_argument("--context", default=""); r.add_argument("--tags", default="")
    r.add_argument("--source", default=""); r.add_argument("--salience", type=float, default=0.0)
    q = sub.add_parser("recall"); q.add_argument("query")
    q.add_argument("--context", default=""); q.add_argument("--mode", default="default")
    q.add_argument("--wide", action="store_true"); q.add_argument("--limit", type=int, default=10)
    a = ap.parse_args(argv)
    conn = connect()
    if a.cmd == "remember":
        print(remember(conn, a.text, context=a.context, tags=a.tags,
                       source=a.source, salience=a.salience))
    elif a.cmd == "recall":
        hits = recall(conn, a.query, context=a.context, mode=a.mode,
                      wide=a.wide, limit=a.limit)
        for h in hits:
            print(f"[{h['id']}] ({h['context'] or '-'}) {h['text']}")
        if a.context and not a.wide and thin_coverage(hits):
            print("local context thin — add --wide (or say 'go wide') to search everything")

if __name__ == "__main__":
    main()

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
