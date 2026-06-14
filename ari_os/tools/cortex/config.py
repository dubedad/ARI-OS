"""ARI-OS Cortex — paths, env, and runtime constants.

Defaults live under ``$ARI_OS_HOME`` (defaulting to ``~/.ari-os``) so a fresh
install is zero-config.
"""
from __future__ import annotations

import json
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


def runtime_config() -> dict:
    """Load optional user config from ``$ARI_OS_HOME/config.json``.

    Missing or malformed config is treated as empty config. The cortex core
    must stay zero-config and fail-soft on SessionStart paths.
    """
    path = state_home() / "config.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _config_value(dotted_key: str):
    data = runtime_config()
    if dotted_key in data:
        return data[dotted_key]
    cur = data
    for part in dotted_key.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def config_bool(dotted_key: str, default: bool) -> bool:
    value = _config_value(dotted_key)
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    if isinstance(value, (int, float)):
        return bool(value)
    return default


def wander_enabled(default: bool = True) -> bool:
    """Return the global ``cortex.wander`` toggle."""
    env = os.environ.get("ARI_OS_WANDER")
    if env is not None:
        return env.strip().lower() in {"1", "true", "yes", "on"}
    return config_bool("cortex.wander", default)
