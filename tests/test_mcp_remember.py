from __future__ import annotations

from pathlib import Path

from ari_os.tools.cortex import mcp_tools
from ari_os.tools.cortex.db import connect


class FakeEmbed:
    """768-d zero vectors, so tests do not need Ollama."""

    def embed(self, texts):
        return [[0.0] * 768 for _ in texts]


def _make_brain(tmp_path: Path) -> Path:
    from ari_os.tools.cortex import db

    path = tmp_path / "brain.db"
    db.init_db(path)
    return path


def test_remember_inserts_one_chunk(tmp_path: Path):
    db = _make_brain(tmp_path)

    out = mcp_tools.remember(
        db,
        "the rooftop shoot used a single hard key",
        embed_client=FakeEmbed(),
    )

    assert isinstance(out, dict)
    assert out["id"] >= 1
    con = connect(db)
    try:
        n = con.execute(
            "SELECT COUNT(*) FROM chunk WHERE text LIKE 'the rooftop shoot%'"
        ).fetchone()[0]
    finally:
        con.close()
    assert n == 1


def test_remember_dedupes_identical_text(tmp_path: Path):
    db = _make_brain(tmp_path)

    a = mcp_tools.remember(db, "same memory text", embed_client=FakeEmbed())
    b = mcp_tools.remember(db, "same memory text", embed_client=FakeEmbed())

    con = connect(db)
    try:
        n = con.execute(
            "SELECT COUNT(*) FROM chunk WHERE text = 'same memory text'"
        ).fetchone()[0]
    finally:
        con.close()
    assert n == 1
    assert a["source"] == b["source"]


def test_brain_remember_registered():
    from ari_os.tools.cortex.mcp_server import build_server

    server = build_server()
    names = {tool.name for tool in server._tool_manager.list_tools()}

    assert "brain.remember" in names


def test_recall_has_no_write_side_effects(tmp_path: Path, monkeypatch):
    db = _make_brain(tmp_path)
    mcp_tools.remember(db, "seed chunk for recall", embed_client=FakeEmbed())
    monkeypatch.setattr("ari_os.tools.cortex.retrieve.EmbedClient", FakeEmbed)

    def snapshot():
        con = connect(db)
        try:
            retrieved_count = con.execute(
                "SELECT COALESCE(SUM(retrieved_count), 0) FROM chunk"
            ).fetchone()[0]
            has_tract_edge = con.execute(
                "SELECT name FROM sqlite_master WHERE name = 'tract_edge'"
            ).fetchone()
            tract_edges = (
                con.execute("SELECT COUNT(*) FROM tract_edge").fetchone()[0]
                if has_tract_edge
                else 0
            )
        finally:
            con.close()
        return (retrieved_count, tract_edges)

    before = snapshot()
    mcp_tools.recall(db, "seed", k=4)
    after = snapshot()

    assert before == after, "recall must not mutate retrieved_count or tract_edge"
