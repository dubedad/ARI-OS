"""Integration test: the Cortex MCP server starts and completes a handshake.

Guards the dependency bound. ``mcp`` 2.0 removed ``mcp.server.FastMCP``, which
``cortex/mcp_server.py`` imports at module scope — so an environment resolved
from an unbounded ``mcp>=1.0`` produces an installer that "succeeds" and a
memory server that cannot start. A unit test on pyproject text proves the
declaration; this proves the resolved environment actually works.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parent.parent

_INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "ari-os-tests", "version": "1"},
    },
}


def test_mcp_server_module_imports():
    """Fails fast and readably when the mcp version is out of bounds."""
    pytest.importorskip("mcp")
    from ari_os.tools.cortex import mcp_server

    assert hasattr(mcp_server, "build_server")


def test_mcp_server_completes_initialize_handshake(tmp_path):
    """Start the server over stdio and read back a valid initialize result."""
    pytest.importorskip("mcp")
    proc = subprocess.run(
        [sys.executable, "-m", "ari_os.tools.cortex.mcp_server", "stdio"],
        input=json.dumps(_INIT) + "\n",
        capture_output=True,
        text=True,
        cwd=str(REPO),
        env={
            "PATH": "/usr/bin:/bin",
            "PYTHONPATH": str(REPO),
            "HOME": str(tmp_path),
            "ARI_OS_HOME": str(tmp_path / "state"),
        },
        timeout=60,
    )
    responses = [
        json.loads(line)
        for line in proc.stdout.splitlines()
        if line.strip().startswith("{")
    ]
    results = [r for r in responses if r.get("id") == 1 and "result" in r]
    assert results, (
        "no initialize result on stdout; "
        f"stderr tail: {proc.stderr[-400:]!r}"
    )
    result = results[0]["result"]
    assert result["serverInfo"]["name"] == "ari-os-cortex"
    assert "tools" in result["capabilities"]
