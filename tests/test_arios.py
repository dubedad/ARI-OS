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
