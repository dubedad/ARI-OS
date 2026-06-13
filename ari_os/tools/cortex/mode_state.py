"""Mode auto state — persistent streaks, locks, and per-cwd active mode.

Ported + scrubbed from the private engine. No path changes needed — all
filesystem operations work on the ``home_dir`` the caller passes (typically
``~/.ari-os``).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


def _state_path(home_dir):
    return Path(home_dir) / "mode_auto_state.json"


def load_state(home_dir):
    p = _state_path(home_dir)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def save_state(home_dir, state):
    p = _state_path(home_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(state))
    tmp.rename(p)


def _lock_path(home_dir, cwd):
    sha = hashlib.sha1(str(cwd).encode()).hexdigest()
    return Path(home_dir) / "mode_lock" / sha


def write_manual_lock(home_dir, cwd, until_ts):
    p = _lock_path(home_dir, cwd)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(str(int(until_ts)))


def read_manual_lock(home_dir, cwd):
    p = _lock_path(home_dir, cwd)
    if not p.exists():
        return 0
    try:
        return int(p.read_text().strip())
    except Exception:
        return 0
