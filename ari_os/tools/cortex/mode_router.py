"""Mode router — decide which retrieval posture (mode) to use.

Decides which retrieval posture (mode) a session should use based on
incoming signals: explicit skill name, current working directory, or
free-text prompt keywords. Also provides thrash-control policy for
weak-signal auto-switching.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

ZONE_RATIOS = {
    "default":   {"persona": 0.20, "episodic": 0.40, "semantic": 0.40},
    "focus":     {"persona": 0.15, "episodic": 0.55, "semantic": 0.30},
    "recall":    {"persona": 0.20, "episodic": 0.50, "semantic": 0.30},
    "synthesis": {"persona": 0.25, "episodic": 0.25, "semantic": 0.50},
    "deep":      {"persona": 0.30, "episodic": 0.20, "semantic": 0.50},
    "creative":  {"persona": 0.35, "episodic": 0.30, "semantic": 0.35},
    "visual":    {"persona": 0.20, "episodic": 0.40, "semantic": 0.40},
}


def zone_ratios_for(mode):
    return dict(ZONE_RATIOS.get(mode or "default", ZONE_RATIOS["default"]))

# Deterministic tie-break order (most decisive situation first).
_TIE_PRIORITY = ["focus", "visual", "recall", "synthesis", "deep", "creative"]


def classify_prompt(prompt, keywords):
    if not prompt:
        return None
    low = prompt.lower()
    hits = {mode: sum(1 for kw in kws if kw in low) for mode, kws in keywords.items()}
    matched = {m: c for m, c in hits.items() if c > 0}
    if not matched:
        return None
    top_count = max(matched.values())
    top = [m for m, c in matched.items() if c == top_count]
    if len(top) == 1:
        return top[0]
    for m in _TIE_PRIORITY:
        if m in top:
            return m
    return None


@dataclass
class Signals:
    skill: Optional[str] = None
    cwd: Optional[str] = None
    prompt: Optional[str] = None


@dataclass
class Decision:
    mode: str
    reason: str
    strength: str  # "strong" | "weak" | "none"


def decide_mode(signals, current_mode, config):
    if signals.skill and signals.skill in config.skills:
        return Decision(config.skills[signals.skill], f"skill:{signals.skill}", "strong")
    if signals.cwd:
        for sub, mode in config.cwd_substrings.items():
            if sub in signals.cwd:
                return Decision(mode, f"cwd:{sub}", "strong")
    if signals.prompt:
        m = classify_prompt(signals.prompt, config.keywords)
        if m:
            return Decision(m, f"prompt:{m}", "weak")
    return Decision(current_mode, "no-signal", "none")


@dataclass
class ThrashPolicy:
    weak_streak_required: int = 2
    cooldown_seconds: int = 90


_CONSENT_PHRASES = ("go global", "widen")
_WIDEN_KEYWORD_SETS = ("global", "synthesis")


@dataclass
class PostureDecision:
    posture: str  # "tunnel" | "global"
    widen_signal: bool = False
    widen_reason: str = ""


def classify_posture(
    prompt,
    keywords,
    *,
    posture_override=None,
):
    """Classify posture from prompt text: tunnel (default) or global (consent-gated).

    posture_override from CLI flag wins unconditionally.
    Consent phrases in prompt text force global.
    Global/synthesis keywords trigger a widen signal but stay tunneled.
    """
    if posture_override in ("tunnel", "global"):
        return PostureDecision(posture=posture_override)

    if not prompt:
        return PostureDecision(posture="tunnel")

    low = prompt.lower()
    for phrase in _CONSENT_PHRASES:
        if phrase in low:
            return PostureDecision(posture="global")

    for kw_set in _WIDEN_KEYWORD_SETS:
        kws = keywords.get(kw_set, [])
        for kw in kws:
            if kw in low:
                return PostureDecision(
                    posture="tunnel",
                    widen_signal=True,
                    widen_reason=f"keyword:{kw}",
                )

    return PostureDecision(posture="tunnel")


def should_switch(decision, current_mode, sess, now, policy, manual_lock_until=0):
    """Pure: returns (switch: bool, new_sess: dict). Strong bypasses cooldown."""
    sess = dict(sess)
    if manual_lock_until and now < manual_lock_until:
        return False, sess
    if decision.strength == "none" or decision.mode == current_mode:
        sess["weak_target"] = None
        sess["weak_streak"] = 0
        return False, sess
    if decision.strength == "strong":
        sess.update(weak_target=None, weak_streak=0, last_switch_at=now,
                    last_auto_mode=decision.mode)
        return True, sess
    # weak
    streak = int(sess.get("weak_streak", 0)) + 1 if sess.get("weak_target") == decision.mode else 1
    sess["weak_target"] = decision.mode
    sess["weak_streak"] = streak
    cooled = now - int(sess.get("last_switch_at", 0)) >= policy.cooldown_seconds
    if streak >= policy.weak_streak_required and cooled:
        sess.update(weak_target=None, weak_streak=0, last_switch_at=now,
                    last_auto_mode=decision.mode)
        return True, sess
    return False, sess
