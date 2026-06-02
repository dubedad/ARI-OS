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
