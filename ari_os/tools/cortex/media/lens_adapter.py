from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

FRONTMATTER = re.compile(r"^---\n([\s\S]*?)\n---\n?([\s\S]*)$")


@dataclass
class LensCard:
    slug: str
    kind: str
    genre: str
    title: str | None
    tags: list[str] = field(default_factory=list)
    related: list[str] = field(default_factory=list)
    owner: str | None = None
    body: str = ""
    source_path: Path | None = None


@dataclass
class Manifest:
    version: int
    generated_at: str
    slugs: dict[str, dict]


def load_manifest(path: Path) -> Manifest:
    data = yaml.safe_load(path.read_text()) or {}
    return Manifest(
        version=int(data.get("version", 1)),
        generated_at=str(data.get("generated_at", "")),
        slugs=data.get("slugs", {}) or {},
    )


def parse_card(path: Path) -> LensCard:
    raw = path.read_text()
    match = FRONTMATTER.match(raw)
    if not match:
        raise ValueError(f"{path}: missing YAML frontmatter block")

    frontmatter = yaml.safe_load(match.group(1)) or {}
    body = match.group(2).strip()
    slug = str(frontmatter.get("id") or frontmatter.get("slug") or path.stem)
    kind = str(frontmatter.get("kind") or _infer_kind(slug, path))

    return LensCard(
        slug=slug,
        kind=kind,
        genre=str(frontmatter.get("genre", "unknown")),
        title=frontmatter.get("title"),
        tags=list(frontmatter.get("tags") or []),
        related=list(frontmatter.get("related") or []),
        owner=frontmatter.get("owner"),
        body=body,
        source_path=path,
    )


def find_card(lens_root: Path, slug: str) -> LensCard | None:
    """Find a card by slug under the user's local LENS state directory."""
    manifest_path = lens_root / "manifest.yaml"
    if manifest_path.exists():
        card = _find_from_manifest(lens_root, manifest_path, slug)
        if card is not None:
            return card

    if not lens_root.exists():
        return None

    for path in sorted(lens_root.rglob("*.md")):
        try:
            card = parse_card(path)
        except ValueError:
            continue
        if card.slug == slug:
            return card
    return None


def _find_from_manifest(lens_root: Path, manifest_path: Path, slug: str) -> LensCard | None:
    try:
        manifest = load_manifest(manifest_path)
    except Exception:
        return None

    entry = manifest.slugs.get(slug)
    if not isinstance(entry, dict):
        return None

    raw_path = entry.get("path") or entry.get("source_path") or entry.get("file")
    if not raw_path:
        return None

    path = Path(str(raw_path))
    if not path.is_absolute():
        path = lens_root / path
    try:
        path.relative_to(lens_root)
    except ValueError:
        return None
    if not path.exists():
        return None
    return parse_card(path)


def _infer_kind(slug: str, path: Path) -> str:
    parts = {part.lower() for part in path.parts}
    if slug.startswith("dna-") or "dna" in parts:
        return "dna"
    return "trend"
