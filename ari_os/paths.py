"""Env-aware filesystem locations shared by the installer + control panel."""
from __future__ import annotations
import os
from pathlib import Path


def state_home() -> Path:
    return Path(os.environ.get("ARI_OS_HOME") or os.path.expanduser("~/.ari-os"))


def claude_dir() -> Path:
    return Path(os.environ.get("ARI_OS_CLAUDE_DIR") or os.path.expanduser("~/.claude"))


def backups_dir() -> Path:
    return state_home() / "backups"


def installed_manifest() -> Path:
    return state_home() / "installed.json"
