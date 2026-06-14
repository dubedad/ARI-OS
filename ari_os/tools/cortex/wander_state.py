from __future__ import annotations

import json
import random
import time
from pathlib import Path


def _state_path(home_dir: Path) -> Path:
    return Path(home_dir) / "wander_state.json"


def load_state(home_dir: Path) -> dict:
    path = _state_path(home_dir)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def save_state(home_dir: Path, state: dict) -> None:
    path = _state_path(home_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state))
    tmp.rename(path)


def tick(
    state: dict,
    session_id: str,
    *,
    cadence_min: int = 5,
    cadence_max: int = 10,
    rng: random.Random | None = None,
    now: int | None = None,
):
    """Increment a session counter and decide whether wander should fire."""
    rng = rng or random.Random()
    now = now if now is not None else int(time.time())
    sess = dict(state.get(session_id) or {})
    count = int(sess.get("count", 0)) + 1
    threshold = int(sess.get("threshold") or rng.randint(cadence_min, cadence_max))
    if count >= threshold:
        sess.update(
            count=0,
            threshold=rng.randint(cadence_min, cadence_max),
            updated_at=now,
        )
        return True, sess
    sess.update(count=count, threshold=threshold, updated_at=now)
    return False, sess


def surface_decision(fired: bool, posture: str) -> bool:
    """Return whether a cadence fire should also force a global surface pass."""
    return bool(fired) and posture == "tunnel"
