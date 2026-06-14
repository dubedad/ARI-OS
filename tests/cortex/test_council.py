"""Council allocation engine tests."""
from __future__ import annotations

import json
from pathlib import Path

from ari_os.tools.cortex.retrieve import RankedChunk


def mk(i: int, region: str, n_words: int = 20, *, word: str | None = None) -> RankedChunk:
    token = word or f"tok{i}"
    return RankedChunk(
        chunk_id=i,
        distance=0.1,
        region=region,
        tier=0,
        importance=0.5,
        retrieved_count=0,
        text=" ".join(f"{token}{j}" for j in range(n_words)),
        path=f"p{i}.md",
        line_start=1,
        line_end=2,
        workspace=None,
        source="vec",
    )


def test_enabled_defaults_off_and_reads_runtime_config(tmp_path: Path, monkeypatch):
    from ari_os.tools.cortex import council

    monkeypatch.setenv("ARI_OS_HOME", str(tmp_path))
    assert council.enabled() is False

    (tmp_path / "config.json").write_text(json.dumps({"cortex": {"council": True}}))
    assert council.enabled() is True


def test_ignition_gates_out_thin_low_salience_region():
    from ari_os.tools.cortex import council

    ranked = [mk(i, "broca") for i in range(6)] + [mk(10, "parietal")]
    packed, tele = council.allocate(
        ranked,
        200,
        salience={"broca": 1.0, "parietal": 0.5},
    )

    assert tele["regions"]["parietal"]["gated_out"] is True
    assert all(c.region != "parietal" for c in packed)
    assert tele["regions"]["broca"]["seats"] > 0


def test_caps_bound_a_region_share():
    from ari_os.tools.cortex import council

    ranked = [mk(i, "broca") for i in range(8)] + [
        mk(100 + i, "wernicke") for i in range(8)
    ]
    _, tele = council.allocate(
        ranked,
        300,
        salience={"broca": 1.0, "wernicke": 1.0},
        params={"caps": {"broca": 0.1}},
    )

    assert tele["regions"]["broca"]["tokens"] < tele["regions"]["wernicke"]["tokens"]


def test_vmpfc_protected_seat_fires_when_gated_out():
    from ari_os.tools.cortex import council

    ranked = [mk(i, "broca") for i in range(8)] + [mk(99, "vmpfc")]
    packed, tele = council.allocate(
        ranked,
        200,
        salience={"broca": 1.0, "vmpfc": 0.05},
    )

    assert tele["regions"]["vmpfc"]["gated_out"] is True
    assert tele["protected_seat"] is True
    assert any(c.region == "vmpfc" for c in packed)


def test_allocation_is_deterministic_and_salience_changes_composition():
    from ari_os.tools.cortex import council

    def build():
        return [mk(i, "broca") for i in range(10)] + [
            mk(50 + i, "wernicke") for i in range(5)
        ]

    budget = sum(int(len(c.text.split()) * 1.3) for c in build()[:4])
    static_ids = {c.chunk_id for c in build()[:4]}

    packed_1, _ = council.allocate(
        build(),
        budget,
        salience={"broca": 1.0, "wernicke": 2.0},
    )
    packed_2, _ = council.allocate(
        build(),
        budget,
        salience={"broca": 1.0, "wernicke": 2.0},
    )

    assert [c.chunk_id for c in packed_1] == [c.chunk_id for c in packed_2]
    assert {c.chunk_id for c in packed_1} != static_ids
    assert any(c.region == "wernicke" for c in packed_1)


def test_epsilon_intrusion_is_seeded_and_tagged():
    from ari_os.tools.cortex import council

    def build():
        return [mk(i, "broca") for i in range(8)] + [
            mk(50 + i, "hippocampus") for i in range(4)
        ]

    kw = dict(
        salience={"broca": 1.0, "hippocampus": 0.05},
        params={"epsilon": 0.9},
        seed=7,
    )
    packed_1, tele = council.allocate(build(), 300, **kw)
    packed_2, _ = council.allocate(build(), 300, **kw)

    assert [c.chunk_id for c in packed_1] == [c.chunk_id for c in packed_2]
    assert tele["intrusion_seats"] > 0
    intruded = [c for c in packed_1 if c.source == "intrusion"]
    assert len(intruded) == tele["intrusion_seats"]
    assert all(c.region in ("hippocampus", "vmpfc") for c in intruded)
