"""Persist and query FSRS state in the Cortex SQLite database."""
from __future__ import annotations

from pathlib import Path

from ari_os.tools.cortex import config
from ari_os.tools.cortex.db import connect
from ari_os.tools.cortex.fsrs.scheduler import DAY, FSRSCard, initial_card, review


def load_state(db_path: Path, *, chunk_id: int) -> FSRSCard | None:
    con = connect(db_path)
    try:
        row = con.execute(
            """SELECT stability, difficulty, retrievability, reps, lapses,
                      last_review_at, next_review_at
                 FROM fsrs_state WHERE chunk_id = ?""",
            (chunk_id,),
        ).fetchone()
    finally:
        con.close()

    if row is None:
        return None
    return FSRSCard(
        stability=row[0],
        difficulty=row[1],
        retrievability=row[2],
        reps=row[3],
        lapses=row[4],
        last_review_at=row[5],
        next_review_at=row[6],
    )


def _save_state(db_path: Path, chunk_id: int, card: FSRSCard) -> None:
    con = connect(db_path)
    try:
        con.execute(
            """INSERT INTO fsrs_state(chunk_id, stability, difficulty, retrievability,
                                       reps, lapses, last_review_at, next_review_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(chunk_id) DO UPDATE SET
                 stability      = excluded.stability,
                 difficulty     = excluded.difficulty,
                 retrievability = excluded.retrievability,
                 reps           = excluded.reps,
                 lapses         = excluded.lapses,
                 last_review_at = excluded.last_review_at,
                 next_review_at = excluded.next_review_at""",
            (
                chunk_id,
                card.stability,
                card.difficulty,
                card.retrievability,
                card.reps,
                card.lapses,
                card.last_review_at,
                card.next_review_at,
            ),
        )
    finally:
        con.close()


def record_review(db_path: Path, *, chunk_id: int, rating: int, now: int) -> FSRSCard:
    state = load_state(db_path, chunk_id=chunk_id)
    card = initial_card(now=now) if state is None else state
    new_card = review(card, rating=rating, now=now)
    _save_state(db_path, chunk_id, new_card)
    return new_card


def record_batch_review(db_path: Path, *, chunk_ids: list[int], rating: int, now: int) -> int:
    """Record one review for every chunk id and return the updated count."""
    for chunk_id in chunk_ids:
        record_review(db_path, chunk_id=chunk_id, rating=rating, now=now)
    return len(chunk_ids)


def due_chunks(db_path: Path, *, now: int, limit: int = 1000) -> list[int]:
    con = connect(db_path)
    try:
        rows = con.execute(
            """SELECT chunk_id
                 FROM fsrs_state
                WHERE next_review_at <= ?
                ORDER BY next_review_at
                LIMIT ?""",
            (now, limit),
        ).fetchall()
    finally:
        con.close()
    return [row[0] for row in rows]


def fsrs_boost_for_chunks(db_path: Path, *, chunk_ids: list[int], now: int) -> dict[int, float]:
    """Return a rerank multiplier per chunk.

    Cold-start chunks are neutral. Overdue chunks receive a capped boost above
    one. Chunks not yet due are softly downweighted below one.
    """
    if not chunk_ids:
        return {}
    if not config.fsrs_enabled():
        return {chunk_id: 1.0 for chunk_id in chunk_ids}

    placeholders = ",".join("?" * len(chunk_ids))
    con = connect(db_path)
    try:
        rows = con.execute(
            f"""SELECT chunk_id, next_review_at, last_review_at
                  FROM fsrs_state
                 WHERE chunk_id IN ({placeholders})""",
            chunk_ids,
        ).fetchall()
    finally:
        con.close()

    state_map = {row[0]: (row[1], row[2]) for row in rows}
    out: dict[int, float] = {}
    for chunk_id in chunk_ids:
        if chunk_id not in state_map:
            out[chunk_id] = 1.0
            continue

        next_at, last_at = state_map[chunk_id]
        if now >= next_at:
            overdue_days = (now - next_at) / DAY
            out[chunk_id] = 1.0 + min(0.5, 0.05 * overdue_days)
            continue

        time_to_due = max(1, next_at - now)
        interval = max(1, next_at - last_at)
        out[chunk_id] = max(0.7, 1.0 - 0.3 * (time_to_due / interval))
    return out
