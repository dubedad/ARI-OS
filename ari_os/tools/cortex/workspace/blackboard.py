"""Global workspace blackboard state for ARI-OS Cortex."""
from __future__ import annotations

import fcntl
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..config import state_home

MAX_ENTRIES = 1000
MAX_AGE_SECONDS = 14 * 86400


@dataclass
class BlackboardEntry:
    ts: int
    kind: str
    source: str
    cwd: str
    summary: str
    body: dict[str, Any] = field(default_factory=dict)


def default_blackboard_path() -> Path:
    return state_home() / "workspace_state.json"


def _resolve_path(path: Path | None) -> Path:
    return Path(path) if path is not None else default_blackboard_path()


def _coerce_entry(raw: object) -> BlackboardEntry | None:
    if not isinstance(raw, dict):
        return None
    try:
        return BlackboardEntry(
            ts=int(raw.get("ts", 0)),
            kind=str(raw.get("kind", "")),
            source=str(raw.get("source", "")),
            cwd=str(raw.get("cwd", "")),
            summary=str(raw.get("summary", "")),
            body=raw.get("body", {}) if isinstance(raw.get("body"), dict) else {},
        )
    except (TypeError, ValueError):
        return None


def read_blackboard(path: Path | None = None) -> list[BlackboardEntry]:
    """Read blackboard JSON state; return [] if missing or malformed."""
    resolved = _resolve_path(path)
    if not resolved.exists():
        return []
    try:
        raw = json.loads(resolved.read_text())
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(raw, list):
        return []
    return [entry for item in raw if (entry := _coerce_entry(item)) is not None]


def _fresh_raw_entries(raw: object, *, cutoff: int) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            ts = int(item.get("ts", 0))
        except (TypeError, ValueError):
            continue
        if ts >= cutoff:
            out.append(item)
    return out


def append_finding(entry: BlackboardEntry, path: Path | None = None) -> None:
    """Append a blackboard entry with a lock-protected read-modify-write."""
    resolved = _resolve_path(path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    cutoff = entry.ts - MAX_AGE_SECONDS
    with resolved.open("a+") as f:
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        except OSError:
            pass
        f.seek(0)
        try:
            raw = json.loads(f.read() or "[]")
        except json.JSONDecodeError:
            raw = []
        entries = _fresh_raw_entries(raw, cutoff=cutoff)
        entries.append(asdict(entry))
        if len(entries) > MAX_ENTRIES:
            entries = entries[-MAX_ENTRIES:]
        f.seek(0)
        f.truncate()
        f.write(json.dumps(entries, indent=2))
        f.write("\n")
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass


def list_recent(
    path: Path | None = None,
    limit: int = 10,
    since_ts: int | None = None,
) -> list[BlackboardEntry]:
    """Return newest-first blackboard entries."""
    entries = read_blackboard(path)
    if since_ts is not None:
        entries = [entry for entry in entries if entry.ts >= since_ts]
    entries.sort(key=lambda entry: entry.ts, reverse=True)
    return entries[:limit]


def render_recent_md(
    path: Path | None = None,
    limit: int = 5,
    since_ts: int | None = None,
) -> str:
    """Render recent blackboard entries as markdown; empty string when none."""
    recent = list_recent(path=path, limit=limit, since_ts=since_ts)
    if not recent:
        return ""
    lines = ["## Brain - recent workspace findings", ""]
    for entry in recent:
        lines.append(
            f"- **{entry.kind}** ({entry.source}, ts={entry.ts}): {entry.summary}"
        )
    return "\n".join(lines) + "\n"


def observation(
    summary: str,
    *,
    source: str = "main",
    cwd: str = "",
    body: dict[str, Any] | None = None,
    ts: int | None = None,
) -> BlackboardEntry:
    """Convenience factory for callers that only need to log an observation."""
    return BlackboardEntry(
        ts=int(time.time()) if ts is None else ts,
        kind="observation",
        source=source,
        cwd=cwd,
        summary=summary,
        body=body or {},
    )
