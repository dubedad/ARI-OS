"""ARI-OS output formatting: the four response markers + summary boxes.

Output-only. Never write these into files ARI-OS produces — chat output only.
Paths go in a numbered legend beneath a box (cmd-clickable), never inside.
"""
from __future__ import annotations
import sys
from .box import render_box

MARKERS = {
    "action": "→ ACTION",
    "decision": "→ DECISION",
    "question": "→ QUESTION",
    "none": "→ NO DECISION NEEDED",
}


def marker(kind: str) -> str:
    try:
        return MARKERS[kind]
    except KeyError:
        raise ValueError(f"Unknown marker kind: {kind!r}. "
                         f"One of {sorted(MARKERS)}")


def with_marker(body: str, kind: str) -> str:
    return f"{body.rstrip()}\n\n**{marker(kind)}**"


def summary_box(title: str, rows: list[str], paths: list[str] | None = None) -> str:
    box = render_box(title, rows)
    if not paths:
        return box
    legend = "\n".join(f"{i}. {p}" for i, p in enumerate(paths, 1))
    return f"{box}\n\n{legend}"


def main() -> None:
    kind = sys.argv[1] if len(sys.argv) > 1 else "none"
    body = sys.stdin.read() if not sys.stdin.isatty() else ""
    print(with_marker(body, kind))


if __name__ == "__main__":
    main()
