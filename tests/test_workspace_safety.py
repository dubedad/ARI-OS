"""Regression tests: a workspace-scoped install must stay inside the workspace.

These cover the defects found when installing ARI-OS against a single project
directory rather than the user's global Claude config:

1. the generated SessionStart hook was shell-commented-out, so it never ran;
2. ``--dry-run`` crashed instead of reporting its plan;
3. a workspace-scoped install still wrote to global Codex/Gemini configs;
4. the Claude MCP registration landed where Claude Code does not read it;
5. an ``--update`` re-introduced 1 and 3 over a working install.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ari_os import install, paths


REPO = Path(__file__).resolve().parent.parent


@pytest.fixture()
def workspace(tmp_path, monkeypatch):
    """A project directory whose .claude dir is the install target."""
    ws = tmp_path / "project"
    (ws / ".claude").mkdir(parents=True)
    monkeypatch.setenv("ARI_OS_CLAUDE_DIR", str(ws / ".claude"))
    monkeypatch.setenv("ARI_OS_HOME", str(tmp_path / "state"))
    return ws


@pytest.fixture()
def global_roots(tmp_path, monkeypatch):
    """Populated global Codex/Gemini configs that must survive untouched."""
    codex = tmp_path / "codex"
    gemini = tmp_path / "gemini"
    codex.mkdir()
    gemini.mkdir()
    codex_cfg = codex / "config.toml"
    gemini_cfg = gemini / "settings.json"
    codex_cfg.write_text('[mcp_servers.user_owned]\ncommand = "node"\nargs = []\n')
    gemini_cfg.write_text(json.dumps({"mcpServers": {"user_owned": {"command": "node"}}}))
    monkeypatch.setenv("CODEX_HOME", str(codex))
    monkeypatch.setenv("GEMINI_DIR", str(gemini))
    return {"codex": codex_cfg, "gemini": gemini_cfg}


# --- 1. SessionStart hook must be executable -------------------------------

def test_session_start_hook_is_executable_not_commented(workspace):
    """The hook command must run, not be swallowed by a leading '#'."""
    install.apply(install.plan_actions(REPO), dry_run=False, bootstrap_brain=False)
    settings = json.loads((workspace / ".claude" / "settings.json").read_text())
    cmd = settings["hooks"]["SessionStart"][0]["hooks"][0]["command"]
    assert not cmd.lstrip().startswith("#"), (
        f"SessionStart command is a shell comment and will never run: {cmd!r}"
    )
    assert "ari_os.hooks.session_start_cortex" in cmd


def test_session_start_hook_is_idempotent(workspace):
    """Installing twice must not stack up duplicate ARI-OS hooks."""
    install.apply(install.plan_actions(REPO), dry_run=False, bootstrap_brain=False)
    install.apply(install.plan_actions(REPO), dry_run=False, bootstrap_brain=False)
    settings = json.loads((workspace / ".claude" / "settings.json").read_text())
    entries = [
        h
        for group in settings["hooks"]["SessionStart"]
        for h in group.get("hooks", [])
        if "session_start_cortex" in h.get("command", "")
    ]
    assert len(entries) == 1, f"expected one ARI-OS hook, found {len(entries)}"


# --- 2. Dry run must report and write nothing ------------------------------

def test_dry_run_reports_every_target_and_exits_clean(workspace, global_roots, capsys):
    """--dry-run must not raise, and must name every planned destination."""
    reported = install.apply(
        install.plan_actions(REPO), dry_run=True, register_mcp=True
    )
    # main() unpacks each item as a (kind, destination) pair.
    for item in reported:
        assert len(item) == 2, f"dry-run emitted a non-pair item: {item!r}"
    kinds = {kind for kind, _dst in reported}
    assert {"skill", "command", "settings", "claude_md"} <= kinds


def test_dry_run_writes_nothing_anywhere(workspace, global_roots):
    before = {p: p.read_text() for p in global_roots.values()}
    install.apply(install.plan_actions(REPO), dry_run=True, register_mcp=True)
    assert not (workspace / ".claude" / "settings.json").exists()
    assert not (workspace / ".mcp.json").exists()
    for path, text in before.items():
        assert path.read_text() == text, f"dry run mutated {path}"


# --- 3. Global configs must stay untouched ---------------------------------

def test_workspace_install_leaves_global_configs_untouched(workspace, global_roots):
    """The headline defect: a scoped install must not reach global harnesses."""
    before = {p: p.read_text() for p in global_roots.values()}
    install.apply(
        install.plan_actions(REPO), dry_run=False, register_mcp=True,
        bootstrap_brain=False,
    )
    for path, text in before.items():
        assert path.read_text() == text, (
            f"workspace-scoped install modified global config {path}"
        )


def test_global_harness_registration_requires_explicit_opt_in(workspace, global_roots):
    """Global registration must exist only behind an unmistakable flag."""
    install.apply(
        install.plan_actions(REPO), dry_run=False, register_mcp=True,
        register_global_harnesses=True, bootstrap_brain=False,
    )
    assert "ari-os-cortex" in global_roots["codex"].read_text()
    assert "ari-os-cortex" in json.loads(global_roots["gemini"].read_text())["mcpServers"]


# --- 4. Claude MCP must land where Claude Code reads it --------------------

def test_mcp_registration_lands_at_workspace_root(workspace, global_roots):
    """Claude Code reads .mcp.json at the project root, not inside .claude/."""
    install.apply(
        install.plan_actions(REPO), dry_run=False, register_mcp=True,
        bootstrap_brain=False,
    )
    root_mcp = workspace / ".mcp.json"
    assert root_mcp.exists(), "no .mcp.json at the workspace root"
    assert not (workspace / ".claude" / ".mcp.json").exists(), (
        "wrote .mcp.json inside .claude/, where Claude Code does not read it"
    )
    servers = json.loads(root_mcp.read_text())["mcpServers"]
    assert "ari-os-cortex" in servers
    # Must name a concrete interpreter, not a bare python3 off $PATH.
    assert servers["ari-os-cortex"]["command"] != "python3"


# --- 5. Update must not regress a working install --------------------------

def test_update_preserves_working_hook_and_stays_local(workspace, global_roots):
    install.apply(
        install.plan_actions(REPO), dry_run=False, register_mcp=True,
        bootstrap_brain=False,
    )
    before = {p: p.read_text() for p in global_roots.values()}
    install.update(register_mcp=True)
    settings = json.loads((workspace / ".claude" / "settings.json").read_text())
    cmd = settings["hooks"]["SessionStart"][0]["hooks"][0]["command"]
    assert not cmd.lstrip().startswith("#"), "update re-broke the SessionStart hook"
    for path, text in before.items():
        assert path.read_text() == text, f"update modified global config {path}"


# --- 6. Dependency bound must be declared, not left to the installer -------

def test_pyproject_pins_mcp_below_2():
    """mcp 2.x removed mcp.server.FastMCP, which the cortex server imports."""
    text = (REPO / "pyproject.toml").read_text()
    assert "mcp>=1.0,<2" in text or 'mcp<2' in text, (
        "pyproject does not bound mcp below 2.0; the memory server will not start"
    )


# --- 7. Documented CLI commands must exist ---------------------------------

def test_docs_do_not_reference_nonexistent_cli_commands():
    """README and the installed CLAUDE.md block must use real CLI verbs."""
    from ari_os.tools.cortex import cortex as cortex_cli

    real = set(cortex_cli.main.commands)
    assert {"ingest", "retrieve"} <= real
    for name, text in (
        ("README.md", (REPO / "README.md").read_text()),
        ("CLAUDE_BODY", install.CLAUDE_BODY),
    ):
        for bogus in ("cortex recall", "cortex remember"):
            assert bogus not in text, (
                f"{name} documents `{bogus}`, which is not a Cortex CLI command"
            )


# --- 8. Status line must name a working interpreter ------------------------

def test_statusline_uses_a_resolvable_interpreter(workspace):
    """A bare 'python3' is rarely the interpreter ARI-OS was installed into."""
    import subprocess
    import sys

    install.apply(install.plan_actions(REPO), dry_run=False, bootstrap_brain=False)
    settings = json.loads((workspace / ".claude" / "settings.json").read_text())
    cmd = settings["statusLine"]["command"]
    assert not cmd.startswith("python3 "), (
        f"status line uses a bare python3 off $PATH: {cmd!r}"
    )
    assert cmd.startswith(sys.executable)
    payload = json.dumps({
        "model": {"display_name": "m"},
        "workspace": {"current_dir": str(workspace)},
        "context": {"percent_remaining": 50},
    })
    proc = subprocess.run(
        cmd.split(), input=payload, capture_output=True, text=True, timeout=60
    )
    assert proc.returncode == 0, proc.stderr[-300:]
    assert "ModuleNotFoundError" not in proc.stderr
    assert proc.stdout.strip(), "status line produced no output"
