"""MCP server — stdio + HTTP/SSE transports for the ARI-OS Cortex brain.

Public port + scrub of the private engine's MCP server. The brain tool
set is preserved 1:1 (brain.recall / lineage / regions / tracts / modes
/ see / lens) so a client wired against the private surface degrades
gracefully when the public package returns "not supported" for the
vision / LENS backends.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp.server import FastMCP

from .config import brain_db_path


def build_server(
    db_path: Path | None = None,
    port: int = 7831,
    *,
    _transport_security: Any = None,
) -> FastMCP:
    """Build and return a FastMCP server with all brain tools registered."""
    from . import mcp_tools

    db = db_path or brain_db_path()
    kwargs: dict[str, Any] = {"port": port}
    if _transport_security is not None:
        kwargs["transport_security"] = _transport_security
    mcp = FastMCP("ari-os-cortex", **kwargs)

    @mcp.tool(name="brain.recall", description="Retrieve relevant brain context for a query.")
    def brain_recall(query: str, mode: str = "default", k: int = 12, token_budget: int = 4000, session_id: str | None = None) -> str:
        return mcp_tools.recall(db, query, mode=mode, k=k, token_budget=token_budget, session_id=session_id)

    @mcp.tool(name="brain.lineage", description="Walk a chunk's parent lineage back to its raw source.")
    def brain_lineage(chunk_id: int) -> dict:
        return mcp_tools.lineage(db, chunk_id)

    @mcp.tool(name="brain.regions", description="Return chunk counts grouped by brain region.")
    def brain_regions() -> dict:
        return mcp_tools.regions(db)

    @mcp.tool(name="brain.tracts", description="Return the top N Hebbian tract edges by weight.")
    def brain_tracts(n: int = 100) -> list:
        return mcp_tools.tracts(db, n=n)

    @mcp.tool(name="brain.modes", description="List available mode YAML files.")
    def brain_modes() -> list:
        return mcp_tools.modes(db)

    @mcp.tool(name="brain.see", description="Describe an image and retrieve similar brain chunks.")
    def brain_see(image_path: str, mode: str = "visual") -> dict:
        return mcp_tools.see_image(db, image_path, mode=mode)

    @mcp.tool(name="brain.lens", description="Retrieve a LENS card by slug.")
    def brain_lens(slug: str) -> str:
        return mcp_tools.lens(db, slug)

    return mcp


def run_stdio(db_path: Path | None = None) -> None:
    """Run the MCP server using stdio transport."""
    build_server(db_path).run("stdio")


def run_http(port: int = 7831, db_path: Path | None = None) -> None:
    """Run the MCP server using HTTP/SSE transport."""
    build_server(db_path, port=port).run("sse")


if __name__ == "__main__":
    # Invoked via `python -m ari_os.tools.cortex.mcp_server stdio|http`.
    # Default to stdio if no transport arg was given (Claude Code MCP
    # config registers stdio anyway).
    import sys as _sys
    _transport = _sys.argv[1] if len(_sys.argv) > 1 else "stdio"
    if _transport == "stdio":
        run_stdio()
    elif _transport in ("sse", "http"):
        run_http()
    else:
        raise SystemExit(f"unknown transport: {_transport!r}")
