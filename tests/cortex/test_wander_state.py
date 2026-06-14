import random

from ari_os.tools.cortex.wander_state import (
    load_state,
    save_state,
    surface_decision,
    tick,
)


def test_tick_does_not_fire_before_threshold():
    rng = random.Random(0)
    state = {}

    fired, sess = tick(state, "s1", cadence_min=5, cadence_max=5, rng=rng, now=100)

    assert fired is False
    assert sess["count"] == 1
    assert sess["threshold"] == 5
    assert sess["updated_at"] == 100


def test_tick_fires_at_threshold_and_resets_with_bounded_cadence():
    rng = random.Random(0)
    state = {"s1": {"count": 4, "threshold": 5}}

    fired, sess = tick(state, "s1", cadence_min=5, cadence_max=10, rng=rng, now=200)

    assert fired is True
    assert sess["count"] == 0
    assert 5 <= sess["threshold"] <= 10
    assert sess["updated_at"] == 200


def test_state_round_trips(tmp_path):
    state = {"s1": {"count": 2, "threshold": 7, "recent_ids": [1, 2]}}

    save_state(tmp_path, state)

    assert load_state(tmp_path) == state


def test_load_missing_returns_empty(tmp_path):
    assert load_state(tmp_path) == {}


def test_surface_decision_only_fires_in_tunnel_posture():
    assert surface_decision(True, "tunnel") is True
    assert surface_decision(True, "global") is False
    assert surface_decision(True, "focus") is False
    assert surface_decision(False, "tunnel") is False
