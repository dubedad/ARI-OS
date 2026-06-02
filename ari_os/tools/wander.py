"""Mind Wander — Cortex's engineered re-orientation switch.

On a jittered 5-10 cadence the brain surfaces one tangential memory from OUTSIDE
the current tunnel, then dives back. Off in focus mode. The one automatic
boundary-cross — fired for you because inertia stops you firing it yourself.
Stdlib only.
"""
from __future__ import annotations
import random
from . import cortex


def _cadence(rng) -> int:
    return rng.randint(5, 10)


def tick(conn, session, *, rng=None) -> bool:
    rng = rng or random.Random()
    row = conn.execute(
        "SELECT count, next_at FROM wander_state WHERE session=?", (session,)).fetchone()
    if row is None:
        count, next_at = 0, _cadence(rng)
        conn.execute("INSERT INTO wander_state(session, count, next_at) VALUES (?,?,?)",
                     (session, count, next_at))
    else:
        count, next_at = row
    count += 1
    fired = count >= next_at
    if fired:
        conn.execute("UPDATE wander_state SET count=0, next_at=? WHERE session=?",
                     (_cadence(rng), session))
    else:
        conn.execute("UPDATE wander_state SET count=? WHERE session=?", (count, session))
    conn.commit()
    return fired


def divergence_for(coverage, lo=0.2, hi=0.6) -> float:
    c = max(0.0, min(1.0, coverage))
    return lo + (hi - lo) * c


def pick(conn, context="", *, embedder=None, divergence=0.3, rng=None):
    rng = rng or random.Random()
    rows = conn.execute("SELECT id, context, tags FROM memory").fetchall()
    outside = [(mid, tags) for (mid, ctx, tags) in rows if not context or ctx != context]
    if not outside:
        return None
    in_tags = set()
    if context:
        for (tags,) in conn.execute("SELECT tags FROM memory WHERE context=?", (context,)):
            in_tags |= set(tags.split())
    linked = [mid for (mid, tags) in outside if set(tags.split()) & in_tags]
    if linked and rng.random() > divergence:
        chosen = rng.choice(linked)
    else:
        chosen = rng.choice([mid for (mid, _t) in outside])
    r = cortex._row(conn, chosen)
    r["wander"] = True
    return r


def maybe(conn, session, *, mode="default", context="", embedder=None, coverage=0.5, rng=None):
    if not cortex.MODES.get(mode, cortex.MODES["default"])["wander"]:
        return None
    if not tick(conn, session, rng=rng):
        return None
    return pick(conn, context, embedder=embedder,
                divergence=divergence_for(coverage), rng=rng)
