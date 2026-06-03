import time
from ari_os.tools import cortex, dream


def test_consolidate_dedups_exact_keeping_high_salience(tmp_path):
    conn = cortex.connect(str(tmp_path / "c.db"))
    lo = cortex.remember(conn, "same note", context="p", salience=0.1)
    hi = cortex.remember(conn, "same note", context="p", salience=0.9)
    rep = dream.consolidate(conn)
    assert rep["deduped"] == 1
    rows = conn.execute("SELECT id FROM memory").fetchall()
    assert [r[0] for r in rows] == [hi]          # the high-salience one survives


def test_consolidate_decays_old_low_salience(tmp_path):
    conn = cortex.connect(str(tmp_path / "c.db"))
    mid = cortex.remember(conn, "old", context="p", salience=1.0)
    old_ts = time.time() - 200 * 86400
    conn.execute("UPDATE memory SET ts=? WHERE id=?", (old_ts, mid)); conn.commit()
    dream.consolidate(conn)
    sal = conn.execute("SELECT salience FROM memory WHERE id=?", (mid,)).fetchone()[0]
    assert sal == 0.5                            # 1.0 * DECAY_FACTOR


def test_consolidate_leaves_fresh_untouched(tmp_path):
    conn = cortex.connect(str(tmp_path / "c.db"))
    mid = cortex.remember(conn, "fresh", context="p", salience=1.0)
    dream.consolidate(conn)
    assert conn.execute("SELECT salience FROM memory WHERE id=?", (mid,)).fetchone()[0] == 1.0


def test_audit_flags_orphan_and_duplicate_and_mutates_nothing(tmp_path):
    conn = cortex.connect(str(tmp_path / "c.db"))
    cortex.remember(conn, "dup text", context="p", tags="a")
    cortex.remember(conn, "dup text", context="p", tags="a")      # exact dup
    cortex.remember(conn, "orphan note")                          # no tags, no context
    cortex.remember(conn, "unique", context="p", tags="z")
    before = conn.execute("SELECT count(*) FROM memory").fetchone()[0]
    sugg = dream.audit(conn)
    kinds = {s["kind"] for s in sugg}
    assert "orphan" in kinds and "duplicate_cluster" in kinds
    assert conn.execute("SELECT count(*) FROM memory").fetchone()[0] == before  # no mutation


def test_audit_flags_bloat(tmp_path, monkeypatch):
    conn = cortex.connect(str(tmp_path / "c.db"))
    monkeypatch.setattr(dream, "BLOAT_LIMIT", 2)
    for i in range(3):
        cortex.remember(conn, f"note {i}", context="p", tags="t")
    assert any(s["kind"] == "bloat" for s in dream.audit(conn))


def test_summarise_none_without_key(monkeypatch):
    import ari_os.tools.ask as ask
    def _no_key(provider):
        raise SystemExit(1)
    monkeypatch.setattr(ask, "get_key", _no_key)
    assert dream.summarise(["note one", "note two"]) is None


def test_dream_cli_prints_report(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ARI_OS_HOME", str(tmp_path))
    conn = cortex.connect(str(tmp_path / "cortex.db"))
    cortex.remember(conn, "dup", context="p"); cortex.remember(conn, "dup", context="p")
    conn.close()
    dream.main([])
    out = capsys.readouterr().out
    assert "Consolidated" in out
