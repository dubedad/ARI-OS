import stat

from ari_os import paths
from ari_os.tools import arios
from ari_os.tools import state as _state


def _mode(path):
    return stat.S_IMODE(path.stat().st_mode)


def test_state_files_are_private(tmp_path, monkeypatch):
    monkeypatch.setenv("ARI_OS_HOME", str(tmp_path))

    _state.write_workers([{"id": "w-ab12-x", "status": "running"}])

    assert _mode(_state.workers_path()) == 0o600
    assert _mode(tmp_path) == 0o700
    assert _mode(tmp_path / "logs") == 0o700
    assert _mode(tmp_path / "questions") == 0o700


def test_config_file_is_private(tmp_path, monkeypatch):
    monkeypatch.setenv("ARI_OS_HOME", str(tmp_path))

    arios.save_config({"theme": "stipple"})

    assert _mode(tmp_path / "config.json") == 0o600


def test_installed_manifest_is_private(tmp_path, monkeypatch):
    monkeypatch.setenv("ARI_OS_HOME", str(tmp_path))

    paths.write_private(paths.installed_manifest(), "{}")

    assert _mode(paths.installed_manifest()) == 0o600
