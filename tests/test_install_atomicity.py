import json

import pytest

from ari_os import install, paths
from ari_os.install import MCP_SERVER_NAME, START


def _seed_repo(tmp_path):
    repo = tmp_path / "repo"
    (repo / "ari_os" / "skills" / "advisor").mkdir(parents=True)
    (repo / "ari_os" / "skills" / "advisor" / "SKILL.md").write_text(
        "---\nname: advisor\n---\n# A"
    )
    (repo / "ari_os" / "commands").mkdir(parents=True)
    (repo / "ari_os" / "commands" / "monitor.md").write_text(
        "---\ndescription: m\n---\nbody"
    )
    (repo / "ari_os" / "VERSION").write_text("2.1.0")
    return repo


def test_failed_bootstrap_leaves_revertable_manifest_and_revert_restores_all(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("ARI_OS_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("ARI_OS_CLAUDE_DIR", str(tmp_path / "claude"))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    monkeypatch.setenv("GEMINI_DIR", str(tmp_path / "gemini"))
    monkeypatch.setenv("KIMI_CODE_HOME", str(tmp_path / "kimi"))

    claude = paths.claude_dir()
    claude.mkdir(parents=True)
    (claude / "CLAUDE.md").write_text("my rules\n")
    (claude / "settings.json").write_text(json.dumps({"apiKeyHelper": "keep"}))
    (claude / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"user": {"command": "node", "args": []}}})
    )

    codex_config = tmp_path / "codex" / "config.toml"
    codex_config.parent.mkdir(parents=True)
    codex_config.write_text('[mcp_servers.user]\ncommand = "node"\nargs = []\n')

    gemini_settings = tmp_path / "gemini" / "settings.json"
    gemini_settings.parent.mkdir(parents=True)
    gemini_settings.write_text(
        json.dumps({"mcpServers": {"user": {"command": "node", "args": []}}})
    )

    kimi_mcp = tmp_path / "kimi" / "mcp.json"
    kimi_mcp.parent.mkdir(parents=True)
    kimi_mcp.write_text(
        json.dumps({"mcpServers": {"user": {"command": "node", "args": []}}})
    )

    repo = _seed_repo(tmp_path)

    def fail_bootstrap(**_kwargs):
        raise RuntimeError("bootstrap failed")

    monkeypatch.setattr(install, "bootstrap_heavy_brain", fail_bootstrap)

    with pytest.raises(RuntimeError, match="bootstrap failed"):
        install.apply(install.plan_actions(repo), dry_run=False, register_mcp=True)

    assert paths.installed_manifest().exists()
    assert START in (claude / "CLAUDE.md").read_text()
    assert MCP_SERVER_NAME in json.loads((claude / ".mcp.json").read_text())["mcpServers"]

    install.revert()

    assert (claude / "CLAUDE.md").read_text() == "my rules\n"
    assert json.loads((claude / "settings.json").read_text()) == {
        "apiKeyHelper": "keep"
    }
    assert not (claude / "skills" / "advisor" / "SKILL.md").exists()
    assert not (claude / "commands" / "monitor.md").exists()
    assert MCP_SERVER_NAME not in json.loads((claude / ".mcp.json").read_text())[
        "mcpServers"
    ]
    assert MCP_SERVER_NAME not in codex_config.read_text()
    assert MCP_SERVER_NAME not in json.loads(gemini_settings.read_text())["mcpServers"]
    assert MCP_SERVER_NAME not in json.loads(kimi_mcp.read_text())["mcpServers"]
    assert not paths.installed_manifest().exists()

