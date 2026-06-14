"""Neutral council salience seed and loader tests."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ari_os.tools.cortex import council_salience


REGIONS = (
    "wernicke",
    "broca",
    "occipital",
    "parietal",
    "hippocampus",
    "vmpfc",
    "frontoparietal",
)
TASK_TYPES = ("build", "voice", "ideate", "reason", "research", "visual")


def test_load_artifact_missing_or_invalid_is_none(tmp_path: Path):
    assert council_salience.load_artifact(tmp_path / "missing.json") is None

    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert council_salience.load_artifact(bad) is None

    bad.write_text(json.dumps({"table": {}}))
    assert council_salience.load_artifact(bad) is None


def test_build_v1_normalizes_by_surface_row_mean():
    source = {
        "version": 1,
        "aggregate": {
            "broca": 2.0,
            "wernicke": 1.0,
            "frontoparietal": 1.0,
            "vmpfc": 1.0,
        },
        "table": {
            "build": {
                "broca": 3.0,
                "wernicke": 1.5,
                "frontoparietal": 1.5,
                "vmpfc": 0.2,
            },
        },
    }

    art = council_salience.build_v1(source)

    assert art["row_mean_w"]["__all__"] == pytest.approx(1.3333)
    assert art["aggregate"]["broca"] == pytest.approx(1.5)
    assert art["table"]["build"]["broca"] == pytest.approx(1.5)
    assert art["table"]["build"]["vmpfc"] == pytest.approx(0.1)


def test_salience_for_blends_and_falls_back_to_aggregate_below_conf_floor():
    artifact = {
        "version": 1,
        "row_mean_w": {"__all__": 1.0, "build": 1.0},
        "aggregate": {"broca": 1.0, "wernicke": 1.0, "vmpfc": 1.0},
        "table": {"build": {"broca": 1.5, "wernicke": 0.5, "vmpfc": 1.0}},
    }

    blended = council_salience.salience_for("build", 0.75, artifact)
    assert blended["broca"] == pytest.approx(0.75 * 1.5 + 0.25 * 1.0)
    assert blended["wernicke"] == pytest.approx(0.75 * 0.5 + 0.25 * 1.0)

    aggregate = council_salience.salience_for(None, None, artifact)
    assert council_salience.salience_for("build", 0.2, artifact) == aggregate
    assert council_salience.salience_for("unknown", 0.9, artifact) == aggregate


def test_shipped_neutral_seed_loads_and_has_no_user_calibrated_rows():
    artifact = council_salience.load_artifact()

    assert artifact is not None
    assert artifact["neutral"] is True
    assert artifact["provenance"]["kind"] == "neutral-public-seed"
    assert artifact["row_mean_w"] == {"__all__": 1.0}
    assert artifact["table"] == {}
    assert set(artifact["aggregate"]) == set(REGIONS)
    assert all(value == 1.0 for value in artifact["aggregate"].values())


def test_shipped_neutral_seed_contains_no_non_uniform_salience_values():
    text = council_salience.DEFAULT_ARTIFACT_PATH.read_text()
    artifact = json.loads(text)

    assert "220" not in text
    assert artifact.get("built_from") == {"artifact": "neutral-defaults"}
    assert artifact["policy"]["conf_floor"] == council_salience.CONF_FLOOR

    for row in [artifact["aggregate"], *artifact["table"].values()]:
        assert set(row) <= set(REGIONS)
        assert set(row.values()) <= {1.0}


def test_default_neutral_salience_uses_aggregate_for_any_task():
    artifact = council_salience.load_artifact()

    assert artifact is not None
    for task in TASK_TYPES:
        assert council_salience.salience_for(task, 0.99, artifact) == artifact["aggregate"]
