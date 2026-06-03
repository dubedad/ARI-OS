"""/morning and /night routines — thin orchestration over recall + dream.

Local only: reads/writes cortex.db, never pushes. morning() resurfaces recent
threads + open loops + a suggested focus; night() consolidates, reviews what was
captured, and writes a carry-forward. Stdlib only.
"""
from __future__ import annotations
import argparse, time
from . import cortex, dream

OPEN_TAG = "open"

def open_loops(conn, context="") -> list:
    like = f"% {OPEN_TAG} %"
    if context:
        rows = conn.execute(
            "SELECT id FROM memory WHERE context=? AND (' '||tags||' ') LIKE ?",
            (context, like)).fetchall()
    else:
        rows = conn.execute(
            "SELECT id FROM memory WHERE (' '||tags||' ') LIKE ?", (like,)).fetchall()
    return [cortex._row(conn, r[0]) for r in rows]

def _recent(conn, context="", limit=5) -> list:
    if context:
        rows = conn.execute(
            "SELECT id FROM memory WHERE context=? ORDER BY ts DESC LIMIT ?",
            (context, limit)).fetchall()
    else:
        rows = conn.execute(
            "SELECT id FROM memory ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
    return [cortex._row(conn, r[0]) for r in rows]

def morning(conn, context="") -> dict:
    recent = _recent(conn, context, limit=5)
    loops = open_loops(conn, context)
    if loops:
        focus = max(loops, key=lambda r: r["salience"])["text"]
    elif recent:
        focus = recent[0]["text"]
    else:
        focus = None
    return {"recent": recent, "open_loops": loops, "suggested_focus": focus}

def night(conn, context="") -> dict:
    rep = dream.consolidate(conn)
    suggestions = dream.audit(conn)
    cutoff = time.time() - 86400
    if context:
        rows = conn.execute(
            "SELECT id FROM memory WHERE context=? AND ts>=? ORDER BY ts",
            (context, cutoff)).fetchall()
    else:
        rows = conn.execute(
            "SELECT id FROM memory WHERE ts>=? ORDER BY ts", (cutoff,)).fetchall()
    captured = [cortex._row(conn, r[0]) for r in rows]
    carry_forward = [r["text"] for r in open_loops(conn, context)]
    return {"consolidation": rep, "audit": suggestions,
            "captured_today": captured, "carry_forward": carry_forward}
