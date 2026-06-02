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
