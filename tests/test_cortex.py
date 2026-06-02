# tests/test_cortex.py
from ari_os.tools import cortex

def test_connect_creates_tables(tmp_path):
    db = tmp_path / "c.db"
    conn = cortex.connect(str(db))
    names = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table','view')").fetchall()}
    assert {"memory", "memory_fts", "meta", "wander_state"} <= names

def test_connect_is_idempotent(tmp_path):
    db = str(tmp_path / "c.db")
    cortex.connect(db).close()
    conn = cortex.connect(db)  # must not raise on second open
    assert conn.execute("SELECT count(*) FROM memory").fetchone()[0] == 0

def test_db_path_honors_env(tmp_path, monkeypatch):
    monkeypatch.setenv("ARI_OS_HOME", str(tmp_path))
    assert cortex.db_path() == tmp_path / "cortex.db"

def test_remember_inserts_row_and_fts(tmp_path):
    conn = cortex.connect(str(tmp_path / "c.db"))
    mid = cortex.remember(conn, "the deploy uses blue-green", context="proj-a",
                          tags="ops deploy", salience=0.5)
    assert isinstance(mid, int) and mid > 0
    row = conn.execute("SELECT text, context, salience FROM memory WHERE id=?", (mid,)).fetchone()
    assert row == ("the deploy uses blue-green", "proj-a", 0.5)
    # FTS5 bare 'blue-green' is parsed as NOT operator; phrase-query double-quotes needed
    hit = conn.execute(
        'SELECT rowid FROM memory_fts WHERE memory_fts MATCH \'"blue-green"\'').fetchone()
    assert hit[0] == mid

def test_remember_stores_vector_as_json(tmp_path):
    conn = cortex.connect(str(tmp_path / "c.db"))
    mid = cortex.remember(conn, "x", vector=[0.1, 0.2, 0.3])
    raw = conn.execute("SELECT vector FROM memory WHERE id=?", (mid,)).fetchone()[0]
    import json as _j
    assert _j.loads(raw) == [0.1, 0.2, 0.3]

import time as _t

def test_recency_decay_halves_each_half_life():
    now = 1_000_000.0
    assert abs(cortex.recency_decay(now, now=now) - 1.0) < 1e-9
    older = now - 30 * 86400
    assert abs(cortex.recency_decay(older, now=now) - 0.5) < 1e-6

def test_recall_ranks_by_match(tmp_path):
    conn = cortex.connect(str(tmp_path / "c.db"))
    cortex.remember(conn, "blue-green deploy rollout strategy", tags="ops")
    cortex.remember(conn, "the cat sat on the mat")
    out = cortex.recall(conn, "deploy", limit=5)
    assert out and out[0]["text"].startswith("blue-green")

def test_recall_salience_breaks_ties(tmp_path):
    conn = cortex.connect(str(tmp_path / "c.db"))
    low = cortex.remember(conn, "deploy notes alpha", salience=0.0)
    high = cortex.remember(conn, "deploy notes beta", salience=5.0)
    out = cortex.recall(conn, "deploy notes", limit=5)
    assert out[0]["id"] == high
