# ari_os/tools/embed.py
"""Optional embeddings for Cortex — stdlib only.

cosine() is always available. embed() returns a vector via an embeddings key the
user already configured (reusing ask.py key resolution) or a local Ollama model,
and returns None when nothing is configured so recall stays lexical. No pip deps.
"""
from __future__ import annotations
import json, math, os
from urllib.request import Request, urlopen

def cosine(a, b) -> float:
    num = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)); nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return num / (na * nb)

def _ollama_up() -> bool:
    try:
        urlopen("http://localhost:11434/api/tags", timeout=1).read()
        return True
    except Exception:
        return False

def _google_key():
    try:
        from .ask import get_key
        return get_key("google")
    except SystemExit:
        return None
    except Exception:
        return None

def embedding_provider() -> str:
    if _ollama_up():
        return "ollama"
    if _google_key():
        return "google"
    return "off"

def _embed_ollama(text, model="nomic-embed-text"):
    req = Request("http://localhost:11434/api/embeddings",
                  data=json.dumps({"model": model, "prompt": text}).encode(),
                  headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=60) as r:
        return json.loads(r.read()).get("embedding")

def _embed_google(text, key, model="text-embedding-004"):
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/{model}"
           f":embedContent?key={key}")
    body = {"model": f"models/{model}", "content": {"parts": [{"text": text}]}}
    with urlopen(Request(url, data=json.dumps(body).encode(),
                         headers={"Content-Type": "application/json"}), timeout=60) as r:
        return json.loads(r.read()).get("embedding", {}).get("values")

def embed(text, provider="auto"):
    prov = embedding_provider() if provider == "auto" else provider
    if prov == "ollama":
        return _embed_ollama(text)
    if prov == "google":
        return _embed_google(text, _google_key())
    return None
