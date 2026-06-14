"""P4 LLM backend tests.

The consolidation backend must be optional, public, and import-safe:
``off`` returns no adapter, ``ollama`` and ``api`` construct without touching
the network, and generation calls are testable through monkeypatched HTTP.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from ari_os.tools.cortex import config
from ari_os.tools.cortex.llm import get_llm
from ari_os.tools.cortex.llm.api import ApiLLM
from ari_os.tools.cortex.llm.ollama import OllamaLLM
from ari_os.tools.cortex.model_routing import model_for_stage, route_for_stage


class _Response:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        return None

    def json(self):
        return self._data


def test_get_llm_off_returns_none():
    assert get_llm("off") is None


def test_get_llm_default_uses_config(monkeypatch):
    monkeypatch.setattr(config, "DEFAULT_LLM", "off")
    assert get_llm() is None


def test_get_llm_ollama_constructs_without_network():
    llm = get_llm("ollama:test-model")
    assert isinstance(llm, OllamaLLM)
    assert llm.model == "test-model"


def test_get_llm_api_constructs_without_network(monkeypatch):
    monkeypatch.setattr("ari_os.tools.cortex.llm.api.ask.get_key", lambda provider: "secret")
    llm = get_llm("api:moonshot:test-model")
    assert isinstance(llm, ApiLLM)
    assert llm.provider == "moonshot"
    assert llm.model == "test-model"


def test_ollama_consolidate_and_distill_call_generate_endpoint(monkeypatch):
    calls = []

    def fake_post(url, json, timeout):
        calls.append(SimpleNamespace(url=url, json=json, timeout=timeout))
        return _Response({"response": "  compact summary  "})

    monkeypatch.setattr("ari_os.tools.cortex.llm.ollama.httpx.post", fake_post)

    llm = OllamaLLM(model="demo", url="http://ollama.test")

    assert llm.consolidate(["alpha", "beta"]) == "compact summary"
    assert llm.distill("alpha beta", tier=1) == "compact summary"
    assert len(calls) == 2
    assert calls[0].url == "http://ollama.test/api/generate"
    assert calls[0].json["model"] == "demo"
    assert calls[0].json["stream"] is False


def test_ollama_extract_entities_returns_line_list(monkeypatch):
    calls = []

    def fake_post(url, json, timeout):
        calls.append(SimpleNamespace(url=url, json=json, timeout=timeout))
        return _Response(
            {
                "response": (
                    "ARI OS | project | 0.95\n"
                    "ARI OS | uses | cortex | 0.82\n\n"
                    "cortex | tool | 0.88"
                )
            }
        )

    monkeypatch.setattr("ari_os.tools.cortex.llm.ollama.httpx.post", fake_post)

    llm = OllamaLLM(model="demo", url="http://ollama.test")

    assert llm.extract_entities("ARI OS uses cortex.") == [
        "ARI OS | project | 0.95",
        "ARI OS | uses | cortex | 0.82",
        "cortex | tool | 0.88",
    ]
    assert calls[0].url == "http://ollama.test/api/generate"
    assert "name | kind | confidence" in calls[0].json["prompt"]
    assert "subject | predicate | object | confidence" in calls[0].json["prompt"]


def test_api_consolidate_and_distill_call_public_provider(monkeypatch):
    calls = []
    monkeypatch.setattr("ari_os.tools.cortex.llm.api.ask.get_key", lambda provider: "secret")

    def fake_post(url, json, headers, timeout):
        calls.append(SimpleNamespace(url=url, json=json, headers=headers, timeout=timeout))
        return _Response({"choices": [{"message": {"content": "  api summary  "}}]})

    monkeypatch.setattr("ari_os.tools.cortex.llm.api.httpx.post", fake_post)

    llm = ApiLLM(provider="moonshot", model="demo", base_url="https://api.example/v1")

    assert llm.consolidate(["alpha", "beta"]) == "api summary"
    assert llm.distill("alpha beta", tier=1) == "api summary"
    assert len(calls) == 2
    assert calls[0].url == "https://api.example/v1/chat/completions"
    assert calls[0].json["model"] == "demo"
    assert calls[0].headers["Authorization"] == "Bearer secret"


def test_api_extract_entities_returns_line_list(monkeypatch):
    calls = []
    monkeypatch.setattr("ari_os.tools.cortex.llm.api.ask.get_key", lambda provider: "secret")

    def fake_post(url, json, headers, timeout):
        calls.append(SimpleNamespace(url=url, json=json, headers=headers, timeout=timeout))
        return _Response(
            {
                "choices": [
                    {
                        "message": {
                            "content": "ARI OS | project | 0.95\ncortex | tool | 0.88"
                        }
                    }
                ]
            }
        )

    monkeypatch.setattr("ari_os.tools.cortex.llm.api.httpx.post", fake_post)

    llm = ApiLLM(provider="moonshot", model="demo", base_url="https://api.example/v1")

    assert llm.extract_entities("ARI OS uses cortex.") == [
        "ARI OS | project | 0.95",
        "cortex | tool | 0.88",
    ]
    assert calls[0].url == "https://api.example/v1/chat/completions"
    assert "name | kind | confidence" in calls[0].json["messages"][0]["content"]
    assert "subject | predicate | object | confidence" in calls[0].json["messages"][0]["content"]


def test_model_for_stage_uses_public_default_and_env_override(monkeypatch):
    route = route_for_stage("consolidation")
    assert route.primary.startswith("ollama:")
    assert "gemma" in route.primary

    monkeypatch.setenv("ARI_OS_CONSOLIDATION_LLM", "api:moonshot:public-model")
    assert model_for_stage("consolidation") == "api:moonshot:public-model"


def test_model_for_stage_has_kg_extraction_route_and_env_override(monkeypatch):
    route = route_for_stage("kg_extraction")
    assert route.primary.startswith("ollama:")
    assert route.env_var == "ARI_OS_KG_LLM"
    assert "off" in route.fallbacks

    monkeypatch.setenv("ARI_OS_KG_LLM", "off")
    assert model_for_stage("kg_extraction") == "off"


def test_model_for_stage_rejects_unknown_stage():
    with pytest.raises(ValueError, match="Unknown cortex model stage"):
        model_for_stage("nope")
