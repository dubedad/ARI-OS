"""ARI-OS Cortex — paths, env, and runtime constants.

Defaults live under ``$ARI_OS_HOME`` (defaulting to ``~/.ari-os``) so a fresh
install is zero-config.
"""
from __future__ import annotations

import os
from pathlib import Path

# --- Embedding defaults (overridable via env) -------------------------------
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
EMBED_MODEL = os.environ.get("ARI_OS_EMBED_MODEL", "nomic-embed-text")
EMBED_DIM = int(os.environ.get("ARI_OS_EMBED_DIM", "768"))
DEFAULT_LLM = os.environ.get("ARI_OS_LLM", "ollama:gemma3:4b")

# --- Database path ----------------------------------------------------------
# Resolution order: $ARI_OS_BRAIN_DB → $ARI_OS_HOME/brain.db → ~/.ari-os/brain.db


def state_home() -> Path:
    """Root directory for all ARI-OS on-disk state (brain, caches, modes)."""
    return Path(os.environ.get("ARI_OS_HOME") or os.path.expanduser("~/.ari-os"))


def brain_db_path() -> Path:
    """Path to the local brain SQLite database.

    Honors ``$ARI_OS_BRAIN_DB`` (escape hatch for tests / alt roots),
    otherwise ``$ARI_OS_HOME/brain.db``.
    """
    env = os.environ.get("ARI_OS_BRAIN_DB")
    if env:
        return Path(env)
    return state_home() / "brain.db"


# --- Ingest roots (placeholders — populated in ar.t3 ingest pipeline) ------
# (path_glob, layer) — layer is one of: core | semantic | episodic | procedural | short_term
INGEST_ROOTS: list[tuple[str, str]] = []

# --- Exclude globs (placeholders — populated in ar.t3) ---------------------
EXCLUDE_GLOBS: list[str] = [
    "**/.git/**",
    "**/node_modules/**",
    "**/__pycache__/**",
    "**/*.log",
    "**/_archived/**",
    "**/_trash/**",
    "**/.venv/**",
    "**/dist/**",
    "**/build/**",
]

# --- Runtime toggles (consumed by later tasks) ------------------------------
ASSEMBLER_ENABLED = os.getenv("ARI_OS_ASSEMBLER", "0") in ("1", "true", "True")
USAGE_ENABLED = os.getenv("ARI_OS_USAGE", "0") in ("1", "true", "True")
USAGE_USED_HI = float(os.getenv("ARI_OS_USAGE_HI", "0.60"))
USAGE_USED_LO = float(os.getenv("ARI_OS_USAGE_LO", "0.55"))
USAGE_TS_WINDOW = int(os.getenv("ARI_OS_USAGE_WINDOW", "1800"))
USAGE_RESPONSE_REGION = "broca"
ZONES = ("persona", "episodic", "semantic")
