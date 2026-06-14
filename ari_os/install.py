"""ARI-OS installer: copy skills/commands, register statusline, manage a
CLAUDE.md block — all backed up + recorded so --revert / --uninstall / --update
are exact. Non-destructive: edits stay inside managed markers; settings.json is
parsed + merged, never rewritten."""
from __future__ import annotations
import argparse, json, shutil, sys
from datetime import datetime, timezone
from pathlib import Path
from . import paths

START = "<!-- ARI-OS:start -->"
END = "<!-- ARI-OS:end -->"

CLAUDE_BODY = ("# ARI-OS\n"
               "Orchestrator-first workflow: brainstorm -> plan -> dispatch "
               "background workers -> watch -> review -> ship.\n"
               "Skills: brainstorm, handoff, advisor, teach, remember, recall, dream. "
               "Memory: `python3 -m ari_os.tools.cortex recall \"<query>\"` / "
               "`remember \"<note>\"`. Routines: /morning, /night. "
               "Monitor: `python3 -m ari_os.tools.monitor`.")


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def inject_block(text: str, body: str) -> str:
    block = f"{START}\n{body}\n{END}"
    if START in text and END in text:
        pre = text[:text.index(START)]
        post = text[text.index(END) + len(END):]
        return f"{pre}{block}{post}"
    sep = "" if text.endswith("\n") or text == "" else "\n"
    return f"{text}{sep}{block}\n"


def backup(path) -> Path | None:
    path = Path(path)
    if not path.exists():
        return None
    dest_dir = paths.backups_dir() / _ts()
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / path.name
    shutil.copy2(path, dest)
    return dest


def merge_settings(existing: dict, statusline_cmd: str) -> dict:
    """Merge ARI-OS's statusline into an existing settings.json (legacy).

    Statusline-only — does NOT register the SessionStart hook. The hook
    lives in :func:`merge_settings_with_hooks` and is applied by
    :func:`apply` when the installer writes settings.json. Tests that
    assert hook-free behaviour keep the same contract.
    """
    out = dict(existing)
    out["statusLine"] = {"type": "command", "command": statusline_cmd}
    return out


def merge_settings_with_hooks(existing: dict, statusline_cmd: str) -> dict:
    """Settings merge that ALSO registers the managed SessionStart hook.

    Used by :func:`apply` when writing ``settings.json`` to ``$CLAUDE_DIR``.
    Idempotent: a prior ARI-OS SessionStart entry is replaced in place;
    non-ARI-OS hooks (e.g. PostToolUse entries) are preserved verbatim.
    """
    out = merge_settings(existing, statusline_cmd)
    hooks = dict(out.get("hooks") or {})
    ss = _strip_ari_os_session_start(hooks.get("SessionStart", []))
    ss.append(_session_start_hook_entry())
    hooks["SessionStart"] = ss
    out["hooks"] = hooks
    return out


# --- MCP server registration (added for ar.t12) -----------------------------
# The ARI-OS Cortex MCP server (brain.recall / lineage / regions / tracts /
# modes) is registered into the user's ``$CLAUDE_DIR/.mcp.json`` so LLM
# sessions can query the brain mid-session. Registered by default during
# ``install``/``update``; ``--no-mcp`` opts out.
MCP_SERVER_NAME = "ari-os-cortex"
MCP_SERVER_COMMAND = "python3"
MCP_SERVER_MODULE = "ari_os.tools.cortex.mcp_server"
MCP_SERVER_ARGS = ["-m", MCP_SERVER_MODULE, "stdio"]


def _mcp_server_entry() -> dict:
    """The single ARI-OS Cortex MCP server entry we own (stdio transport)."""
    return {
        "command": MCP_SERVER_COMMAND,
        "args": MCP_SERVER_ARGS,
    }


def _strip_ari_os_mcp_server(servers: dict) -> dict:
    """Remove any prior ARI-OS Cortex MCP server entry by command marker.

    Idempotent: a prior install is recognised by ``ari_os.tools.cortex.mcp_server``
    in the args (the module is stable across versions) and replaced in place.
    Other user-owned MCP servers (e.g. vercel, stripe) are preserved.
    """
    out = {}
    for name, entry in (servers or {}).items():
        if not isinstance(entry, dict):
            out[name] = entry
            continue
        args = entry.get("args") or []
        if MCP_SERVER_MODULE in args:
            continue
        out[name] = entry
    return out


def merge_mcp_servers(existing: dict) -> dict:
    """Merge the ARI-OS Cortex MCP server entry into an existing mcpServers map.

    Idempotent: a prior ARI-OS entry is replaced in place; non-ARI-OS
    servers are preserved verbatim. Always returns a dict with a
    ``mcpServers`` key.
    """
    base = dict(existing or {})
    servers = _strip_ari_os_mcp_server(base.get("mcpServers") or {})
    servers[MCP_SERVER_NAME] = _mcp_server_entry()
    base["mcpServers"] = servers
    return base


def write_mcp_servers(register: bool = True) -> Path | None:
    """Write ``$CLAUDE_DIR/.mcp.json`` registering the ARI-OS Cortex server.

    Returns the path on success, or ``None`` if not registered (``register=False``).
    Idempotent: a prior ARI-OS entry is replaced in place; non-ARI-OS
    entries are preserved verbatim. Creates the file (with the ARI-OS
    entry) if it does not exist.
    """
    if not register:
        return None
    cd = paths.claude_dir()
    cd.mkdir(parents=True, exist_ok=True)
    mcp_json = cd / ".mcp.json"
    existing: dict = {}
    if mcp_json.exists():
        try:
            existing = json.loads(mcp_json.read_text() or "{}")
        except (json.JSONDecodeError, OSError):
            existing = {}
    backup(mcp_json)  # best-effort; no-op if file didn't exist
    mcp_json.write_text(json.dumps(merge_mcp_servers(existing), indent=2))
    return mcp_json


def unregister_mcp_server() -> bool:
    """Remove the ARI-OS Cortex MCP server entry from ``$CLAUDE_DIR/.mcp.json``.

    Returns True if the entry was present and removed, False otherwise.
    Non-ARI-OS entries are preserved.
    """
    cd = paths.claude_dir()
    mcp_json = cd / ".mcp.json"
    if not mcp_json.exists():
        return False
    try:
        existing = json.loads(mcp_json.read_text() or "{}")
    except (json.JSONDecodeError, OSError):
        return False
    servers = existing.get("mcpServers") or {}
    if MCP_SERVER_NAME not in servers:
        return False
    backup(mcp_json)
    del servers[MCP_SERVER_NAME]
    existing["mcpServers"] = servers
    mcp_json.write_text(json.dumps(existing, indent=2))
    return True


# --- SessionStart hook registration (reversible, managed) ------------------
# We register exactly one SessionStart command hook in settings.json. The
# command is a stable Python invocation that prints the regioned brain
# context block. Re-running install/update is idempotent: any prior
# ARI-OS SessionStart entry (matched by a stable marker line) is replaced
# in place; non-ARI-OS hooks (e.g. PostToolUse entries) are preserved.
SESSION_START_HOOK_MARKER = "# ari-os-session-start"


def _session_start_hook_entry() -> dict:
    """The single ARI-OS SessionStart command hook entry we own."""
    cmd = f"{SESSION_START_HOOK_MARKER} python3 -m ari_os.hooks.session_start_cortex"
    return {
        "type": "command",
        "command": cmd,
        "timeout": 15,
    }


def _strip_ari_os_session_start(hooks_list: list) -> list:
    """Remove any prior ARI-OS SessionStart entries (marked + bare) from a list.

    Idempotent. We match on the marker comment + the module invocation, so a
    legacy install (no marker) is still recognised and replaced.
    """
    kept = []
    for entry in hooks_list or []:
        if not isinstance(entry, dict):
            kept.append(entry)
            continue
        cmd = entry.get("command", "")
        if "ari_os.hooks.session_start_cortex" in cmd:
            continue
        kept.append(entry)
    return kept


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _version(repo: Path) -> str:
    vf = Path(repo) / "ari_os" / "VERSION"
    return vf.read_text().strip() if vf.exists() else "0.0.0"


def plan_actions(repo) -> list[tuple[str, Path, Path]]:
    repo = Path(repo)
    cd = paths.claude_dir()
    actions: list[tuple[str, Path, Path]] = []
    for skill in sorted((repo / "ari_os" / "skills").glob("*/SKILL.md")):
        actions.append(("skill", skill, cd / "skills" / skill.parent.name / "SKILL.md"))
    for cmd in sorted((repo / "ari_os" / "commands").glob("*.md")):
        actions.append(("command", cmd, cd / "commands" / cmd.name))
    actions.append(("settings", repo, cd / "settings.json"))
    actions.append(("claude_md", repo, cd / "CLAUDE.md"))
    return actions


def apply(actions, dry_run: bool, register_mcp: bool = True):
    if dry_run:
        # MCP registration: even in dry-run we report intent.
        mcp_path = paths.claude_dir() / ".mcp.json"
        if register_mcp:
            return [(k, str(dst)) for (k, _src, dst) in actions] + [
                ("mcp", MCP_SERVER_MODULE, str(mcp_path))
            ]
        return [(k, str(dst)) for (k, _src, dst) in actions]
    changes = []
    for kind, src, dst in actions:
        dst.parent.mkdir(parents=True, exist_ok=True)
        b = backup(dst)
        if kind in ("skill", "command"):
            shutil.copy2(src, dst)
        elif kind == "settings":
            existing = json.loads(dst.read_text()) if dst.exists() else {}
            dst.write_text(json.dumps(
                merge_settings_with_hooks(existing, "python3 -m ari_os.tools.statusline"),
                indent=2))
        elif kind == "claude_md":
            text = dst.read_text() if dst.exists() else ""
            dst.write_text(inject_block(text, CLAUDE_BODY))
        changes.append({"path": str(dst), "backup": str(b) if b else None})
    # MCP server registration (default on; opt out with --no-mcp).
    if register_mcp:
        mcp_path = write_mcp_servers(register=True)
        if mcp_path is not None:
            changes.append({"path": str(mcp_path), "backup": None, "kind": "mcp"})
    manifest = {"version": _version(_repo_root()), "ts": _ts(), "changes": changes}
    paths.installed_manifest().parent.mkdir(parents=True, exist_ok=True)
    paths.installed_manifest().write_text(json.dumps(manifest, indent=2))
    return [(k, str(dst)) for (k, _s, dst) in actions]


def revert() -> None:
    mf = paths.installed_manifest()
    if not mf.exists():
        print("Nothing to revert.")
        return
    manifest = json.loads(mf.read_text())
    for ch in reversed(manifest["changes"]):
        dst = Path(ch["path"])
        bk = ch.get("backup")
        kind = ch.get("kind")
        if kind == "mcp":
            unregister_mcp_server()
            continue
        if bk:
            shutil.copy2(bk, dst)
        elif dst.exists():
            dst.unlink()
    mf.unlink()


def uninstall(purge_keys: bool = False) -> None:
    unregister_mcp_server()
    revert()
    if purge_keys:
        cfg = paths.state_home() / "config.json"
        if cfg.exists():
            cfg.unlink()


def update(register_mcp: bool = True) -> None:
    # Re-apply from the repo; config.json + keychain keys are never touched.
    apply(plan_actions(_repo_root()), dry_run=False, register_mcp=register_mcp)
    try:
        from ari_os.tools.cortex.config import brain_db_path
        from ari_os.tools.cortex.db import migrate

        brain_path = brain_db_path()
        if brain_path.exists():
            migrate(brain_path)
    except Exception as exc:
        print(f"ARI-OS brain migration skipped: {exc}")


def main() -> None:
    ap = argparse.ArgumentParser(prog="install")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--revert", action="store_true")
    ap.add_argument("--uninstall", action="store_true")
    ap.add_argument("--update", action="store_true")
    ap.add_argument("--purge-keys", action="store_true")
    ap.add_argument("--no-mcp", action="store_true",
                    help="Skip registering the ARI-OS Cortex MCP server.")
    a = ap.parse_args()
    register_mcp = not a.no_mcp
    if a.revert:
        revert()
        print("Reverted last ARI-OS change.")
        return
    if a.uninstall:
        uninstall(a.purge_keys)
        print("ARI-OS uninstalled.")
        return
    if a.update:
        update(register_mcp=register_mcp)
        print("ARI-OS updated.")
        return
    actions = apply(plan_actions(_repo_root()), dry_run=a.dry_run,
                    register_mcp=register_mcp)
    verb = "Would apply" if a.dry_run else "Applied"
    for kind, dst in actions:
        print(f"{verb}: {kind} -> {dst}")


if __name__ == "__main__":
    main()
