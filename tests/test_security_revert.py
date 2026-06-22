import json
import hashlib

from ari_os import install, paths


def test_revert_skips_out_of_tree_paths(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ARI_OS_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("ARI_OS_CLAUDE_DIR", str(tmp_path / "claude"))
    victim = tmp_path / "victim.txt"
    victim.write_text("keep me")
    mf = paths.installed_manifest()
    mf.parent.mkdir(parents=True, exist_ok=True)
    mf.write_text(
        json.dumps(
            {
                "version": "x",
                "ts": "x",
                "complete": True,
                "changes": [
                    {"path": str(victim), "backup": None},
                ],
            }
        )
    )

    install.revert()

    assert victim.exists()


def test_revert_skips_backup_with_checksum_mismatch(tmp_path, monkeypatch):
    monkeypatch.setenv("ARI_OS_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("ARI_OS_CLAUDE_DIR", str(tmp_path / "claude"))
    victim = paths.claude_dir() / "CLAUDE.md"
    victim.parent.mkdir(parents=True)
    victim.write_text("current")
    backup = paths.backups_dir() / "run" / "CLAUDE.md"
    backup.parent.mkdir(parents=True)
    backup.write_text("original")
    wrong_hash = hashlib.sha256(b"different").hexdigest()
    mf = paths.installed_manifest()
    mf.parent.mkdir(parents=True, exist_ok=True)
    mf.write_text(
        json.dumps(
            {
                "version": "x",
                "ts": "x",
                "complete": True,
                "changes": [
                    {
                        "path": str(victim),
                        "backup": str(backup),
                        "backup_sha256": wrong_hash,
                    },
                ],
            }
        )
    )

    install.revert()

    assert victim.read_text() == "current"
