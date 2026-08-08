from ari_os import install


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
    return repo


def test_dry_run_with_mcp_returns_intents_without_writing(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("ARI_OS_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("ARI_OS_CLAUDE_DIR", str(tmp_path / "claude"))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    (tmp_path / "codex").mkdir()

    repo = _seed_repo(tmp_path)

    intents = install.apply(
        install.plan_actions(repo), dry_run=True, register_mcp=True
    )

    assert ("skill", str(tmp_path / "claude" / "skills" / "advisor" / "SKILL.md")) in intents
    assert any(intent[0] == "mcp:claude" for intent in intents)
    # Global harnesses are opt-in, so a default dry run must NOT claim it will
    # touch them — the report has to match what the install actually does.
    assert not any(intent[0] == "mcp:codex" for intent in intents)
    assert not (tmp_path / "claude").exists()
    assert not install.paths.installed_manifest().exists()


def test_dry_run_reports_global_harnesses_only_when_opted_in(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("ARI_OS_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("ARI_OS_CLAUDE_DIR", str(tmp_path / "claude"))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    (tmp_path / "codex").mkdir()

    intents = install.apply(
        install.plan_actions(_seed_repo(tmp_path)),
        dry_run=True,
        register_mcp=True,
        register_global_harnesses=True,
    )

    assert any(intent[0] == "mcp:codex" for intent in intents)
    assert not (tmp_path / "codex" / "config.toml").exists()

