"""ARI-OS installer: copy skills/commands, register statusline, manage a
CLAUDE.md block — all backed up + recorded so --revert / --uninstall / --update
are exact. Non-destructive: edits stay inside managed markers; settings.json is
parsed + merged, never rewritten."""
from __future__ import annotations
import argparse, hashlib, json, os, re, shutil, sys
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
from urllib import request
from . import paths

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 compatibility.
    tomllib = None

START = "<!-- ARI-OS:start -->"
END = "<!-- ARI-OS:end -->"
_BLOCK_RE = re.compile(re.escape(START) + r".*?" + re.escape(END), re.DOTALL)

CLAUDE_BODY = ("# ARI-OS\n"
               "Orchestrator-first workflow: brainstorm -> plan -> dispatch "
               "background workers -> watch -> review -> ship.\n"
               "Skills: brainstorm, handoff, advisor, teach, remember, recall, dream. "
               "Memory: `python3 -m ari_os.tools.cortex recall \"<query>\"` / "
               "`remember \"<note>\"`. Routines: /morning, /night. "
               "Monitor: `python3 -m ari_os.tools.monitor`.")

SUPPORTED_TARGETS = ("claude", "codex", "gemini", "kimi", "custom")


@dataclass(frozen=True)
class AgentTarget:
    name: str
    root: Path
    instruction_file: str
    supports_skills: bool = False
    supports_commands: bool = False
    supports_status_settings: bool = False
    supports_mcp: bool = True


def resolve_agent_target(target: str | None = None, custom_dir: str | os.PathLike | None = None) -> AgentTarget:
    """Resolve installer target metadata without touching the filesystem."""
    name = target or os.environ.get("ARI_OS_AGENT_TARGET") or "claude"
    if name not in SUPPORTED_TARGETS:
        raise ValueError(f"unsupported agent target: {name}")
    root = paths.agent_config_dir(name, custom_dir)
    if name == "claude":
        return AgentTarget(
            name=name,
            root=root,
            instruction_file="CLAUDE.md",
            supports_skills=True,
            supports_commands=True,
            supports_status_settings=True,
        )
    if name == "codex":
        return AgentTarget(name=name, root=root, instruction_file="AGENTS.md", supports_skills=True)
    if name == "gemini":
        return AgentTarget(name=name, root=root, instruction_file="GEMINI.md")
    if name == "kimi":
        return AgentTarget(name=name, root=root, instruction_file="AGENTS.md")
    return AgentTarget(name=name, root=root, instruction_file="AGENTS.md", supports_mcp=False)


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _strip_blocks(text: str) -> str:
    cleaned = _BLOCK_RE.sub("", text)
    return cleaned.replace(START, "").replace(END, "")


def inject_block(text: str, body: str) -> str:
    block = f"{START}\n{body}\n{END}"
    base = _strip_blocks(text).rstrip("\n")
    sep = "" if base == "" else "\n\n"
    return f"{base}{sep}{block}\n"


def _chmod_private_file(path: Path) -> None:
    try:
        Path(path).chmod(0o600)
    except OSError:
        pass


def _write_text_private(path: Path, text: str) -> None:
    paths.write_private(path, text)


def _write_json_private(path: Path, data: dict) -> None:
    _write_text_private(path, json.dumps(data, indent=2))


def _sha256_file(path: Path) -> str | None:
    try:
        h = hashlib.sha256()
        with Path(path).open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def backup(path) -> Path | None:
    path = Path(path)
    if not path.exists():
        return None
    dest_dir = paths.backups_dir() / _ts()
    try:
        paths.ensure_private_dir(dest_dir)
    except OSError:
        return None
    dest = dest_dir / path.name
    if dest.exists():
        stem = path.stem
        suffix = path.suffix
        i = 1
        while dest.exists():
            dest = dest_dir / f"{stem}-{i}{suffix}"
            i += 1
    try:
        shutil.copy2(path, dest)
    except OSError:
        return None
    _chmod_private_file(dest)
    return dest


def _write_manifest_atomic(changes: list[dict], complete: bool = False) -> None:
    """Persist the install journal with a temp file + atomic replace."""
    mf = paths.installed_manifest()
    paths.ensure_private_dir(mf.parent)
    manifest = {
        "version": _version(_repo_root()),
        "ts": _ts(),
        "complete": complete,
        "changes": changes,
    }
    tmp = mf.with_name(f".{mf.name}.tmp")
    paths.write_private(tmp, json.dumps(manifest, indent=2))
    os.replace(tmp, mf)
    _chmod_private_file(mf)


def _record_change(
    changes: list[dict],
    path: Path | str,
    backup_path: Path | None,
    **extra,
) -> None:
    change = {"path": str(path), "backup": str(backup_path) if backup_path else None}
    if backup_path:
        change["backup_sha256"] = _sha256_file(backup_path)
    change.update(extra)
    changes.append(change)
    _write_manifest_atomic(changes, complete=False)


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
MCP_SERVER_MODULE = "ari_os.tools.cortex.mcp_server"
MCP_SERVER_ARGS = ["-m", MCP_SERVER_MODULE, "stdio"]

# Use the interpreter that ran the installer: it has ari_os + the heavy deps
# (mcp, sqlite_vec, scikit-learn). PYTHONPATH keeps the editable source importable.
_ARI_OS_ROOT = str(Path(__file__).resolve().parent.parent)
MCP_SERVER_COMMAND = sys.executable or "python3"
MCP_SERVER_ENV = {"PYTHONPATH": _ARI_OS_ROOT}


def _mcp_server_entry() -> dict:
    """The single ARI-OS Cortex MCP server entry we own (stdio transport)."""
    return {
        "command": MCP_SERVER_COMMAND,
        "args": MCP_SERVER_ARGS,
        "env": MCP_SERVER_ENV,
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


def _write_mcp_servers_with_backup(register: bool = True) -> tuple[Path, Path | None] | None:
    """Write ``$CLAUDE_DIR/.mcp.json`` registering the ARI-OS Cortex server.

    Returns the path on success, or ``None`` if not registered (``register=False``).
    Idempotent: a prior ARI-OS entry is replaced in place; non-ARI-OS
    entries are preserved verbatim. Creates the file (with the ARI-OS
    entry) if it does not exist.
    """
    if not register:
        return None
    cd = paths.claude_dir()
    try:
        paths.ensure_private_dir(cd)
    except OSError:
        return None
    mcp_json = cd / ".mcp.json"
    existing: dict = {}
    if mcp_json.exists():
        try:
            existing = json.loads(mcp_json.read_text() or "{}")
        except (json.JSONDecodeError, OSError):
            existing = {}
    b = backup(mcp_json)  # best-effort; no-op if file didn't exist
    try:
        _write_json_private(mcp_json, merge_mcp_servers(existing))
    except OSError:
        return None
    return mcp_json, b


def write_mcp_servers(register: bool = True) -> Path | None:
    result = _write_mcp_servers_with_backup(register=register)
    return result[0] if result else None


def _config_dir(env_var: str, default: str, create_explicit: bool = True) -> Path | None:
    """Return a harness config dir, creating only when explicitly configured."""
    configured = os.environ.get(env_var)
    if configured:
        path = Path(os.path.expanduser(configured))
        if create_explicit:
            paths.ensure_private_dir(path)
        return path
    path = Path(os.path.expanduser(default))
    return path if path.is_dir() else None


def _write_json_mcp_servers_with_backup(config_path: Path) -> tuple[Path, Path | None] | None:
    existing: dict = {}
    if config_path.exists():
        try:
            existing = json.loads(config_path.read_text() or "{}")
        except (json.JSONDecodeError, OSError):
            return None
    b = backup(config_path)
    try:
        _write_json_private(config_path, merge_mcp_servers(existing))
    except OSError:
        return None
    return config_path, b


def _write_json_mcp_servers(config_path: Path) -> Path | None:
    result = _write_json_mcp_servers_with_backup(config_path)
    return result[0] if result else None


def _strip_codex_mcp_server_toml(text: str) -> str:
    """Remove our Codex MCP TOML table, preserving all user-owned tables."""
    owned = f"mcp_servers.{MCP_SERVER_NAME}"
    kept: list[str] = []
    skipping = False
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            table = stripped.strip("[]").strip()
            skipping = table == owned or table.startswith(f"{owned}.")
        if not skipping:
            kept.append(line)
    return "".join(kept).rstrip()


def _codex_mcp_server_toml() -> str:
    lines = [
        f"[mcp_servers.{MCP_SERVER_NAME}]",
        f"command = {json.dumps(MCP_SERVER_COMMAND)}",
        f"args = {json.dumps(MCP_SERVER_ARGS)}",
        "",
        f"[mcp_servers.{MCP_SERVER_NAME}.env]",
    ]
    for k, v in MCP_SERVER_ENV.items():
        lines.append(f"{k} = {json.dumps(v)}")
    return "\n".join(lines) + "\n"


def _write_codex_mcp_server_with_backup(config_dir: Path | None = None) -> tuple[Path, Path | None] | None:
    codex_dir = config_dir or _config_dir("CODEX_HOME", "~/.codex")
    if codex_dir is None:
        return None
    paths.ensure_private_dir(codex_dir)
    config_toml = codex_dir / "config.toml"
    text = config_toml.read_text() if config_toml.exists() else ""
    if tomllib is not None and text:
        try:
            tomllib.loads(text)
        except tomllib.TOMLDecodeError:
            return None
    elif tomllib is None and text:
        return None
    b = backup(config_toml)
    stripped = _strip_codex_mcp_server_toml(text)
    prefix = f"{stripped}\n\n" if stripped else ""
    try:
        _write_text_private(config_toml, prefix + _codex_mcp_server_toml())
    except OSError:
        return None
    return config_toml, b


def _write_codex_mcp_server() -> Path | None:
    result = _write_codex_mcp_server_with_backup()
    return result[0] if result else None


def _write_gemini_mcp_server_with_backup(config_dir: Path | None = None) -> tuple[Path, Path | None] | None:
    gemini_dir = config_dir or _config_dir("GEMINI_DIR", "~/.gemini")
    if gemini_dir is None:
        return None
    paths.ensure_private_dir(gemini_dir)
    return _write_json_mcp_servers_with_backup(gemini_dir / "settings.json")


def _write_gemini_mcp_server() -> Path | None:
    result = _write_gemini_mcp_server_with_backup()
    return result[0] if result else None


def _write_kimi_mcp_server_with_backup(config_dir: Path | None = None) -> tuple[Path, Path | None] | None:
    if config_dir is None and not os.environ.get("KIMI_CODE_HOME"):
        return None
    kimi_dir = config_dir or _config_dir("KIMI_CODE_HOME", "~/.kimi-code")
    if kimi_dir is None:
        return None
    paths.ensure_private_dir(kimi_dir)
    return _write_json_mcp_servers_with_backup(kimi_dir / "mcp.json")


def _write_kimi_mcp_server() -> Path | None:
    result = _write_kimi_mcp_server_with_backup()
    return result[0] if result else None


def write_all_mcp_registrations(register: bool = True) -> dict[str, str]:
    """Register the Cortex MCP server into every supported local harness."""
    if not register:
        return {}
    written: dict[str, str] = {}
    claude = write_mcp_servers(register=True)
    if claude is not None:
        written["claude"] = str(claude)
    codex = _write_codex_mcp_server()
    if codex is not None:
        written["codex"] = str(codex)
    gemini = _write_gemini_mcp_server()
    if gemini is not None:
        written["gemini"] = str(gemini)
    kimi = _write_kimi_mcp_server()
    if kimi is not None:
        written["kimi"] = str(kimi)
    return written


def _write_all_mcp_registrations_recorded(changes: list[dict]) -> dict[str, str]:
    """Register MCP servers while journaling each touched config file."""
    written: dict[str, str] = {}
    writers = (
        ("claude", lambda: _write_mcp_servers_with_backup(register=True)),
        ("codex", _write_codex_mcp_server_with_backup),
        ("gemini", _write_gemini_mcp_server_with_backup),
        ("kimi", _write_kimi_mcp_server_with_backup),
    )
    for harness, writer in writers:
        result = writer()
        if result is None:
            continue
        mcp_path, b = result
        _record_change(changes, mcp_path, b, kind="mcp", harness=harness)
        written[harness] = str(mcp_path)
    return written


def _write_target_mcp_registration_recorded(
    changes: list[dict],
    spec: AgentTarget,
) -> dict[str, str]:
    if spec.name == "custom":
        return {}
    writers = {
        "claude": lambda: _write_mcp_servers_with_backup(register=True),
        "codex": lambda: _write_codex_mcp_server_with_backup(spec.root),
        "gemini": lambda: _write_gemini_mcp_server_with_backup(spec.root),
        "kimi": lambda: _write_kimi_mcp_server_with_backup(spec.root),
    }
    result = writers[spec.name]()
    if result is None:
        return {}
    mcp_path, b = result
    extra = {"kind": "mcp", "harness": spec.name}
    if spec.name != "claude":
        extra["target_root"] = str(spec.root)
    _record_change(changes, mcp_path, b, **extra)
    return {spec.name: str(mcp_path)}


def _unregister_json_mcp_server(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        existing = json.loads(path.read_text() or "{}")
    except (json.JSONDecodeError, OSError):
        return False
    servers = existing.get("mcpServers") or {}
    if MCP_SERVER_NAME not in servers:
        return False
    backup(path)
    del servers[MCP_SERVER_NAME]
    existing["mcpServers"] = servers
    try:
        _write_json_private(path, existing)
    except OSError:
        return False
    return True


def _unregister_codex_mcp_server() -> bool:
    codex_dir = _config_dir("CODEX_HOME", "~/.codex", create_explicit=False)
    if codex_dir is None:
        return False
    config_toml = codex_dir / "config.toml"
    if not config_toml.exists():
        return False
    text = config_toml.read_text()
    stripped = _strip_codex_mcp_server_toml(text)
    if stripped == text.rstrip():
        return False
    backup(config_toml)
    try:
        _write_text_private(config_toml, f"{stripped}\n" if stripped else "")
    except OSError:
        return False
    return True


def _unregister_gemini_mcp_server() -> bool:
    gemini_dir = _config_dir("GEMINI_DIR", "~/.gemini", create_explicit=False)
    if gemini_dir is None:
        return False
    return _unregister_json_mcp_server(gemini_dir / "settings.json")


def _unregister_kimi_mcp_server() -> bool:
    kimi_dir = _config_dir("KIMI_CODE_HOME", "~/.kimi-code", create_explicit=False)
    if kimi_dir is None:
        return False
    return _unregister_json_mcp_server(kimi_dir / "mcp.json")


def unregister_mcp_server() -> bool:
    """Remove the ARI-OS Cortex MCP server entry from all registered harnesses.

    Returns True if the entry was present and removed, False otherwise.
    Non-ARI-OS entries are preserved.
    """
    cd = paths.claude_dir()
    removed = _unregister_json_mcp_server(cd / ".mcp.json")
    removed = _unregister_codex_mcp_server() or removed
    removed = _unregister_gemini_mcp_server() or removed
    removed = _unregister_kimi_mcp_server() or removed
    return removed


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


def _emit_target_skip_notes(spec: AgentTarget) -> None:
    if spec.supports_skills is False:
        print(f"{spec.name}: skills not supported, skipped", file=sys.stderr)
    if spec.supports_commands is False:
        print(f"{spec.name}: commands not supported, skipped", file=sys.stderr)
    if spec.supports_status_settings is False:
        print(f"{spec.name}: statusline hooks not supported, skipped", file=sys.stderr)
    if spec.supports_mcp is False:
        print(f"{spec.name}: MCP registration not supported, skipped", file=sys.stderr)


def plan_actions(
    repo,
    target: str | None = None,
    custom_dir: str | os.PathLike | None = None,
) -> list[tuple[str, Path, Path]]:
    repo = Path(repo)
    spec = resolve_agent_target(target, custom_dir)
    cd = spec.root
    actions: list[tuple[str, Path, Path]] = []
    if spec.supports_skills:
        for skill in sorted((repo / "ari_os" / "skills").glob("*/SKILL.md")):
            actions.append(("skill", skill, cd / "skills" / skill.parent.name / "SKILL.md"))
    if spec.supports_commands:
        for cmd in sorted((repo / "ari_os" / "commands").glob("*.md")):
            actions.append(("command", cmd, cd / "commands" / cmd.name))
    if spec.supports_status_settings:
        actions.append(("settings", repo, cd / "settings.json"))
    instruction_kind = "claude_md" if spec.name == "claude" else "instruction"
    actions.append((instruction_kind, repo, cd / spec.instruction_file))
    return actions


def _soft_check_ollama(config) -> None:
    """Best-effort Ollama reachability hint; never blocks install."""
    try:
        request.urlopen(f"{config.OLLAMA_URL.rstrip('/')}/api/tags", timeout=0.25).close()
    except Exception:
        print(
            f"ARI-OS hint: Ollama is not reachable at {config.OLLAMA_URL}; "
            "install continued, but local LLM recall may be offline.",
            file=sys.stderr,
        )


def bootstrap_heavy_brain(llm: str = "ollama", ears: bool = False, lens: bool = False) -> Path:
    """Create the heavy brain and persist install-time cortex choices."""
    if llm not in {"ollama", "api", "off"}:
        raise ValueError("llm must be one of: ollama, api, off")
    from ari_os.tools.cortex import config
    from ari_os.tools.cortex.db import init_db

    brain_path = init_db(config.brain_db_path())
    config.set_config_value("cortex.llm", llm)
    if ears:
        config.set_config_value("cortex.ears", True)
    if lens:
        config.set_config_value("cortex.lens", True)
    if llm == "ollama":
        _soft_check_ollama(config)
    return brain_path


def apply(
    actions,
    dry_run: bool,
    register_mcp: bool = True,
    llm: str = "ollama",
    ears: bool = False,
    lens: bool = False,
    bootstrap_brain: bool = True,
    target: str | None = None,
    custom_dir: str | os.PathLike | None = None,
):
    spec = resolve_agent_target(target, custom_dir)
    if dry_run:
        # MCP registration: even in dry-run we report intent.
        if register_mcp:
            if spec.name == "claude":
                mcp_paths = {
                    "claude": str(paths.claude_dir() / ".mcp.json"),
                }
                codex_dir = _config_dir("CODEX_HOME", "~/.codex", create_explicit=False)
                if codex_dir is not None:
                    mcp_paths["codex"] = str(codex_dir / "config.toml")
                gemini_dir = _config_dir("GEMINI_DIR", "~/.gemini", create_explicit=False)
                if gemini_dir is not None:
                    mcp_paths["gemini"] = str(gemini_dir / "settings.json")
            elif spec.supports_mcp:
                target_mcp = {
                    "codex": spec.root / "config.toml",
                    "gemini": spec.root / "settings.json",
                    "kimi": spec.root / "mcp.json",
                }
                mcp_paths = {spec.name: str(target_mcp[spec.name])}
            else:
                mcp_paths = {}
            return [(k, str(dst)) for (k, _src, dst) in actions] + [
                (f"mcp:{harness}", MCP_SERVER_MODULE, path)
                for harness, path in mcp_paths.items()
            ]
        return [(k, str(dst)) for (k, _src, dst) in actions]
    if spec.name != "claude":
        _emit_target_skip_notes(spec)
    changes = []
    for kind, src, dst in actions:
        paths.ensure_private_dir(dst.parent)
        b = backup(dst)
        if kind in ("skill", "command"):
            shutil.copy2(src, dst)
            _chmod_private_file(dst)
        elif kind == "settings":
            existing = json.loads(dst.read_text()) if dst.exists() else {}
            _write_json_private(
                dst,
                merge_settings_with_hooks(existing, "python3 -m ari_os.tools.statusline"),
            )
        elif kind in ("claude_md", "instruction"):
            text = dst.read_text() if dst.exists() else ""
            _write_text_private(dst, inject_block(text, CLAUDE_BODY))
        extra = {}
        if spec.name != "claude":
            extra["target_root"] = str(spec.root)
        _record_change(changes, dst, b, **extra)
    # MCP server registration (default on; opt out with --no-mcp).
    if register_mcp:
        if spec.name == "claude":
            _write_all_mcp_registrations_recorded(changes)
        elif spec.supports_mcp:
            _write_target_mcp_registration_recorded(changes, spec)
    if bootstrap_brain:
        bootstrap_heavy_brain(llm=llm, ears=ears, lens=lens)
    _write_manifest_atomic(changes, complete=True)
    return [(k, str(dst)) for (k, _s, dst) in actions]


def _managed_roots(manifest: dict | None = None) -> list[Path]:
    roots = [paths.claude_dir()]
    for env_var, default in (
        ("CODEX_HOME", "~/.codex"),
        ("GEMINI_DIR", "~/.gemini"),
        ("KIMI_CODE_HOME", "~/.kimi-code"),
    ):
        cfg = _config_dir(env_var, default, create_explicit=False)
        if cfg is not None:
            roots.append(cfg)
    if manifest is not None:
        for ch in manifest.get("changes") or []:
            if not isinstance(ch, dict):
                continue
            target_root = ch.get("target_root")
            if target_root:
                roots.append(Path(target_root))
    return [p.resolve() for p in roots]


def _resolve_within_any(roots: list[Path], candidate: str) -> Path:
    last_error: ValueError | None = None
    for root in roots:
        try:
            return paths.resolve_within(root, candidate)
        except ValueError as exc:
            last_error = exc
    raise last_error or ValueError(f"path is outside managed roots: {candidate!r}")


def _load_manifest(path: Path) -> dict:
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError("installed manifest must be a JSON object")
    changes = data.get("changes")
    if not isinstance(changes, list):
        raise ValueError("installed manifest changes must be a list")
    return data


def revert() -> None:
    mf = paths.installed_manifest()
    if not mf.exists():
        print("Nothing to revert.")
        return
    try:
        manifest = _load_manifest(mf)
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"Refusing invalid install manifest: {exc}", file=sys.stderr)
        return
    roots = _managed_roots(manifest)
    backups_root = paths.backups_dir().resolve()
    for ch in reversed(manifest["changes"]):
        if not isinstance(ch, dict):
            print("Skipping invalid manifest change entry.", file=sys.stderr)
            continue
        try:
            dst = _resolve_within_any(roots, ch["path"])
        except (KeyError, TypeError, ValueError):
            print(
                f"Skipping out-of-tree manifest path: {ch.get('path')!r}",
                file=sys.stderr,
            )
            continue
        bk = ch.get("backup")
        if bk:
            try:
                backup_path = paths.resolve_within(backups_root, bk)
            except (TypeError, ValueError):
                print(f"Skipping out-of-tree backup: {bk!r}", file=sys.stderr)
                continue
            expected_hash = ch.get("backup_sha256")
            actual_hash = _sha256_file(backup_path)
            if expected_hash and actual_hash != expected_hash:
                print(f"Skipping backup with checksum mismatch: {backup_path}", file=sys.stderr)
                continue
            paths.ensure_private_dir(dst.parent)
            shutil.copy2(backup_path, dst)
            _chmod_private_file(dst)
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


def update(
    register_mcp: bool = True,
    target: str | None = None,
    custom_dir: str | os.PathLike | None = None,
) -> None:
    # Re-apply from the repo; config.json + keychain keys are never touched.
    apply(
        plan_actions(_repo_root(), target=target, custom_dir=custom_dir),
        dry_run=False,
        register_mcp=register_mcp,
        bootstrap_brain=False,
        target=target,
        custom_dir=custom_dir,
    )
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
    ap.add_argument("--llm", choices=("ollama", "api", "off"), default="ollama",
                    help="Cortex LLM backend to persist during install. "
                         "Default/recommended: ollama for local-first recall.")
    ap.add_argument("--ears", action="store_true",
                    help="Opt in to EARS capture. Default is off.")
    ap.add_argument("--lens", action="store_true",
                    help="Opt in to LENS capture. Default is off.")
    ap.add_argument("--target", choices=SUPPORTED_TARGETS,
                    help="Agent harness to install into. Defaults to ARI_OS_AGENT_TARGET or claude.")
    ap.add_argument("--dir",
                    help="Config root for --target custom.")
    a = ap.parse_args()
    try:
        target = resolve_agent_target(a.target, a.dir)
    except ValueError as exc:
        ap.error(str(exc))
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
        update(register_mcp=register_mcp, target=target.name, custom_dir=a.dir)
        print("ARI-OS updated.")
        return
    actions = apply(
        plan_actions(_repo_root(), target=target.name, custom_dir=a.dir),
        dry_run=a.dry_run,
        register_mcp=register_mcp,
        llm=a.llm,
        ears=a.ears,
        lens=a.lens,
        target=target.name,
        custom_dir=a.dir,
    )
    verb = "Would apply" if a.dry_run else "Applied"
    for kind, dst in actions:
        print(f"{verb}: {kind} -> {dst}")


if __name__ == "__main__":
    main()
