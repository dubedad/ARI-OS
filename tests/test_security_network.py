import json

from ari_os.tools import ask, embed
from ari_os.tools.cortex import embed as cortex_embed


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return json.dumps(self._payload).encode()


def test_google_generation_key_uses_header_not_query(monkeypatch):
    seen = {}

    def fake_open(req, timeout):
        seen["url"] = req.full_url
        seen["headers"] = req.headers
        return _Response({"candidates": []})

    monkeypatch.setattr(ask._http, "open_url", fake_open)

    ask.call_google("secret-key", "gemini-x", "prompt", None)

    assert "secret-key" not in seen["url"]
    assert seen["headers"]["X-goog-api-key"] == "secret-key"


def test_google_embedding_key_uses_header_not_query(monkeypatch):
    seen = {}

    def fake_open(req, timeout):
        seen["url"] = req.full_url
        seen["headers"] = req.headers
        return _Response({"embedding": {"values": [1.0]}})

    monkeypatch.setattr(embed._http, "open_url", fake_open)

    assert embed._embed_google("hello", "secret-key") == [1.0]
    assert "secret-key" not in seen["url"]
    assert seen["headers"]["X-goog-api-key"] == "secret-key"


def test_cortex_api_embedding_key_uses_header_not_query(monkeypatch):
    seen = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"embedding": {"values": [1.0, 2.0]}}

    def fake_post(url, json, timeout, headers=None):
        seen["url"] = url
        seen["headers"] = headers or {}
        return Response()

    monkeypatch.setenv("GEMINI_API_KEY", "secret-key")
    monkeypatch.setattr(cortex_embed.httpx, "post", fake_post)

    assert cortex_embed._api_embed_one("hello", model="text-embedding-004", dim=2) == [
        1.0,
        2.0,
    ]
    assert "secret-key" not in seen["url"]
    assert seen["headers"]["x-goog-api-key"] == "secret-key"
