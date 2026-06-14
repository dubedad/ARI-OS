"""SessionStart pre-fetch — top-K chunks past-retrieved at the current cwd."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from ari_os.tools.cortex.db import connect as _connect


def past_chunks_for_cwd(db_path: Path, cwd: str, limit: int = 3) -> list[tuple[int, int]]:
    """Return [(chunk_id, hit_count), ...] sorted desc; chunks retrieved at this cwd before."""
    if not cwd:
        return []
    con = _connect(db_path)
    try:
        rows = con.execute(
            "SELECT chunk_ids FROM retrieval_event WHERE cwd=?",
            (cwd,),
        ).fetchall()
    finally:
        con.close()
    counter: Counter[int] = Counter()
    for (raw,) in rows:
        try:
            ids = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if not isinstance(ids, list):
            continue
        for cid in ids:
            if isinstance(cid, int):
                counter[cid] += 1
    return counter.most_common(limit)


def prefetch_for_cwd(db_path: Path, cwd: str, limit: int = 3) -> str:
    """Return a markdown block of top-K past-co-retrieved chunks; empty string if none."""
    ranked = past_chunks_for_cwd(db_path, cwd, limit=limit)
    if not ranked:
        return ""
    ids_csv = ",".join(str(c) for c, _ in ranked)
    con = _connect(db_path)
    try:
        rows = con.execute(
            f"SELECT id, region, text FROM chunk WHERE id IN ({ids_csv})"
        ).fetchall()
    finally:
        con.close()
    by_id = {int(r[0]): (r[1], r[2]) for r in rows}
    lines = [f"## Brain — workspace pre-fetch (`{cwd}`)", ""]
    for cid, hits in ranked:
        if cid not in by_id:
            continue
        region, text = by_id[cid]
        snippet = text.replace("\n", " ")[:240]
        lines.append(f"- **chunk_id {cid}** (`{region}`, hits={hits}): {snippet}")
    return "\n".join(lines) + "\n"
