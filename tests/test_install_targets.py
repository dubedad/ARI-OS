import json
import tomllib
from pathlib import Path

import pytest

from ari_os import install, paths
from ari_os.install import MCP_SERVER_NAME, START


def _seed_repo(tmp_path):
    repo = tmp_path / "repo"
    (repo / "ari_os" / "skills" / "advisor").mkdir(parents=True)
    (repo / "ari_os" / "skills" / "advisor" / "SKILL.md").write_text(
        "---\nname: advisor\n---\n# Advisor\n"
    )
    (repo / "ari_os" / "commands").mkdir(parents=True)
    (repo / "ari_os" / "commands" / "monitor.md").write_text(
        "---\ndescription: monitor\n---\nbody\n"
    )
    (repo / "ari_os" / "VERSION").write_text("2.3.0\n")
    return repo


def test_agent_config_dir_resolves_supported_targets(tmp_path, monkeypatch):
    monkeypatch.setenv("ARI_OS_CLAUDE_DIR", str(tmp_path / "claude"))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    monkeypatch.setenv("GEMINI_DIR", str(tmp_path / "gemini"))
    monkeypatch.setenv("KIMI_CODE_HOME", str(tmp_path / "kimi"))

    assert paths.agent_config_dir("claude") == tmp_path / "claude"
    assert paths.agent_config_dir("codex") == tmp_path / "codex"
    assert paths.agent_config_dir("gemini") == tmp_path / "gemini"
    assert paths.agent_config_dir("kimi") == tmp_path / "kimi"
    assert paths.agent_config_dir("custom", tmp_path / "other") == tmp_path / "other"


def test_agent_target_honors_env_default(monkeypatch):
    monkeypatch.setenv("ARI_OS_AGENT_TARGET", "gemini")
    assert install.resolve_agent_target(None, None).name == "gemini"
    assert install.resolve_agent_target("codex", None).name == "codex"


def test_custom_target_requires_dir(monkeypatch):
    monkeypatch.setenv("ARI_OS_AGENT_TARGET", "custom")
    with pytest.raises(ValueError, match="--dir"):
        install.resolve_agent_target(None, None)


def test_invalid_agent_target_errors_cleanly(monkeypatch):
    monkeypatch.setenv("ARI_OS_AGENT_TARGET", "nope")
    with pytest.raises(ValueError, match="unsupported agent target"):
        install.resolve_agent_target(None, None)


def test_default_and_explicit_claude_plan_match_existing_layout(tmp_path, monkeypatch):
    monkeypatch.setenv("ARI_OS_CLAUDE_DIR", str(tmp_path / "claude"))
    repo = _seed_repo(tmp_path)

    default_actions = install.plan_actions(repo)
    explicit_actions = install.plan_actions(repo, target="claude")

    assert default_actions == explicit_actions
    assert ("skill", repo / "ari_os" / "skills" / "advisor" / "SKILL.md", tmp_path / "claude" / "skills" / "advisor" / "SKILL.md") in default_actions
    assert ("command", repo / "ari_os" / "commands" / "monitor.md", tmp_path / "claude" / "commands" / "monitor.md") in default_actions
    assert ("settings", repo, tmp_path / "claude" / "settings.json") in default_actions
    assert ("claude_md", repo, tmp_path / "claude" / "CLAUDE.md") in default_actions


def test_codex_target_installs_agents_md_skills_and_mcp_only(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ARI_OS_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    repo = _seed_repo(tmp_path)

    actions = install.plan_actions(repo, target="codex")
    install.apply(actions, dry_run=False, register_mcp=True, bootstrap_brain=False, target="codex")

    root = tmp_path / "codex"
    assert START in (root / "AGENTS.md").read_text()
    assert (root / "skills" / "advisor" / "SKILL.md").read_text().startswith("---")
    assert not (root / "commands").exists()
    assert (root / "config.toml").exists()
    assert MCP_SERVER_NAME in tomllib.loads((root / "config.toml").read_text())["mcp_servers"]

    notes = capsys.readouterr().err
    assert "codex: commands not supported, skipped" in notes
    assert "codex: statusline hooks not supported, skipped" in notes


def test_gemini_target_installs_gemini_md_and_settings_mcp_with_skips(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ARI_OS_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("GEMINI_DIR", str(tmp_path / "gemini"))
    repo = _seed_repo(tmp_path)

    actions = install.plan_actions(repo, target="gemini")
    install.apply(actions, dry_run=False, register_mcp=True, bootstrap_brain=False, target="gemini")

    root = tmp_path / "gemini"
    assert START in (root / "GEMINI.md").read_text()
    settings = json.loads((root / "settings.json").read_text())
    assert MCP_SERVER_NAME in settings["mcpServers"]
    assert not (root / "skills").exists()
    assert not (root / "commands").exists()

    notes = capsys.readouterr().err
    assert "gemini: skills not supported, skipped" in notes
    assert "gemini: commands not supported, skipped" in notes
    assert "gemini: statusline hooks not supported, skipped" in notes


def test_kimi_target_installs_agents_md_and_mcp_with_skips(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ARI_OS_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("KIMI_CODE_HOME", str(tmp_path / "kimi"))
    repo = _seed_repo(tmp_path)

    actions = install.plan_actions(repo, target="kimi")
    install.apply(actions, dry_run=False, register_mcp=True, bootstrap_brain=False, target="kimi")

    root = tmp_path / "kimi"
    assert START in (root / "AGENTS.md").read_text()
    mcp = json.loads((root / "mcp.json").read_text())
    assert MCP_SERVER_NAME in mcp["mcpServers"]
    assert not (root / "skills").exists()
    assert not (root / "commands").exists()

    notes = capsys.readouterr().err
    assert "kimi: skills not supported, skipped" in notes
    assert "kimi: commands not supported, skipped" in notes
    assert "kimi: statusline hooks not supported, skipped" in notes


def test_custom_target_installs_agents_md_and_reverts(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ARI_OS_HOME", str(tmp_path / "state"))
    custom_dir = tmp_path / "custom-agent"
    repo = _seed_repo(tmp_path)

    actions = install.plan_actions(repo, target="custom", custom_dir=custom_dir)
    install.apply(
        actions,
        dry_run=False,
        register_mcp=True,
        bootstrap_brain=False,
        target="custom",
        custom_dir=custom_dir,
    )

    assert START in (custom_dir / "AGENTS.md").read_text()
    assert not (custom_dir / "skills").exists()
    assert not (custom_dir / "commands").exists()
    assert not (custom_dir / ".mcp.json").exists()
    assert "custom: MCP registration not supported, skipped" in capsys.readouterr().err

    install.revert()
    assert not (custom_dir / "AGENTS.md").exists()
