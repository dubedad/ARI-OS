"""Best-effort ASCII box renderer for ARI-OS chat output.

Low-overhead, pure string ops. Pads every line to identical width so the
box closes. Single-width characters only (no emoji/CJK inside).
"""
from __future__ import annotations
import sys

_CHARS = {
    "single": {"tl": "┌", "tr": "┐", "bl": "└", "br": "┘", "h": "─", "v": "│"},
    "double": {"tl": "╔", "tr": "╗", "bl": "╚", "br": "╝", "h": "═", "v": "║"},
}

def render_box(title: str, rows: list[str], width: int | None = None,
               weight: str = "single") -> str:
    c = _CHARS["double" if weight == "double" else "single"]
    content_max = max([len(r) for r in rows] + [len(title) + 4])
    inner = width if width is not None else content_max + 2
    inner = max(inner, len(title) + 3)

    top = c["tl"] + c["h"] + " " + title + " " + c["h"] * (inner - len(title) - 3) + c["tr"]
    bottom = c["bl"] + c["h"] * inner + c["br"]
    lines = [top]
    for r in rows:
        lines.append(c["v"] + " " + r.ljust(inner - 2) + " " + c["v"])
    lines.append(bottom)
    return "\n".join(lines)

def main() -> None:
    title = sys.argv[1] if len(sys.argv) > 1 else "BOX"
    rows = [ln.rstrip("\n") for ln in sys.stdin] if not sys.stdin.isatty() else []
    print(render_box(title, rows))

if __name__ == "__main__":
    main()
