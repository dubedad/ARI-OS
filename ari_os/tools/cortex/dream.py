"""Dream orchestration for ARI-OS Cortex consolidation.

The dream pass coordinates the local, non-destructive consolidation loop:
run tiered distillation when an LLM is supplied, write tier-3 summaries into
the public ARI-OS dream queue, decay cold chunk importance, and leave a mode
hint for the next retrieval/session path.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import time

from ari_os.tools.cortex import config, distill
from ari_os.tools.cortex.db import connect
from ari_os.tools.cortex.llm.base import BrainLLM

COLD_THRESHOLD_SECS: int = 7 * 24 * 3600
IMPORTANCE_DECAY: float = 0.97
LOW_TIER_THRESHOLD: int = 5


@dataclass(frozen=True)
class DreamResult:
    """Summary of one dream orchestration pass."""

    session_digests: int
    daily_syntheses: int
    weekly_arcs: int
    dream_queue_items: int
    mode: str


def promote_tier3_to_dream_queue(
    db_path: Path,
    output_dir: Path | None = None,
) -> int:
    """Write tier-3 chunks into ``<state_home>/dream/queue/<date>.md``.

    The queue is idempotent per UTC day. Existing queue files are left intact,
    and source chunks are never modified or deleted.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    dream_dir = _dream_root(output_dir) / "queue"
    dream_dir.mkdir(parents=True, exist_ok=True)
    target = dream_dir / f"{today}.md"
    if target.exists():
        return 0

    con = connect(db_path)
    try:
        rows = con.execute(
            """SELECT id, text
                 FROM chunk
                WHERE distillation_tier = 3
             ORDER BY importance DESC, id ASC"""
        ).fetchall()
    finally:
        con.close()

    if not rows:
        return 0

    lines = [f"# Dream Queue - {today}", ""]
    for chunk_id, text in rows:
        lines.append(f"## Chunk {chunk_id}")
        lines.append("")
        lines.append(str(text))
        lines.append("")
    target.write_text("\n".join(lines).rstrip() + "\n")
    return len(rows)


def decay_pass(db_path: Path) -> int:
    """Decay cold chunk importance without deleting or rewriting memories.

    Cold means a chunk has been retrieved before, but not within the current
    threshold window. Never-retrieved chunks are left untouched.
    """
    now = int(time.time())
    cold_cutoff = now - COLD_THRESHOLD_SECS

    con = connect(db_path)
    try:
        con.execute("BEGIN IMMEDIATE")
        cur = con.execute(
            """UPDATE chunk
                  SET importance = MAX(0.0, importance * ?)
                WHERE last_retrieved_at IS NOT NULL
                  AND last_retrieved_at < ?""",
            (IMPORTANCE_DECAY, cold_cutoff),
        )
        con.execute("COMMIT")
        return int(cur.rowcount or 0)
    except Exception:
        con.execute("ROLLBACK")
        raise
    finally:
        con.close()


def suggest_mode(
    db_path: Path,
    mode_dir: Path | None = None,
) -> str:
    """Write a simple mode hint based on low-tier consolidation pressure."""
    target_dir = Path(mode_dir) if mode_dir is not None else config.state_home() / "modes"

    con = connect(db_path)
    try:
        low_tier = con.execute(
            "SELECT COUNT(*) FROM chunk WHERE distillation_tier IN (0, 1)"
        ).fetchone()[0]
        high_tier = con.execute(
            "SELECT COUNT(*) FROM chunk WHERE distillation_tier IN (2, 3)"
        ).fetchone()[0]
    finally:
        con.close()

    if low_tier >= LOW_TIER_THRESHOLD and low_tier > high_tier:
        mode = "synthesis"
    else:
        mode = "default"

    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "suggested_mode").write_text(mode + "\n")
    return mode


def run_dream(
    db_path: Path,
    *,
    llm: BrainLLM | None = None,
    output_dir: Path | None = None,
    mode_dir: Path | None = None,
) -> DreamResult:
    """Run one local dream pass.

    Passing ``llm=None`` is the public off gate: distillation exits with zero
    work and no backend resolution. Decay, queue promotion, and mode hints still
    run because they are deterministic SQLite/file operations.
    """
    session_digests = distill.distill_session_to_digest(
        db_path, output_dir=output_dir, llm=llm
    )
    daily_syntheses = distill.distill_daily_synthesis(
        db_path, output_dir=output_dir, llm=llm
    )
    weekly_arcs = distill.distill_weekly_arc(db_path, output_dir=output_dir, llm=llm)

    dream_queue_items = promote_tier3_to_dream_queue(db_path, output_dir=output_dir)
    decay_pass(db_path)
    resolved_mode_dir = Path(mode_dir) if mode_dir is not None else _dream_root(output_dir) / "modes"
    mode = suggest_mode(db_path, mode_dir=resolved_mode_dir)

    return DreamResult(
        session_digests=session_digests,
        daily_syntheses=daily_syntheses,
        weekly_arcs=weekly_arcs,
        dream_queue_items=dream_queue_items,
        mode=mode,
    )


def _dream_root(output_dir: Path | None) -> Path:
    base = Path(output_dir) if output_dir is not None else config.state_home()
    return base / "dream"


# P5: surprising-connections (KG)


__all__ = [
    "COLD_THRESHOLD_SECS",
    "DreamResult",
    "IMPORTANCE_DECAY",
    "LOW_TIER_THRESHOLD",
    "decay_pass",
    "promote_tier3_to_dream_queue",
    "run_dream",
    "suggest_mode",
]
