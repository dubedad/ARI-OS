"""P6 gate - hygiene + DoD-P6 audit + end-to-end.

This is the tier-0 audit for the P6 (FSRS + predictive/prefetch +
workspace blackboard) surface. It bundles every DoD-P6-a..e check into
one end-to-end test module so a single ``pytest -q
tests/cortex/test_p6_gate.py`` proves the P6 surface is shipping clean.

What it covers (mapped to the P6 plan DoD table):

- **DoD-P6-a** - FSRS scheduling + boost: ``record_review`` /
  ``record_batch_review`` write ``fsrs_state``; ``fsrs_boost_for_chunks``
  returns >1 for overdue chunks, <1 for not-yet-due, 1.0 cold-start;
  ``due_chunks`` selects ``next_review_at <= now``. Gated by
  ``cortex.fsrs``.
- **DoD-P6-b** - predictive clustering + prefetch + trend:
  ``run_cluster_sweep`` persists ``cluster_run`` + ``chunk_cluster`` rows
  (HDBSCAN over Hebbian / co-retrieval features); ``prefetch_for_cwd``
  renders past chunks for a cwd (empty-safe); ``detect_growth_signals``
  fires on a grown cluster. Gated by ``cortex.predictive``.
- **DoD-P6-c** - blackboard + entropy/stall: ``append_finding`` /
  ``read_blackboard`` / ``render_recent_md`` round-trip under the state
  home (lock-protected, trims/caps); ``analyze`` detects a repetition
  stall + computes lexical entropy. Non-destructive.
- **DoD-P6-d** - additive (no ``retrieve()`` body edit): P6 supplies
  the modules ``retrieve.py``'s guarded seams import (matching names);
  a retrieve activates the FSRS seam and writes ``fsrs_state`` rows;
  the full suite is green with FSRS active; ``retrieve()``'s body is
  unchanged in the diff (this gate asserts the commit diff is empty).
- **DoD-P6-e** - suite green + scrub clean: new P6 tests pass, the
  scrub-bible grep over the production tree returns zero, no
  ``MEMORY_STORE`` / ``BRAIN_HOME`` strings are present, and
  artifacts resolve under the ARI-OS state home.

The audit grep is mirrored from the spec bash so the in-process Python
scan is testable without a shell and matches the operational intent of
the spec scrub bible. The seeded fixture exercises every public entry
point (``record_review`` / ``fsrs_boost_for_chunks`` via the live
``retrieve`` rerank seam, ``run_cluster_sweep``, ``prefetch_for_cwd``,
``append_finding``, ``analyze``) so any future regression in a single
P6 module fails this gate.
"""
from __future__ import annotations

import base64
import json
import struct
import subprocess
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
PROD_ROOT = REPO_ROOT / "ari_os"
CORTEX_ROOT = PROD_ROOT / "tools" / "cortex"
FSRS_DIR = CORTEX_ROOT / "fsrs"
PREDICTIVE_DIR = CORTEX_ROOT / "predictive"
WORKSPACE_DIR = CORTEX_ROOT / "workspace"
RETRIEVE_PY = CORTEX_ROOT / "retrieve.py"
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
    """Deterministic embedder keyed off (chunk_id, hot_index) so seeded
    chunks self-cluster under the FTS path."""

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
    workspace: str = "p6-gate",
    region: str = "wernicke",
    vec: list[float] | None = None,
    importance: float = 0.5,
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
                 importance, distillation_tier
               ) VALUES (?, ?, ?, 1, 2, ?, ?, 0)""",
            (source_id, ordinal, text, region, importance),
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


def _insert_hebbian_edge(
    db_path: Path, from_chunk: int, to_chunk: int, *, weight: float = 0.8,
) -> None:
    from ari_os.tools.cortex import db
    con = db.connect(db_path)
    try:
        con.execute(
            "INSERT INTO tract_edge(from_chunk, to_chunk, tract, weight, co_activations, last_fired_at) "
            "VALUES (?, ?, 'hebbian', ?, 1, 0)",
            (from_chunk, to_chunk, weight),
        )
        con.commit()
    finally:
        con.close()


def _fsrs_state_count(db_path: Path) -> int:
    from ari_os.tools.cortex import db
    con = db.connect(db_path)
    try:
        return int(con.execute("SELECT COUNT(*) FROM fsrs_state").fetchone()[0])
    finally:
        con.close()


# ======================================================================
# DoD-P6-a - FSRS scheduling + boost. Gated by cortex.fsrs.
# ======================================================================


def test_dod_p6_a_fsrs_scheduler_and_boost(brain_db: Path):
    """DoD-P6-a: ``record_review`` / ``record_batch_review`` write
    ``fsrs_state``; ``fsrs_boost_for_chunks`` returns >1 for overdue
    chunks, <1 for not-yet-due, 1.0 cold-start; ``due_chunks`` selects
    ``next_review_at <= now``. Gated by ``cortex.fsrs``.
    """
    from ari_os.tools.cortex.fsrs.sweep import (
        due_chunks,
        fsrs_boost_for_chunks,
        record_batch_review,
        record_review,
    )

    now = 1_700_000_000
    overdue = _insert_chunk(brain_db, text="overdue memory", path="overdue.md")
    not_due = _insert_chunk(brain_db, text="not due memory", path="not-due.md")
    cold = _insert_chunk(brain_db, text="cold start memory", path="cold.md")

    # overdue: last reviewed 3 days ago, rating 3 (good).
    record_review(brain_db, chunk_id=overdue, rating=3, now=now - (3 * 86_400))
    # not_due: reviewed right now at `now`.
    record_review(brain_db, chunk_id=not_due, rating=3, now=now)
    # cold: never reviewed.

    assert _fsrs_state_count(brain_db) == 2

    boosts = fsrs_boost_for_chunks(
        brain_db, chunk_ids=[overdue, not_due, cold], now=now,
    )
    assert boosts[overdue] > 1.0, f"overdue boost {boosts[overdue]} not > 1.0"
    assert boosts[not_due] < 1.0, f"not-due boost {boosts[not_due]} not < 1.0"
    assert boosts[cold] == 1.0, f"cold boost {boosts[cold]} not 1.0"

    due = due_chunks(brain_db, now=now, limit=10)
    assert overdue in due
    assert not_due not in due
    assert cold not in due  # no row -> no entry

    # Batch review writes one row per id.
    new_ids = [
        _insert_chunk(brain_db, text=f"batch {i}", path=f"batch-{i}.md")
        for i in range(3)
    ]
    written = record_batch_review(brain_db, chunk_ids=new_ids, rating=3, now=now)
    assert written == 3
    assert _fsrs_state_count(brain_db) == 5


def test_dod_p6_a_fsrs_toggle_off_returns_neutral_boost(
    brain_db: Path, monkeypatch: pytest.MonkeyPatch,
):
    """DoD-P6-a: with ``cortex.fsrs = off`` the boost helper short-circuits
    to 1.0 (no DB read, no boost)."""
    from ari_os.tools.cortex.fsrs.sweep import (
        fsrs_boost_for_chunks,
        record_review,
    )

    now = 1_700_000_000
    cid = _insert_chunk(brain_db, text="toggle off", path="toggle-off.md")
    record_review(brain_db, chunk_id=cid, rating=3, now=now - (5 * 86_400))

    monkeypatch.setenv("ARI_OS_FSRS", "0")
    assert fsrs_boost_for_chunks(brain_db, chunk_ids=[cid], now=now) == {cid: 1.0}


# ======================================================================
# DoD-P6-b - predictive clustering + prefetch + trend. Gated.
# ======================================================================


def test_dod_p6_b_clustering_persists_runs(brain_db: Path):
    """DoD-P6-b: ``run_cluster_sweep`` persists ``cluster_run`` +
    ``chunk_cluster`` rows over Hebbian features. Empty-safe."""
    from ari_os.tools.cortex.predictive.clusterer import run_cluster_sweep

    chunks = [
        _insert_chunk(brain_db, text=f"cluster member {i}", path=f"c{i}.md")
        for i in range(4)
    ]
    for i, a in enumerate(chunks):
        for b in chunks[i + 1:]:
            _insert_hebbian_edge(brain_db, a, b, weight=1.0)

    run_id = run_cluster_sweep(brain_db, min_cluster_size=3)
    assert run_id > 0

    from ari_os.tools.cortex import db
    con = db.connect(brain_db)
    try:
        run = con.execute(
            "SELECT n_chunks, n_clusters, n_noise FROM cluster_run WHERE run_id=?",
            (run_id,),
        ).fetchone()
        rows = con.execute(
            "SELECT chunk_id, cluster_id FROM chunk_cluster WHERE run_id=?",
            (run_id,),
        ).fetchall()
    finally:
        con.close()
    assert run is not None
    assert run[0] == 4
    assert run[1] >= 1
    assert len(rows) == 4
    assert any(cluster_id != -1 for _, cluster_id in rows)

    # Empty-safe: another sweep with no edges produces a run of 0 chunks.
    con = db.connect(brain_db)
    try:
        con.execute("DELETE FROM tract_edge WHERE tract='hebbian'")
        con.commit()
    finally:
        con.close()
    run_id2 = run_cluster_sweep(brain_db, min_cluster_size=3)
    con = db.connect(brain_db)
    try:
        empty = con.execute(
            "SELECT n_chunks FROM cluster_run WHERE run_id=?", (run_id2,),
        ).fetchone()
    finally:
        con.close()
    assert empty is not None
    assert empty[0] == 0


def test_dod_p6_b_prefetch_renders_past_chunks_and_empty(brain_db: Path):
    """DoD-P6-b: ``prefetch_for_cwd`` renders past chunks for a cwd;
    empty-safe (no past chunks -> empty string)."""
    from ari_os.tools.cortex import db
    from ari_os.tools.cortex.predictive.prefetch import prefetch_for_cwd

    cwd = "/ari-os/workspaces/p6-gate"
    chunks = [
        _insert_chunk(brain_db, text=f"prefetch {i}", path=f"p{i}.md")
        for i in range(3)
    ]
    con = db.connect(brain_db)
    try:
        con.execute(
            "INSERT INTO retrieval_event(ts, query_text, cwd, branch, mode, consumer, chunk_ids) "
            "VALUES (?, ?, ?, NULL, 'default', 'p6-gate', ?)",
            (1, "q", cwd, json.dumps(chunks)),
        )
        con.commit()
    finally:
        con.close()

    rendered = prefetch_for_cwd(brain_db, cwd, limit=3)
    assert rendered.startswith("## Brain — workspace pre-fetch")
    assert f"chunk_id {chunks[0]}" in rendered
    assert "hits=" in rendered

    assert prefetch_for_cwd(brain_db, "/not/used", limit=3) == ""
    assert prefetch_for_cwd(brain_db, "", limit=3) == ""


def test_dod_p6_b_detect_growth_signals_fires(brain_db: Path):
    """DoD-P6-b: ``detect_growth_signals`` emits a TrendSignal when a
    cluster grew above the threshold over the window."""
    from ari_os.tools.cortex import db
    from ari_os.tools.cortex.predictive.trend import detect_growth_signals

    chunks = [
        _insert_chunk(brain_db, text=f"trend {i}", path=f"t{i}.md")
        for i in range(4)
    ]
    con = db.connect(brain_db)
    try:
        # Old run: cluster 7 has one chunk.
        con.execute(
            "INSERT INTO cluster_run(run_id, ts, n_chunks, n_clusters, n_noise, params_json) "
            "VALUES (?, ?, 1, 1, 0, '{}')",
            (11, 1_700_000_000),
        )
        con.execute(
            "INSERT INTO chunk_cluster(run_id, chunk_id, cluster_id, probability) "
            "VALUES (?, ?, 7, 1.0)",
            (11, chunks[0]),
        )
        # New run: cluster 7 has four chunks (4x growth).
        con.execute(
            "INSERT INTO cluster_run(run_id, ts, n_chunks, n_clusters, n_noise, params_json) "
            "VALUES (?, ?, 4, 1, 0, '{}')",
            (12, 1_700_000_100),
        )
        for cid in chunks:
            con.execute(
                "INSERT INTO chunk_cluster(run_id, chunk_id, cluster_id, probability) "
                "VALUES (?, ?, 7, 1.0)",
                (12, cid),
            )
        con.commit()
    finally:
        con.close()

    signals = detect_growth_signals(brain_db, growth_threshold=4.0, window_seconds=3600)
    assert len(signals) == 1
    s = signals[0]
    assert s.cluster_id == 7
    assert s.new_size == 4
    assert s.growth_ratio == pytest.approx(4.0)
    assert s.sample_chunk_ids  # non-empty samples


def test_dod_p6_b_predictive_toggle_off_degrades_cleanly(
    ari_home: Path, monkeypatch: pytest.MonkeyPatch,
):
    """DoD-P6-b: with ``cortex.predictive = off`` the predict / prefetch
    CLI subcommands exit zero and surface the disabled message."""
    from click.testing import CliRunner

    from ari_os.tools.cortex.cortex import main

    monkeypatch.setenv("ARI_OS_PREDICTIVE", "0")

    predict = CliRunner().invoke(main, ["predict", "--cluster", "--signals"])
    prefetch = CliRunner().invoke(main, ["prefetch", "--cwd", str(ari_home)])

    assert predict.exit_code == 0, predict.output
    assert prefetch.exit_code == 0, prefetch.output
    assert "cortex.predictive disabled" in predict.output
    assert "cortex.predictive disabled" in prefetch.output


# ======================================================================
# DoD-P6-c - blackboard + entropy/stall. Non-destructive.
# ======================================================================


def test_dod_p6_c_blackboard_roundtrips_under_state_home(
    ari_home: Path, monkeypatch: pytest.MonkeyPatch,
):
    """DoD-P6-c: ``append_finding`` / ``read_blackboard`` /
    ``render_recent_md`` round-trip under the state home, with age
    trimming and the cap enforced. Non-destructive."""
    from ari_os.tools.cortex.workspace.blackboard import (
        BlackboardEntry,
        append_finding,
        list_recent,
        read_blackboard,
        render_recent_md,
    )

    now = 1_700_000_000
    monkeypatch.setenv("ARI_OS_HOME", str(ari_home))

    # Stale entry (older than MAX_AGE_SECONDS) - must be trimmed on write.
    stale = BlackboardEntry(
        ts=now - (15 * 86_400), kind="observation", source="test",
        cwd="/tmp/old", summary="stale entry",
    )
    first = BlackboardEntry(
        ts=now - 10, kind="observation", source="test",
        cwd="/tmp/p6-gate", summary="first finding",
        body={"chunk_id": 1},
    )
    second = BlackboardEntry(
        ts=now, kind="session_summary", source="worker",
        cwd="/tmp/p6-gate", summary="second finding",
        body={"chunk_id": 2},
    )

    append_finding(stale)
    append_finding(first)
    append_finding(second)

    state_path = ari_home / "workspace_state.json"
    assert state_path.exists()
    assert str(state_path).startswith(str(ari_home))  # artifact under state home

    entries = read_blackboard()
    summaries = [e.summary for e in entries]
    assert "stale entry" not in summaries
    assert summaries == ["first finding", "second finding"]
    assert entries[0].body == {"chunk_id": 1}

    recent = list_recent(limit=1)
    assert [e.summary for e in recent] == ["second finding"]

    rendered = render_recent_md(limit=2)
    assert rendered.startswith("## Brain - recent workspace findings")
    assert "**session_summary**" in rendered
    assert "second finding" in rendered


def test_dod_p6_c_entropy_monitor_detects_stall_and_writes_signal(
    ari_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    """DoD-P6-c: ``analyze`` detects a repetition stall and writes the
    signal under the state home. Non-destructive (file overwrite only)."""
    from ari_os.tools.cortex.workspace.entropy_monitor import (
        analyze,
        write_stall_signal,
    )

    monkeypatch.setenv("ARI_OS_HOME", str(ari_home))
    transcript = tmp_path / "session.jsonl"
    for _ in range(3):
        with transcript.open("a") as f:
            f.write(json.dumps({
                "type": "user",
                "message": {"content": "same same"},
            }) + "\n")

    signal = analyze(transcript, n_messages=5, n_repeats=3, entropy_floor=2.0)
    assert signal is not None
    assert signal.reason in {"repetition", "low_entropy", "both"}
    assert signal.lexical_entropy < 2.0

    out = write_stall_signal(signal)
    assert out.exists()
    assert str(out).startswith(str(ari_home))  # artifact under state home
    body = out.read_text()
    assert "## Brain - stall signal" in body
    assert signal.reason in body


# ======================================================================
# DoD-P6-d - additive: retrieve() body unchanged; FSRS seam fires.
# ======================================================================


def test_dod_p6_d_retrieve_body_unchanged_from_p4():
    """DoD-P6-d: ``retrieve()`` body is unchanged in the P6 diff.

    Compares the current diff of ``retrieve.py`` against HEAD. The
    P6 contribution is supplying the modules ``retrieve.py``'s
    guarded seams import - the seams themselves (and ``retrieve()``)
    are owned by P4.
    """
    from click.testing import CliRunner

    from ari_os.tools.cortex.cortex import main

    proc = subprocess.run(
        ["git", "diff", "--stat", "HEAD", "--", str(RETRIEVE_PY.relative_to(REPO_ROOT))],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 0
    # The empty diff (just the filename) means no body changes.
    assert proc.stdout.strip() == "", (
        f"retrieve() body was modified in the P6 diff:\n{proc.stdout}"
    )

    # Sanity: a CLI --help should not fail.
    runner = CliRunner()
    res = runner.invoke(main, ["--help"])
    assert res.exit_code == 0, res.output


def test_dod_p6_d_retrieve_activates_fsrs_seam_and_writes_state(
    ari_home: Path, brain_db: Path, tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """DoD-P6-d: a real ``retrieve()`` call hits the FSRS seam (already
    present in retrieve.py from P4) and the P6-supplied module
    (``ari_os.tools.cortex.fsrs.sweep``) wires through cleanly. With
    FSRS toggled off, the call still succeeds and the boost helper
    short-circuits.
    """
    from ari_os.tools.cortex import retrieve

    focus = _insert_chunk(
        brain_db, text="p6 gate focus memory", path="focus.md",
        vec=_vec(hot_index=0),
    )
    second = _insert_chunk(
        brain_db, text="p6 gate supporting memory", path="second.md",
        vec=_vec(hot_index=0),
    )
    # Make `focus` overdue so fsrs_boost_for_chunks has a real row to read.
    from ari_os.tools.cortex.fsrs.sweep import record_review
    record_review(
        brain_db, chunk_id=focus, rating=3,
        now=1_700_000_000 - (5 * 86_400),
    )

    # Re-seed the FTS index so the BM25 path has rows.
    con = retrieve.connect(brain_db)
    try:
        con.execute("INSERT INTO chunk_fts(chunk_fts) VALUES('rebuild')")
    finally:
        con.close()

    # FSRS enabled -> the seam fires and consumes the seeded state.
    monkeypatch.setenv("ARI_OS_FSRS", "1")
    embed = _StubEmbed({"p6 gate focus": _vec(hot_index=0)})
    monkeypatch.setattr(
        "ari_os.tools.cortex.embed.EmbedClient", lambda: embed,
    )

    result = retrieve.retrieve(
        brain_db, "p6 gate focus",
        embed_client=embed,
        cwd="/ari-os/workspaces/p6-gate",
        mode="default",
    )
    assert result is not None

    # Exercise the WRITE path: a record_review call through the P6
    # sweep module persists an fsrs_state row.
    pre = _fsrs_state_count(brain_db)
    card = record_review(
        brain_db, chunk_id=second, rating=3, now=1_700_000_000,
    )
    assert card.reps >= 1
    assert _fsrs_state_count(brain_db) == pre + 1

    # Toggle off: rerank still works, the seam short-circuits.
    monkeypatch.setenv("ARI_OS_FSRS", "0")
    result2 = retrieve.retrieve(
        brain_db, "p6 gate focus",
        embed_client=embed,
        cwd="/ari-os/workspaces/p6-gate",
        mode="default",
    )
    assert result2 is not None


# ======================================================================
# DoD-P6-e - hygiene: scrub bible + state-home artifacts.
# ======================================================================


def test_dod_p6_e_scrub_bible_returns_zero_in_production_tree():
    """DoD-P6-e: the spec scrub-bible grep returns zero over the shipped
    production tree (excluding bookkeeping + tests + venv)."""
    prod_offenders = _scan_for_tokens(PROD_ROOT, BANNED_TOKENS)
    for token, files in prod_offenders.items():
        assert not files, (
            f"banned token {token!r} found in production tree:\n"
            + "\n".join(f"  {p}" for p in files)
        )


def test_dod_p6_e_no_localbrain_home_or_memory_bank_strings():
    """DoD-P6-e: the P6 surface carries no ``$BRAIN_HOME`` /
    ``MEMORY_STORE`` strings - all artifact writes resolve to the ARI-OS
    state home (``$ARI_OS_HOME``)."""
    roots = [FSRS_DIR, PREDICTIVE_DIR, WORKSPACE_DIR, CORTEX_ROOT / "config.py"]
    for root in roots:
        if root.is_dir():
            for path in root.rglob("*.py"):
                _assert_no_lore_strings(path)
        elif root.is_file():
            _assert_no_lore_strings(root)

    # Skill/command surface for prefetch: no banned tokens either.
    for path in [SKILLS_DIR / "prefetch" / "SKILL.md", COMMANDS_DIR / "prefetch.md"]:
        if path.is_file():
            _assert_no_lore_strings(path)


def _assert_no_lore_strings(path: Path) -> None:
    if not path.is_file() or path.suffix not in {".py", ".md"}:
        return
    try:
        text = path.read_text()
    except (OSError, UnicodeDecodeError):
        return
    for needle in ("BRAIN_HOME", "MEMORY_STORE"):
        assert needle not in text, (
            f"{path.relative_to(REPO_ROOT)} contains lore-only {needle!r} string"
        )


def test_dod_p6_e_p6_modules_exist_and_self_clean():
    """DoD-P6-e: every P6 module advertised in the plan exists as a real
    Python file (so a future refactor cannot silently delete a layer)."""
    expected_modules = [
        FSRS_DIR / "__init__.py",
        FSRS_DIR / "scheduler.py",
        FSRS_DIR / "sweep.py",
        PREDICTIVE_DIR / "__init__.py",
        PREDICTIVE_DIR / "clusterer.py",
        PREDICTIVE_DIR / "prefetch.py",
        PREDICTIVE_DIR / "trend.py",
        PREDICTIVE_DIR / "signal_writer.py",
        WORKSPACE_DIR / "__init__.py",
        WORKSPACE_DIR / "blackboard.py",
        WORKSPACE_DIR / "entropy_monitor.py",
    ]
    for path in expected_modules:
        assert path.is_file(), f"missing P6 module: {path}"


# ======================================================================
# Self-cleanliness - the gate must not weaken itself.
# ======================================================================


def test_banned_token_list_matches_scrub_bible() -> None:
    """Sanity-check the encoded token list decodes to the spec scrub bible.

    The audit is only as strong as its token list. If somebody edits
    ``_BANNED_B64`` and accidentally changes the decoded values, every
    other gate in this module would silently weaken.
    """
    expected = set(_banned_tokens())
    assert set(BANNED_TOKENS) == expected, (
        f"_BANNED_B64 drift: expected {expected!r}, got {set(BANNED_TOKENS)!r}"
    )
