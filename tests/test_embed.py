# tests/test_embed.py
import math
from ari_os.tools import embed

def test_cosine_identical_is_one():
    assert abs(embed.cosine([1.0, 0.0], [1.0, 0.0]) - 1.0) < 1e-9

def test_cosine_orthogonal_is_zero():
    assert abs(embed.cosine([1.0, 0.0], [0.0, 1.0])) < 1e-9

def test_cosine_zero_vector_is_zero():
    assert embed.cosine([0.0, 0.0], [1.0, 1.0]) == 0.0

def test_embed_returns_none_when_unconfigured(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(embed, "_ollama_up", lambda: False)
    monkeypatch.setattr(embed, "_google_key", lambda: None)
    assert embed.embedding_provider() == "off"
    assert embed.embed("anything") is None
