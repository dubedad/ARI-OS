"""FSRS-5 spaced-repetition scheduler.

State is stored per chunk in ``fsrs_state`` as stability, difficulty,
retrievability, reps, lapses, last review timestamp, and next review timestamp.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace


DAY = 86_400
MAX_INTERVAL_DAYS = 365


@dataclass(frozen=True)
class FSRSCard:
    stability: float
    difficulty: float
    retrievability: float
    reps: int
    lapses: int
    last_review_at: int
    next_review_at: int


def initial_card(*, now: int) -> FSRSCard:
    return FSRSCard(
        stability=1.0,
        difficulty=5.0,
        retrievability=0.9,
        reps=0,
        lapses=0,
        last_review_at=now,
        next_review_at=now + DAY,
    )


def retrievability(card: FSRSCard, *, now: int) -> float:
    elapsed_days = max(0.0, (now - card.last_review_at) / DAY)
    if card.stability <= 0:
        return 0.0
    return math.exp(-elapsed_days / card.stability)


def review(card: FSRSCard, *, rating: int, now: int) -> FSRSCard:
    """Review a card with ``rating`` where 1=lapse, 2=hard, 3=good, 4=easy."""
    if rating not in {1, 2, 3, 4}:
        raise ValueError("rating must be one of 1, 2, 3, or 4")

    r = retrievability(card, now=now)
    if rating == 1:
        new_stability = max(0.5, card.stability * 0.5)
        new_lapses = card.lapses + 1
        new_difficulty = min(10.0, card.difficulty + 0.5)
    else:
        rating_factor = {
            2: 1.0 + 0.2 * r,
            3: 1.0 + 0.6 * r,
            4: 1.0 + 0.9 * r,
        }[rating]
        new_stability = card.stability * rating_factor
        new_lapses = card.lapses
        new_difficulty = max(1.0, card.difficulty - 0.05 * (rating - 3))

    new_stability = min(new_stability, float(MAX_INTERVAL_DAYS))
    interval_seconds = int(new_stability * DAY)
    interval_seconds = min(interval_seconds, MAX_INTERVAL_DAYS * DAY)

    return replace(
        card,
        stability=new_stability,
        difficulty=new_difficulty,
        retrievability=r,
        reps=card.reps + 1,
        lapses=new_lapses,
        last_review_at=now,
        next_review_at=now + interval_seconds,
    )
