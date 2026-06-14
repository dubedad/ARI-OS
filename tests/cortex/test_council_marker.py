"""Council marker tests for retrieve and wander-yield integration."""
from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest

from ari_os.tools.cortex import db, retrieve, wander


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
    path: str,
    region: str = "frontoparietal",
    workspace: str | None = None,
    vec=None,
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


def test_serving_false_when_marker_absent(tmp_path: Path):
    from ari_os.tools.cortex.council_marker import council_serving

    assert council_serving("s1", home_dir=tmp_path) is False
    assert council_serving("", home_dir=tmp_path) is False


def test_record_then_serving_round_trip(tmp_path: Path):
    from ari_os.tools.cortex.council_marker import _marker_path, council_serving, record_tier

    record_tier("s1", "normal", home_dir=tmp_path, now=10)
    assert council_serving("s1", home_dir=tmp_path) is True

    record_tier("s1", "static", home_dir=tmp_path, now=20)
    assert council_serving("s1", home_dir=tmp_path) is False

    state = json.loads(_marker_path(tmp_path).read_text())
    assert state["s1"]["tier"] == "static"


def test_empty_session_id_noops(tmp_path: Path):
    from ari_os.tools.cortex.council_marker import _marker_path, council_serving, record_tier

    record_tier("", "normal", home_dir=tmp_path)
    assert not _marker_path(tmp_path).exists()
    assert council_serving("", home_dir=tmp_path) is False


def test_corrupt_marker_fails_static_and_recovers(tmp_path: Path):
    from ari_os.tools.cortex.council_marker import _marker_path, council_serving, record_tier

    marker = _marker_path(tmp_path)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("{not json")

    assert council_serving("s1", home_dir=tmp_path) is False

    record_tier("s1", "normal", home_dir=tmp_path)
    assert council_serving("s1", home_dir=tmp_path) is True


def test_retrieve_records_static_tier_by_default(brain_db: Path, tmp_path: Path, monkeypatch):
    from ari_os.tools.cortex.council_marker import _marker_path, council_serving

    monkeypatch.setenv("ARI_OS_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("ARI_OS_COUNCIL", raising=False)
    qvec = _vec()
    _insert_chunk(brain_db, text="hello world", path="hello.md", vec=qvec)

    result = retrieve.retrieve(
        brain_db,
        "hello",
        embed_client=_StubEmbed({"hello": qvec}),
        session_id="S16",
    )

    assert result.chunks
    assert council_serving("S16", home_dir=tmp_path / "home") is False
    state = json.loads(_marker_path(tmp_path / "home").read_text())
    assert state["S16"]["tier"] == "static"


def test_retrieve_records_normal_tier_when_council_enabled(
    brain_db: Path, tmp_path: Path, monkeypatch
):
    from ari_os.tools.cortex.council_marker import council_serving

    monkeypatch.setenv("ARI_OS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("ARI_OS_COUNCIL", "1")
    qvec = _vec()
    _insert_chunk(brain_db, text="hello world", path="hello.md", vec=qvec)

    retrieve.retrieve(
        brain_db,
        "hello",
        embed_client=_StubEmbed({"hello": qvec}),
        session_id="S16",
    )

    assert council_serving("S16", home_dir=tmp_path / "home") is True


def test_marker_failure_never_breaks_retrieve(brain_db: Path, tmp_path: Path, monkeypatch):
    import ari_os.tools.cortex.council_marker as council_marker

    monkeypatch.setenv("ARI_OS_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(
        council_marker,
        "record_tier",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("marker down")),
    )
    qvec = _vec()
    _insert_chunk(brain_db, text="hello world", path="hello.md", vec=qvec)

    result = retrieve.retrieve(
        brain_db,
        "hello",
        embed_client=_StubEmbed({"hello": qvec}),
        session_id="S16",
    )

    assert result.chunks


def test_wander_yields_when_council_served_session(
    brain_db: Path, tmp_path: Path, monkeypatch
):
    from ari_os.tools.cortex.council_marker import record_tier

    monkeypatch.setenv("ARI_OS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("ARI_OS_WANDER_YIELD", "1")
    focus_vec = _vec()
    focus = _insert_chunk(
        brain_db,
        text="database migration rollback checklist",
        path="focus.md",
        workspace="project-a",
        vec=focus_vec,
    )
    target = _insert_chunk(
        brain_db,
        text="ceramic kiln timing and glaze cooling pattern",
        path="associative.md",
        region="hippocampus",
        workspace="project-b",
    )
    for i in range(5):
        _insert_chunk(brain_db, text=f"local filler {i}", path=f"local-{i}.md")
    _link(brain_db, focus, target)
    record_tier("S16", "normal", home_dir=tmp_path / "home")
    embed = _StubEmbed({"database migration": focus_vec})

    result = wander.wander(
        brain_db,
        "database migration",
        embed_client=embed,
        session_id="S16",
    )

    assert result.fired is False
    assert result.seed is None
    assert embed.calls == []


def test_wander_yield_absent_marker_preserves_draw(brain_db: Path, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ARI_OS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("ARI_OS_WANDER_YIELD", "1")
    focus_vec = _vec()
    focus = _insert_chunk(
        brain_db,
        text="database migration rollback checklist",
        path="focus.md",
        workspace="project-a",
        vec=focus_vec,
    )
    target = _insert_chunk(
        brain_db,
        text="ceramic kiln timing and glaze cooling pattern",
        path="associative.md",
        region="hippocampus",
        workspace="project-b",
    )
    for i in range(5):
        _insert_chunk(brain_db, text=f"local filler {i}", path=f"local-{i}.md")
    _link(brain_db, focus, target)

    result = wander.wander(
        brain_db,
        "database migration",
        divergence=1.0,
        embed_client=_StubEmbed({"database migration": focus_vec}),
        rng_seed=1,
        session_id="S16",
    )

    assert result.fired is True
    assert result.seed is not None
    assert result.seed.chunk_id == target
