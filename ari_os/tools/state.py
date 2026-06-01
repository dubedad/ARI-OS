"""Shared state directory for ARI-OS dispatch + monitor.

Default ~/.ari-os, overridable with $ARI_OS_HOME (used by tests and by users
who want a custom location). Creates logs/ and questions/ on first access.
"""
from __future__ import annotations
import json, os
from pathlib import Path


def state_dir() -> Path:
    base = os.environ.get("ARI_OS_HOME") or os.path.expanduser("~/.ari-os")
    d = Path(base)
    (d / "logs").mkdir(parents=True, exist_ok=True)
    (d / "questions").mkdir(parents=True, exist_ok=True)
    return d


def workers_path() -> Path:
    return state_dir() / "workers.json"


def read_workers() -> list[dict]:
    p = workers_path()
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text())
    except Exception:
        return []


def write_workers(workers: list[dict]) -> None:
    workers_path().write_text(json.dumps(workers, indent=2))
