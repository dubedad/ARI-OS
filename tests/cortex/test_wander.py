"""P4 wander tests — associative surfacing and toggle behavior."""
from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest

from ari_os.tools.cortex import db
from ari_os.tools.cortex import wander


def _pack(vec):
    return struct.pack(f"{len(vec)}f", *vec)


def _vec(dim=768, *, hot_index=0, value=1.0):
    out = [0.0] * dim
    out[hot_index] = value
    return out


class _StubEmbed:
    def __init__(self, table=None, dim=768):
        self.table = table or {}
        self.dim = dim
        self.calls: list[str] = []

    def embed(self, texts):
        out = []
        for text in texts:
            self.calls.append(text)
            out.append(self.table.get(text, [0.0] * self.dim))
        return out


@pytest.fixture
def brain_db(tmp_path: Path) -> Path:
    path = tmp_path / "brain.db"
    db.init_db(path)
    return path


def _insert_chunk(
    db_path: Path,
    *,
    text: str,
    region: str = "frontoparietal",
    vec=None,
    path: str,
    workspace: str | None = None,
    retrieved_count: int = 0,
) -> int:
    con = db.connect(db_path)
    try:
        con.execute(
            "INSERT OR IGNORE INTO source(path, layer, workspace, mtime, sha256, last_indexed_at) "
            "VALUES (?, 'semantic', ?, 0, 'x', 0)",
            (path, workspace),
        )
        sid = con.execute("SELECT id FROM source WHERE path=?", (path,)).fetchone()[0]
        cur = con.execute(
            "INSERT INTO chunk(source_id, ordinal, text, line_start, line_end, region, "
            "importance, distillation_tier, retrieved_count) "
            "VALUES (?, 0, ?, 1, 2, ?, 0.5, 0, ?)",
            (sid, text, region, retrieved_count),
        )
        cid = cur.lastrowid
        if vec is not None:
            con.execute("INSERT INTO chunk_vec(rowid, embedding) VALUES (?, ?)", (cid, _pack(vec)))
        return cid
    finally:
        con.close()


def _link(db_path: Path, from_id: int, to_id: int, *, weight: float = 0.8) -> None:
    con = db.connect(db_path)
    try:
        con.execute(
            "INSERT INTO tract_edge(from_chunk, to_chunk, tract, weight, co_activations) "
            "VALUES (?, ?, 'hebbian', ?, 1)",
            (from_id, to_id, weight),
        )
    finally:
        con.close()


def test_wander_surfaces_associative_non_lexical_chunk(brain_db):
    focus_vec = _vec(hot_index=0)
    focus = _insert_chunk(
        brain_db,
        text="database migration rollback checklist",
        region="frontoparietal",
        vec=focus_vec,
        path="focus.md",
        workspace="project-a",
    )
    target = _insert_chunk(
        brain_db,
        text="ceramic kiln timing and glaze cooling pattern",
        region="hippocampus",
        path="associative.md",
        workspace="project-b",
    )
    for i in range(5):
        _insert_chunk(
            brain_db,
            text=f"local filler memory {i}",
            region="frontoparietal",
            path=f"local-{i}.md",
            workspace="project-a",
        )
    _link(brain_db, focus, target)

    result = wander.wander(
        brain_db,
        "database migration",
        divergence=1.0,
        embed_client=_StubEmbed({"database migration": focus_vec}),
        rng_seed=1,
    )

    assert result.fired is True
    assert result.seed is not None
    assert result.seed.chunk_id == target
    assert result.seed.chunk_id not in result.focus_ids
    assert "database" not in result.seed.text
    assert "migration" not in result.seed.text


def test_wander_mode_params_merge_over_defaults():
    focus = wander.resolve_wander_params("focus")
    creative = wander.resolve_wander_params("creative")
    default = wander.resolve_wander_params("default")

    assert focus["enabled"] is False
    assert creative["divergence"] > default["divergence"]
    assert focus["cadence_min"] == 5


def test_unknown_mode_uses_default_wander_params():
    assert wander.resolve_wander_params("does-not-exist") == {
        "enabled": True,
        "divergence": 0.3,
        "cadence_min": 5,
        "cadence_max": 10,
        "divergence_min": 0.1,
        "divergence_max": 0.6,
    }


def test_wander_off_config_blocks_surface_and_embed(tmp_path, brain_db, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    (home / "config.json").write_text(json.dumps({"cortex": {"wander": False}}))
    monkeypatch.setenv("ARI_OS_HOME", str(home))
    embed = _StubEmbed({"anything": _vec()})

    assert wander.surface_pass(brain_db, "anything", embed_client=embed) == ""

    result = wander.wander(brain_db, "anything", embed_client=embed)
    assert result.fired is False
    assert embed.calls == []


def test_render_blocks_are_empty_without_candidates():
    assert wander.render_wander_block(wander.WanderResult(focus_ids=[], seed=None)) == ""
    assert wander.render_surface_block([]) == ""


def test_adaptive_divergence_is_bounded():
    assert wander.adaptive_divergence(0.3, -1.0, lo=0.1, hi=0.6) == 0.1
    assert wander.adaptive_divergence(0.3, 2.0, lo=0.1, hi=0.6) == 0.6
