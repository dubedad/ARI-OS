"""ARI-OS Cortex — click CLI: ``ingest``, ``retrieve``, ``mode``.

Public port + scrub of the heavy brain's CLI. Subcommands map 1:1 to the
retrieval spine:

- ``ingest`` — index a file or sweep default roots (writes chunks + vectors).
- ``retrieve`` — run the hybrid (FTS+vec, region rerank, divisive-norm,
  kg_expand) pipeline and print the assembled regioned block.
- ``mode`` — list / get / set / auto the active cognitive mode for a cwd.

The mesh / distiller / dream / wander / kg subcommands of the private engine
are intentionally NOT ported — ARI-OS is a single-machine brain.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import click

from .config import brain_db_path, state_home
from .db import init_db


@click.group()
def main() -> None:
    """ARI-OS Cortex — heavy single-machine brain."""


# ---------------------------------------------------------------------------
# ingest
# ---------------------------------------------------------------------------


@main.command()
@click.option("--rebuild", is_flag=True, help="Wipe and recreate the brain DB before indexing.")
@click.option("--path", "path_filter", default=None, help="Ingest a single file (auto-detect extension).")
@click.option("--dry-run", is_flag=True, help="Print what would be indexed without writing.")
def ingest(rebuild: bool, path_filter: str | None, dry_run: bool) -> None:
    """Index transcripts (default sweep) or a single file."""
    from .embed import EmbedClient
    from .index import index_file, index_sweep, set_markdown_indexing

    db = brain_db_path()
    if dry_run:
        click.echo(f"[dry-run] would index to {db}")
        return

    # Auto-enable repo-file ingest for single-file invocations on a markdown
    # path; sweep mode stays transcript-only (no surprise repo sweeps).
    if path_filter and Path(path_filter).suffix != ".jsonl":
        set_markdown_indexing(True)

    if rebuild and db.exists():
        db.unlink()
    init_db(db)

    emb = EmbedClient()
    if path_filter:
        p = Path(path_filter)
        layer = "semantic"
        try:
            chunk_ids = index_file(db, p, layer, emb)
        except PermissionError as e:
            click.echo(f"error: {e}", err=True)
            sys.exit(2)
        click.echo(f"indexed: {p} ({len(chunk_ids)} chunks)")
        return

    stats = index_sweep(db, embed_client=emb)
    click.echo(json.dumps(stats))


# ---------------------------------------------------------------------------
# retrieve
# ---------------------------------------------------------------------------


@main.command()
@click.option("--query", "-q", required=True)
@click.option("--cwd", default=None, help="Working directory (sets the workspace / posture gate).")
@click.option("--branch", default=None)
@click.option("--mode", default="default", show_default=True)
@click.option("--k", "k_vector", default=12, show_default=True, type=int)
@click.option("--token-budget", default=4000, show_default=True, type=int)
@click.option("--kg-expand", is_flag=True, help="Surface chunks that share kg_entities with vec hits.")
@click.option(
    "--harness",
    type=click.Choice(["claude", "codex", "kimi"]),
    default=None,
    help="Filter results to skills compatible with this harness.",
)
@click.option(
    "--posture",
    type=click.Choice(["tunnel", "global", "auto"]),
    default="auto",
    show_default=True,
    help="Retrieval posture: tunnel (workspace-local), global (full corpus), auto.",
)
@click.option("--session-id", default=None)
def retrieve(
    query: str,
    cwd: str | None,
    branch: str | None,
    mode: str,
    k_vector: int,
    token_budget: int,
    kg_expand: bool,
    harness: str | None,
    posture: str,
    session_id: str | None,
) -> None:
    """Run the hybrid retrieval pipeline and print the regioned context block."""
    from . import retrieve as _retrieve

    db = brain_db_path()
    if not db.exists():
        click.echo(f"## Brain — not yet initialised (db missing at {db})")
        return

    try:
        _posture_val: str | None = None
        if posture == "auto":
            from .mode_router import classify_posture
            from .mode_routing import load_routing_config
            try:
                kws = load_routing_config().keywords
            except Exception:
                kws = {}
            pd = classify_posture(query, kws)
            _posture_val = pd.posture
        else:
            _posture_val = posture

        result = _retrieve.retrieve(
            db,
            query=query,
            cwd=cwd,
            branch=branch,
            mode=mode,
            k_vector=k_vector,
            token_budget=token_budget,
            kg_expand=kg_expand,
            posture=_posture_val,
            session_id=session_id,
        )
        chunks = _retrieve.filter_by_harness(result.chunks, harness=harness)
        click.echo(_retrieve.format_for_harness(
            chunks, harness=harness, mode=mode,
            sufficiency=result.sufficiency, reason=result.reason,
            posture_offer=result.posture_offer))
    except Exception as e:  # never block the consumer
        click.echo(f"## Brain — retrieval failed: {e}", err=True)


# ---------------------------------------------------------------------------
# mode
# ---------------------------------------------------------------------------


@main.group()
def mode() -> None:
    """Cognitive modes — overlay retrieval parameter sets."""


@mode.command("list")
def mode_list() -> None:
    """List available modes."""
    from .modes.loader import list_modes as _list
    for m in _list():
        click.echo(m)


@mode.command("get")
@click.option("--cwd", default=None, help="cwd to inspect (default: $PWD).")
def mode_get(cwd: str | None) -> None:
    """Print the active mode for the given cwd (or $PWD)."""
    from .modes.loader import active_mode_for_cwd
    click.echo(active_mode_for_cwd(cwd or os.getcwd(), home_dir=state_home()))


@mode.command("set")
@click.argument("name")
@click.option("--cwd", default=None, help="cwd to set the mode for (default: $PWD).")
def mode_set(name: str, cwd: str | None) -> None:
    """Set the active mode for the current cwd (manual; locks out auto-shift)."""
    import time as _time
    from .mode_state import write_manual_lock
    from .modes.loader import list_modes, set_active_mode

    if name not in list_modes():
        raise click.UsageError(f"unknown mode '{name}'. Available: {', '.join(list_modes())}")
    target_cwd = cwd or os.getcwd()
    set_active_mode(target_cwd, name, home_dir=state_home())
    write_manual_lock(state_home(), target_cwd, int(_time.time()) + 1200)  # 20-min manual lock
    click.echo(f"mode set: {name} (cwd={target_cwd})")


@mode.command("auto")
@click.option("--prompt", default=None)
@click.option("--cwd", default=None, help="cwd to decide for (default: $PWD).")
@click.option("--skill", default=None)
@click.option("--session-id", default=None)
def mode_auto(prompt: str | None, cwd: str | None, skill: str | None, session_id: str | None) -> None:
    """Auto-shift cognitive mode from situation signals (universal entry point)."""
    import time as _time
    from .mode_router import Signals, ThrashPolicy, decide_mode, should_switch
    from .mode_routing import load_routing_config
    from .mode_state import load_state, read_manual_lock, save_state
    from .modes.loader import active_mode_for_cwd, list_modes, set_active_mode

    target_cwd = cwd or os.getcwd()
    home = state_home()
    sid = session_id or hashlib.sha1(str(target_cwd).encode()).hexdigest()
    try:
        cfg = load_routing_config()
    except Exception:
        return  # no-op on missing/broken config — never block a prompt

    state = load_state(home)
    sess = dict(state.get(sid) or {})
    now = int(_time.time())
    if skill:
        # Namespaced skills (e.g. "superpowers:brainstorming") — strip the prefix.
        skill = skill.split(":")[-1]
        sess["last_skill"] = skill
        sess["last_skill_at"] = now

    signals = Signals(skill=sess.get("last_skill"), cwd=target_cwd, prompt=prompt)
    current = active_mode_for_cwd(target_cwd, home_dir=home)
    decision = decide_mode(signals, current, cfg)

    if decision.mode not in list_modes():
        state[sid] = sess
        save_state(home, state)
        return

    lock = read_manual_lock(home, target_cwd)
    switch, sess = should_switch(decision, current, sess, now, ThrashPolicy(), manual_lock_until=lock)
    if switch:
        set_active_mode(target_cwd, decision.mode, home_dir=home)
        click.echo(f"🧠 mode → {decision.mode} ({decision.reason})")
    state[sid] = sess
    save_state(home, state)


if __name__ == "__main__":  # pragma: no cover
    main()
