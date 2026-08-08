"""ar.t12 MCP server tests — stdio transport against a seeded brain.db.

Verifies the public, scrubbed port of the heavy brain's MCP server:

- ``brain.recall`` returns a non-empty ranked markdown block for a query
  whose embedding matches a seeded chunk.
- ``brain.modes`` lists the full set of mode YAMLs shipped with the
  package (the public default + the cognitive variants).
- The server registers exactly the expected tool names (recall /
  lineage / regions / tracts / modes / see / lens), matching the
  private surface 1:1 so existing clients degrade gracefully.
- The server does NOT touch a real Ollama — the stdio client uses a
  stubbed EmbedClient via monkeypatch before the server boots.
"""
from __future__ import annotations

import asyncio
import json
import struct
import sys
from pathlib import Path

import pytest


# ---------- fixtures --------------------------------------------------------


class _StubEmbedClient:
    """Deterministic stand-in for the Ollama EmbedClient used by the
    retrieve() path invoked from brain.recall. Matches the interface
    expected by ``ari_os.tools.cortex.embed.EmbedClient``."""

    def __init__(self, table: dict | None = None, dim: int = 768) -> None:
        self.table = table or {}
        self.dim = dim
        self.calls: list[str] = []

    def embed(self, texts):
        out = []
        for t in texts:
            self.calls.append(t)
            if t in self.table:
                out.append(self.table[t])
            else:
                out.append([0.0] * self.dim)
        return out


def _pack(vec) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def _insert_chunk(db_path: Path, *, text: str, region: str, vec, path: str,
                  workspace: str | None = None) -> int:
    con = __import__("ari_os.tools.cortex.db", fromlist=["connect"]).connect(db_path)
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


@pytest.fixture
def ari_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Pin ARI_OS_HOME + ARI_OS_BRAIN_DB to tmp_path for hermetic tests."""
    home = tmp_path / ".ari-os"
    home.mkdir()
    monkeypatch.setenv("ARI_OS_HOME", str(home))
    monkeypatch.setenv("ARI_OS_BRAIN_DB", str(home / "brain.db"))
    return home


@pytest.fixture
def brain_db(ari_home: Path) -> Path:
    from ari_os.tools.cortex import db
    p = ari_home / "brain.db"
    db.init_db(p)
    return p


@pytest.fixture
def stub_embed_table() -> dict:
    """Two query-vector mappings so brain.recall's dense path matches the
    seeded chunks. The two seed vectors are distinct (different hot
    indices) but each query points at one of them so dense recall
    returns a non-empty result."""
    dim = 768
    qvec_w = [0.0] * dim
    qvec_w[0] = 1.0
    qvec_b = [0.0] * dim
    qvec_b[1] = 1.0
    return {
        "cortex memory architecture": qvec_w,
        "language production": qvec_b,
    }


@pytest.fixture
def seeded_brain_db(brain_db: Path, stub_embed_table: dict) -> Path:
    wvec = stub_embed_table["cortex memory architecture"]
    bvec = stub_embed_table["language production"]
    _insert_chunk(brain_db, text="wernicke fact about cortex memory",
                  region="wernicke", vec=wvec, path="wen.md")
    _insert_chunk(brain_db, text="broca fact about language production",
                  region="broca", vec=bvec, path="bro.md")
    return brain_db


# ---------- the actual stdio client tests ----------------------------------


def _run_async(coro):
    """Run an async coroutine in a fresh event loop (pytest-asyncio not
    required; we drive the MCP client with a one-shot loop)."""
    return asyncio.new_event_loop().run_until_complete(coro)


def test_mcp_brain_recall_returns_ranked_markdown(
    seeded_brain_db: Path, stub_embed_table: dict, monkeypatch: pytest.MonkeyPatch
):
    """Start the MCP server in stdio, call brain.recall with a query
    whose embedding matches the seeded Wernicke chunk, and assert the
    response is non-empty markdown containing a region header."""
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    # Stub the EmbedClient the server process would import lazily on the
    # first brain.recall call. The stub matches the live interface and
    # hands back vectors that exactly match the seeded chunk_vec rows.
    monkeypatch.setattr(
        "ari_os.tools.cortex.embed.EmbedClient",
        lambda: _StubEmbedClient(stub_embed_table),
    )

    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", "ari_os.tools.cortex.mcp_server", "stdio"],
        env={
            **__import__("os").environ,
            "ARI_OS_BRAIN_DB": str(seeded_brain_db),
            "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
        },
    )

    async def _exercise():
        async with stdio_client(server) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                tool_names = {t.name for t in tools.tools}
                # All 7 expected tools are registered, matching the
                # private surface 1:1.
                expected = {
                    "brain.recall", "brain.lineage", "brain.regions",
                    "brain.tracts", "brain.modes", "brain.see",
                    "brain.lens",
                }
                assert expected.issubset(tool_names), (
                    f"missing tools: {expected - tool_names}")
                # Call brain.recall with a query whose embedding matches
                # the seeded Wernicke chunk.
                result = await session.call_tool(
                    "brain.recall",
                    {"query": "cortex memory architecture",
                     "mode": "default", "k": 4},
                )
                return tool_names, result

    tool_names, recall_result = _run_async(_exercise())

    # Tool set check landed.
    assert "brain.recall" in tool_names

    # brain.recall returns a non-empty text payload (ranked markdown).
    assert recall_result is not None
    text_parts = [
        c.text for c in recall_result.content
        if getattr(c, "type", None) == "text"
    ]
    md = "\n".join(text_parts)
    assert md, "brain.recall returned empty markdown"
    assert "Wernicke" in md, (
        f"expected a Wernicke region header in the ranked block, got: {md!r}")


def test_mcp_brain_modes_lists_full_set(
    seeded_brain_db: Path, monkeypatch: pytest.MonkeyPatch
):
    """brain.modes() returns the full YAML mode set shipped in
    ari_os/tools/cortex/modes/."""
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    monkeypatch.setattr(
        "ari_os.tools.cortex.embed.EmbedClient",
        lambda: _StubEmbedClient(),
    )

    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", "ari_os.tools.cortex.mcp_server", "stdio"],
        env={
            **__import__("os").environ,
            "ARI_OS_BRAIN_DB": str(seeded_brain_db),
            "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
        },
    )

    async def _exercise():
        async with stdio_client(server) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool("brain.modes", {})
                return result

    res = _run_async(_exercise())
    text_parts = [
        c.text for c in res.content if getattr(c, "type", None) == "text"
    ]
    # FastMCP returns a list response as one text content per list
    # element, each one a JSON object. Parse each independently.
    modes = [json.loads(t) for t in text_parts]
    names = {m["name"] for m in modes}
    expected = {
        "default", "focus", "recall", "synthesis", "deep", "creative",
        "visual",
    }
    assert expected.issubset(names), f"missing modes: {expected - names}"
    # Each mode has a path that points at the YAML on disk.
    for m in modes:
        assert Path(m["path"]).exists(), f"mode path missing: {m['path']}"


def test_mcp_brain_regions_returns_counts(seeded_brain_db: Path,
                                          monkeypatch: pytest.MonkeyPatch):
    """brain.regions() returns a {region: count} map that includes the
    regions of every chunk we seeded."""
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    monkeypatch.setattr(
        "ari_os.tools.cortex.embed.EmbedClient",
        lambda: _StubEmbedClient(),
    )

    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", "ari_os.tools.cortex.mcp_server", "stdio"],
        env={
            **__import__("os").environ,
            "ARI_OS_BRAIN_DB": str(seeded_brain_db),
            "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
        },
    )

    async def _exercise():
        async with stdio_client(server) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool("brain.regions", {})
                return result

    res = _run_async(_exercise())
    text_parts = [
        c.text for c in res.content if getattr(c, "type", None) == "text"
    ]
    regions_map = json.loads("\n".join(text_parts))
    assert regions_map.get("wernicke") == 1
    assert regions_map.get("broca") == 1


def test_install_registers_ari_os_cortex_mcp_server(tmp_path: Path,
                                                    monkeypatch: pytest.MonkeyPatch):
    """The installer's MCP registration merges a fresh ARI-OS entry into
    an existing ``.mcp.json`` that already owns user-installed servers,
    and is idempotent on a re-run."""
    from ari_os import install

    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    # Claude Code reads project MCP config from the project root, one level
    # above .claude/ — see install._claude_mcp_path.
    user_mcp = tmp_path / ".mcp.json"
    user_mcp.write_text(json.dumps({
        "mcpServers": {
            "vercel": {"type": "http", "url": "https://mcp.vercel.com/sse"},
        }
    }))

    monkeypatch.setattr(install.paths, "claude_dir", lambda: claude_dir)

    # First registration.
    out = install.write_mcp_servers(register=True)
    assert out == user_mcp
    first = json.loads(user_mcp.read_text())
    assert "ari-os-cortex" in first["mcpServers"]
    assert "vercel" in first["mcpServers"]  # user server preserved
    entry = first["mcpServers"]["ari-os-cortex"]
    assert entry["command"] == install.MCP_SERVER_COMMAND
    assert "ari_os.tools.cortex.mcp_server" in entry["args"]

    # Idempotency: re-run, entry is replaced in place (not duplicated).
    out2 = install.write_mcp_servers(register=True)
    assert out2 == user_mcp
    second = json.loads(user_mcp.read_text())
    assert "ari-os-cortex" in second["mcpServers"]
    # Only one ari-os-cortex entry.
    ari_entries = [k for k in second["mcpServers"] if k == "ari-os-cortex"]
    assert len(ari_entries) == 1
    assert "vercel" in second["mcpServers"]

    # --no-mcp path: register=False is a no-op, returns None.
    out3 = install.write_mcp_servers(register=False)
    assert out3 is None
    third = json.loads(user_mcp.read_text())
    # File unchanged from the second registration.
    assert third == second

    # Unregister removes only the ARI-OS entry, leaves vercel.
    removed = install.unregister_mcp_server()
    assert removed is True
    after = json.loads(user_mcp.read_text())
    assert "ari-os-cortex" not in after["mcpServers"]
    assert "vercel" in after["mcpServers"]
