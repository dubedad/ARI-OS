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


def apply(actions, dry_run: bool):
    if dry_run:
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
        bk = ch["backup"]
        if bk:
            shutil.copy2(bk, dst)
        elif dst.exists():
            dst.unlink()
    mf.unlink()


def uninstall(purge_keys: bool = False) -> None:
    revert()
    if purge_keys:
        cfg = paths.state_home() / "config.json"
        if cfg.exists():
            cfg.unlink()


def update() -> None:
    # Re-apply from the repo; config.json + keychain keys are never touched.
    apply(plan_actions(_repo_root()), dry_run=False)


def main() -> None:
    ap = argparse.ArgumentParser(prog="install")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--revert", action="store_true")
    ap.add_argument("--uninstall", action="store_true")
    ap.add_argument("--update", action="store_true")
    ap.add_argument("--purge-keys", action="store_true")
    a = ap.parse_args()
    if a.revert:
        revert()
        print("Reverted last ARI-OS change.")
        return
    if a.uninstall:
        uninstall(a.purge_keys)
        print("ARI-OS uninstalled.")
        return
    if a.update:
        update()
        print("ARI-OS updated.")
        return
    actions = apply(plan_actions(_repo_root()), dry_run=a.dry_run)
    verb = "Would apply" if a.dry_run else "Applied"
    for kind, dst in actions:
        print(f"{verb}: {kind} -> {dst}")


if __name__ == "__main__":
    main()
