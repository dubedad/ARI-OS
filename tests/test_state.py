import json, os, subprocess
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


def test_reconcile_dead_pid_becomes_done(tmp_path, monkeypatch):
    monkeypatch.setenv("ARI_OS_HOME", str(tmp_path))
    proc = subprocess.Popen(["true"]); proc.wait()  # reaped -> pid is dead
    state.write_workers([{"id": "w-1-x", "status": "running", "pid": proc.pid}])
    assert state.reconcile()[0]["status"] == "done"


def test_reconcile_live_pid_stays_running(tmp_path, monkeypatch):
    monkeypatch.setenv("ARI_OS_HOME", str(tmp_path))
    state.write_workers([{"id": "w-1-x", "status": "running", "pid": os.getpid()}])
    assert state.reconcile()[0]["status"] == "running"


def test_reconcile_open_question_blocks(tmp_path, monkeypatch):
    monkeypatch.setenv("ARI_OS_HOME", str(tmp_path))
    (state.state_dir() / "questions" / "w-1-x.md").write_text("Decision?")
    state.write_workers([{"id": "w-1-x", "status": "running", "pid": os.getpid()}])
    assert state.reconcile()[0]["status"] == "blocked"


def test_reconcile_persists_change(tmp_path, monkeypatch):
    monkeypatch.setenv("ARI_OS_HOME", str(tmp_path))
    proc = subprocess.Popen(["true"]); proc.wait()
    state.write_workers([{"id": "w-1-x", "status": "running", "pid": proc.pid}])
    state.reconcile()
    assert state.read_workers()[0]["status"] == "done"  # written back to disk
