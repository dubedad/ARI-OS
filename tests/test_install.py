from pathlib import Path
from ari_os import paths, install
from ari_os.install import START


def test_paths_honor_env(tmp_path, monkeypatch):
    monkeypatch.setenv("ARI_OS_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("ARI_OS_CLAUDE_DIR", str(tmp_path / "claude"))
    assert paths.state_home() == tmp_path / "state"
    assert paths.claude_dir() == tmp_path / "claude"
    assert paths.backups_dir() == tmp_path / "state" / "backups"
    assert paths.installed_manifest() == tmp_path / "state" / "installed.json"


def test_inject_block_appends_when_absent():
    out = install.inject_block("# My rules\nkeep this\n", "ARI-OS line")
    assert "<!-- ARI-OS:start -->" in out and "<!-- ARI-OS:end -->" in out
    assert "ARI-OS line" in out
    assert out.startswith("# My rules\nkeep this\n")


def test_inject_block_is_idempotent():
    once = install.inject_block("orig\n", "v1")
    twice = install.inject_block(once, "v1")
    assert once == twice


def test_inject_block_replaces_only_between_markers():
    once = install.inject_block("orig\n", "v1")
    updated = install.inject_block(once, "v2")
    assert "v2" in updated and "v1" not in updated
    assert updated.startswith("orig\n")


def test_backup_copies_existing_file(tmp_path, monkeypatch):
    monkeypatch.setenv("ARI_OS_HOME", str(tmp_path / "state"))
    f = tmp_path / "CLAUDE.md"
    f.write_text("hello")
    b = install.backup(f)
    assert b is not None and b.read_text() == "hello"


def test_backup_missing_file_returns_none(tmp_path, monkeypatch):
    monkeypatch.setenv("ARI_OS_HOME", str(tmp_path / "state"))
    assert install.backup(tmp_path / "nope.md") is None


def test_merge_settings_preserves_user_keys():
    existing = {"apiKeyHelper": "x", "hooks": {"a": 1}}
    out = install.merge_settings(existing, "python3 -m ari_os.tools.statusline")
    assert out["apiKeyHelper"] == "x"
    assert out["hooks"] == {"a": 1}
    assert out["statusLine"]["command"] == "python3 -m ari_os.tools.statusline"
    assert existing.get("statusLine") is None  # input not mutated


def _seed_repo(tmp_path):
    repo = tmp_path / "repo"
    (repo / "ari_os" / "skills" / "advisor").mkdir(parents=True)
    (repo / "ari_os" / "skills" / "advisor" / "SKILL.md").write_text("---\nname: advisor\n---\n# A")
    (repo / "ari_os" / "commands").mkdir(parents=True)
    (repo / "ari_os" / "commands" / "monitor.md").write_text("---\ndescription: m\n---\nbody")
    (repo / "ari_os" / "VERSION").write_text("0.1.0")
    return repo


def test_dry_run_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("ARI_OS_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("ARI_OS_CLAUDE_DIR", str(tmp_path / "claude"))
    repo = _seed_repo(tmp_path)
    actions = install.apply(install.plan_actions(repo), dry_run=True)
    assert actions
    assert not (tmp_path / "claude").exists()
    assert not paths.installed_manifest().exists()


def test_install_then_revert_restores(tmp_path, monkeypatch):
    monkeypatch.setenv("ARI_OS_HOME", str(tmp_path / "state"))
    cdir = tmp_path / "claude"
    cdir.mkdir()
    monkeypatch.setenv("ARI_OS_CLAUDE_DIR", str(cdir))
    (cdir / "CLAUDE.md").write_text("my rules\n")
    repo = _seed_repo(tmp_path)
    install.apply(install.plan_actions(repo), dry_run=False)
    assert (cdir / "skills" / "advisor" / "SKILL.md").exists()
    assert START in (cdir / "CLAUDE.md").read_text()
    install.revert()
    assert (cdir / "CLAUDE.md").read_text() == "my rules\n"


def test_install_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("ARI_OS_HOME", str(tmp_path / "state"))
    cdir = tmp_path / "claude"
    monkeypatch.setenv("ARI_OS_CLAUDE_DIR", str(cdir))
    repo = _seed_repo(tmp_path)
    install.apply(install.plan_actions(repo), dry_run=False)
    before = (cdir / "CLAUDE.md").read_text()
    install.apply(install.plan_actions(repo), dry_run=False)
    assert (cdir / "CLAUDE.md").read_text() == before

def test_claude_body_mentions_brain():
    body = install.CLAUDE_BODY
    for needle in ("remember", "recall", "dream", "/morning", "/night"):
        assert needle in body

# NOTE: test_update_preserves_cortex_memories was removed in the heavy-Cortex port.
# It exercised the light-cortex store API (cortex.connect/remember). The heavy
# light->heavy cortex.db update-migration (spec DoD-8) is built in P7; its
# preserves-memories test lands with that phase.
