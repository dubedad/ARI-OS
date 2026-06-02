import random
from ari_os.tools import cortex, wander


def test_tick_fires_at_next_at_and_resets(tmp_path):
    conn = cortex.connect(str(tmp_path / "c.db"))
    conn.execute("INSERT INTO wander_state(session, count, next_at) VALUES ('s', 0, 3)")
    conn.commit()
    rng = random.Random(1)
    assert wander.tick(conn, "s", rng=rng) is False   # count 1
    assert wander.tick(conn, "s", rng=rng) is False   # count 2
    assert wander.tick(conn, "s", rng=rng) is True     # count 3 == next_at → fire
    count, next_at = conn.execute(
        "SELECT count, next_at FROM wander_state WHERE session='s'").fetchone()
    assert count == 0 and 5 <= next_at <= 10            # reset + re-jittered


def test_tick_seeds_unknown_session(tmp_path):
    conn = cortex.connect(str(tmp_path / "c.db"))
    wander.tick(conn, "fresh", rng=random.Random(0))
    row = conn.execute("SELECT count, next_at FROM wander_state WHERE session='fresh'").fetchone()
    assert row is not None and 5 <= row[1] <= 10


def test_divergence_rises_with_coverage():
    assert wander.divergence_for(0.0) < wander.divergence_for(0.5) < wander.divergence_for(1.0)
    assert 0.0 <= wander.divergence_for(0.0) <= 1.0
    assert 0.0 <= wander.divergence_for(1.0) <= 1.0
    assert wander.divergence_for(2.0) == wander.divergence_for(1.0)   # clamps


def test_pick_returns_memory_outside_context(tmp_path):
    conn = cortex.connect(str(tmp_path / "c.db"))
    cortex.remember(conn, "inside the tunnel", context="A", tags="x")
    cortex.remember(conn, "far away thought", context="B", tags="y")
    p = wander.pick(conn, context="A", rng=random.Random(0))
    assert p is not None and p["context"] == "B" and p["wander"] is True


def test_pick_none_when_nothing_outside(tmp_path):
    conn = cortex.connect(str(tmp_path / "c.db"))
    cortex.remember(conn, "only context", context="A", tags="x")
    assert wander.pick(conn, context="A", rng=random.Random(0)) is None


def test_pick_prefers_linked_at_low_divergence(tmp_path):
    conn = cortex.connect(str(tmp_path / "c.db"))
    cortex.remember(conn, "tunnel note", context="A", tags="shared")
    linked = cortex.remember(conn, "linked outside", context="B", tags="shared")
    cortex.remember(conn, "unlinked outside", context="C", tags="other")
    # divergence 0 → always the tag-linked one
    picks = {wander.pick(conn, context="A", divergence=0.0,
                         rng=random.Random(i))["id"] for i in range(8)}
    assert picks == {linked}


def test_focus_mode_never_wanders(tmp_path):
    conn = cortex.connect(str(tmp_path / "c.db"))
    cortex.remember(conn, "a", context="A"); cortex.remember(conn, "b", context="B")
    for _ in range(20):
        assert wander.maybe(conn, "s", mode="focus", context="A",
                            rng=random.Random(0)) is None


def test_maybe_returns_pick_when_tick_fires(tmp_path):
    conn = cortex.connect(str(tmp_path / "c.db"))
    cortex.remember(conn, "a", context="A"); cortex.remember(conn, "b", context="B")
    conn.execute("INSERT INTO wander_state(session, count, next_at) VALUES ('s', 0, 1)")
    conn.commit()
    out = wander.maybe(conn, "s", mode="default", context="A", rng=random.Random(0))
    assert out is not None and out["context"] == "B"
