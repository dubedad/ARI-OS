from ari_os.tools import cortex, routines


def test_open_loops_matches_whole_tag(tmp_path):
    conn = cortex.connect(str(tmp_path / "c.db"))
    a = cortex.remember(conn, "unfinished", context="p", tags="open ops")
    cortex.remember(conn, "done", context="p", tags="opens")        # must NOT match
    cortex.remember(conn, "other ctx", context="q", tags="open")
    loops = routines.open_loops(conn, context="p")
    assert [r["id"] for r in loops] == [a]

import time as _t

def test_morning_surfaces_loops_and_focus(tmp_path):
    conn = cortex.connect(str(tmp_path / "c.db"))
    cortex.remember(conn, "old thread", context="p", salience=0.1)
    cortex.remember(conn, "ship the thing", context="p", tags="open", salience=0.9)
    out = routines.morning(conn, context="p")
    assert out["suggested_focus"] == "ship the thing"        # highest-salience open loop
    assert any(r["text"] == "ship the thing" for r in out["open_loops"])
    assert len(out["recent"]) >= 1

def test_morning_focus_falls_back_to_recent(tmp_path):
    conn = cortex.connect(str(tmp_path / "c.db"))
    cortex.remember(conn, "only note", context="p")
    assert routines.morning(conn, context="p")["suggested_focus"] == "only note"
