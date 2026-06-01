import os, pytest
from ari_os.tools import ask

def test_registry_has_core_models():
    for m in ("haiku", "sonnet", "opus", "gemini", "kimi", "minimax", "gemma"):
        assert m in ask.MODELS

def test_get_key_from_env(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-123")
    assert ask.get_key("anthropic") == "sk-test-123"

def test_get_key_missing_does_not_leak(monkeypatch, capsys):
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    monkeypatch.setattr(ask, "_keychain_lookup", lambda *a, **k: None)
    with pytest.raises(SystemExit):
        ask.get_key("minimax")
    err = capsys.readouterr().err
    assert "MINIMAX_API_KEY" in err          # names the var to set
    assert "sk-" not in err                    # never prints a key value
