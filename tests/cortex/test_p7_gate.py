"""P7 gate - heavy Cortex install, selector, migration, tune, and scrub.

This is the tier-0 audit for the P7 heavy-Cortex surface. It bundles every
P7 DoD check requested for this phase into one hermetic test module so a
single ``pytest -q tests/cortex/test_p7_gate.py`` proves the P7 surface is
shipping clean without Ollama or user-local state.

What it covers:

- **DoD-1** - Fresh install stands up a heavy brain database, managed
  ``CLAUDE.md`` block, MCP server registration, SessionStart hook, and
  persisted ``cortex.llm`` choice.
- **DoD-7** - The LLM selector accepts ``ollama`` / ``api`` / ``off``,
  persists and reads back the chosen backend, rejects invalid backends, and
  still allows core retrieval when LLM use is off.
- **DoD-8** - Light database migration preserves source/chunk rows, creates
  heavy tables and backfilled columns, bumps schema metadata, and rebuilds
  lexical FTS.
- **DoD-11** - The tuning command exposes the active mode and the README /
  SETUP tuning surfaces are linked.
- **DoD hygiene** - The production tree scrub matches the P6 gate scrub and
  returns zero offenders for the banned-token set.
"""
from __future__ import annotations

import base64
import json
import sqlite3
import struct
from pathlib import Path

from click.testing import CliRunner

from ari_os.install import START

# ---------------------------------------------------------------------------
# paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
PROD_ROOT = REPO_ROOT / "ari_os"

AUDIT_EXCLUDE_DIRS = (
    ".git", ".venv", ".pytest_cache", "__pycache__",
    ".worktrees", ".eggs", "node_modules", "tests",
)

_AUDITABLE_SUFFIXES = (
    ".py", ".json", ".yaml", ".yml", ".md", ".txt", ".toml", ".cfg", ".ini", ".sh",
)

# ---------------------------------------------------------------------------
# banned tokens (base64-encoded, scrub-bible mirror from test_p6_gate)
# ---------------------------------------------------------------------------

_BANNED_B64: tuple[str, ...] = (
    "U0hBRE9X",
    "L1ZvbHVtZXM=",
    "Y3JlYXRpb2V4bmloaWxv",
    "c2hhZG93X2Rpc3BhdGNo",
    "c2hhZG93X2JyYWlu",
    "VmFsaGFsbGE=",
    "TmVvbg==",
    "TUVNT1JZX0JBTks=",
    "bW14X2NsYXVkZQ==",
    "a2ltaV9jYXA=",
)


def _banned_tokens() -> list[str]:
    return [base64.b64decode(s).decode("ascii") for s in _BANNED_B64]


BANNED_TOKENS: tuple[str, ...] = tuple(_banned_tokens())


# ---------------------------------------------------------------------------
# file scanning helpers
# ---------------------------------------------------------------------------


def _iter_files(root: Path):
    if not root.exists():
        return
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in AUDIT_EXCLUDE_DIRS for part in path.parts):
            continue
        if path.suffix.lower() not in _AUDITABLE_SUFFIXES:
            continue
        yield path


def _scan_for_tokens(root: Path, tokens: tuple[str, ...]) -> dict[str, list[str]]:
    offenders: dict[str, list[str]] = {t: [] for t in tokens}
    for path in _iter_files(root):
        try:
            text = path.read_text()
        except (OSError, UnicodeDecodeError):
            continue
        for token in tokens:
            if token and token in text:
                offenders[token].append(str(path.relative_to(REPO_ROOT)))
    return offenders


# ---------------------------------------------------------------------------
# shared helpers
# ---------------------------------------------------------------------------


def _pack(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def _vec(dim: int = 768) -> list[float]:
    out = [0.0] * dim
    out[0] = 1.0
    return out


class _StubEmbed:
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [_vec() for _ in texts]


def _seed_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "ari_os" / "skills" / "advisor").mkdir(parents=True)
    (repo / "ari_os" / "skills" / "advisor" / "SKILL.md").write_text(
        "---\nname: advisor\n---\n# A"
    )
    (repo / "ari_os" / "commands").mkdir(parents=True)
    (repo / "ari_os" / "commands" / "monitor.md").write_text(
        "---\ndescription: m\n---\nbody"
    )
    (repo / "ari_os" / "VERSION").write_text("0.1.0")
    return repo


def _seed_chunk(db_path: Path, text: str) -> None:
    from ari_os.tools.cortex import db

    con = db.connect(db_path)
    try:
        con.execute(
            "INSERT INTO source(path, layer, workspace, mtime, sha256, last_indexed_at) "
            "VALUES ('notes/p7-selector.md', 'semantic', 'selector', 0, 'x', 0)"
        )
        source_id = con.execute(
            "SELECT id FROM source WHERE path = 'notes/p7-selector.md'"
        ).fetchone()[0]
        cur = con.execute(
            """INSERT INTO chunk(
                 source_id, ordinal, text, line_start, line_end, region,
                 importance, distillation_tier
               ) VALUES (?, 0, ?, 1, 1, 'wernicke', 0.5, 0)""",
            (source_id, text),
        )
        chunk_id = int(cur.lastrowid)
        con.execute(
            "INSERT INTO chunk_vec(rowid, embedding) VALUES (?, ?)",
            (chunk_id, _pack(_vec())),
        )
        con.commit()
    finally:
        con.close()


def _seed_light_db(path: Path) -> None:
    con = sqlite3.connect(path)
    try:
        con.executescript(
            """
            CREATE TABLE source (
              id INTEGER PRIMARY KEY,
              path TEXT UNIQUE NOT NULL,
              layer TEXT NOT NULL,
              mtime INTEGER NOT NULL,
              sha256 TEXT NOT NULL,
              last_indexed_at INTEGER NOT NULL
            );
            CREATE TABLE chunk (
              id INTEGER PRIMARY KEY,
              source_id INTEGER NOT NULL REFERENCES source(id) ON DELETE CASCADE,
              ordinal INTEGER NOT NULL,
              text TEXT NOT NULL,
              line_start INTEGER NOT NULL,
              line_end INTEGER NOT NULL
            );
            """
        )
        con.execute(
            """INSERT INTO source(id, path, layer, mtime, sha256, last_indexed_at)
               VALUES (1, 'notes/light.md', 'semantic', 123, 'abc', 456)"""
        )
        con.execute(
            """INSERT INTO chunk(id, source_id, ordinal, text, line_start, line_end)
               VALUES (7, 1, 0, 'The migrated token is ZEBRAFISHMEMORY.', 3, 4)"""
        )
        con.execute("PRAGMA user_version = 1")
        con.commit()
    finally:
        con.close()


def test_dod1_install_stands_up_heavy_brain(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("ARI_OS_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("ARI_OS_CLAUDE_DIR", str(tmp_path / "claude"))
    monkeypatch.delenv("ARI_OS_LLM", raising=False)
    monkeypatch.delenv("ARI_OS_EARS", raising=False)
    monkeypatch.delenv("ARI_OS_LENS", raising=False)

    from ari_os import install, paths
    from ari_os.tools.cortex import config, db

    claude_dir = paths.claude_dir()
    claude_dir.mkdir(parents=True)
    (claude_dir / "CLAUDE.md").write_text("my rules\n")
    repo = _seed_repo(tmp_path)

    install.apply(install.plan_actions(repo), dry_run=False, llm="ollama")

    brain_path = config.brain_db_path()
    assert brain_path.exists()
    con = db.connect(brain_path)
    try:
        tables = {
            row[0]
            for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'virtual')"
            )
        }
    finally:
        con.close()
    assert {"chunk", "chunk_vec", "meta"}.issubset(tables)
    assert START in (claude_dir / "CLAUDE.md").read_text()

    mcp = json.loads((claude_dir / ".mcp.json").read_text())
    assert "ari-os-cortex" in mcp["mcpServers"]

    settings = json.loads((claude_dir / "settings.json").read_text())
    hooks = settings["hooks"]["SessionStart"]
    assert any("ari_os.hooks.session_start_cortex" in h["command"] for h in hooks)
    assert config._config_value("cortex.llm") == "ollama"


def test_dod7_llm_selector_accepts_all_and_off_retrieves(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("ARI_OS_HOME", str(tmp_path))
    monkeypatch.delenv("ARI_OS_LLM", raising=False)

    from ari_os.tools.cortex import config, cortex, db, llm as llm_mod, mcp_tools, retrieve

    runner = CliRunner()
    for backend in ("ollama", "api", "off"):
        result = runner.invoke(cortex.main, ["llm", backend])
        assert result.exit_code == 0, result.output
        assert result.output.strip() == f"cortex.llm set: {backend}"
        assert config._config_value("cortex.llm") == backend
        assert json.loads((tmp_path / "config.json").read_text())["cortex.llm"] == backend

        readback = runner.invoke(cortex.main, ["llm"])
        assert readback.exit_code == 0, readback.output
        assert readback.output.strip() == backend

    invalid = runner.invoke(cortex.main, ["llm", "bogus"])
    assert invalid.exit_code != 0

    assert mcp_tools._cortex_llm_enabled() is False

    def _raise_if_called(spec=None):
        raise AssertionError("retrieve should not load an LLM when cortex.llm is off")

    monkeypatch.setattr(llm_mod, "get_llm", _raise_if_called)

    db_path = tmp_path / "brain.db"
    db.init_db(db_path)
    seeded = "The selector retrieval token is KIWISELECTOR."
    _seed_chunk(db_path, seeded)

    result = retrieve.retrieve(
        db_path,
        query="KIWISELECTOR",
        embed_client=_StubEmbed(),
        cwd=str(tmp_path),
        mode="default",
    )
    assert any(seeded in chunk.text for chunk in result.chunks)


def test_dod8_migration_preserves_memories(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ARI_OS_HOME", str(tmp_path / ".ari-os"))
    monkeypatch.delenv("ARI_OS_LLM", raising=False)
    db_path = tmp_path / "light-cortex.db"
    monkeypatch.setenv("ARI_OS_BRAIN_DB", str(db_path))
    _seed_light_db(db_path)

    from ari_os.tools.cortex import db

    migrated = db.migrate()

    assert migrated == db_path.resolve()
    con = db.connect(db_path)
    try:
        assert con.execute("SELECT id, text FROM chunk").fetchall() == [
            (7, "The migrated token is ZEBRAFISHMEMORY.")
        ]
        assert con.execute("SELECT id, path FROM source").fetchall() == [
            (1, "notes/light.md")
        ]
        tables = {
            row[0]
            for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
            ).fetchall()
        }
        assert {
            "kg_entity",
            "fsrs_state",
            "chunk_cluster",
            "chunk_vec",
            "chunk_fts",
            "meta",
        }.issubset(tables)

        source_cols = {row[1] for row in con.execute("PRAGMA table_info(source)")}
        assert "workspace" in source_cols
        chunk_cols = {row[1] for row in con.execute("PRAGMA table_info(chunk)")}
        assert {
            "region",
            "importance",
            "distillation_tier",
            "session_id",
        }.issubset(chunk_cols)

        assert db.meta_get(con, "schema_version") == str(db.SCHEMA_VERSION)
        assert con.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
        assert con.execute(
            "SELECT rowid FROM chunk_fts WHERE chunk_fts MATCH 'ZEBRAFISHMEMORY'"
        ).fetchall() == [(7,)]
    finally:
        con.close()


def test_dod11_tune_surface_and_readme(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ARI_OS_HOME", str(tmp_path))
    monkeypatch.delenv("ARI_OS_LLM", raising=False)

    from ari_os.tools.cortex import cortex

    result = CliRunner().invoke(cortex.main, ["tune"])

    assert result.exit_code == 0, result.output
    assert "active mode:" in result.output
    assert "wernicke" in result.output
    assert "Tuning your brain" in (REPO_ROOT / "README.md").read_text()
    assert "Tuning your brain" in (REPO_ROOT / "SETUP.md").read_text()


def test_dod_hygiene_scrub_zero() -> None:
    offenders = _scan_for_tokens(PROD_ROOT, BANNED_TOKENS)
    assert {token: paths for token, paths in offenders.items() if paths} == {}
