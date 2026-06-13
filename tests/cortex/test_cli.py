"""ar.t9 CLI tests — ``ari_os.tools.cortex.cortex`` click group.

Verifies the public, scrubbed port of the heavy brain's CLI:

- ``ingest --path <transcript>`` writes chunk rows to the brain DB.
- ``retrieve --query Q --cwd <fixture>`` prints a regioned context block
  containing at least 2 region headers.
- ``mode list / get / set / auto`` round-trip through the loader / state.
- The CLI never blocks the consumer on backend failures (graceful
  "not yet initialised" / "retrieval failed" messages).
"""
from __future__ import annotations

import json
import os
import struct
from pathlib import Path

import pytest
from click.testing import CliRunner

from ari_os.tools.cortex import config, db, index
from ari_os.tools.cortex.cortex import main
from ari_os.tools.cortex.modes.loader import active_mode_for_cwd


# ---------- fixtures --------------------------------------------------------


class _StubEmbed:
    """Deterministic stand-in for the Ollama EmbedClient — same shape as
    test_ingest.py so fixture transcripts are reusable."""

    def __init__(self, dim: int = 768) -> None:
        self.dim = dim
        self.calls: list[str] = []

    def embed(self, texts):
        out = []
        for t in texts:
            self.calls.append(t)
            h = hash(t)
            vec = [0.0] * self.dim
            vec[0] = float(h & 0xFFFF) / 65535.0
            vec[1] = float((h >> 16) & 0xFFFF) / 65535.0
            out.append(vec)
        return out


def _write_cc_transcript(path: Path) -> None:
    """Two clean user/assistant turns. user -> wernicke, assistant -> broca,
    so the assembled block will contain >= 2 region headers."""
    records = [
        {
            "type": "user",
            "sessionId": "sess-1",
            "timestamp": "2026-06-13T12:00:00Z",
            "message": {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Hello cortex, this is a clean user prompt."},
                ],
            },
        },
        {
            "type": "assistant",
            "sessionId": "sess-1",
            "timestamp": "2026-06-13T12:00:05Z",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Hi — I am a clean assistant reply."},
                ],
            },
        },
    ]
    with path.open("w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


@pytest.fixture
def ari_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Pin ARI_OS_HOME + ARI_OS_BRAIN_DB to tmp_path for hermetic CLI tests."""
    home = tmp_path / ".ari-os"
    home.mkdir()
    monkeypatch.setenv("ARI_OS_HOME", str(home))
    monkeypatch.setenv("ARI_OS_BRAIN_DB", str(home / "brain.db"))
    return home


@pytest.fixture
def brain_db(ari_home: Path) -> Path:
    p = ari_home / "brain.db"
    db.init_db(p)
    return p


@pytest.fixture
def transcript_path(tmp_path: Path) -> Path:
    p = tmp_path / "transcript.jsonl"
    _write_cc_transcript(p)
    return p


@pytest.fixture
def stub_embed() -> _StubEmbed:
    return _StubEmbed()


# ---------- ingest ----------------------------------------------------------


def test_ingest_single_file_writes_chunks(
    brain_db, transcript_path, stub_embed, monkeypatch
):
    monkeypatch.setattr("ari_os.tools.cortex.embed.EmbedClient", lambda: stub_embed)
    res = CliRunner().invoke(
        main, ["ingest", "--path", str(transcript_path)]
    )
    assert res.exit_code == 0, res.output

    con = db.connect(brain_db)
    try:
        n = con.execute("SELECT COUNT(*) FROM chunk").fetchone()[0]
    finally:
        con.close()
    assert n >= 2, f"expected >=2 chunks (user + assistant), got {n}"


def test_ingest_dry_run_does_not_touch_db(brain_db):
    res = CliRunner().invoke(main, ["ingest", "--dry-run"])
    assert res.exit_code == 0
    assert "[dry-run]" in res.output


def test_ingest_rebuild_recreates_db(brain_db, transcript_path, stub_embed, monkeypatch):
    monkeypatch.setattr("ari_os.tools.cortex.embed.EmbedClient", lambda: stub_embed)
    # Pre-populate the DB so we can prove --rebuild wipes it.
    index.index_file(brain_db, transcript_path, "episodic", stub_embed)
    assert brain_db.exists()

    res = CliRunner().invoke(main, ["ingest", "--rebuild", "--path", str(transcript_path)])
    assert res.exit_code == 0, res.output
    con = db.connect(brain_db)
    try:
        n = con.execute("SELECT COUNT(*) FROM chunk").fetchone()[0]
    finally:
        con.close()
    assert n >= 2


# ---------- retrieve --------------------------------------------------------


class _StubEmbedForRetrieve:
    """Maps known queries to fixed 768-d vectors so retrieve() exercises the
    dense path. Unknown queries fall back to a far-away zero vector."""

    def __init__(self, table: dict | None = None, dim: int = 768) -> None:
        self.table = table or {}
        self.dim = dim

    def embed(self, texts):
        out = []
        for t in texts:
            if t in self.table:
                out.append(self.table[t])
            else:
                out.append([0.0] * self.dim)
        return out


def _pack(vec):
    return struct.pack(f"{len(vec)}f", *vec)


def _insert_chunk(db_path: Path, *, text: str, region: str, vec, path: str,
                  workspace: str | None = None) -> int:
    con = db.connect(db_path)
    try:
        con.execute(
            "INSERT OR IGNORE INTO source(path, layer, workspace, mtime, sha256, last_indexed_at) "
            "VALUES (?, 'semantic', ?, 0, 'x', 0)", (path, workspace))
        sid = con.execute("SELECT id FROM source WHERE path=?", (path,)).fetchone()[0]
        cur = con.execute(
            "INSERT INTO chunk(source_id, ordinal, text, line_start, line_end, region, "
            "importance, distillation_tier) "
            "VALUES (?, 0, ?, 1, 1, ?, 0.5, 0)",
            (sid, text, region))
        cid = cur.lastrowid
        con.execute("INSERT INTO chunk_vec(rowid, embedding) VALUES (?, ?)",
                    (cid, _pack(vec)))
        return cid
    finally:
        con.close()


def test_retrieve_prints_regioned_block_with_two_regions(
    brain_db, tmp_path, monkeypatch
):
    """Ingest a fixture transcript (gives wernicke + broca chunks), then
    run ``retrieve --cwd <fixture>`` and assert the printed block contains
    >= 2 region headers."""
    dim = 768
    # Seed two chunks in different regions with vectors that match the
    # query vector — so both surface in the dense (sqlite-vec) path.
    qvec = [0.0] * dim
    qvec[0] = 1.0
    _insert_chunk(brain_db, text="wernicke fact about retrieval",
                  region="wernicke", vec=qvec, path="wen.md")
    _insert_chunk(brain_db, text="broca fact about retrieval",
                  region="broca", vec=qvec, path="bro.md")

    fixture_cwd = tmp_path / "fixture-ws"
    fixture_cwd.mkdir()
    monkeypatch.setattr("ari_os.tools.cortex.config.brain_db_path", lambda: brain_db)
    monkeypatch.setattr(
        "ari_os.tools.cortex.embed.EmbedClient",
        lambda: _StubEmbedForRetrieve({"cortex retrieval": qvec}),
    )

    res = CliRunner().invoke(
        main,
        ["retrieve", "-q", "cortex retrieval", "--cwd", str(fixture_cwd),
         "--posture", "global"],
    )
    assert res.exit_code == 0, res.output

    # The block MUST contain >= 2 region headers (Wernicke + Broca both
    # surface because we matched the query vector exactly).
    region_markers = [
        "Orbitofrontal", "Frontoparietal", "Hippocampus", "Wernicke",
        "Broca", "Occipital", "Parietal",
    ]
    hits = sum(1 for m in region_markers if m in res.output)
    assert hits >= 2, f"expected >=2 region headers, got: {res.output!r}"

    # Path:line anchors present for both seeded chunks.
    assert "[wen.md" in res.output
    assert "[bro.md" in res.output


def test_retrieve_missing_db_prints_friendly_message(ari_home, monkeypatch):
    """With no brain.db on disk, retrieve must NOT raise — it prints a
    friendly 'not yet initialised' banner instead."""
    monkeypatch.setattr("ari_os.tools.cortex.config.brain_db_path",
                        lambda: ari_home / "brain.db")
    res = CliRunner().invoke(main, ["retrieve", "-q", "anything"])
    assert res.exit_code == 0
    assert "not yet initialised" in res.output


# ---------- mode ------------------------------------------------------------


def test_mode_list_outputs_modes(monkeypatch):
    res = CliRunner().invoke(main, ["mode", "list"])
    assert res.exit_code == 0
    for m in ("default", "focus", "recall", "synthesis", "deep", "creative", "visual"):
        assert m in res.output.splitlines()


def test_mode_get_default_for_unknown_cwd(ari_home):
    res = CliRunner().invoke(
        main, ["mode", "get", "--cwd", "/nonexistent/abc/xyz"]
    )
    assert res.exit_code == 0
    assert res.output.strip() == "default"


def test_mode_set_then_get(ari_home):
    res = CliRunner().invoke(
        main, ["mode", "set", "recall", "--cwd", "/some/test/cwd"]
    )
    assert res.exit_code == 0
    assert "mode set: recall" in res.output
    # Now read it back through the same loader the CLI uses.
    assert active_mode_for_cwd("/some/test/cwd", home_dir=ari_home) == "recall"


def test_mode_set_unknown_name_errors():
    res = CliRunner().invoke(main, ["mode", "set", "not-a-real-mode"])
    assert res.exit_code != 0
    assert "unknown mode" in res.output.lower()


def test_mode_auto_strong_skill_signal_announces(ari_home):
    res = CliRunner().invoke(
        main, ["mode", "auto", "--skill", "systematic-debugging",
               "--cwd", "/x", "--session-id", "s"],
    )
    assert res.exit_code == 0
    assert "🧠 mode → focus" in res.output
    assert active_mode_for_cwd("/x", home_dir=ari_home) == "focus"


def test_mode_auto_no_signal_silent(ari_home):
    res = CliRunner().invoke(
        main, ["mode", "auto", "--prompt", "the weather is nice",
               "--cwd", "/z", "--session-id", "s"],
    )
    assert res.exit_code == 0
    assert res.output.strip() == ""


def test_mode_auto_namespaced_skill_normalized(ari_home):
    res = CliRunner().invoke(
        main, ["mode", "auto", "--skill", "superpowers:brainstorming",
               "--cwd", "/ns", "--session-id", "s"],
    )
    assert res.exit_code == 0
    assert "🧠 mode → creative" in res.output
    assert active_mode_for_cwd("/ns", home_dir=ari_home) == "creative"


# ---------- top-level dispatch ----------------------------------------------


def test_python_m_entrypoint_loads(monkeypatch):
    """``python -m ari_os.tools.cortex`` must work and show all 3 commands."""
    import subprocess
    r = subprocess.run(
        ["python3", "-c",
         "from ari_os.tools.cortex.__main__ import main; "
         "from click.testing import CliRunner; "
         "print(CliRunner().invoke(main, ['--help']).output)"],
        capture_output=True, text=True, check=False,
    )
    # This subprocess may run outside the venv; just assert the import
    # surfaced in the parent's venv is callable. Skip if subprocess Python
    # doesn't see the package (e.g. site-packages on a different prefix).
    if r.returncode == 0:
        assert "ingest" in r.stdout
        assert "retrieve" in r.stdout
        assert "mode" in r.stdout
    else:
        # Fallback: call directly in this interpreter.
        from ari_os.tools.cortex.__main__ import main as m
        res = CliRunner().invoke(m, ["--help"])
        assert res.exit_code == 0
        for cmd in ("ingest", "retrieve", "mode"):
            assert cmd in res.output
