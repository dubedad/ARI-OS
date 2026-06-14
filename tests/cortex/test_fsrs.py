"""P6 FSRS scheduler and sweep tests."""
from __future__ import annotations

from pathlib import Path

import pytest

from ari_os.tools.cortex import db
from ari_os.tools.cortex.fsrs.scheduler import DAY, initial_card, review
from ari_os.tools.cortex.fsrs.sweep import (
    due_chunks,
    fsrs_boost_for_chunks,
    load_state,
    record_batch_review,
    record_review,
)


@pytest.fixture
def brain_db(tmp_path: Path) -> Path:
    path = tmp_path / "brain.db"
    db.init_db(path)
    return path


def insert_chunk(db_path: Path, *, text: str = "memory", path: str = "memory.md") -> int:
    con = db.connect(db_path)
    try:
        con.execute(
            "INSERT OR IGNORE INTO source(path, layer, workspace, mtime, sha256, last_indexed_at) "
            "VALUES (?, 'semantic', NULL, 0, 'x', 0)",
            (path,),
        )
        source_id = con.execute("SELECT id FROM source WHERE path=?", (path,)).fetchone()[0]
        cur = con.execute(
            "INSERT INTO chunk(source_id, ordinal, text, line_start, line_end, region, "
            "importance, distillation_tier) VALUES (?, 0, ?, 1, 2, 'frontoparietal', 0.5, 0)",
            (source_id, text),
        )
        return cur.lastrowid
    finally:
        con.close()


def test_review_updates_stability_and_difficulty_by_rating():
    now = 1_700_000_000
    card = initial_card(now=now)

    good = review(card, rating=3, now=now + DAY)
    easy = review(card, rating=4, now=now + DAY)
    lapse = review(card, rating=1, now=now + DAY)

    assert good.reps == 1
    assert good.stability > card.stability
    assert good.difficulty == pytest.approx(card.difficulty)
    assert easy.stability > good.stability
    assert easy.difficulty < card.difficulty
    assert lapse.stability < card.stability
    assert lapse.difficulty > card.difficulty
    assert lapse.lapses == 1


def test_record_batch_review_upserts_fsrs_state(brain_db):
    now = 1_700_000_000
    first = insert_chunk(brain_db, text="alpha", path="alpha.md")
    second = insert_chunk(brain_db, text="bravo", path="bravo.md")

    assert record_batch_review(brain_db, chunk_ids=[first, second], rating=3, now=now) == 2
    assert load_state(brain_db, chunk_id=first).reps == 1
    assert load_state(brain_db, chunk_id=second).reps == 1

    updated = record_review(brain_db, chunk_id=first, rating=4, now=now + (2 * DAY))

    assert updated.reps == 2
    assert load_state(brain_db, chunk_id=first).reps == 2
    assert load_state(brain_db, chunk_id=second).reps == 1


def test_fsrs_boost_for_chunks_overdue_not_due_and_cold_start(brain_db):
    now = 1_700_000_000
    overdue = insert_chunk(brain_db, text="overdue", path="overdue.md")
    not_due = insert_chunk(brain_db, text="not due", path="not-due.md")
    cold = insert_chunk(brain_db, text="cold", path="cold.md")

    record_review(brain_db, chunk_id=overdue, rating=3, now=now - (3 * DAY))
    record_review(brain_db, chunk_id=not_due, rating=3, now=now)

    boosts = fsrs_boost_for_chunks(brain_db, chunk_ids=[overdue, not_due, cold], now=now)

    assert boosts[overdue] > 1.0
    assert boosts[not_due] < 1.0
    assert boosts[cold] == 1.0


def test_due_chunks_selects_next_review_at_at_or_before_now(brain_db):
    now = 1_700_000_000
    older_due = insert_chunk(brain_db, text="older due", path="older.md")
    due = insert_chunk(brain_db, text="due", path="due.md")
    later = insert_chunk(brain_db, text="later", path="later.md")

    record_review(brain_db, chunk_id=older_due, rating=1, now=now - (3 * DAY))
    record_review(brain_db, chunk_id=due, rating=1, now=now - DAY)
    record_review(brain_db, chunk_id=later, rating=3, now=now)

    assert due_chunks(brain_db, now=now, limit=10) == [older_due, due]
    assert due_chunks(brain_db, now=now, limit=1) == [older_due]


def test_fsrs_boost_is_neutral_when_disabled(brain_db, monkeypatch):
    now = 1_700_000_000
    chunk_id = insert_chunk(brain_db, text="disabled", path="disabled.md")
    record_review(brain_db, chunk_id=chunk_id, rating=3, now=now - (3 * DAY))
    monkeypatch.setenv("ARI_OS_FSRS", "0")

    assert fsrs_boost_for_chunks(brain_db, chunk_ids=[chunk_id], now=now) == {chunk_id: 1.0}
