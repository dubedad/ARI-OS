from __future__ import annotations

import hashlib
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ari_os.tools.cortex import config
from ari_os.tools.cortex.embed import EmbedClient
from ari_os.tools.cortex.retrieve import RetrievalResult, retrieve


class VisionUnavailable(RuntimeError):
    """Raised when the local vision backend cannot produce a caption."""


@dataclass
class SeeResult:
    caption: str
    retrieval: RetrievalResult


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _ollama_caption(path: Path, model: str = "llava") -> str:
    """Caption an image with local Ollama.

    Ollama is an optional external dependency. Missing binaries, failed local
    model calls, and empty output all raise ``VisionUnavailable`` so public
    callers can degrade to the friendly off/unavailable response.
    """
    if not path.exists():
        raise VisionUnavailable(f"image not found: {path}")
    prompt = (
        "Describe this image briefly in 2-3 sentences. Focus on style, "
        "lighting, mood, palette, and any visible text."
    )
    try:
        result = subprocess.run(
            ["ollama", "run", model, f"{prompt}\n\nImage: {path}"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (FileNotFoundError, subprocess.SubprocessError) as exc:
        raise VisionUnavailable("local Ollama llava is unavailable") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        suffix = f": {detail}" if detail else ""
        raise VisionUnavailable(f"local Ollama llava failed{suffix}")
    caption = result.stdout.strip()
    if not caption:
        raise VisionUnavailable("local Ollama llava returned no caption")
    return caption


def caption_for_image(
    path: Path,
    *,
    vision_client: Callable[[Path], str] | None = None,
    lens_root: Path | None = None,
) -> str:
    """Return a local LENS note for the image, or call local Ollama llava."""
    image = Path(path)
    note = _lens_note_for_image(image, lens_root or (config.state_home() / "lens"))
    if note:
        return note
    client = vision_client or _ollama_caption
    caption = client(image).strip()
    if not caption:
        raise VisionUnavailable("vision backend returned no caption")
    return caption


def see(
    db_path: Path,
    caption_or_image: str | Path,
    *,
    embed_client: EmbedClient | None = None,
    mode: str = "visual",
    cwd: str | None = None,
    branch: str | None = None,
    vision_client: Callable[[Path], str] | None = None,
) -> SeeResult:
    """Bimodal entry point: image or caption text to retrieval."""
    if isinstance(caption_or_image, Path):
        caption = caption_for_image(caption_or_image, vision_client=vision_client)
    else:
        candidate = Path(caption_or_image)
        if candidate.exists():
            caption = caption_for_image(candidate, vision_client=vision_client)
        else:
            caption = caption_or_image

    result = retrieve(
        db_path,
        query=caption,
        embed_client=embed_client,
        mode=mode,
        cwd=cwd,
        branch=branch,
        consumer="see",
    )
    return SeeResult(caption=caption, retrieval=result)


def _lens_note_for_image(image: Path, lens_root: Path) -> str | None:
    if not image.exists() or not lens_root.exists():
        return None
    try:
        digest = file_sha256(image)
    except OSError:
        return None
    for card in sorted(lens_root.rglob("*.md")):
        try:
            note = _scan_card_for_image_note(card, digest, image.name)
        except OSError:
            continue
        if note:
            return note
    return None


def _scan_card_for_image_note(card_path: Path, digest: str, filename: str) -> str | None:
    text = card_path.read_text(errors="replace")
    markers = [re.escape(digest), re.escape(filename)]
    for marker in markers:
        match = re.search(
            rf"-\s+path:\s*[^\n]*{marker}[^\n]*\n\s+note:\s*([^\n]+)",
            text,
        )
        if match:
            return match.group(1).strip()
    return None
