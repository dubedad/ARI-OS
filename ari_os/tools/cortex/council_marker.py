"""Local per-session marker for the council tier served by retrieval."""
from __future__ import annotations

import json
import time
from pathlib import Path

from . import config

_MARKER_FILE = "council_tier.json"
_MAX_ENTRIES = 50


def _home(home_dir: Path | None = None) -> Path:
    if home_dir is not None:
        return Path(home_dir)
    return config.state_home()


def _marker_path(home_dir: Path | None = None) -> Path:
    return _home(home_dir) / _MARKER_FILE


def _load(home_dir: Path | None = None) -> dict:
    path = _marker_path(home_dir)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def record_tier(
    session_id: str,
    tier: str,
    *,
    home_dir: Path | None = None,
    now: int | None = None,
) -> None:
    """Record the council tier served by the session's last retrieval."""
    if not session_id:
        return
    timestamp = now if now is not None else int(time.time())
    state = _load(home_dir)
    state[session_id] = {"tier": tier, "ts": timestamp}
    if len(state) > _MAX_ENTRIES:
        newest = sorted(state.items(), key=lambda item: item[1].get("ts", 0), reverse=True)
        state = dict(newest[:_MAX_ENTRIES])

    marker = _marker_path(home_dir)
    marker.parent.mkdir(parents=True, exist_ok=True)
    tmp = marker.with_suffix(".tmp")
    tmp.write_text(json.dumps(state))
    tmp.replace(marker)


def council_serving(session_id: str, *, home_dir: Path | None = None) -> bool:
    """Return true if the last retrieval served this session with council normal tier."""
    try:
        if not session_id:
            return False
        entry = _load(home_dir).get(session_id)
        return bool(entry) and entry.get("tier") == "normal"
    except Exception:
        return False
