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
