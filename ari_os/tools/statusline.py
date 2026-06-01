"""ARI-OS status footer for Claude Code's statusLine hook.

Reads the session JSON Claude Code passes on stdin and prints one line:
  19% · claude-opus-4-8 · my-project · main* · 1🛠 · 00:24
Every segment degrades gracefully when its source is unavailable.
"""
from __future__ import annotations
import json, os, subprocess, sys
from datetime import datetime
from pathlib import Path

STATE_DIR = Path(os.path.expanduser("~/.ari-os"))

def _git_branch(cwd: str) -> tuple[str | None, bool]:
    try:
        b = subprocess.run(["git", "-C", cwd, "rev-parse", "--abbrev-ref", "HEAD"],
                           capture_output=True, text=True, timeout=2)
        if b.returncode != 0:
            return None, False
        branch = b.stdout.strip() or None
        st = subprocess.run(["git", "-C", cwd, "status", "--porcelain"],
                            capture_output=True, text=True, timeout=2)
        return branch, bool(st.stdout.strip())
    except Exception:
        return None, False

def _worker_count() -> int:
    try:
        data = json.loads((STATE_DIR / "workers.json").read_text())
        return sum(1 for w in data.get("workers", []) if w.get("status") == "running")
    except Exception:
        return 0

def build_line(payload: dict, branch: str | None, dirty: bool, workers: int,
               now: str, ctx_pct: int | None) -> str:
    segs: list[str] = []
    if ctx_pct is not None:
        segs.append(f"{ctx_pct}%")
    model = payload.get("model", {}).get("display_name", "?")
    segs.append(model)
    cur = payload.get("workspace", {}).get("current_dir", "")
    if cur:
        segs.append(os.path.basename(cur.rstrip("/")) or cur)
    if branch:
        segs.append(f"{branch}{'*' if dirty else ''}")
    segs.append(f"{workers}🛠")
    segs.append(now)
    return " · ".join(segs)

def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}
    cur = payload.get("workspace", {}).get("current_dir", os.getcwd())
    branch, dirty = _git_branch(cur)
    ctx = payload.get("context", {}).get("percent_remaining")
    print(build_line(payload, branch, dirty, _worker_count(),
                     datetime.now().strftime("%H:%M"), ctx))

if __name__ == "__main__":
    main()
