from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Region = Literal[
    "wernicke",
    "broca",
    "occipital",
    "parietal",
    "hippocampus",
    "vmpfc",
    "frontoparietal",
]

_ALL_REGIONS = {
    "wernicke",
    "broca",
    "occipital",
    "parietal",
    "hippocampus",
    "vmpfc",
    "frontoparietal",
}
_HINTABLE_REGIONS = _ALL_REGIONS - {"occipital"}
_FRONTMATTER_SCAN_LINES = 80
_IMAGE_EXTS = {".avif", ".gif", ".heic", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}
_AUDIO_EXTS = {".aac", ".aiff", ".flac", ".m4a", ".mp3", ".ogg", ".wav"}


@dataclass
class Classification:
    layer: str
    region: Region
    workspace: str | None


def classify(
    path: Path,
    *,
    configured_layer: str,
    content_kind: str | None = None,
    region_hint: str | None = None,
    text: str | None = None,
) -> Classification:
    """Classify local media and notes into a cortex region."""
    path = Path(path)
    sp = path.as_posix().lower()
    suffix = path.suffix.lower()
    workspace = _extract_workspace(path)
    stamped = _frontmatter_region(text)

    if stamped is not None:
        region: Region = stamped  # type: ignore[assignment]
    elif _looks_like_lens_card(sp):
        region = "occipital"
    elif suffix in _IMAGE_EXTS or "/visual/" in sp:
        region = "occipital"
    elif suffix in _AUDIO_EXTS or "/audio/" in sp or "/ears/" in sp:
        region = "wernicke"
    elif region_hint in _HINTABLE_REGIONS:
        region = region_hint  # type: ignore[assignment]
    elif suffix == ".jsonl" and content_kind == "user":
        region = "wernicke"
    elif suffix == ".jsonl" and content_kind == "assistant":
        region = "broca"
    else:
        region = _region_for_layer(configured_layer)

    return Classification(layer=configured_layer, region=region, workspace=workspace)


def _extract_workspace(path: Path) -> str | None:
    parts = path.parts
    if "workspaces" in parts:
        i = parts.index("workspaces")
        if i + 1 < len(parts):
            return parts[i + 1]
    return None


def _frontmatter_region(text: str | None) -> str | None:
    if not text or not text.startswith("---"):
        return None
    lines = text.splitlines()
    for line in lines[1:_FRONTMATTER_SCAN_LINES]:
        if line.rstrip() == "---":
            return None
        if line.startswith("region:"):
            value = line[len("region:") :].strip().strip("'\"")
            return value if value in _ALL_REGIONS else None
    return None


def _looks_like_lens_card(path_text: str) -> bool:
    return "/lens/" in path_text or path_text.startswith("lens/")


def _region_for_layer(layer: str) -> Region:
    return {
        "core": "frontoparietal",
        "semantic": "wernicke",
        "procedural": "frontoparietal",
        "episodic": "hippocampus",
        "short_term": "hippocampus",
    }.get(layer, "wernicke")  # type: ignore[return-value]
