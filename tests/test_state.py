import json
from ari_os.tools import state


def test_state_dir_honors_env(tmp_path, monkeypatch):
    monkeypatch.setenv("ARI_OS_HOME", str(tmp_path))
    d = state.state_dir()
    assert str(d) == str(tmp_path)
    assert (tmp_path / "logs").is_dir()
    assert (tmp_path / "questions").is_dir()


def test_workers_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("ARI_OS_HOME", str(tmp_path))
    state.write_workers([{"id": "w-1-x", "status": "running"}])
    got = state.read_workers()
    assert got == [{"id": "w-1-x", "status": "running"}]


def test_read_workers_empty_when_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("ARI_OS_HOME", str(tmp_path))
    assert state.read_workers() == []
