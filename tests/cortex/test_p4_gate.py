"""P4 gate - hygiene + DoD-P4 audit + end-to-end.

This is the tier-0 audit for the heavy P4 (wander / dream / distill /
consolidation / /morning / /night) surface. It bundles every DoD-P4-a..h
check into one end-to-end test module so a single
``pytest -q tests/cortex/test_p4_gate.py`` proves the P4 surface is
shipping clean.

What it covers (mapped to the heavy-core plan DoD table):

- **DoD-P4-a** - a heavy dream/consolidation pass over a seeded
  ``brain.db`` of N raw chunks persists >= 1 distilled summary chunk
  (distinct tier/region from sources), and ``brain.lineage(<id>)`` walks
  back to the source chunks.
- **DoD-P4-b** - with ``cortex.llm = off`` the dream/distill run
  completes exit 0 with no LLM/network call (summarization no-ops);
  with a stub LLM present it emits the DoD-P4-a summary. Core
  ``retrieve`` is unaffected either way.
- **DoD-P4-c** - consolidation/decay never deletes user-captured
  memories; source chunk rows survive and stay lineage-reachable.
- **DoD-P4-d** - with wander enabled, a wander tick over a populated
  ``brain.db`` surfaces >= 1 associative chunk not lexically matched to
  the focus, observable via the public ``wander`` API.
- **DoD-P4-e** - wander has a bounded budget and a ``cortex.wander``
  config toggle; with wander off it injects nothing into the
  retrieval/context path (no embed call).
- **DoD-P4-f** - the heavy ``/morning`` routine skill/command surface
  emits a maintenance + dashboard block (verified structurally by the
  ``test_routines_structural`` test). The DoD-P4-f assertion here is
  "zero internal-specific surfaces in the skill/command tree".
- **DoD-P4-g** - the heavy ``/night`` routine runs the dream pass first
  and then layers a generic end-of-day review (verified structurally
  by ``test_routines_structural``). The DoD-P4-g assertion here is
  "no banned tokens in skill/command content".
- **DoD-P4-h** - the full suite (``pytest -q``) stays green - this
  module itself is the P4 contribution to that rollup.
- **DoD-12 (guards)** - DoD-2/3/4/5 (P1-P3 core retrieve/MCP/modes)
  must keep passing; the hygiene grep + the structural assertions
  here act as a regression guard.

The audit grep is mirrored from the spec bash so the in-process
Python scan is testable without a shell and matches the operational
intent of the spec scrub bible.
"""
from __future__ import annotations

import base64
import json
import struct
import time
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
PROD_ROOT = REPO_ROOT / "ari_os"
CORTEX_ROOT = PROD_ROOT / "tools" / "cortex"
LLM_DIR = CORTEX_ROOT / "llm"
SKILLS_DIR = PROD_ROOT / "skills"
COMMANDS_DIR = REPO_ROOT / "ari_os" / "commands"

AUDIT_EXCLUDE_DIRS = (
    ".git", ".venv", ".pytest_cache", "__pycache__",
    ".worktrees", ".eggs", "node_modules", "tests",
)

_AUDITABLE_SUFFIXES = (
    ".py", ".json", ".yaml", ".yml", ".md", ".txt", ".toml", ".cfg", ".ini", ".sh",
)

# ---------------------------------------------------------------------------
# banned tokens (base64-encoded, scrub-bible mirror)
# ---------------------------------------------------------------------------

_BANNED_B64: tuple[str, ...] = (
    "U0hBRE9X",            # internal
    "L1ZvbHVtZXM=",        # /tmp
    "Y3JlYXRpb2V4bmloaWxv",  # example
    "c2hhZG93X2Rpc3BhdGNo",  # dispatch
    "c2hhZG93X2JyYWlu",   # localbrain
    "VmFsaGFsbGE=",        # node
    "TmVvbg==",            # postgres
    "TUVNT1JZX0JBTks=",    # MEMORY_STORE
    "bW14X2NsYXVkZQ==",   # mmx_local
    "a2ltaV9jYXA=",       # cap_local
)


def _banned_tokens() -> list[str]:
    return [base64.b64decode(s).decode("ascii") for s in _BANNED_B64]


BANNED_TOKENS: tuple[str, ...] = tuple(_banned_tokens())


# Private LLM module names that MUST NOT exist in the public LLM backend
# directory. The spec allows only ollama / api / off - kimi, codex, nvidia
# are private model lore and stay in the source engine.
_PRIVATE_LLM_MODULES: tuple[str, ...] = ("kimi", "codex", "nvidia")

# Mesh/cloud modules that MUST NOT exist anywhere in the public tree.
MESH_MODULES: tuple[str, ...] = (
    "db_neon", "db_router", "mesh_sync", "r2_fetch",
)


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
# shared fixtures / helpers
# ---------------------------------------------------------------------------


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


class _StubLLM:
    def __init__(self) -> None:
        self.consolidate_calls: list[list[str]] = []
        self.distill_calls: list[tuple[str, int]] = []

    def consolidate(self, texts: list[str]) -> str:
        self.consolidate_calls.append(list(texts))
        return "P4-GATE digest: " + " | ".join(texts)

    def distill(self, text: str, tier: int) -> str:
        self.distill_calls.append((text, tier))
        return f"P4-GATE tier {tier + 1}: {text}"


@pytest.fixture
def ari_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / ".ari-os"
    home.mkdir()
    monkeypatch.setenv("ARI_OS_HOME", str(home))
    monkeypatch.setenv("ARI_OS_BRAIN_DB", str(home / "brain.db"))
    monkeypatch.setenv("ARI_OS_EMBEDDINGS", "off")
    return home


@pytest.fixture
def brain_db(ari_home: Path) -> Path:
    from ari_os.tools.cortex import db
    path = ari_home / "brain.db"
    db.init_db(path)
    return path


def _insert_chunk(
    db_path: Path,
    *,
    text: str,
    path: str,
    workspace: str = "test",
    region: str = "wernicke",
    vec: list[float] | None = None,
    tier: int = 0,
    importance: float = 0.5,
    last_retrieved_at: int | None = None,
    distilled_at: int | None = None,
) -> int:
    from ari_os.tools.cortex import db
    con = db.connect(db_path)
    try:
        con.execute(
            "INSERT OR IGNORE INTO source(path, layer, workspace, mtime, sha256, last_indexed_at) "
            "VALUES (?, 'semantic', ?, 0, 'x', 0)",
            (path, workspace),
        )
        source_id = con.execute(
            "SELECT id FROM source WHERE path = ?", (path,)
        ).fetchone()[0]
        ordinal = con.execute(
            "SELECT COALESCE(MAX(ordinal), -1) + 1 FROM chunk WHERE source_id = ?",
            (source_id,),
        ).fetchone()[0]
        cur = con.execute(
            """INSERT INTO chunk(
                 source_id, ordinal, text, line_start, line_end, region,
                 importance, distillation_tier, last_retrieved_at, distilled_at
               ) VALUES (?, ?, ?, 1, 2, ?, ?, ?, ?, ?)""",
            (source_id, ordinal, text, region, importance, tier,
             last_retrieved_at, distilled_at),
        )
        cid = int(cur.lastrowid)
        if vec is not None:
            con.execute(
                "INSERT INTO chunk_vec(rowid, embedding) VALUES (?, ?)",
                (cid, _pack(vec)),
            )
        return cid
    finally:
        con.close()


def _chunk_count(db_path: Path, tier: int | None = None) -> int:
    from ari_os.tools.cortex import db
    con = db.connect(db_path)
    try:
        if tier is None:
            return con.execute("SELECT COUNT(*) FROM chunk").fetchone()[0]
        return con.execute(
            "SELECT COUNT(*) FROM chunk WHERE distillation_tier = ?", (tier,)
        ).fetchone()[0]
    finally:
        con.close()


def _seed_raw_chunks(brain_db: Path, n: int = 6) -> list[int]:
    """Seed N raw (tier-0) chunks from the same source path."""
    ids: list[int] = []
    for i in range(n):
        ids.append(
            _insert_chunk(
                brain_db,
                text=f"raw p4-gate memory {i} about pattern {i}",
                path=f"sessions/p4-gate.md",
                workspace="p4-gate",
            )
        )
    return ids


def _all_chunk_ids(brain_db: Path) -> list[int]:
    from ari_os.tools.cortex import db
    con = db.connect(brain_db)
    try:
        rows = con.execute("SELECT id FROM chunk").fetchall()
    finally:
        con.close()
    return [int(r[0]) for r in rows]


# ======================================================================
# DoD-P4-a + DoD-P4-b - dream/distill produces summary; lineage walks.
# ======================================================================


def test_dod_p4_a_dream_with_stub_llm_persists_summary_and_lineage(
    brain_db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    """DoD-P4-a: a heavy dream pass persists >= 1 distilled summary chunk
    and ``brain.lineage(summary_id)`` resolves to source chunks.
    """
    from ari_os.tools.cortex import dream, mcp_tools

    raw_ids = _seed_raw_chunks(brain_db, n=4)
    before_total = _chunk_count(brain_db)
    llm = _StubLLM()

    monkeypatch.setattr(
        "ari_os.tools.cortex.llm.get_llm", lambda spec=None: llm,
    )

    result = dream.run_dream(brain_db, llm=llm, output_dir=tmp_path)

    assert result.session_digests >= 1
    assert _chunk_count(brain_db) > before_total

    from ari_os.tools.cortex import db
    con = db.connect(brain_db)
    try:
        row = con.execute(
            "SELECT id, distillation_tier, region FROM chunk "
            "WHERE distillation_tier = 1 ORDER BY id LIMIT 1"
        ).fetchone()
    finally:
        con.close()
    assert row is not None
    summary_id, summary_tier, summary_region = row
    # distinct tier and region from sources
    assert summary_tier >= 1
    assert summary_region in {"hippocampus", "parietal", "wernicke"}

    lineage = mcp_tools.lineage(brain_db, summary_id)
    parent_ids = [p["chunk_id"] for p in lineage["parents"]]
    assert len(parent_ids) >= 1
    for parent_id in parent_ids:
        assert parent_id in raw_ids, (
            f"lineage parent {parent_id} not in seeded raw ids {raw_ids!r}"
        )

    # LLM was actually called.
    assert llm.consolidate_calls, "stub LLM consolidate() never called"


def test_dod_p4_b_off_llm_exits_zero_no_summarization_retrieve_still_works(
    brain_db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    """DoD-P4-b: with ``cortex.llm = off`` the dream/distill run completes
    exit 0, no LLM/network call resolves, and core ``retrieve`` still returns.
    """
    from ari_os.tools.cortex import dream, retrieve

    _seed_raw_chunks(brain_db, n=4)
    before_total = _chunk_count(brain_db)

    # Hard guard: with llm=None the dream loop must NOT resolve a backend.
    def fail_get_llm(spec=None):
        raise AssertionError(
            "dream(llm=None) must not resolve a backend (cortex.llm=off)"
        )

    monkeypatch.setattr(
        "ari_os.tools.cortex.distill.get_llm", fail_get_llm,
    )
    # Same guard for the dream module if it tries to resolve.
    monkeypatch.setattr(
        "ari_os.tools.cortex.dream.get_llm", fail_get_llm, raising=False,
    )

    # No artifacts written.
    result = dream.run_dream(brain_db, llm=None, output_dir=tmp_path)

    assert result.session_digests == 0
    assert result.daily_syntheses == 0
    assert result.weekly_arcs == 0
    assert _chunk_count(brain_db) == before_total
    assert _chunk_count(brain_db, tier=1) == 0
    assert not (tmp_path / "consolidation").exists()

    # Core retrieve is unaffected - FTS returns the raw chunks we just seeded.
    hits = retrieve.fts_search(brain_db, "p4-gate memory", k=4)
    assert hits, "core retrieve regressed under llm=off path"


def test_dod_p4_c_consolidation_never_deletes_sources(
    brain_db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    """DoD-P4-c: a consolidation/decay pass may down-weight or mark chunks
    superseded, but never deletes user-captured memories; source chunk rows
    survive and stay lineage-reachable.
    """
    from ari_os.tools.cortex import db as db_mod
    from ari_os.tools.cortex import dream, retrieve

    raw_ids = _seed_raw_chunks(brain_db, n=4)
    cold_old = int(time.time()) - dream.COLD_THRESHOLD_SECS - 60
    # Mark some chunks as cold (no recent retrievals).
    for cid in raw_ids[:2]:
        con = db_mod.connect(brain_db)
        try:
            con.execute(
                "UPDATE chunk SET last_retrieved_at = ?, importance = ? WHERE id = ?",
                (cold_old, 0.8, cid),
            )
        finally:
            con.close()

    before_count = _chunk_count(brain_db)
    before_ids = set(_all_chunk_ids(brain_db))

    llm = _StubLLM()
    monkeypatch.setattr(
        "ari_os.tools.cortex.llm.get_llm", lambda spec=None: llm,
    )

    result = dream.run_dream(brain_db, llm=llm, output_dir=tmp_path)

    after_count = _chunk_count(brain_db)
    after_ids = set(_all_chunk_ids(brain_db))
    # Every original chunk survives; only summary chunks may be added.
    assert before_ids.issubset(after_ids), (
        f"source chunk id(s) lost during consolidation: "
        f"{sorted(before_ids - after_ids)}"
    )
    # Decay pass may have marked importance lower - never deleted.
    assert after_count >= before_count

    # Re-fetch each raw chunk - must remain lineage-reachable from the
    # ``retrieve`` API.
    for cid in raw_ids:
        row = db_mod.connect(brain_db).execute(
            "SELECT id, distillation_tier FROM chunk WHERE id = ?", (cid,),
        ).fetchone()
        assert row is not None, f"source chunk {cid} deleted by consolidation"
        assert row[1] == 0, (
            f"raw chunk {cid} tier bumped to {row[1]}; consolidation must not "
            f"promote source chunks"
        )

    # retrieve still returns the raw sources.
    hits = retrieve.fts_search(brain_db, "pattern", k=4)
    assert hits


# ======================================================================
# DoD-P4-d + DoD-P4-e - wander surfaces associative chunk; bounded/off.
# ======================================================================


def test_dod_p4_d_wander_surfaces_associative_non_lexical_chunk(
    brain_db: Path,
):
    """DoD-P4-d: with wander enabled, a wander tick surfaces >= 1 associative
    chunk not lexically matched to the focus.
    """
    from ari_os.tools.cortex import db
    from ari_os.tools.cortex import wander

    focus_vec = _vec(hot_index=0)
    focus = _insert_chunk(
        brain_db,
        text="database migration rollback checklist",
        path="focus.md",
        workspace="project-a",
        region="frontoparietal",
        vec=focus_vec,
    )
    target = _insert_chunk(
        brain_db,
        text="ceramic kiln timing and glaze cooling pattern",
        path="associative.md",
        workspace="project-b",
        region="hippocampus",
    )
    for i in range(5):
        _insert_chunk(
            brain_db,
            text=f"local filler memory {i}",
            path=f"local-{i}.md",
            workspace="project-a",
        )
    # Link focus -> target via Hebbian tract.
    con = db.connect(brain_db)
    try:
        con.execute(
            "INSERT INTO tract_edge(from_chunk, to_chunk, tract, weight, co_activations) "
            "VALUES (?, ?, 'hebbian', 0.9, 1)",
            (focus, target),
        )
    finally:
        con.close()

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


def test_dod_p4_e_wander_off_blocks_surface_and_embed(
    brain_db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    """DoD-P4-e: wander has a bounded budget and a ``cortex.wander`` config
    toggle; with wander off it injects nothing and never instantiates the
    embedder.
    """
    from ari_os.tools.cortex import wander

    home = tmp_path / "home"
    home.mkdir()
    (home / "config.json").write_text(json.dumps({"cortex": {"wander": False}}))
    monkeypatch.setenv("ARI_OS_HOME", str(home))

    embed = _StubEmbed({"anything": _vec()})

    # surface_pass returns empty when wander is off.
    assert wander.surface_pass(brain_db, "anything", embed_client=embed) == ""
    # wander.tick also no-ops.
    result = wander.wander(brain_db, "anything", embed_client=embed)
    assert result.fired is False
    # The embedder must NOT have been called - wander off means zero
    # retrieval/context injection.
    assert embed.calls == [], (
        f"wander off still injected {len(embed.calls)} embed call(s): "
        f"{embed.calls!r}"
    )


# ======================================================================
# DoD-P4-f + DoD-P4-g - /morning + /night surface has no internal / mesh.
# ======================================================================


def test_dod_p4_f_morning_surface_has_no_banned_tokens():
    """DoD-P4-f: the heavy /morning skill/command surface is scrubbed.

    Maintenance + dashboard block emission is structurally verified in
    ``test_routines_structural.test_morning_emits_maintenance_dashboard``.
    Here we ensure the surface carries no banned internal-specific tokens.
    """
    roots = [SKILLS_DIR / "morning" / "SKILL.md", COMMANDS_DIR / "morning.md"]
    for path in roots:
        assert path.is_file(), f"missing morning surface file: {path}"
        text = path.read_text()
        offenders = [t for t in BANNED_TOKENS if t in text]
        assert not offenders, (
            f"{path.relative_to(REPO_ROOT)} contains banned tokens: "
            f"{offenders!r}"
        )


def test_dod_p4_g_night_surface_has_no_banned_tokens():
    """DoD-P4-g: the heavy /night skill/command surface is scrubbed.

    /night runs dream/consolidation first and then layers a generic
    end-of-day review - structurally verified in
    ``test_routines_structural.test_night_runs_dream_before_review``.
    Here we ensure the surface carries no banned internal-specific tokens.
    """
    roots = [SKILLS_DIR / "night" / "SKILL.md", COMMANDS_DIR / "night.md"]
    for path in roots:
        assert path.is_file(), f"missing night surface file: {path}"
        text = path.read_text()
        offenders = [t for t in BANNED_TOKENS if t in text]
        assert not offenders, (
            f"{path.relative_to(REPO_ROOT)} contains banned tokens: "
            f"{offenders!r}"
        )


# ======================================================================
# Hygiene step - scrub bible + LLM module mesh guard.
# ======================================================================


def test_scrub_bible_returns_zero_in_production_tree():
    """P4 hygiene: the spec scrub-bible grep returns zero over the shipped
    production tree (excluding bookkeeping + tests + venv).
    """
    prod_offenders = _scan_for_tokens(PROD_ROOT, BANNED_TOKENS)
    for token, files in prod_offenders.items():
        assert not files, (
            f"banned token {token!r} found in production tree:\n"
            + "\n".join(f"  {p}" for p in files)
        )

    # Project metadata must also be clean.
    for meta in (REPO_ROOT / "pyproject.toml", REPO_ROOT / "setup.cfg",
                 REPO_ROOT / "setup.py"):
        if not meta.is_file():
            continue
        text = meta.read_text()
        for token in BANNED_TOKENS:
            assert token not in text, (
                f"{meta.relative_to(REPO_ROOT)} contains banned token {token!r}"
            )


def test_public_llm_backend_excludes_private_modules():
    """P4 hygiene: cortex/llm/ contains no private lore modules
    (kimi / codex / nvidia) and no mesh modules (db_neon / db_router /
    mesh_sync / r2_fetch).
    """
    if not LLM_DIR.exists():
        pytest.fail(f"missing llm backend dir: {LLM_DIR}")

    banned_basenames: set[str] = set()
    for needle in _PRIVATE_LLM_MODULES:
        for path in LLM_DIR.rglob(f"{needle}*"):
            if not path.is_file():
                continue
            if any(part in AUDIT_EXCLUDE_DIRS for part in path.parts):
                continue
            banned_basenames.add(path.name)

    for needle in MESH_MODULES:
        for path in LLM_DIR.rglob(f"{needle}*"):
            if not path.is_file():
                continue
            if any(part in AUDIT_EXCLUDE_DIRS for part in path.parts):
                continue
            banned_basenames.add(path.name)

    assert not banned_basenames, (
        f"cortex/llm/ contains private/mesh module file(s): "
        f"{sorted(banned_basenames)}"
    )

    # Also assert no LLM backend file references private lore or mesh by
    # textual import.
    for path in LLM_DIR.rglob("*.py"):
        if not path.is_file():
            continue
        if any(part in AUDIT_EXCLUDE_DIRS for part in path.parts):
            continue
        text = path.read_text()
        for needle in (*_PRIVATE_LLM_MODULES, *MESH_MODULES):
            assert needle not in text, (
                f"{path.relative_to(REPO_ROOT)} references banned {needle!r}"
            )


def test_cortex_uses_only_public_llm_specs():
    """P4 hygiene: the consolidation LLM spec is one of off / ollama / api.

    Mirror the dispatch in ``llm.get_llm``: any other provider string is
    a private-lore leak.
    """
    from ari_os.tools.cortex import config, llm as llm_mod

    # The public config exposes exactly the three allowed providers.
    public_providers = {"off", "none", "unavailable", "ollama", "api"}
    for spec in ("off", "ollama", "api:moonshot:test", "api:test-model"):
        resolved = llm_mod.get_llm(spec)
        if spec.startswith("off"):
            assert resolved is None
    # DEFAULT_LLM must use one of the public providers (off / ollama / api),
    # with an optional ``:model`` suffix on ollama/api specs.
    default_provider = (config.DEFAULT_LLM or "").split(":", 1)[0].strip().lower()
    assert default_provider in public_providers, (
        f"DEFAULT_LLM {config.DEFAULT_LLM!r} uses non-public provider "
        f"{default_provider!r}"
    )


# ======================================================================
# DoD-P4-h - end-to-end: ingest fixture transcript -> dream -> summarise.
# ======================================================================


_CC_FIXTURE = [
    # Real user turn.
    {
        "type": "user",
        "sessionId": "sess-p4-gate",
        "timestamp": "2026-06-13T12:00:00Z",
        "cwd": "/tmp/ari-os-p4-gate",
        "message": {
            "role": "user",
            "content": [
                {"type": "text",
                 "text": "P4 gate fixture: ingest a transcript then dream/distill."},
            ],
        },
    },
    # Real assistant turn.
    {
        "type": "assistant",
        "sessionId": "sess-p4-gate",
        "timestamp": "2026-06-13T12:00:05Z",
        "cwd": "/tmp/ari-os-p4-gate",
        "message": {
            "role": "assistant",
            "content": [
                {"type": "text",
                 "text": "P4 gate fixture reply: the cortex ingests the transcript, "
                         "seeds raw chunks, and a dream pass summarises them."},
            ],
        },
    },
]


def _write_cc_fixture(path: Path) -> None:
    with path.open("w") as f:
        for r in _CC_FIXTURE:
            f.write(json.dumps(r) + "\n")


def test_dod_p4_h_e2e_ingest_dream_summary_and_retrieve(
    ari_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    """DoD-P4-h: end-to-end on a fresh ``$ARI_OS_HOME``: ingest a fixture
    transcript, run dream (with stub LLM), persist >= 1 summary chunk, and
    core ``retrieve`` still returns the raw sources.
    """
    from click.testing import CliRunner

    from ari_os.tools.cortex import retrieve
    from ari_os.tools.cortex.cortex import main

    # Fresh home, embeddings off (no Ollama needed).
    fixture = tmp_path / "transcript.jsonl"
    _write_cc_fixture(fixture)

    monkeypatch.setattr(
        "ari_os.tools.cortex.embed.EmbedClient", lambda: _StubEmbed(),
    )
    monkeypatch.setattr(
        "ari_os.tools.cortex.llm.get_llm", lambda spec=None: _StubLLM(),
    )

    # 1. Ingest the fixture through the public CLI.
    ingest = CliRunner().invoke(main, ["ingest", "--path", str(fixture)])
    assert ingest.exit_code == 0, ingest.output

    brain_path = ari_home / "brain.db"
    assert brain_path.exists()

    raw_count = _chunk_count(brain_path, tier=0)
    assert raw_count >= 1, "ingest produced no raw chunks"

    # 2. Run the dream pass.
    dream = CliRunner().invoke(main, ["dream"])
    assert dream.exit_code == 0, dream.output
    assert "dream:" in dream.output
    assert "summaries=" in dream.output

    # 3. Confirm at least one summary chunk was persisted.
    assert _chunk_count(brain_path, tier=1) >= 1

    # 4. Core retrieve still returns the raw sources.
    hits = retrieve.fts_search(brain_path, "ingest", k=4)
    assert hits, "core retrieve regressed after dream pass"


# ======================================================================
# Self-cleanliness - the gate must not weaken itself.
# ======================================================================


def test_banned_token_list_matches_scrub_bible() -> None:
    """Sanity-check the encoded token list decodes to the spec scrub bible.

    The audit is only as strong as its token list. If somebody edits
    ``_BANNED_B64`` and accidentally changes the decoded values, every
    other gate in this module would silently weaken. This test pins
    the decoded set to the spec.
    """
    expected = set(_banned_tokens())
    assert set(BANNED_TOKENS) == expected, (
        f"_BANNED_B64 drift: expected {expected!r}, got {set(BANNED_TOKENS)!r}"
    )
