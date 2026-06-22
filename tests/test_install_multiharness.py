import json
import tomllib
from pathlib import Path

from ari_os import install


def test_writes_all_harness_configs(tmp_path, monkeypatch):
    monkeypatch.setenv("ARI_OS_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("ARI_OS_CLAUDE_DIR", str(tmp_path / "claude"))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    monkeypatch.setenv("GEMINI_DIR", str(tmp_path / "gemini"))

    codex_config = tmp_path / "codex" / "config.toml"
    codex_config.parent.mkdir()
    codex_config.write_text('[mcp_servers.existing]\ncommand = "node"\nargs = []\n')
    gemini_config = tmp_path / "gemini" / "settings.json"
    gemini_config.parent.mkdir()
    gemini_config.write_text(json.dumps({
        "mcpServers": {
            "existing": {"command": "node", "args": []},
        },
        "model": {"name": "gemini-3-flash-preview"},
    }))

    written = install.write_all_mcp_registrations(register=True)

    assert set(written) == {"claude", "codex", "gemini"}

    claude = json.loads(Path(written["claude"]).read_text())
    assert "ari-os-cortex" in claude["mcpServers"]
    assert claude["mcpServers"]["ari-os-cortex"]["command"] == install.MCP_SERVER_COMMAND

    codex = tomllib.loads(Path(written["codex"]).read_text())
    assert codex["mcp_servers"]["existing"]["command"] == "node"
    assert codex["mcp_servers"]["ari-os-cortex"]["command"] == install.MCP_SERVER_COMMAND
    assert codex["mcp_servers"]["ari-os-cortex"]["args"] == [
        "-m",
        "ari_os.tools.cortex.mcp_server",
        "stdio",
    ]

    gemini = json.loads(Path(written["gemini"]).read_text())
    assert gemini["model"]["name"] == "gemini-3-flash-preview"
    assert "existing" in gemini["mcpServers"]
    assert "ari-os-cortex" in gemini["mcpServers"]

    written_again = install.write_all_mcp_registrations(register=True)
    assert written_again == written
    codex_again = tomllib.loads(Path(written["codex"]).read_text())
    assert list(codex_again["mcp_servers"]).count("ari-os-cortex") == 1


def test_no_mcp_opts_out(tmp_path, monkeypatch):
    monkeypatch.setenv("ARI_OS_CLAUDE_DIR", str(tmp_path / "claude"))
    assert install.write_all_mcp_registrations(register=False) == {}
    assert not (tmp_path / "claude").exists()


def test_unregister_all_mcp_registrations_preserves_user_entries(tmp_path, monkeypatch):
    monkeypatch.setenv("ARI_OS_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("ARI_OS_CLAUDE_DIR", str(tmp_path / "claude"))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    monkeypatch.setenv("GEMINI_DIR", str(tmp_path / "gemini"))

    install.write_all_mcp_registrations(register=True)

    codex_config = tmp_path / "codex" / "config.toml"
    codex_config.write_text(
        codex_config.read_text()
        + '\n[mcp_servers.user]\ncommand = "node"\nargs = []\n'
    )
    gemini_config = tmp_path / "gemini" / "settings.json"
    gemini = json.loads(gemini_config.read_text())
    gemini["mcpServers"]["user"] = {"command": "node", "args": []}
    gemini_config.write_text(json.dumps(gemini, indent=2))

    removed = install.unregister_mcp_server()

    assert removed is True
    claude = json.loads((tmp_path / "claude" / ".mcp.json").read_text())
    assert "ari-os-cortex" not in claude["mcpServers"]

    codex = tomllib.loads(codex_config.read_text())
    assert "ari-os-cortex" not in codex.get("mcp_servers", {})
    assert codex["mcp_servers"]["user"]["command"] == "node"

    gemini = json.loads(gemini_config.read_text())
    assert "ari-os-cortex" not in gemini["mcpServers"]
    assert gemini["mcpServers"]["user"]["command"] == "node"
