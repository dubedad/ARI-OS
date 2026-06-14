"""ar.t6 modes tests — modes/ + mode_router + mode_state.

Verifies the public, scrubbed port of the heavy brain's mode spine:

- The mode YAMLs under ``ari_os/tools/cortex/modes/`` enumerate exactly the
  full public set: default, creative, deep, recall, synthesis, focus,
  visual, dyslexic, adhd — no private/legacy mode names ship.
- The default loader picks up that exact set; each shipped mode YAML
  validates against ``loader.validate_mode`` (required keys + optional
  ``dn_strength``/``dn_sigma`` numeric constraints).
- ``mode_router.Zone_ratios_for`` returns the canonical zone mix per
  posture; default and recall are not equal (smoke check on the table).
- ``mode_router.classify_prompt`` is deterministic: single group wins,
  higher counts beat tie-priority, no match returns None.
- ``mode_router.decide_mode`` honours the structural > inferred ordering
  (skill > cwd > prompt) and stamps the reason string.
- ``mode_state`` round-trips state JSON and per-cwd manual locks to
  ``home_dir``.
- CODE RED scrub bible: committed production code contains zero banned
  tokens.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from ari_os.tools.cortex import mode_router, mode_routing, mode_state
from ari_os.tools.cortex.modes import loader as modes_loader


# ---------- paths ----------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
MODES_DIR = REPO_ROOT / "ari_os" / "tools" / "cortex" / "modes"

EXPECTED_MODES = tuple(sorted((
    "default", "creative", "deep", "recall", "synthesis",
    "focus", "visual", "dyslexic", "adhd", "wide",
)))


# ---------- mode yaml inventory -------------------------------------------

def test_listing_modes_returns_full_set():
    assert tuple(modes_loader.list_modes(MODES_DIR)) == EXPECTED_MODES


@pytest.mark.parametrize("name", list(EXPECTED_MODES))
def test_each_shipped_mode_validates(name):
    data = modes_loader.load_mode(name, modes_dir=MODES_DIR)
    assert data["name"] == name
    assert "region_weights" in data
    assert "tier_weights" in data
    assert "dn_strength" in data
    assert "dn_sigma" in data
    # Re-validate through the public validator to make sure nothing was
    # smuggled in.
    modes_loader.validate_mode(data)


# ---------- explicit --mode select ---------------------------------------

def test_explicit_mode_loads_by_name():
    focus = modes_loader.load_mode("focus", modes_dir=MODES_DIR)
    assert focus["name"] == "focus"
    # focus should be a narrow, low-noise retrieval posture
    assert focus["k_vector"] <= 12
    assert focus["kg_expand"] is False


def test_default_mode_is_default():
    """A bare call to ``active_mode_for_cwd`` falls back to 'default'."""
    assert modes_loader.active_mode_for_cwd("/no/such/cwd", home_dir=MODES_DIR) == "default"


def test_set_active_mode_round_trips(tmp_path):
    cwd = "/some/cwd"
    modes_loader.set_active_mode(cwd, "creative", home_dir=tmp_path)
    assert modes_loader.active_mode_for_cwd(cwd, home_dir=tmp_path) == "creative"


def test_set_active_mode_rejects_unknown(tmp_path):
    with pytest.raises(ValueError):
        modes_loader.set_active_mode("/x", "nope-not-a-mode", home_dir=tmp_path)


# ---------- mode_router zone ratios --------------------------------------

def test_zone_ratios_default_keys():
    z = mode_router.zone_ratios_for("default")
    assert set(z) == {"persona", "episodic", "semantic"}
    # published baseline ratios
    assert z == {"persona": 0.20, "episodic": 0.40, "semantic": 0.40}


def test_zone_ratios_recall_differs_from_default():
    assert mode_router.zone_ratios_for("recall") != mode_router.zone_ratios_for("default")


def test_zone_ratios_falls_back_to_default():
    assert mode_router.zone_ratios_for(None) == mode_router.zone_ratios_for("default")
    assert mode_router.zone_ratios_for("nope") == mode_router.zone_ratios_for("default")


# ---------- mode_router classify_prompt ----------------------------------

KW = {
    "recall": ["what did i", "last week"],
    "focus": ["fix", "bug"],
    "visual": ["palette", "lens"],
    "synthesis": ["connect", "bridge"],
    "deep": ["distill"],
    "creative": ["brainstorm"],
}


def test_classify_single_match():
    assert mode_router.classify_prompt("can you fix this", KW) == "focus"


def test_classify_no_match_returns_none():
    assert mode_router.classify_prompt("the weather is nice", KW) is None
    assert mode_router.classify_prompt(None, KW) is None
    assert mode_router.classify_prompt("", KW) is None


def test_classify_tie_priority_focus_over_visual():
    assert mode_router.classify_prompt("fix the palette", KW) == "focus"


def test_classify_higher_count_wins():
    assert mode_router.classify_prompt("lens and palette but also fix", KW) == "visual"


# ---------- mode_router decide_mode --------------------------------------

CFG = mode_routing.RoutingConfig(
    skills={"brainstorming": "creative", "systematic-debugging": "focus"},
    cwd_substrings={"LENS_": "visual"},
    keywords={"recall": ["what did i"], "focus": ["fix"]},
)


def test_decide_skill_is_strong():
    d = mode_router.decide_mode(mode_router.Signals(skill="brainstorming"), "default", CFG)
    assert (d.mode, d.strength) == ("creative", "strong")
    assert d.reason == "skill:brainstorming"


def test_decide_cwd_is_strong():
    d = mode_router.decide_mode(
        mode_router.Signals(cwd="/tmp/ws/x"), "default", CFG
    )
    assert (d.mode, d.strength) == ("visual", "strong")


def test_decide_structural_beats_inferred():
    d = mode_router.decide_mode(
        mode_router.Signals(skill="systematic-debugging", prompt="what did i write"),
        "default", CFG,
    )
    assert d.mode == "focus"


def test_decide_prompt_is_weak():
    d = mode_router.decide_mode(
        mode_router.Signals(prompt="fix this"), "default", CFG
    )
    assert (d.mode, d.strength) == ("focus", "weak")


def test_decide_no_signal_stays():
    d = mode_router.decide_mode(
        mode_router.Signals(prompt="hello there"), "synthesis", CFG
    )
    assert (d.mode, d.strength) == ("synthesis", "none")


# ---------- should_switch thrash policy ----------------------------------

P = mode_router.ThrashPolicy(weak_streak_required=2, cooldown_seconds=90)


def _strong(mode): return mode_router.Decision(mode, "skill:x", "strong")
def _weak(mode): return mode_router.Decision(mode, "prompt:x", "weak")


def test_strong_switches_now():
    sw, sess = mode_router.should_switch(_strong("focus"), "default", {}, now=1000, policy=P)
    assert sw is True
    assert sess["last_auto_mode"] == "focus"


def test_same_mode_is_noop():
    sw, _ = mode_router.should_switch(_strong("focus"), "focus", {}, now=1000, policy=P)
    assert sw is False


def test_none_strength_resets_streak():
    sw, sess = mode_router.should_switch(
        mode_router.Decision("focus", "no-signal", "none"), "default",
        {"weak_target": "focus", "weak_streak": 1}, now=1000, policy=P,
    )
    assert sw is False
    assert sess["weak_streak"] == 0


def test_weak_needs_two_in_a_row():
    sw1, sess1 = mode_router.should_switch(_weak("recall"), "default", {}, now=1000, policy=P)
    assert sw1 is False and sess1["weak_streak"] == 1
    sw2, _ = mode_router.should_switch(_weak("recall"), "default", sess1, now=1200, policy=P)
    assert sw2 is True


def test_weak_blocked_by_cooldown():
    sess = {"weak_target": "recall", "weak_streak": 1, "last_switch_at": 1000}
    sw, _ = mode_router.should_switch(_weak("recall"), "default", sess, now=1030, policy=P)
    assert sw is False


def test_manual_lock_blocks_strong():
    sw, _ = mode_router.should_switch(
        _strong("focus"), "default", {}, now=1000, policy=P,
        manual_lock_until=2000,
    )
    assert sw is False


# ---------- mode_state ----------------------------------------------------

def test_state_round_trips(tmp_path):
    mode_state.save_state(tmp_path, {"s": {"last_skill": "brainstorming"}})
    assert mode_state.load_state(tmp_path) == {"s": {"last_skill": "brainstorming"}}


def test_load_missing_state_returns_empty(tmp_path):
    assert mode_state.load_state(tmp_path) == {}


def test_manual_lock_round_trips(tmp_path):
    mode_state.write_manual_lock(tmp_path, "/some/cwd", 5000)
    assert mode_state.read_manual_lock(tmp_path, "/some/cwd") == 5000
    assert mode_state.read_manual_lock(tmp_path, "/other/cwd") == 0


# ---------- mode_routing config ------------------------------------------

def test_default_routing_config_loads():
    c = mode_routing.load_routing_config()
    assert c.skills["brainstorming"] == "creative"
    assert c.skills["systematic-debugging"] == "focus"
    assert c.cwd_substrings["LENS_"] == "visual"
    assert "fix" in c.keywords["focus"]


def test_user_override_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("ARI_OS_HOME", str(tmp_path))
    (tmp_path / "mode_routing.yaml").write_text(
        "structural:\n  skills:\n    brainstorming: deep\n  cwd_substrings: {}\n"
        "inferred:\n  keywords: {}\n"
    )
    c = mode_routing.load_routing_config()
    assert c.skills["brainstorming"] == "deep"


# ---------- CODE RED scrub bible -----------------------------------------

SCRUB_TOKENS = (
    "internal", "localbrain", "local-brain", "example",
    "node", "postgres", "MEMORY_STORE", "mmx_local", "cap_local",
)


def test_no_banned_tokens_in_modes_py():
    # Walk the cortex/ tree we just ported and ensure nothing snuck through.
    base = REPO_ROOT / "ari_os" / "tools" / "cortex"
    targets = [
        base / "mode_router.py",
        base / "mode_routing.py",
        base / "mode_routing.yaml",
        base / "mode_state.py",
    ]
    for path in targets:
        if not path.exists():
            continue
        text = path.read_text()
        for tok in SCRUB_TOKENS:
            assert tok not in text, f"{path} contains banned token {tok!r}"


def test_no_volume_paths_in_modes_py():
    base = REPO_ROOT / "ari_os" / "tools" / "cortex"
    targets = [
        base / "mode_router.py",
        base / "mode_routing.py",
        base / "mode_routing.yaml",
        base / "mode_state.py",
        base / "modes" / "loader.py",
    ]
    for path in targets:
        if not path.exists():
            continue
        text = path.read_text()
        assert "/tmp/" not in text, f"{path} contains /tmp/ path"
