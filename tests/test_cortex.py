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

def test_gate_tunnels_to_context(tmp_path):
    conn = cortex.connect(str(tmp_path / "c.db"))
    a = cortex.remember(conn, "deploy runbook", context="proj-a")
    cortex.remember(conn, "deploy runbook", context="proj-b")
    out = cortex.recall(conn, "deploy", context="proj-a")
    assert [r["id"] for r in out] == [a]            # proj-b never appears

def test_gate_wide_crosses_only_on_consent(tmp_path):
    conn = cortex.connect(str(tmp_path / "c.db"))
    cortex.remember(conn, "deploy runbook", context="proj-a")
    cortex.remember(conn, "deploy runbook", context="proj-b")
    assert len(cortex.recall(conn, "deploy", context="proj-a")) == 1
    assert len(cortex.recall(conn, "deploy", context="proj-a", wide=True)) == 2

def test_thin_coverage_flags_sparse_result():
    assert cortex.thin_coverage([{"id": 1}], floor=3) is True
    assert cortex.thin_coverage([{"id": i} for i in range(5)], floor=3) is False

def test_cli_remember_then_recall(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ARI_OS_HOME", str(tmp_path))
    cortex.main(["remember", "blue-green deploy", "--context", "proj-a", "--tags", "ops"])
    mid_line = capsys.readouterr().out.strip()
    assert mid_line.isdigit()
    cortex.main(["recall", "deploy", "--context", "proj-a"])
    out = capsys.readouterr().out
    assert "blue-green deploy" in out

def test_hybrid_recalls_paraphrase_with_no_shared_keywords(tmp_path):
    conn = cortex.connect(str(tmp_path / "c.db"))
    # fake embedder: map known strings to vectors; "automobile" ~ "car"
    vecs = {"the car is red": [1.0, 0.0], "a sweet dessert": [0.0, 1.0],
            "automobile": [0.95, 0.05]}
    fake = lambda t: vecs.get(t, [0.0, 0.0])
    cortex.remember(conn, "the car is red", vector=fake("the car is red"))
    cortex.remember(conn, "a sweet dessert", vector=fake("a sweet dessert"))
    out = cortex.recall(conn, "automobile", embedder=fake, limit=2)
    assert out[0]["text"] == "the car is red"     # recalled with zero shared keywords

def test_lexical_still_works_without_embedder(tmp_path):
    conn = cortex.connect(str(tmp_path / "c.db"))
    cortex.remember(conn, "blue-green deploy")
    out = cortex.recall(conn, "deploy")            # embedder=None
    assert out and out[0]["text"] == "blue-green deploy"

def test_modes_table_has_three():
    assert set(cortex.MODES) == {"focus", "default", "wide"}
    assert cortex.MODES["focus"]["wander"] is False
    assert cortex.MODES["wide"]["dn_strength"] > cortex.MODES["focus"]["dn_strength"]

def test_dn_rerank_demotes_duplicates_at_high_alpha():
    # three rows: two near-identical high scorers (shared tag), one unique slightly lower
    rows = [
        {"id": 1, "score": 1.00, "context": "p", "tags": "dup", "vector": None},
        {"id": 2, "score": 0.98, "context": "p", "tags": "dup", "vector": None},
        {"id": 3, "score": 0.95, "context": "p", "tags": "unique", "vector": None},
    ]
    high = cortex.dn_rerank([dict(r) for r in rows], alpha=5.0)
    # the unique row should rise above the second near-duplicate
    # (with strong same-context sim=0.5, row3 rises to top; assert it beats row2)
    ids = [r["id"] for r in high]
    assert ids.index(3) < ids.index(2)
    low = cortex.dn_rerank([dict(r) for r in rows], alpha=0.0)
    assert [r["id"] for r in low] == [1, 2, 3]      # no suppression → original order

def test_mode_changes_ordering(tmp_path):
    conn = cortex.connect(str(tmp_path / "c.db"))
    # Three dup rows + one unique row with moderate salience.
    # focus (low alpha=0.2): dup rows stay near top.
    # wide (high alpha=3.0): dup cross-suppression promotes the unique row.
    cortex.remember(conn, "deploy plan alpha", context="p", tags="dup", salience=1.0)
    cortex.remember(conn, "deploy plan beta", context="p", tags="dup", salience=0.9)
    cortex.remember(conn, "deploy plan gamma", context="p", tags="dup", salience=0.8)
    cortex.remember(conn, "deploy summary unique", context="p", tags="sum", salience=0.5)
    focus = [r["id"] for r in cortex.recall(conn, "deploy", context="p", mode="focus")]
    wide = [r["id"] for r in cortex.recall(conn, "deploy", context="p", mode="wide")]
    assert focus != wide                      # diversity knob actually bites
    assert set(focus) == set(wide)            # same set, only order differs
