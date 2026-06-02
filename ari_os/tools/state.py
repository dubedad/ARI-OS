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


def pid_alive(pid) -> bool:
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists but owned by another user
    except (ValueError, TypeError, OSError):
        return False
    return True


def _open_questions() -> set[str]:
    return {p.stem for p in (state_dir() / "questions").glob("*.md")}


def reconcile(workers: list[dict] | None = None) -> list[dict]:
    """Update worker statuses from reality: an open question -> blocked,
    a dead PID -> done, otherwise running. Persists if anything changed."""
    if workers is None:
        workers = read_workers()
    open_q = _open_questions()
    changed = False
    for w in workers:
        if w.get("status") == "done":
            continue
        if w.get("id", "") in open_q:
            new = "blocked"
        elif w.get("pid") is not None and not pid_alive(w["pid"]):
            new = "done"
        else:
            new = "running"
        if new != w.get("status"):
            w["status"] = new
            changed = True
    if changed:
        write_workers(workers)
    return workers
