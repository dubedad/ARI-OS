"""dream — Cortex memory consolidation + self-audit.

consolidate() applies only safe mutations (exact-dedup keeping the highest
salience; decay of stale low-value items). audit() mutates nothing and returns
suggestions (duplicate clusters, orphans, bloat). summarise() returns None unless
a provider key is present. Stdlib only; the optional LLM step reuses ask.py.
"""
from __future__ import annotations
import json, time
from . import cortex

DECAY_HORIZON_DAYS = 90.0
DECAY_FACTOR = 0.5
BLOAT_LIMIT = 500


def consolidate(conn, *, now=None) -> dict:
    now = time.time() if now is None else now
    deduped = 0
    seen = {}
    for mid, text, context, sal in conn.execute(
            "SELECT id, text, context, salience FROM memory ORDER BY id").fetchall():
        key = (text, context)
        if key in seen:
            keep_id, keep_sal = seen[key]
            loser = mid if sal <= keep_sal else keep_id
            if sal > keep_sal:
                seen[key] = (mid, sal)
            conn.execute("DELETE FROM memory WHERE id=?", (loser,))
            conn.execute("DELETE FROM memory_fts WHERE rowid=?", (loser,))
            deduped += 1
        else:
            seen[key] = (mid, sal)
    decayed = 0
    for mid, ts, sal in conn.execute("SELECT id, ts, salience FROM memory").fetchall():
        if (now - ts) / 86400.0 > DECAY_HORIZON_DAYS and sal > 0:
            conn.execute("UPDATE memory SET salience=? WHERE id=?", (sal * DECAY_FACTOR, mid))
            decayed += 1
    conn.commit()
    return {"deduped": deduped, "decayed": decayed}


def _dup(a, b) -> bool:
    if a["text"].strip().lower() == b["text"].strip().lower():
        return True
    if a.get("vector") and b.get("vector"):
        from .embed import cosine
        return cosine(json.loads(a["vector"]), json.loads(b["vector"])) >= 0.92
    return False


def audit(conn) -> list:
    ids = [r[0] for r in conn.execute("SELECT id FROM memory ORDER BY id").fetchall()]
    full = [cortex._row(conn, mid) for mid in ids]
    out = []
    orphans = [r["id"] for r in full if not r["tags"].strip() and not r["context"].strip()]
    if orphans:
        out.append({"kind": "orphan", "ids": orphans,
                    "detail": f"{len(orphans)} memories with no tags or context"})
    clustered = set()
    for i, a in enumerate(full):
        if a["id"] in clustered:
            continue
        grp = [a["id"]]
        for b in full[i + 1:]:
            if b["id"] not in clustered and _dup(a, b):
                grp.append(b["id"]); clustered.add(b["id"])
        if len(grp) > 1:
            clustered.add(a["id"])
            out.append({"kind": "duplicate_cluster", "ids": grp,
                        "detail": f"{len(grp)} similar memories could merge"})
    total = conn.execute("SELECT count(*) FROM memory").fetchone()[0]
    if total > BLOAT_LIMIT:
        out.append({"kind": "bloat", "ids": [],
                    "detail": f"{total} memories over the {BLOAT_LIMIT} soft cap"})
    return out
