"""Neutral council salience artifact loader.

The public seed is deliberately uniform. Real per-task salience can be rebuilt
locally by users, but the package ships no calibrated user rows.
"""
from __future__ import annotations

import json
from pathlib import Path

DEFAULT_ARTIFACT_PATH = (
    Path(__file__).resolve().parent.parent / "seeds" / "council_salience.neutral.json"
)
LATENT_FLOORS_WEIGHT = {"vmpfc": 1.0}
SURFACE = ("frontoparietal", "wernicke", "broca", "occipital", "parietal", "hippocampus")
CONF_FLOOR = 0.35
AGGREGATE_ROW = "__all__"


def load_artifact(path: Path | None = None) -> dict | None:
    """Load the salience artifact; return None when missing or invalid."""
    p = path if path is not None else DEFAULT_ARTIFACT_PATH
    try:
        artifact = json.loads(Path(p).read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(artifact, dict):
        return None
    if not all(key in artifact for key in ("table", "aggregate", "row_mean_w")):
        return None
    if not isinstance(artifact["table"], dict) or not isinstance(artifact["aggregate"], dict):
        return None
    if not isinstance(artifact["row_mean_w"], dict):
        return None
    return artifact


def _floored_row(row: dict, mean_w: float) -> dict[str, float]:
    out = {region: float(value) for region, value in row.items()}
    if mean_w > 0:
        for region, floor_w in LATENT_FLOORS_WEIGHT.items():
            if region in out:
                out[region] = max(out[region], floor_w / mean_w)
    return out


def salience_for(
    task_type: str | None,
    confidence: float | None,
    artifact: dict,
) -> dict[str, float] | None:
    """Return the effective salience prior for a classified task."""
    means = artifact.get("row_mean_w", {})
    aggregate_raw = artifact.get("aggregate") or {}
    if not aggregate_raw:
        return None
    aggregate = _floored_row(aggregate_raw, float(means.get(AGGREGATE_ROW, 0.0) or 0.0))

    row_raw = artifact.get("table", {}).get(task_type) if task_type else None
    if not row_raw or confidence is None or confidence < CONF_FLOOR:
        return aggregate

    row = _floored_row(row_raw, float(means.get(task_type, 0.0) or 0.0))
    conf = min(1.0, max(0.0, float(confidence)))
    blended: dict[str, float] = {}
    for region in set(row) | set(aggregate):
        task_value = row.get(region, aggregate.get(region, 1.0))
        aggregate_value = aggregate.get(region, task_value)
        blended[region] = conf * task_value + (1.0 - conf) * aggregate_value
    return blended


def build_v1(source: dict) -> dict:
    """Build a v1 salience artifact from a task-region weight artifact."""
    def _normalize(row: dict) -> tuple[dict[str, float], float] | None:
        surface_weights = [float(row[region]) for region in SURFACE if region in row]
        if not surface_weights:
            return None
        mean_w = sum(surface_weights) / len(surface_weights)
        if mean_w <= 0:
            return None
        return {region: round(float(value) / mean_w, 4) for region, value in row.items()}, round(mean_w, 4)

    aggregate_normalized = _normalize(source.get("aggregate") or {})
    if aggregate_normalized is None:
        raise ValueError("source artifact has no usable aggregate row")

    aggregate, aggregate_mean = aggregate_normalized
    table: dict[str, dict[str, float]] = {}
    row_mean_w: dict[str, float] = {AGGREGATE_ROW: aggregate_mean}
    for task, row in sorted((source.get("table") or {}).items()):
        normalized = _normalize(row)
        if normalized is None:
            continue
        table[task], row_mean_w[task] = normalized

    return {
        "version": 1,
        "neutral": bool(source.get("neutral", False)),
        "built_from": {
            "artifact": "task_region_weights",
            "version": source.get("version"),
        },
        "policy": {
            "normalizer": "surface_row_mean",
            "surface": list(SURFACE),
            "latent_floors_weight": dict(LATENT_FLOORS_WEIGHT),
            "conf_floor": CONF_FLOOR,
        },
        "row_mean_w": row_mean_w,
        "aggregate": aggregate,
        "table": table,
        "provenance": source.get("provenance"),
    }
