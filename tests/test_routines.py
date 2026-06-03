from ari_os.tools import cortex, routines


def test_open_loops_matches_whole_tag(tmp_path):
    conn = cortex.connect(str(tmp_path / "c.db"))
    a = cortex.remember(conn, "unfinished", context="p", tags="open ops")
    cortex.remember(conn, "done", context="p", tags="opens")        # must NOT match
    cortex.remember(conn, "other ctx", context="q", tags="open")
    loops = routines.open_loops(conn, context="p")
    assert [r["id"] for r in loops] == [a]
