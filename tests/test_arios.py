import pytest
from ari_os.tools import arios


def test_config_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("ARI_OS_HOME", str(tmp_path))
    arios.save_config({"theme": "stipple"})
    assert arios.load_config()["theme"] == "stipple"


def test_set_theme_validates(tmp_path, monkeypatch):
    monkeypatch.setenv("ARI_OS_HOME", str(tmp_path))
    arios.set_theme("stipple")
    assert arios.load_config()["theme"] == "stipple"
    with pytest.raises(ValueError):
        arios.set_theme("not-a-theme")


def test_toggle_writes_bool(tmp_path, monkeypatch):
    monkeypatch.setenv("ARI_OS_HOME", str(tmp_path))
    arios.toggle("teach", True)
    assert arios.load_config()["toggles"]["teach"] is True


def test_keys_status_never_prints_value(tmp_path, monkeypatch):
    monkeypatch.setenv("ARI_OS_HOME", str(tmp_path))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret-xyz")
    status = arios.keys_status()
    assert status["anthropic"] in ("present", "missing")
    assert "sk-secret-xyz" not in repr(status)


def test_cortex_embeddings_validates(tmp_path, monkeypatch):
    monkeypatch.setenv("ARI_OS_HOME", str(tmp_path))
    arios.set_embeddings("ollama")
    assert arios.load_config()["cortex"]["embeddings"] == "ollama"
    with pytest.raises(ValueError):
        arios.set_embeddings("nonsense")

def test_cortex_mode_and_wander(tmp_path, monkeypatch):
    monkeypatch.setenv("ARI_OS_HOME", str(tmp_path))
    arios.set_mode("wide")
    arios.set_wander(False)
    cfg = arios.load_config()["cortex"]
    assert cfg["mode"] == "wide" and cfg["wander"] is False
    with pytest.raises(ValueError):
        arios.set_mode("not-a-mode")

def test_cortex_status_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("ARI_OS_HOME", str(tmp_path))
    assert arios.cortex_status() == {"embeddings": "auto", "mode": "default", "wander": True}

def test_cli_cortex_sets_and_status(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ARI_OS_HOME", str(tmp_path))
    arios.main(["cortex", "mode", "focus"])
    assert arios.load_config()["cortex"]["mode"] == "focus"
    arios.main(["cortex", "status"])
    assert "focus" in capsys.readouterr().out
