"""Learned (task-type x region) base weights — Layer 1 of the two-layer model.

    final_weight(region) = learned_base[task_type][region] * posture_delta[mode][region]

Layer 1 (this module) is the LEARNED base profile per task-type. The shipped
artifact is the **neutral seed** (``task_region_weights.neutral.json``):
every region is weighted 1.0 for every task type and for the aggregate row.
A user calibrates locally by editing the artifact under their ARI_OS_HOME,
or by running the offline calibration harness from the design spec.

Layer 2 (posture) stays the hand-tuned ``modes/*.yaml`` tables; they are
applied as a DELTA relative to the static ``DEFAULT_REGION_WEIGHTS`` baseline.

Policy invariants:
- LATENT FLOORS: vmpfc floor is 1.0 in the neutral seed (the system may RAISE
  it on evidence, never lower it). A posture delta MAY still lower the final
  weight — that is the user's explicit hand-tuned choice, not a learned
  verdict.
- NO ARTIFACT, NO CHANGE: if ``task_region_weights.neutral.json`` is absent
  or invalid, every caller sees exactly the pre-learned static behavior.
- EXPLICIT WEIGHTS WIN: retrieve() callers that pass ``region_weights`` bypass
  this module entirely.
"""
from __future__ import annotations

import json
from pathlib import Path

DEFAULT_ARTIFACT_PATH = (
    Path(__file__).resolve().parent.parent / "seeds" / "task_region_weights.neutral.json"
)
LATENT_FLOORS = {"vmpfc": 1.0}


def load_artifact(path: Path | None = None) -> dict | None:
    """Load the weights artifact; None when missing or unreadable (fail-static)."""
    p = path if path is not None else DEFAULT_ARTIFACT_PATH
    try:
        artifact = json.loads(Path(p).read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(artifact, dict) or "table" not in artifact:
        return None
    return artifact


def base_weights(task_type: str | None, artifact: dict) -> dict[str, float]:
    """The learned base row for a task-type; aggregate row for unknown types.

    ``task_type=None`` requests the aggregate row explicitly — callers use it
    when the classifier abstained (tie / low confidence), because the predicted
    label is its fallback dumping ground and carries no per-task authority.

    Latent floors are clamped here so no artifact (hand-edited, stale, or built
    by a buggy table run) can ever ship a lowered vmpfc base.
    """
    row = artifact.get("table", {}).get(task_type) or artifact.get("aggregate") or {}
    out = {r: float(w) for r, w in row.items()}
    for region, floor in LATENT_FLOORS.items():
        if region in out and out[region] < floor:
            out[region] = floor
    return out


def compose_region_weights(
    task_type: str | None,
    mode_region_weights: dict[str, float] | None,
    *,
    path: Path | None = None,
) -> dict[str, float] | None:
    """learned_base[task] x posture_delta, or None when no artifact exists.

    ``task_type=None`` composes from the aggregate row (classifier abstained).

    Posture delta = mode_table / DEFAULT_REGION_WEIGHTS (the baseline the mode
    YAMLs were authored against), so a mode that mirrors the static defaults
    contributes deltas of exactly 1.0.
    """
    artifact = load_artifact(path)
    if artifact is None:
        return None
    base = base_weights(task_type, artifact)
    if not base:
        return None
    if not mode_region_weights:
        return base

    # DEFAULT_REGION_WEIGHTS is the hand-tuned baseline the mode YAMLs were
    # authored against (lives in retrieve.py in the full engine). For the
    # neutral seed (every region == 1.0) the delta is a no-op anyway; we keep
    # the contract symmetric with the source engine for forward compatibility.
    DEFAULT_REGION_WEIGHTS = {
        "wernicke": 1.0,
        "broca": 1.0,
        "occipital": 1.0,
        "parietal": 1.0,
        "hippocampus": 1.0,
        "vmpfc": 1.0,
        "frontoparietal": 1.0,
    }

    composed: dict[str, float] = {}
    for region in set(base) | set(mode_region_weights):
        b = base.get(region, 1.0)
        delta = mode_region_weights.get(region, 1.0) / DEFAULT_REGION_WEIGHTS.get(region, 1.0)
        composed[region] = b * delta
    return composed
